#!/usr/bin/env python3
"""Regression check for the bridge delegation-pacing patch (2026-09-17).

Builds a two-sentence WAV with a 0.95 s gap (below the 2.5 s coalesce window but
above the 0.9 s VAD end-of-utterance), then plays it through the fake mic via
selftest_speech.py. Expected in the bridge log:

    user said: Number one.
    delegating to Hermes in 2.5s: Number one.
    user said: Number two.
    delegating to Hermes (2 queued merged)      <- both fragments, one turn

Usage: ./.venv/bin/python regress_two_utterances.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import urllib.request
import wave

import numpy as np

SPEACHES = "http://127.0.0.1:8000"
OUT = "/tmp/speech-two.wav"
GAP_S = 0.95
SENTENCES = ["Number one.", "Number two."]


def tts(text: str) -> tuple[np.ndarray, int]:
    req = urllib.request.Request(
        f"{SPEACHES}/v1/audio/speech",
        data=json.dumps({
            "model": "speaches-ai/Kokoro-82M-v1.0-ONNX",
            "voice": "af_heart",
            "input": text,
            "response_format": "wav",
            "speed": 1.2,
        }).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=90) as resp:
        raw = resp.read()
    with wave.open(__import__("io").BytesIO(raw), "rb") as w:
        rate, ch, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32)
    if ch > 1:
        data = data.reshape(-1, ch).mean(axis=1)
    if width != 2:
        sys.exit(f"unexpected sample width {width} from Speaches")
    print(f"  {text!r}: {data.size / rate:.2f}s @ {rate} Hz")
    return data, rate


def main() -> int:
    clips = [tts(s) for s in SENTENCES]
    rate = clips[0][1]
    if any(c[1] != rate for c in clips):
        sys.exit("clips have different sample rates")
    silence = np.zeros(int(rate * GAP_S), dtype=np.float32)
    pcm = np.concatenate([clips[0][0], silence, clips[1][0], np.zeros(int(rate * 4.0), dtype=np.float32)])
    with wave.open(OUT, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(np.clip(pcm, -32768, 32767).astype(np.int16).tobytes())
    print(f"wrote {OUT}: {pcm.size / rate:.2f}s total, {GAP_S}s gap between the two sentences")

    out = subprocess.run(
        ["./.venv/bin/python", "selftest_speech.py", "http://127.0.0.1:8899", OUT],
        capture_output=True, text=True, timeout=180,
    )
    print(out.stdout[-1500:])
    print(out.stderr[-500:])
    return 0


if __name__ == "__main__":
    sys.exit(main())