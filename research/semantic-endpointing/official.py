#!/usr/bin/env python3
"""Correctness + latency for Smart Turn v3.2 using the OFFICIAL Whisper feature extractor
(exactly as the reference inference.py does), on the Mac natively.
"""
import json, os, statistics, subprocess, time
import numpy as np
import onnxruntime as ort
from transformers import WhisperFeatureExtractor

os.chdir(os.path.expanduser("~/smart-turn-bench"))
SR, NS = 16000, 8 * 16000
FE = WhisperFeatureExtractor(chunk_length=8)
SENTENCE = ("So I was thinking about the voice pipeline, and the thing that keeps "
            "bothering me is that it cuts me off while I am still talking.")


def feats(audio):
    a = audio[-NS:] if len(audio) > NS else audio
    inp = FE(a, sampling_rate=SR, return_tensors="np", padding="max_length",
             max_length=NS, truncation=True, do_normalize=True)
    return inp.input_features.squeeze(0)[None].astype(np.float32)


def load_wav16k_mono(path):
    import wave
    with wave.open(path, "rb") as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0


def rss_mb():
    import resource
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024), 1)


if __name__ == "__main__":
    aiff, wav = "/tmp/turn_test.aiff", "/tmp/turn_test.wav"
    subprocess.run(["say", "-v", "Samantha", "-o", aiff, SENTENCE], check=True)
    subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@16000", "-c", "1", aiff, wav], check=True)
    audio = load_wav16k_mono(wav)
    print(f"utterance {len(audio)/SR:.2f}s\n")

    so = ort.SessionOptions()
    so.intra_op_num_threads = 4
    so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    t0 = time.perf_counter()
    sess = ort.InferenceSession("models/smart-turn-v3.2-cpu.onnx", so, providers=["CPUExecutionProvider"])
    build_ms = (time.perf_counter() - t0) * 1000

    def raw(a):
        return float(sess.run(None, {"input_features": feats(a)})[0][0][0])

    print("OFFICIAL preprocessing -- p(turn complete) vs cut point:")
    print(f"{'cut':>8} {'frac':>5} {'raw':>9} {'sigmoid':>9}  verdict")
    rows = []
    for frac in [0.2, 0.35, 0.5, 0.6, 0.7, 0.8, 0.9, 0.97, 1.0]:
        cut = int(len(audio) * frac)
        r = raw(audio[:cut])
        p = 1 / (1 + np.exp(-r))
        rows.append({"frac": frac, "raw": round(r, 4), "p": round(float(p), 4)})
        print(f"{cut/SR:7.2f}s {frac:5.2f} {r:9.4f} {p:9.4f}  "
              f"{'COMPLETE' if p >= .5 else 'mid-turn'}")

    print("\nthe actual bridge case: VAD pause => 0.5s trailing silence appended")
    for frac in [0.5, 0.7, 1.0]:
        cut = int(len(audio) * frac)
        seg = np.concatenate([audio[:cut], np.zeros(int(0.5 * SR), dtype=np.float32)])
        r = raw(seg); p = 1 / (1 + np.exp(-r))
        print(f"  cut {frac:4.2f} +0.5s silence -> raw={r:8.4f} p={p:.4f} "
              f"{'COMPLETE' if p >= .5 else 'mid-turn'}")

    # ---- latency with official preprocessing ----
    seg = audio[: int(len(audio) * 0.7)]
    def timed(fn, iters=40, warm=5):
        for _ in range(warm): fn()
        ts = []
        for _ in range(iters):
            t = time.perf_counter(); fn(); ts.append((time.perf_counter() - t) * 1000)
        return ts

    fe_ts = timed(lambda: feats(seg))
    f = feats(seg)
    inf = {}
    for thr in (1, 2, 4, 8):
        so = ort.SessionOptions(); so.intra_op_num_threads = thr
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        s = ort.InferenceSession("models/smart-turn-v3.2-cpu.onnx", so, providers=["CPUExecutionProvider"])
        ts = timed(lambda: s.run(None, {"input_features": f}))
        inf[thr] = statistics.median(ts)

    print(f"\nsession build: {build_ms:.1f} ms | peak RSS: {rss_mb()} MB")
    print(f"featurizer (official WhisperFeatureExtractor): median {statistics.median(fe_ts):.2f} ms")
    print("model inference median by thread count (int8 cpu model):")
    for thr, v in inf.items():
        print(f"  {thr} thread(s): {v:6.2f} ms  -> decision total {statistics.median(fe_ts)+v:6.2f} ms")
    json.dump({"rows": rows, "fe_ms": statistics.median(fe_ts),
               "inf_ms": inf, "build_ms": build_ms, "rss_mb": rss_mb()},
              open("official-results.json", "w"), indent=2)
    print("\nwrote official-results.json")