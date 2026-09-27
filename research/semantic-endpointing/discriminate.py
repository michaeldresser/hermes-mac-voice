#!/usr/bin/env python3
"""Does Smart Turn actually discriminate mid-sentence from finished -- on CONTENT, not silence?
Each phrase is synthesized with macOS `say` (real prosody), then scored through the official
Whisper featurizer + the int8 ONNX model. p>0.5 => "user is done, you may answer".
"""
import os, subprocess
import numpy as np
import onnxruntime as ort
from transformers import WhisperFeatureExtractor

os.chdir(os.path.expanduser("~/smart-turn-bench"))
SR, NS = 16000, 8 * 16000
FE = WhisperFeatureExtractor(chunk_length=8)
so = ort.SessionOptions(); so.intra_op_num_threads = 4
so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
SESS = ort.InferenceSession("models/smart-turn-v3.2-cpu.onnx", so, providers=["CPUExecutionProvider"])

CASES = [
    ("INCOMPLETE (mid-thought)", [
        "So I was thinking about the voice pipeline and the thing that",
        "Can you go ahead and check whether the bridge",
        "I was going to say",
        "the problem is that when I",
    ]),
    ("COMPLETE (finished thought)", [
        "So I was thinking about the voice pipeline and the thing that bothers me is the delay.",
        "Can you go ahead and check whether the bridge is running?",
        "I was going to say hello.",
        "The problem is that when I pause, it cuts me off.",
    ]),
]


def load(path):
    import wave
    with wave.open(path, "rb") as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0


def say(text, tag):
    aiff, wav = f"/tmp/st_{tag}.aiff", f"/tmp/st_{tag}.wav"
    subprocess.run(["say", "-v", "Samantha", "-o", aiff, text], check=True)
    subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@16000", "-c", "1", aiff, wav], check=True)
    return load(wav)


def p_complete(audio, trail=0.5):
    a = np.concatenate([audio, np.zeros(int(trail * SR), dtype=np.float32)])
    a = a[-NS:] if len(a) > NS else a
    f = FE(a, sampling_rate=SR, return_tensors="np", padding="max_length",
           max_length=NS, truncation=True, do_normalize=True).input_features.squeeze(0)[None].astype(np.float32)
    return float(SESS.run(None, {"input_features": f})[0][0][0])   # already a probability


for group, phrases in CASES:
    print(f"\n{group}")
    for i, ph in enumerate(phrases):
        p = p_complete(say(ph, f"{group[:4]}{i}"))
        print(f"  p={p:.4f}  {'DONE -> answer' if p >= .5 else 'listening -> hold'}   \"{ph[:58]}\"")
print("\n(expected: INCOMPLETE rows hold, COMPLETE rows answer)")