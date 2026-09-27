# Mac-as-voice-server design — text→speech / speech→text, Mac-only audio (2026-09-14)

Requirement (Michael): **zero audio processing on any machine except the Mac.**
The Mac runs a service whose contract is: text in → audio out (TTS); audio in →
text out (STT). Remote agents never touch audio; they only send/receive text.
Verified seams from the live Hermes docs (`/workspace/hermes-docs-llms-full-current.txt`).
Supersedes the topology tables in `mac-voice-architecture.md` where they
conflict (topologies B relay / C are now disqualified — both execute audio on
the gateway host).

## The single biggest discovery

The OpenAI STT/TTS providers accept custom endpoints:

- `STT_OPENAI_BASE_URL` — "Custom OpenAI STT endpoint"
- `GROQ_BASE_URL` — custom Groq endpoint
- `tts.openai.base_url` in config.yaml — "OpenAI-compatible voice-design
  servers mounted via tts.openai.base_url (e.g. Qwen3-TTS-VoiceDesign via
  oMLX)"; documented example: Kokoro-FastAPI, where `tts.openai.language`
  is forwarded as `lang_code`.

So Hermes can be pointed at an OpenAI-compatible audio server, and that server
can run **on the Mac**. Audio processing then happens nowhere but the Mac.

## Recommended stack

- **TTS on Mac:** Kokoro-FastAPI (`remsky/Kokoro-FastAPI`) — OpenAI-compatible
  `/v1/audio/speech` for Kokoro, runs on Apple Silicon via MLX/ONNX backends.
  Wire as `tts.provider: openai` + `tts.openai.base_url` on the gateway host.
- **STT on Mac:** a whisper server exposing an OpenAI-compatible
  `/v1/audio/transcriptions` (e.g. Speaches / whisper.cpp server /
  faster-whisper-server flavor). Wire as `stt.provider: openai` +
  `STT_OPENAI_BASE_URL` (and `STT_OPENAI_MODEL` as needed) on the gateway host.
- Alternative for TTS if OpenAI-compat shape is insufficient: Hermes
  **command-type provider** (`tts.providers.<name>: type: command`) whose
  command curl's the Mac service: `curl -s -H @auth -d @{input_path} \
  https://mac.local:8000/tts -o {output_path}`. Any HTTP contract works.
  Same seam for STT (`stt.providers.<name>`).
- Key handling: command providers run with Hermes secrets scrubbed; pass
  needed vars via `env_passthrough`. Use curl config files (`-K`) or header
  files rather than inline secrets; never put secrets in config.yaml.

## Why client-direct must be OFF (critical)

With the desktop on a remote gateway profile and cloud STT/TTS selected, the
desktop would call providers **directly from the Mac** by default
(`GET /api/audio/voice-config`, keys in desktop memory). That would appear to
satisfy "Mac does audio" but is disqualified: it puts provider keys on the Mac
and bypasses our audited gateway path. Config:

```yaml
voice:
  client_direct: false   # force relay; the gateway calls the Mac-hosted endpoints
```

The only audio that then exists on the network is recording upstream and
playback audio downstream — no transcription or synthesis happens off-Mac.

## Data flow (final)

```
Mac mic → Desktop capture → [relay] → gateway → HTTP → Mac STT service → text → remote agent (LLM-RQ etc.)
agent reply text → gateway → HTTP → Mac TTS service → audio → [relay] → Desktop → Mac speakers
```

All model inference of any kind that touches audio: Mac only. The gateway
never transcribes/synthesizes; it only forwards bytes and text.

## Transcript corpus findings (YouTube transcripts in the Hermes wiki corpus)

Checked every transcript item under `agentwikis-review|artifacts/agentwikis-audit
/pages/hermes/wiki/summaries/transcript-*.md` plus raw knowledge transcripts:

- `transcript-setup-tutorial-gemma.md` — the Hermes setup tutorial's pick for
  performant local TTS is **NeuTTS** (Neuphonic). The setup wizard offers it
  as the local option and auto-installs dependencies on `Y`.
- `transcript-hermes-full-course-2hr.md` — same verdict for STT privacy
  (local Faster-Whisper); their demo stack used cloud ElevenLabs for TTS, no
  other local TTS project named.
- No transcript names any project beyond NeuTTS/ElevenLabs/whisper.

**Does NeuTTS help us? Yes — arguably better than Kokoro for our exact
constraint.** Hermes' native NeuTTS provider runs `neuphonic/neutts-air-q4-gguf`
(GGUF Q4, llama.cpp-style inference, `device: cpu` default, 2k char cap,
optional 3-second voice clone via `ref_audio`/`ref_text`). It is
CPU-first by design — which is exactly the constraint Docker-on-macOS gives
us (below). Docs also list two more native local providers relevant to the
speed/accuracy balance: **KittenTTS** (nano 25MB int8 — lowest latency, lower
quality) and **Piper** (classic fast CPU TTS, ONNX, optional onnxruntime-gpu
on Linux only). These run as Hermes *providers* wherever Hermes runs (gateway
host), so on the Mac they'd need the command-provider/server wrap like
Kokoro; they're primarily benchmark candidates.

## Docker-on-macOS hardware reality (corrects the acceleration assumption)

