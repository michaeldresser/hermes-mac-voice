# Self-executed research — Mac voice engine selection (2026-09-14 ~22:40Z)

Research Hermes remained silent 8h post-route-fix (status ping msg_5760d014
at 22:29Z unanswered). Per the escalation plan, DarkAgent executed the core
queries directly. Sources fetched in full (not snippet-only) unless noted.

## Verified performance numbers

### STT — whisper.cpp on Apple Silicon (mundwerk-app/whisper-metal-benchmark,
run 2026-05-05-r01, M3 Ultra, whisper.cpp v1.8.4, 11s JFK sample, 22 words)

| Model | Size | Median inference | RTF | Speed vs real-time |
|---|---|---|---|---|
| tiny | 74 MB | 136 ms | 0.012 | 80.9× |
| base | 141 MB | 162 ms | 0.015 | 68.1× |
| small | 465 MB | 310 ms | 0.028 | 35.5× |
| medium | 1.46 GB | 714 ms | 0.065 | 15.4× |
| large-v3-turbo | 1.55 GB | 623 ms | 0.057 | 17.7× |

Caveat: these are **Metal/GPU** numbers. Docker-on-macOS = CPU-only, so expect
slower (rule of thumb 3–8× vs Metal on the same chip — verify with the Mac
benchmark). CPU reference from another source (M5 Pro, faster-whisper int8
CPU): large-v3-turbo ~400–600 ms behind real time for streaming chunks;
small ~200 ms. Even at CPU-only speeds, **every model up to large-v3-turbo is
faster than real time** on M-series → STT latency is a non-issue; choose by
accuracy. Source: promptquorum.com Apple Silicon guide (fetched full).

### TTS — Kokoro-82M

- Independent CPU benchmark (efemaer gist, AWS c6a.8xlarge, 32 vCPU EPYC):
  **RTF 5× on CPU** (PyTorch and ONNX both) — i.e., 1s of audio per 200ms.
  (RTF here = audio_length/process_time, higher better — 5× real-time.)
- Kokoro-FastAPI README (fetched full): realtime speed 35–100× on GPU
  (RTX 4060Ti); CPU image is the supported path for no-GPU hosts; **Apple
  Silicon MPS supported when run directly via UV (no Docker)** — the CPU
  Docker image also works on macOS/arm64.
- Docker deployment one-liner (README): `docker run -p 8880:8880
  ghcr.io/remsky/kokoro-fastapi-cpu:latest` — multi-arch incl. arm64,
  models baked in.

## Verified server choices (OpenAI-compatible, arm64 Docker)

1. **TTS: Kokoro-FastAPI** (`ghcr.io/remsky/kokoro-fastapi-cpu:latest`,
   port 8880). Native `/v1/audio/speech`, OpenAI shapes, multi-arch,
   actively maintained, Home Assistant/agent ecosystem adoption. Confirmed
   Apple Silicon notes in README. Alternative: native MPS via UV
   (`./start-gpu_mac.sh`) if CPU benchmarks disappoint — no container, but
   full Apple GPU.
2. **STT: Speaches** (`speaches-ai/speaches`, formerly faster-whisper-server).
   OpenAI-compatible transcription + translation + speech generation
   (Kokoro & Piper backends too!), streaming/SSE + realtime API,
   `compose.cpu.yaml` provided, faster-whisper (ctranslate2 int8) backend.
   One server could even do BOTH STT and TTS (it embeds Kokoro), but
   Kokoro-FastAPI is the more battle-tested TTS path; decision: use Speaches
   for STT, Kokoro-FastAPI for TTS (both OpenAI-compat, both arm64 Docker).

## Model pick recommendation (pending Mac benchmark confirmation)

- **STT: large-v3-turbo (int8)** — near-large-v3 quality at turbo speed;
  the documented "dictation sweet spot" (M3 Ultra data above); CPU-only
  Docker still comfortably real-time per the M5 Pro CPU data. Fallback:
  medium int8 if turbo RAM/loading is an issue; small if we need minimum
  latency. Accuracy bar (≤5% WER ops vocab) requires ≥ medium class.
- **TTS: Kokoro-82M, voice af_heart** — 5× real-time even on 32 vCPU
  server-class CPU; M-series single-machine CPU should be in the same
  ballpark (RTF ≥ 1 required; verify on the Mac).

## Mac install sheet (Docker, CPU)

```bash
# TTS — Kokoro-FastAPI
docker run -d --name kokoro-tts --restart unless-stopped -p 8880:8880 \
  ghcr.io/remsky/kokoro-fastapi-cpu:latest

# STT — Speaches (CPU compose)
git clone https://github.com/speaches-ai/speaches && cd speaches
docker compose -f compose.cpu.yaml up -d   # default port 8000

# Smoke tests from any machine:
curl http://<mac>:8880/health
curl http://<mac>:8000/health
# then: bash /workspace/mac-voice-conformance-test.sh http://<mac>:8880
# (conformance script tests /v1/audio/speech + /v1/audio/transcriptions)
```

Note: Speaches default port 8000 collides with LLM-RQ's 8000 on the swarm —
irrelevant (different machines), but keep it in mind for firewall rules.
Expose the Mac services on the LAN/Tailscale interface only, with a bearer
token if exposed beyond loopback (conformance test checks auth).

## Provenance

- mundwerk-app/whisper-metal-benchmark summary.md (fetched full, raw file)
- efemaer Kokoro v1.0 benchmark gist (fetched full)
- remsky/Kokoro-FastAPI README (fetched full)
- speaches-ai/speaches README (fetched full)
- promptquorum.com Apple Silicon whisper guide (fetched full)
- All retrieved 2026-09-14 ~22:35–22:45Z by DarkAgent directly.
