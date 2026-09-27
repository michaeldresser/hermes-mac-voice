#!/usr/bin/env python3
"""Benchmark Pipecat Smart Turn v3.2 on Apple Silicon (native, no Docker).

Input is a Whisper-style log-mel [1, 80, 800] (= 8 s @16 kHz). We measure BOTH halves of a
real turn decision -- the mel frontend and the model inference -- on CPU (1/2/4/8 threads)
and on CoreML (GPU + ANE), plus session build cost and peak RSS.
"""
import json, os, statistics, time
import numpy as np
import onnxruntime as ort

os.chdir(os.path.expanduser("~/smart-turn-bench"))
N_FFT, HOP, SR, N_MELS, N_FRAMES = 400, 160, 16000, 80, 800

MODELS = {
    "int8 (cpu file, 8.7MB)": "models/smart-turn-v3.2-cpu.onnx",
    "fp32 (gpu file, 32.4MB)": "models/smart-turn-v3.2-gpu.onnx",
}
CONFIGS = [
    ("CPU 1 thread", "CPUExecutionProvider", {"intra_op_num_threads": 1}),
    ("CPU 2 threads", "CPUExecutionProvider", {"intra_op_num_threads": 2}),
    ("CPU 4 threads", "CPUExecutionProvider", {"intra_op_num_threads": 4}),
    ("CPU 8 threads", "CPUExecutionProvider", {"intra_op_num_threads": 8}),
    ("CoreML (GPU+ANE)", "CoreMLExecutionProvider", {}),
]


def mel_filters():
    def hz2mel(f): return 2595.0 * np.log10(1.0 + f / 700.0)

    def mel2hz(m): return 700.0 * (10.0 ** (m / 2595.0) - 1.0)

    pts = mel2hz(np.linspace(hz2mel(0.0), hz2mel(SR / 2), N_MELS + 2))
    freqs = np.fft.rfftfreq(N_FFT, 1.0 / SR)
    fb = np.zeros((N_MELS, len(freqs)), dtype=np.float32)
    for i in range(N_MELS):
        lo, ctr, hi = pts[i], pts[i + 1], pts[i + 2]
        fb[i] = np.clip(np.minimum((freqs - lo) / max(ctr - lo, 1e-9),
                                   (hi - freqs) / max(hi - ctr, 1e-9)), 0, None)
    return fb


FB = mel_filters()
WINDOW = np.hanning(N_FFT).astype(np.float32)


def log_mel(audio):
    """8 s of float32 PCM -> Whisper log-mel [1, 80, 800]."""
    x = np.pad(audio, N_FFT // 2, mode="reflect")
    frames = np.lib.stride_tricks.sliding_window_view(x, N_FFT)[::HOP][:N_FRAMES]
    spec = np.abs(np.fft.rfft(frames * WINDOW, axis=1)).astype(np.float32) ** 2
    mel = spec @ FB.T
    return (((np.log10(np.maximum(mel, 1e-10))).T + 4.0) / 4.0)[None].astype(np.float32)


def make_audio(seconds=8.0, seed=0):
    n = int(seconds * SR)
    rng = np.random.default_rng(seed)
    t = np.arange(n) / SR
    env = 0.5 + 0.5 * np.sin(2 * np.pi * 3.0 * t)
    return (env * (0.05 * np.sin(2 * np.pi * 180 * t) + 0.02 * rng.standard_normal(n))).astype(np.float32)


def timed(fn, iters=60, warm=8):
    for _ in range(warm):
        fn()
    ts = []
    for _ in range(iters):
        t0 = time.perf_counter()
        fn()
        ts.append((time.perf_counter() - t0) * 1000.0)
    return ts


def stats_of(ts):
    s = sorted(ts)
    return {"min": round(s[0], 2), "median": round(statistics.median(s), 2),
            "p90": round(s[int(0.9 * len(s))], 2), "max": round(s[-1], 2)}


def rss_mb():
    import resource
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024), 1)


out = {"host": os.uname().machine, "ort": ort.__version__, "rows": []}
print(f"onnxruntime {ort.__version__} | available: {ort.get_available_providers()}\n")

audio = make_audio(8.0)
# --- mel frontend cost (what the bridge pays to build the model input) ---
mel = log_mel(audio)
assert mel.shape == (1, N_MELS, N_FRAMES), mel.shape
mel_ms = stats_of(timed(lambda: log_mel(audio), iters=40, warm=5))
print(f"MEL FRONTEND (8.0s audio -> [1,80,800]): min={mel_ms['min']}  med={mel_ms['median']}  "
      f"p90={mel_ms['p90']}  max={mel_ms['max']} ms\n")
out["mel_frontend_ms"] = mel_ms

for label, path in MODELS.items():
    for cname, prov, opts in CONFIGS:
        so = ort.SessionOptions()
        so.log_severity_level = 3
        for k, v in opts.items():
            setattr(so, k, v)
        t0 = time.perf_counter()
        try:
            sess = ort.InferenceSession(path, so, providers=[prov])
        except Exception as e:
            print(f"SKIP {label} / {cname}: {e}")
            continue
        build_ms = (time.perf_counter() - t0) * 1000.0
        iname = sess.get_inputs()[0].name
        logit = sess.run(None, {iname: mel})[0]
        ms = stats_of(timed(lambda: sess.run(None, {iname: mel}), iters=60, warm=8))
        row = {"model": label, "config": cname, "session_build_ms": round(build_ms, 1),
               "output_shape": list(logit.shape), **ms,
               "total_decision_ms": round(mel_ms["median"] + ms["median"], 2),
               "rss_mb": rss_mb(), "n": 60}
        out["rows"].append(row)
        print(f"{label:26s} {cname:17s} build={build_ms:7.1f}ms med={ms['median']:7.2f}ms "
              f"max={ms['max']:7.2f}ms  +mel=> {row['total_decision_ms']:7.2f}ms")

with open("bench-results.json", "w") as f:
    json.dump(out, f, indent=2)
print("\nwrote bench-results.json")