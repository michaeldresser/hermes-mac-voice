"""
Local GPT-Live bridge for Hermes Desktop — OpenAI *Live API* server side,
backed entirely by local services on this Mac.

Contract implemented (reverse-engineered from Hermes upstream, 2026-09-16):

  POST /v1/live/sessions
    body: {"session": {...}, "transport": {"type": "webrtc", "sdp": <offer>}}
    resp: {"session": {"id": ...}, "transport": {"type": "webrtc", "sdp": <answer>}}

  Data channel "oai-events" (JSON), server -> desktop:
    session.started                 {"session": {"id": ...}}
    session.input_transcript.delta  {"delta": str, "start_ms": int, "end_ms": int}
    session.output_transcript.delta {"delta": str, "start_ms": int, "end_ms": int}
    session.delegation.created      {"delegation": {"id","type":"client","target"}}
    error                           {"error": {"code","message"}}
    session.closed                  {"reason": str, "usage": {"seconds": float}}

  Data channel, desktop -> server:
    session.commentary.append       {"content": str, "delegation_id": str|None}
    session.thinking.append         {"content": str, "delegation_id": str|None}
    session.instructions.append     {"content": str}

Pipeline: mic audio (WebRTC) -> VAD segmentation -> Whisper (Speaches) ->
  transcript -> either delegate to Hermes (default) or answer locally (LM Studio)
  -> Kokoro (Speaches) TTS -> audio back over WebRTC.
Hermes answers arrive as session.commentary.append and are spoken.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
import uuid
import wave
from collections import deque
from io import BytesIO
from typing import Any, Dict, Optional

import numpy as np
import httpx
from aiortc import RTCPeerConnection, RTCSessionDescription, MediaStreamTrack
from aiortc.mediastreams import AudioFrame
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("gpt-live-bridge")

# ---------------------------------------------------------------- local services
SPEACHES = os.environ.get("SPEACHES_URL", "http://127.0.0.1:8000")
STT_MODEL = os.environ.get("STT_MODEL", "Systran/faster-whisper-small")
STT_PROMPT = os.environ.get(
    "STT_PROMPT",
    "Hermes homelab: Docker Swarm, swarmctl, LLM-RQ, LM Studio, DarkAgent, "
    "Speaches, Kokoro, Whisper, Qwen, gateway, staging, checkpoint.",
)
TTS_MODEL = os.environ.get("TTS_MODEL", "speaches-ai/Kokoro-82M-v1.0-ONNX")
TTS_VOICE = os.environ.get("TTS_VOICE", "af_heart")
TTS_SPEED = float(os.environ.get("TTS_SPEED", "1.2"))
LLM_URL = os.environ.get("LLM_URL", "http://127.0.0.1:1234/v1")
LLM_MODEL = os.environ.get("LLM_MODEL", "qwen/qwen3.8-27b")

# ---------------------------------------------------------------- audio params
SAMPLE_RATE = 48_000          # WebRTC opus rate we produce/consume
FRAME_SAMPLES = 960           # 20 ms @ 48k
SPEECH_RMS = float(os.environ.get("SPEECH_RMS", "450"))     # int16 RMS = speech
SILENCE_MS = int(os.environ.get("SILENCE_MS", "900"))        # end-of-utterance
MIN_UTTERANCE_MS = int(os.environ.get("MIN_UTTERANCE_MS", "350"))
MAX_UTTERANCE_MS = int(os.environ.get("MAX_UTTERANCE_MS", "180000"))
BARGE_IN_RMS = float(os.environ.get("BARGE_IN_RMS", "900"))
# "Reasonably done talking" pause: utterances transcribe instantly, but the
# Hermes delegation only fires after this much quiet. Long enough that a
# mid-thought pause never hands a partial request to the agent.
SETTLE_MS = int(os.environ.get("SETTLE_MS", "5000"))

# Small-talk that should NOT be delegated to Hermes (spoken locally, instantly).
SMALL_TALK = re.compile(
    r"^\s*(hi|hey|hello|yo|good (morning|evening|afternoon)|thanks|thank you|"
    r"ok(ay)?|got it|sounds good|cool|nice|bye|goodbye|stop|never ?mind|"
    r"yes|no|yep|nope|sure|right)\.?\s*$",
    re.IGNORECASE,
)

# ---------------------------------------------------------------- TTS output track


class TTSOutTrack(MediaStreamTrack):
    """Outbound audio: pre-chunked 20 ms frames on an absolute-deadline clock.

    The old implementation paced with asyncio.sleep(20ms) and concatenated a
    growing buffer on every recv() — O(n^2) CPU on the event loop during
    playback, which stalled the loop and made the voice jitter. Frames are now
    chunked once at enqueue time and served from a deque; the clock is an
    absolute perf_counter deadline that resyncs if the loop falls behind.
    """

    kind = "audio"
    FRAME_BYTES = FRAME_SAMPLES * 2  # s16 mono

    def __init__(self) -> None:
        super().__init__()
        self.frames: deque = deque()      # 20 ms s16-mono byte chunks
        self._deadline: Optional[float] = None
        self._pts = 0
        self.speaking = False

    def enqueue_pcm(self, pcm: np.ndarray) -> None:
        step = FRAME_SAMPLES
        for i in range(0, max(pcm.size, 1), step):
            chunk = pcm[i:i + step]
            if chunk.size < step:
                chunk = np.pad(chunk, (0, step - chunk.size))
            self.frames.append(chunk.tobytes())

    def clear(self) -> None:
        self.frames.clear()
        self.speaking = False
        self._deadline = None

    async def recv(self) -> AudioFrame:
        if not self.frames:
            # idle: keep the RTP flow alive with silence (avoids mute/unmute
            # transitions at the receiver) and wait for new audio.
            self.speaking = False
            self._deadline = None
            await asyncio.sleep(FRAME_SAMPLES / SAMPLE_RATE)
            data = b"\x00" * self.FRAME_BYTES
        else:
            if self._deadline is None:
                # resuming: small pre-buffer absorbs event-loop jitter
                t0 = time.perf_counter()
                while len(self.frames) < 4 and time.perf_counter() - t0 < 0.15:
                    await asyncio.sleep(0.005)
                self._deadline = time.perf_counter()
            delay = self._deadline - time.perf_counter()
            if delay > 0:
                await asyncio.sleep(delay)
            self._deadline += FRAME_SAMPLES / SAMPLE_RATE
            if self._deadline - time.perf_counter() < -0.2:
                # loop stalled badly (STT burst, GC): resync the clock
                self._deadline = time.perf_counter()
            self.speaking = True
            data = self.frames.popleft()

        self._pts += FRAME_SAMPLES
        frame = AudioFrame(format="s16", layout="mono", samples=FRAME_SAMPLES)
        frame.sample_rate = SAMPLE_RATE
        frame.pts = self._pts
        frame.planes[0].update(data)
        return frame


# ---------------------------------------------------------------- helpers


def pcm_to_wav(pcm: np.ndarray, rate: int = SAMPLE_RATE) -> bytes:
    buf = BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def wav_to_pcm(data: bytes, out_rate: int = SAMPLE_RATE) -> np.ndarray:
    with wave.open(BytesIO(data), "rb") as w:
        rate = w.getframerate()
        ch = w.getnchannels()
        width = w.getsampwidth()
        raw = w.readframes(w.getnframes())
    dtype = {1: np.int8, 2: np.int16, 4: np.int32}.get(width, np.int16)
    arr = np.frombuffer(raw, dtype=dtype).astype(np.float32)
    if ch > 1:
        arr = arr.reshape(-1, ch).mean(axis=1)
    if dtype is np.int8:
        arr *= 128
    if dtype is np.int32:
        arr /= 65536.0
    if rate != out_rate and arr.size:
        n = int(arr.size * out_rate / rate)
        arr = np.interp(
            np.linspace(0, arr.size - 1, n, dtype=np.float32),
            np.arange(arr.size, dtype=np.float32),
            arr,
        )
    return np.clip(arr, -32768, 32767).astype(np.int16)


def frame_channels(frame: AudioFrame) -> int:
    """Channel count across PyAV versions: .nb_channels is int everywhere,
    .channels is an int on old versions and a tuple of AudioChannel on new ones."""
    layout = getattr(frame, "layout", None)
    if layout is None:
        return 1
    nb = getattr(layout, "nb_channels", None)
    if isinstance(nb, int) and nb > 0:
        return nb
    ch = getattr(layout, "channels", None)
    if isinstance(ch, (tuple, list)):
        return max(1, len(ch))
    if isinstance(ch, int) and ch > 0:
        return ch
    return 1


def frame_to_mono(frame: AudioFrame) -> np.ndarray:
    """Decode an audio frame to mono int16 samples.

    WebRTC delivers Opus as 48 kHz *stereo*; reading planes[0] as-is treats
    interleaved stereo as mono (2x duration, garbled speech → empty STT).
    Handles planar (C, N), packed interleaved (1, N*C), and float formats.
    """
    channels = frame_channels(frame)
    arr = frame.to_ndarray()
    if arr.ndim == 2 and arr.shape[0] == channels and channels > 1:
        mono = arr.astype(np.float32).mean(axis=0)      # planar-ish: (C, N)
    elif arr.ndim == 2 and arr.shape[0] == 1 and channels > 1:
        mono = arr.reshape(-1, channels).astype(np.float32).mean(axis=1)  # packed
    else:
        mono = arr.reshape(-1).astype(np.float32)
    if mono.size and np.max(np.abs(mono)) <= 1.0:       # float formats: scale up
        mono = mono * 32768.0
    return np.clip(mono, -32768, 32767).astype(np.int16)


def rms(frame: AudioFrame) -> float:
    data = frame_to_mono(frame)
    if data.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(data.astype(np.float32) ** 2)))


# ---------------------------------------------------------------- session


class BridgeSession:
    def __init__(self, session_id: str, config: Dict[str, Any]) -> None:
        self.id = session_id
        self.config = config
        self.pc = RTCPeerConnection()
        self.events = None                     # RTCDataChannel
        self.out = TTSOutTrack()
        self.started_ms = int(time.time() * 1000)
        self.mic_task: Optional[asyncio.Task] = None
        self.pending_delegation: Optional[str] = None
        self.delegation_queue: list[str] = []
        self.delegation_watchdog: Optional[asyncio.Task] = None
        self.settle_buffer: list[str] = []
        self.settle_task: Optional[asyncio.Task] = None
        self.last_voice_ms = time.time()
        self.speaking_until = 0.0
        self.log = logging.getLogger(f"bridge[{session_id[:8]}]")

    # ---------- delegation serialization

    def emit_delegation(self) -> None:
        """Fire session.delegation.created — ONLY when none is in flight.

        A second delegation while one is pending makes the desktop abort the
        in-flight Hermes turn (stream_interrupt_abort), which produces the
        "finished that request without a spoken result" dead end. Utterances
        that arrive while one is pending are queued and released when the
        answer (commentary.append) lands or the watchdog fires. Their
        transcripts were already sent, so the desktop's context window sees
        them either way."""
        if self.pending_delegation is not None:
            return
        delegation_id = f"dg_{uuid.uuid4().hex[:12]}"
        self.pending_delegation = delegation_id
        self.log.info("delegating to Hermes (%d queued merged)", len(self.delegation_queue))
        self.delegation_queue.clear()
        self.send({
            "type": "session.delegation.created",
            "delegation": {"id": delegation_id, "type": "client", "target": "hermes"},
        })
        if self.delegation_watchdog:
            self.delegation_watchdog.cancel()
        self.delegation_watchdog = asyncio.create_task(self._delegation_timeout(delegation_id))

    async def _delegation_timeout(self, delegation_id: str) -> None:
        """If Hermes never speaks, release the lock so the next utterance can go."""
        try:
            await asyncio.sleep(90)
        except asyncio.CancelledError:
            return
        if self.pending_delegation == delegation_id:
            self.log.warning("delegation %s timed out with no commentary; releasing", delegation_id)
            self.pending_delegation = None
            self._release_queue()

    def _release_queue(self) -> None:
        if self.delegation_queue and self.pending_delegation is None:
            self.emit_delegation()


    def send(self, event: Dict[str, Any]) -> None:
        if self.events is not None and self.events.readyState == "open":
            try:
                self.events.send(json.dumps(event))
            except Exception:
                self.log.exception("datachannel send failed")

    def transcript(self, kind: str, text: str, start_ms: int, end_ms: int) -> None:
        self.send({
            "type": f"session.{kind}_transcript.delta",
            "delta": text,
            "start_ms": start_ms,
            "end_ms": end_ms,
        })

    def on_datachannel(self, channel) -> None:
        self.events = channel
        self.log.info("data channel %s attached (state=%s)", channel.label, channel.readyState)

        # Hermes' client marks the session live on session.started, and only
        # then treats the transport as connected. aiortc's readyState is not
        # reliable here, so just keep TRYING to send until one lands.
        async def _announce_when_open() -> None:
            for _ in range(300):
                if self.events is not None:
                    try:
                        self.events.send(json.dumps(
                            {"type": "session.started", "session": {"id": self.id}}))
                        self.log.info("sent session.started")
                        return
                    except Exception:
                        pass  # channel not open yet
                await asyncio.sleep(0.05)
            self.log.warning("could not send session.started")

        asyncio.create_task(_announce_when_open())

        @channel.on("message")
        def _on_message(message: Any) -> None:
            try:
                event = json.loads(message if isinstance(message, str) else message.decode())
            except Exception:
                return
            asyncio.create_task(self.handle_client_event(event))

    async def handle_client_event(self, event: Dict[str, Any]) -> None:
        etype = event.get("type")
        if etype == "session.commentary.append":
            text = str(event.get("content") or "").strip()
            if text:
                self.pending_delegation = None
                self.log.info("speaking Hermes reply (%d chars)", len(text))
                await self.speak(text)
                self._release_queue()
        elif etype == "session.thinking.append":
            self.log.info("thinking: %s", str(event.get("content"))[:120])
        elif etype == "session.instructions.append":
            self.log.info("instructions appended: %s", str(event.get("content"))[:120])
        elif etype == "session.close":
            await self.close("client_closed")

    # ---------- audio

    async def consume_mic(self, track) -> None:
        """Segment the mic stream; transcribe on end-of-utterance.

        Defensive by design: a single bad frame must NEVER kill this loop —
        with the task held by the session, an unhandled exception would be
        swallowed forever ("Task exception was never retrieved" only logs on
        GC), which presents exactly as "connected but nothing happens".
        """
        buf: list[np.ndarray] = []
        speaking = False
        silence_ms = 0
        utt_ms = 0
        utt_start_ms = 0
        frames = 0
        last_level_log = 0.0

        while True:
            try:
                frame = await track.recv()
            except Exception:
                self.log.info("mic track ended after %d frames", frames)
                return

            frames += 1
            if frames == 1:
                self.log.info("first mic frame: %d samples ch=%s rms pending",
                              frame.samples, getattr(getattr(frame, "layout", None), "channels", "?"))
            try:
                level = rms(frame)
                data = frame_to_mono(frame)
            except Exception:
                self.log.exception("frame %d processing failed — skipping", frames)
                continue
            frame_ms = int(1000 * frame.samples / (frame.sample_rate or SAMPLE_RATE))

            now = time.time()
            if not speaking and now - last_level_log >= 2.0 and frames <= 300:
                last_level_log = now
                self.log.info("mic level rms=%.0f (frames=%d)", level, frames)

            # barge-in: user talking while we speak -> stop playback
            if level >= BARGE_IN_RMS and self.out.speaking:
                self.out.clear()
                self.log.info("barge-in (rms=%.0f)", level)

            if level >= SPEECH_RMS:
                self.last_voice_ms = time.time()
                if not speaking:
                    speaking = True
                    utt_start_ms = int(time.time() * 1000)
                    utt_ms = 0
                    buf = []
                silence_ms = 0
            elif speaking:
                silence_ms += frame_ms

            if speaking:
                buf.append(data.copy())
                utt_ms += frame_ms

                done = silence_ms >= SILENCE_MS and utt_ms >= MIN_UTTERANCE_MS
                too_long = utt_ms >= MAX_UTTERANCE_MS
                if done or too_long:
                    speaking = False
                    silence_ms = 0
                    pcm = np.concatenate(buf) if buf else np.zeros(0, dtype=np.int16)
                    buf = []
                    if pcm.size:
                        asyncio.create_task(self.handle_utterance(pcm, utt_start_ms))

    async def handle_utterance(self, pcm: np.ndarray, start_ms: int) -> None:
        end_ms = int(time.time() * 1000)
        text = await self.transcribe(pcm)
        if not text:
            self.log.info("STT empty (utterance %.1fs)", pcm.size / SAMPLE_RATE)
            return
        self.log.info("user said: %s", text)
        self.transcript("input", text, start_ms - self.started_ms, end_ms - self.started_ms)

        # Transcribe immediately (above), but HOLD the Hermes delegation until
        # a "likely done" pause: each new utterance re-arms the settle timer,
        # so a mid-thought pause never hands a partial request to the agent.
        self.settle_buffer.append(text)
        if self.settle_task:
            self.settle_task.cancel()
        self.settle_task = asyncio.create_task(self._settle_then_act())

    async def _settle_then_act(self) -> None:
        try:
            await asyncio.sleep(SETTLE_MS / 1000)
        except asyncio.CancelledError:
            return
        combined = " ".join(self.settle_buffer).strip()
        self.settle_buffer.clear()
        if not combined:
            return
        self.log.info("settled turn: %.120s", combined)

        if SMALL_TALK.match(combined):
            reply = await self.small_talk(combined)
            if reply:
                now_ms = int(time.time() * 1000) - self.started_ms
                self.transcript("output", reply, now_ms, now_ms)
                await self.speak(reply)
            return

        # Hand the settled turn to Hermes. Queue if one is already in flight —
        # a second delegation would make the desktop abort the running turn.
        self.delegation_queue.append(combined)
        if self.pending_delegation is not None:
            self.log.info("queued settled turn (delegation in flight): %.80s", combined)
            return
        self.log.info("delegating to Hermes: %.80s", combined)
        self.emit_delegation()

    # ---------- services

    async def transcribe(self, pcm: np.ndarray) -> str:
        wav = pcm_to_wav(pcm)
        files = {"file": ("segment.wav", wav, "audio/wav")}
        data = {"model": STT_MODEL, "language": "en", "prompt": STT_PROMPT}
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                r = await client.post(f"{SPEACHES}/v1/audio/transcriptions", files=files, data=data)
                r.raise_for_status()
                return str(r.json().get("text") or "").strip()
        except Exception:
            self.log.exception("STT failed")
            return ""

    async def small_talk(self, text: str) -> str:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.post(
                    f"{LLM_URL}/chat/completions",
                    json={
                        "model": LLM_MODEL,
                        "messages": [
                            {"role": "system", "content":
                                "You are Hermes' voice front end. Reply in one short spoken "
                                "sentence. No markdown, no lists."},
                            {"role": "user", "content": text},
                        ],
                        "max_tokens": 80,
                        "temperature": 0.6,
                    },
                )
                r.raise_for_status()
                return str(r.json()["choices"][0]["message"]["content"]).strip()
        except Exception:
            self.log.exception("LLM failed")
            return ""

    async def speak(self, text: str) -> None:
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                r = await client.post(
                    f"{SPEACHES}/v1/audio/speech",
                    json={
                        "model": TTS_MODEL,
                        "voice": TTS_VOICE,
                        "input": text,
                        "response_format": "wav",
                        "speed": TTS_SPEED,
                    },
                )
                r.raise_for_status()
                # decode + resample off the event loop so playback pacing
                # never stalls while Kokoro output is processed
                pcm = await asyncio.to_thread(wav_to_pcm, r.content)
        except Exception:
            self.log.exception("TTS failed")
            return
        self.out.enqueue_pcm(pcm)

    # ---------- lifecycle

    async def close(self, reason: str) -> None:
        self.send({"type": "session.closed", "reason": reason,
                   "usage": {"seconds": round(time.time() - self.started_ms / 1000, 1)}})
        self.out.clear()
        try:
            await self.pc.close()
        except Exception:
            pass
        SESSIONS.pop(self.id, None)


SESSIONS: Dict[str, BridgeSession] = {}

# ---------------------------------------------------------------- HTTP API

app = FastAPI(title="hermes-local-gpt-live-bridge")


@app.get("/healthz")
async def healthz() -> Dict[str, Any]:
    return {"ok": True, "sessions": len(SESSIONS)}


@app.post("/v1/live/sessions")
async def create_session(request: Request) -> JSONResponse:
    body = await request.json()
    offer_sdp = str((body.get("transport") or {}).get("sdp") or "")
    config = body.get("session") or {}
    if not offer_sdp:
        return JSONResponse({"error": {"code": "bad_request", "message": "missing sdp"}},
                            status_code=400)

    session_id = f"sess_{uuid.uuid4().hex[:12]}"
    session = BridgeSession(session_id, config)
    SESSIONS[session_id] = session
    log.info("new session %s (model=%s voice=%s)",
             session_id, config.get("model"), (config.get("audio") or {}).get("output", {}).get("voice"))

    @session.pc.on("datachannel")
    def _dc(channel):
        session.on_datachannel(channel)

    @session.pc.on("track")
    def _track(track):
        session.log.info("mic track from desktop")
        session.mic_task = asyncio.create_task(session.consume_mic(track))

    session.pc.addTrack(session.out)

    await session.pc.setRemoteDescription(RTCSessionDescription(sdp=offer_sdp, type="offer"))
    answer = await session.pc.createAnswer()
    await session.pc.setLocalDescription(answer)

    # Wait briefly for host candidates so the answer carries them (client waits
    # for full ICE gathering before offering, so no trickle needed).
    for _ in range(40):
        if session.pc.iceGatheringState == "complete":
            break
        await asyncio.sleep(0.05)

    session.send({"type": "session.started", "session": {"id": session_id}})
    log.info("session %s answering (ice=%s)", session_id, session.pc.iceGatheringState)
    return JSONResponse({
        "session": {"id": session_id},
        "transport": {"type": "webrtc", "sdp": session.pc.localDescription.sdp},
    })


@app.post("/v1/live/sessions/{session_id}/close")
async def close_session(session_id: str) -> JSONResponse:
    session = SESSIONS.get(session_id)
    if session:
        await session.close("server_closed")
    return JSONResponse({"ok": True})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=os.environ.get("BIND", "0.0.0.0"),
                port=int(os.environ.get("PORT", "8899")), log_level="info")