- Docker on macOS (Docker Desktop/colima/OrbStack) runs containers in a Linux
  VM. **There is no Apple GPU (Metal/MPS) passthrough to containers on macOS
  — at all.** "Forwarding hardware acceleration" into Docker on the Mac is not
  possible; that's a Linux+NVIDIA/KVM capability.
- Consequence: a Dockerized Mac voice service is **CPU-only**. That is
  workable: Kokoro-82M (ONNX/PyTorch CPU) and NeuTTS Air Q4 GGUF are
  CPU-first, and whisper.cpp / faster-whisper int8 at base/small/medium sizes
  are comfortably real-time on M-series CPUs.
- If CPU-Docker benchmarks disappoint, the alternative is **not** GPU-in-Docker
  but a **native macOS service** (launchd/uv venv) using MLX (mlx-whisper,
  mlx-audio/Kokoro-MLX) — full GPU, but no container isolation. Decision point
  after benchmarks.

## Balance plan: "responsive both sides, fast AND accurate" benchmark matrix

Latency is dominated by chunking (Hermes streams sentence-by-sentence, min 20
chars) + per-chunk synthesis time. Measure on the Mac (Docker CPU first):

| Candidate | Role | Metric targets |
|---|---|---|
| Kokoro-82M (Kokoro-FastAPI, CPU backend) | TTS quality baseline | RTF ≤ 0.3, time-to-first-audio ≤ 400 ms/sentence |
| NeuTTS Air Q4 GGUF | TTS, voice-clone option | RTF ≤ 0.3; subjective MOS vs Kokoro |
| KittenTTS nano int8 | TTS latency floor | RTF ≤ 0.1; quality acceptable? |
| Piper (lessac-medium) | TTS fallback | RTF ≤ 0.05; naturalness check |
| whisper.cpp (base/small/medium/large-v3-turbo, int8) | STT | RTF vs WER on a 20-prompt test set incl. technical vocab |
| faster-whisper int8 (Speaches/FW-server container) | STT alt | same, plus OpenAI-compat API for free |

Method: fixed 20-sentence test set (ops/infra vocabulary, numbers, code-ish
terms — the hard cases for STT), same audio, measure RTF, time-to-first-audio,
and WER (STT) / MOS-style listening (TTS). Winner must satisfy: full reply
playback starts before generation finishes (sentence streaming hides synthesis
when RTF < 1) and STT WER ≤ ~5% on the test set. If only native-MLX meets
both, that decides Docker-vs-native too.


## Source verification status — installed gateway 0.21.2 (checked 2026-09-14)

Verified directly in the deployed source tree (`/opt/hermes/…`, editable
install of hermes-agent 0.21.2):

- `voice.client_direct` gate exists and defaults true
  (`hermes_cli/config_defaults.py:1125`); enforced in
  `hermes_cli/web_routers/audio.py:154`.
- `GET /api/audio/voice-config` endpoint exists
  (`hermes_cli/web_routers/audio.py`, `tools/voice_client_config.py`).
- STT endpoint overrides honored: `STT_OPENAI_BASE_URL`,
  `GROQ_BASE_URL` (`tools/transcription_common.py:26-27`) — read at module
  import ⇒ gateway restart required after setting.
- TTS endpoint override honored: `tts.openai.base_url` config key
  (`tools/tts_tool_openai.py:58,102-104`; config beats auth-chain default).
  With `base_url` set, the managed-gateway model allowlist is bypassed.
- STT/TTS command-provider seams present
  (`tools/transcription_command.py`, `agent/transcription_registry.py`).
- GPT-Live (`gpt-live-1`) is NOT in 0.21.2 — docs-only feature; not part of
  this design.

## Remaining work

Gateway-side (DarkAgent, no Mac access needed):
1. End-to-end relay test: mock OpenAI-compatible audio server in the cluster +
   `voice.client_direct: false` + real desktop→gateway voice turn; confirm
   dictation relay and streaming speech WS.
2. Capture the exact transcription request params Hermes sends
   (file/model/language/prompt fields) and confirm the chosen Mac server
   tolerates them.
3. Per-profile voice isolation: confirm profile-scoped config.yaml so only the
   interactive chat profile routes to the Mac service.

Mac Ultra (requires Michael's authorization/hands — boundary):
4. Install + benchmark Kokoro-FastAPI (MLX backend) and the chosen whisper
   server; RTF on real hardware.
5. Exposure plan: Tailscale/LAN, TLS + bearer token (e.g. Caddy front),
   endpoint naming; auth token distribution to the gateway via
   `env_passthrough` (command providers) or provider api_key config.

Research to delegate (Research Hermes):
6. STT server pick: Speaches vs whisper.cpp server vs faster-whisper-server
   (OpenAI-compat completeness, Apple Silicon GPU paths, streaming, auth).
7. Kokoro-FastAPI on macOS/MLX status (or MLX-Kokoro alternative), auth story,
   streaming behavior.

Decisions (Michael):
8. Model sizes (kokoro-82M; whisper large-v3-turbo vs medium) — latency vs
   accuracy on Mac Ultra.
9. Offline-Mac fallback policy: voice fails gracefully vs auto-fallback to a
   cloud provider (default proposal: fail, per "no audio off-Mac").
