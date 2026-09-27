#!/usr/bin/env python3
"""Sanity-check the Smart Turn v3.2 integration: does p(turn complete) actually rise at the
real end of an utterance, using OUR mel frontend? Uses macOS `say` for real speech audio.
Also reports the RSS/footprint rows from the benchmark.
"""
import json, os, subprocess, sys
import numpy as np
import onnxruntime as ort

os.chdir(os.path.expanduser("~/smart-turn-bench"))
N_FFT, HOP, SR, N_MELS, N_FRAMES = 400, 160, 16000, 80, 800

SENTENCE = ("So I was thinking about the voice pipeline, and the thing that keeps "
            "bothering me is that it cuts me off while I am still talking.")


def hz2mel(f): return 2595.0 * np.log10(1.0 + f / 700.0)
def mel2hz(m): return 700.0 * (10.0 ** (m / 2595.0) - 1.0)


def mel_filters():
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
    """<=8 s of float32 PCM, right-aligned into an 8 s window -> [1, 80, 800]."""
    audio = np.asarray(audio, dtype=np.float32)
    if len(audio) < N_FRAMES * HOP:
        audio = np.pad(audio, (N_FRAMES * HOP - len(audio), 0))
    x = np.pad(audio, N_FFT // 2, mode="reflect")
    frames = np.lib.stride_tricks.sliding_window_view(x, N_FFT)[::HOP][:N_FRAMES]
    spec = np.abs(np.fft.rfft(frames * WINDOW, axis=1)).astype(np.float32) ** 2
    mel = spec @ FB.T
    return (((np.log10(np.maximum(mel, 1e-10))).T + 4.0) / 4.0)[None].astype(np.float32)


def load_wav16k_mono(path):
    import wave
    with wave.open(path, "rb") as w:
        assert w.getframerate() == SR and w.getnchannels() == 1, \
            f"expected 16k mono, got {w.getframerate()}Hz/{w.getnchannels()}ch"
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0


def p_complete(sess, audio):
    logit = sess.run(None, {"input_features": log_mel(audio)})[0][0][0]
    return 1.0 / (1.0 + np.exp(-float(logit)))


if __name__ == "__main__":
    aiff, wav = "/tmp/turn_test.aiff", "/tmp/turn_test.wav"
    subprocess.run(["say", "-v", "Samantha", "-o", aiff, SENTENCE], check=True)
    subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@16000", "-c", "1", aiff, wav], check=True)
    audio = load_wav16k_mono(wav)
    dur = len(audio) / SR
    print(f"utterance: {dur:.2f}s @16kHz mono ({len(audio)} samples)\n")

    sess = ort.InferenceSession("models/smart-turn-v3.2-cpu.onnx",
                                sess_options=(lambda s: (setattr(s, "intra_op_num_threads", 4), s)[1])(ort.SessionOptions()),
                                providers=["CPUExecutionProvider"])

    print("p(turn complete) as the window ends at increasingly later cut points:")
    print(f"{'cut at':>8}  {'frac':>5}  {'p_complete':>10}  verdict")
    rows = []
    for frac in [0.2, 0.35, 0.5, 0.6, 0.7, 0.8, 0.9, 0.97, 1.0]:
        cut = int(len(audio) * frac)
        p = p_complete(sess, audio[:cut])
        verdict = "COMPLETE -> answer now" if p >= 0.5 else "mid-turn -> keep listening"
        rows.append({"frac": frac, "p": round(p, 4)})
        print(f"{cut/SR:7.2f}s  {frac:5.2f}  {p:10.4f}  {verdict}")

    # trailing silence: what the bridge actually hands over after a VAD pause
    print("\nwith 0.5s of trailing silence (the VAD-pause case the bridge would trigger on):")
    for frac in [0.5, 0.7, 1.0]:
        cut = int(len(audio) * frac)
        seg = np.concatenate([audio[:cut], np.zeros(int(0.5 * SR), dtype=np.float32)])
        print(f"  cut {frac:4.2f} + 0.5s silence -> p={p_complete(sess, seg):.4f}")

    json.dump(rows, open("sanity-results.json", "w"), indent=2)
    print("\nwrote sanity-results.json")