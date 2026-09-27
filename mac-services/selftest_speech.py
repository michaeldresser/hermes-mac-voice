"""Speech-path self-test: play a real sentence through the fake mic and verify
the bridge transcribes it and emits session.input_transcript.delta.

Usage:  .venv/bin/python selftest_speech.py [bridge_url] [speech.wav]
Generate speech first, e.g.:
  curl -s http://127.0.0.1:8899/../  (no) — use Speaches directly:
  curl -s http://127.0.0.1:8000/v1/audio/speech -H 'Content-Type: application/json' \
    -d '{"model":"speaches-ai/Kokoro-82M-v1.0-ONNX","voice":"af_heart","input":"The quick brown fox jumps over the lazy dog near the dark agent gateway.","response_format":"wav"}' \
    -o /tmp/speech-test.wav
"""

import asyncio
import json
import sys
import wave
import time
from fractions import Fraction

import httpx
import numpy as np
from aiortc import RTCPeerConnection, RTCSessionDescription, MediaStreamTrack
from aiortc.mediastreams import AudioFrame

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8899"
WAV = sys.argv[2] if len(sys.argv) > 2 else "/tmp/speech-test.wav"
SAMPLE_RATE = 48_000
FRAME = 960  # 20 ms


def load_pcm(path):
    with wave.open(path, "rb") as w:
        rate, ch, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(w.getnframes())
    dtype = {1: np.int8, 2: np.int16, 4: np.int32}.get(width, np.int16)
    arr = np.frombuffer(raw, dtype=dtype).astype(np.float32)
    if ch > 1:
        arr = arr.reshape(-1, ch).mean(axis=1)
    if dtype is np.int8:
        arr *= 128
    if dtype is np.int32:
        arr /= 65536.0
    if rate != SAMPLE_RATE:
        n = int(arr.size * SAMPLE_RATE / rate)
        arr = np.interp(np.linspace(0, arr.size - 1, n), np.arange(arr.size), arr)
    return np.clip(arr, -32768, 32767).astype(np.int16)


class SpeechMicTrack(MediaStreamTrack):
    """Streams real speech, then silence (lets the bridge VAD close the utterance)."""

    kind = "audio"

    def __init__(self, pcm, tail_silence_s=4.0):
        super().__init__()
        self.pcm = pcm
        self.pos = 0
        self.tail_frames = int(tail_silence_s * SAMPLE_RATE / FRAME)
        self.tail = 0
        self.t = 0

    async def recv(self):
        await asyncio.sleep(FRAME / SAMPLE_RATE)
        self.t += FRAME
        if self.pos < len(self.pcm):
            chunk = self.pcm[self.pos:self.pos + FRAME]
            self.pos += FRAME
            if len(chunk) < FRAME:
                chunk = np.concatenate([chunk, np.zeros(FRAME - len(chunk), dtype=np.int16)])
        else:
            self.tail += 1
            chunk = np.zeros(FRAME, dtype=np.int16)
        f = AudioFrame(format="s16", layout="stereo", samples=FRAME)
        f.sample_rate = SAMPLE_RATE
        f.pts = self.t
        f.time_base = Fraction(1, SAMPLE_RATE)
        # Pack as interleaved stereo — the bug this test guards against.
        stereo = np.repeat(chunk, 2).astype(np.int16)
        f.planes[0].update(stereo.tobytes())
        return f


async def main():
    pcm = load_pcm(WAV)
    print(f"[test] speech: {len(pcm)/SAMPLE_RATE:.1f}s loaded from {WAV}")

    pc = RTCPeerConnection()
    events = pc.createDataChannel("oai-events")
    received = []

    @events.on("message")
    def _msg(message):
        event = json.loads(message if isinstance(message, str) else message.decode())
        received.append(event)
        print("[test] event:", json.dumps(event)[:200])

    @pc.on("track")
    def _track(track):
        async def pump():
            while True:
                try:
                    await track.recv()
                except Exception:
                    return
        asyncio.ensure_future(pump())

    pc.addTrack(SpeechMicTrack(pcm))
    offer = await pc.createOffer()
    await pc.setLocalDescription(offer)
    for _ in range(40):
        if pc.iceGatheringState == "complete":
            break
        await asyncio.sleep(0.05)

    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(
            f"{BASE}/v1/live/sessions",
            json={"session": {"model": "gpt-live-1"},
                  "transport": {"type": "webrtc", "sdp": pc.localDescription.sdp}},
            headers={"Authorization": "Bearer local"},
        )
    r.raise_for_status()
    body = r.json()
    await pc.setRemoteDescription(RTCSessionDescription(sdp=body["transport"]["sdp"], type="answer"))

    duration = len(pcm) / SAMPLE_RATE + 20  # speech + silence + STT + settle window
    print(f"[test] speaking for {duration:.0f}s...")
    await asyncio.sleep(duration)

    transcripts = [e.get("delta") for e in received if e.get("type") == "session.input_transcript.delta"]
    delegations = [e for e in received if e.get("type") == "session.delegation.created"]
    print("\n[test] RESULT:")
    print("  session_started:", any(e.get("type") == "session.started" for e in received))
    print("  transcripts:", transcripts)
    print("  delegations:", len(delegations))
    print("  PASS" if transcripts and any(t.strip() for t in transcripts) else "  FAIL: no non-empty transcript")
    await pc.close()


asyncio.run(main())
