"""Self-test: act like Hermes Desktop's GPT-Live client against the local bridge.

Creates the same WebRTC session the desktop does (mic track + 'oai-events'
datachannel), sends an SDP offer to POST /v1/live/sessions, then verifies:
  1. an SDP answer comes back
  2. the datachannel opens
  3. session.started arrives
  4. the bridge sends audio (we feed it commentary.append; expect audio frames)

Run:  .venv/bin/python selftest_client.py [http://127.0.0.1:8899]
"""

import asyncio
import json
import sys
import time

import httpx
import numpy as np
from aiortc import RTCPeerConnection, RTCSessionDescription, MediaStreamTrack
from aiortc.mediastreams import AudioFrame

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8899"
SAMPLE_RATE = 48_000
FRAME = 960


class MicTrack(MediaStreamTrack):
    """Pretends to be the desktop's microphone (silence by default)."""

    kind = "audio"

    def __init__(self):
        super().__init__()
        self.t = 0

    async def recv(self):
        await asyncio.sleep(FRAME / SAMPLE_RATE)
        self.t += FRAME
        f = AudioFrame(format="s16", layout="mono", samples=FRAME)
        f.sample_rate = SAMPLE_RATE
        f.pts = self.t
        f.planes[0].update(np.zeros(FRAME, dtype=np.int16).tobytes())
        return f


async def main():
    pc = RTCPeerConnection()
    events = pc.createDataChannel("oai-events")
    received = []
    audio_frames = {"n": 0}

    @events.on("open")
    def _open():
        print("[client] datachannel open")

    @events.on("message")
    def _msg(message):
        event = json.loads(message if isinstance(message, str) else message.decode())
        received.append(event)
        print("[client] event:", json.dumps(event)[:160])

    @pc.on("track")
    def _track(track):
        print("[client] audio track from bridge")

        async def pump():
            while True:
                try:
                    frame = await track.recv()
                    audio_frames["n"] += 1
                    data = np.frombuffer(frame.planes[0], dtype=np.int16).astype(np.float32)
                    if data.size:
                        level = float(np.sqrt(np.mean(data ** 2)))
                        audio_frames["peak_rms"] = max(audio_frames.get("peak_rms", 0.0), level)
                except Exception:
                    return

        asyncio.ensure_future(pump())

    pc.addTrack(MicTrack())
    offer = await pc.createOffer()
    await pc.setLocalDescription(offer)
    for _ in range(40):
        if pc.iceGatheringState == "complete":
            break
        await asyncio.sleep(0.05)

    print("[client] posting offer to", f"{BASE}/v1/live/sessions")
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(
            f"{BASE}/v1/live/sessions",
            json={
                "session": {"model": "gpt-live-1", "instructions": "test",
                            "audio": {"output": {"voice": "marin"}},
                            "delegation": {"type": "client"}},
                "transport": {"type": "webrtc", "sdp": pc.localDescription.sdp},
            },
            headers={"Authorization": "Bearer local"},
        )
    r.raise_for_status()
    body = r.json()
    print("[client] session id:", body.get("session", {}).get("id"))
    assert body.get("transport", {}).get("sdp"), "no SDP answer"

    await pc.setRemoteDescription(
        RTCSessionDescription(sdp=body["transport"]["sdp"], type="answer")
    )

    # wait for connection + session.started
    for _ in range(100):
        if pc.connectionState == "connected" and any(
            e.get("type") == "session.started" for e in received
        ):
            break
        await asyncio.sleep(0.1)
    print("[client] connectionState:", pc.connectionState)

    # ask the bridge to speak -> proves TTS path and audio output
    events.send(json.dumps({
        "type": "session.commentary.append",
        "content": "Self test complete. The local bridge is speaking this sentence.",
        "delegation_id": None,
        "event_id": "say_1",
    }))
    await asyncio.sleep(6)

    ok = {
        "answer_received": bool(body.get("transport", {}).get("sdp")),
        "connected": pc.connectionState == "connected",
        "session_started": any(e.get("type") == "session.started" for e in received),
        "audio_frames_received": audio_frames["n"],
        "audio_peak_rms": round(audio_frames.get("peak_rms", 0.0), 1),
        "speech_heard": audio_frames.get("peak_rms", 0.0) > 300,
    }
    print("[client] RESULT:", json.dumps(ok, indent=1))
    await pc.close()


asyncio.run(main())
