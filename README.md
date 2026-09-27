# hermes-mac-voice — local-first TTS/STT for Hermes Desktop on the Mac

Local-first voice for Hermes: **all audio is processed on the Mac Studio and never leaves it.**
Speech-to-text, text-to-speech, and the real-time turn-taking bridge all run as services on
`michaelacstudio.darknet` (Mac Studio M3 Ultra, macOS 26.3, arm64). A remote Hermes gateway
relays audio to the Mac; no other machine ever sees a waveform.

Status: **live in production** for Michael's desktop voice usage. Verified 2026-09-26.

---

## 1. Architecture

```
┌─────────────────────────┐        ┌──────────────────────────────────────────────┐
│  Hermes Desktop (Mac)   │        │  Remote Hermes gateway (homelab cluster)     │
│  /Applications/Hermes   │        │  /hermes-home/config.yaml                    │
│  .app  v0.17.6+patched  │        │                                              │
│                         │        │  voice.voice_chat_mode: gpt-live             │
│  voice loop:            │        │  voice.client_direct:   false  ── RELAY      │
│   - mic capture         │        │  tts.provider: openai                        │
│   - VAD / endpointing   │        │    base_url → michaelacstudio.darknet:8000   │
│   - Cmd+Q to pick up    │        │  voice.gpt_live.base_url                     │
│     config (per-session)│        │    → michaelacstudio.darknet:8899            │
└───────────┬─────────────┘        └───────────────┬──────────────────────────────┘
            │  audio (relay)                       │  HTTP (LAN)
            └──────────────────────────────────────┘
                                                  │
        ┌─────────────────────────────────────────▼─────────────────────────────┐
        │                     Mac Studio  michaelacstudio.darknet                │
        │                                                                        │
        │  ┌────────────────────┐  ┌──────────────────┐  ┌────────────────────┐  │
        │  │ Speaches  :8000    │  │ kokoro-fastapi   │  │ gpt-live bridge    │  │
        │  │ (Docker, cpu)      │  │ :8880 (Docker)   │  │ :8899 (native,     │  │
        │  │                    │  │ secondary TTS    │  │  launchd, Python)  │  │
        │  │ STT:               │  │                  │  │                    │  │
        │  │  /v1/audio/        │  │                  │  │ STT ← Speaches     │  │
        │  │   transcriptions   │  │                  │  │ TTS → Speaches     │  │
        │  │  faster-whisper-   │  │                  │  │ LLM → LM Studio    │  │
        │  │   small            │  │                  │  │   :1234/v1         │  │
        │  │ TTS:               │  │                  │  │ turn-taking:       │  │
        │  │  /v1/audio/speech  │  │                  │  │  SILENCE_MS 900    │  │
        │  │  Kokoro af_heart   │  │                  │  │  SETTLE_MS  5000   │  │
        │  └────────────────────┘  └──────────────────┘  └────────────────────┘  │
        │                                                                        │
        │  all three bind locally; HF model cache in Docker volume               │
        │  no audio ever leaves this box in either voice mode                     │
        └────────────────────────────────────────────────────────────────────────┘
```

Two voice modes are wired, both landing on the same Mac services:

| Mode | Path | Notes |
|---|---|---|
| `chained` (default) | STT → agent brain → TTS, sentence-by-sentence | used for agent work |
| `gpt-live` | full-duplex WebRTC to a *local* live model via the bridge:8899 | ChatGPT-style conversational feel; the bridge owns turn-taking |

`voice.client_direct: false` is deliberate: it forces the **relay** path so the audio is
processed by the Mac services through the gateway rather than the desktop calling a cloud
provider. With a remote profile, `stt.provider: local` means local *to the gateway host*, which
is exactly why the engines are addressed by DNS name instead.

---

## 2. Components

### 2.1 Speaches — the STT/TTS engine (`:8000`)

Docker, image `ghcr.io/speaches-ai/speaches:latest-cpu`, `--restart unless-stopped`,
`Cmd = uvicorn --factory speaches.main:create_app`, health endpoint `/health` → `200`.

- **STT**: `POST /v1/audio/transcriptions` — model `Systran/faster-whisper-small`
- **TTS**: `POST /v1/audio/speech` — model `speaches-ai/Kokoro-82M-v1.0-ONNX`, voice `af_heart`
- OpenAI-compatible surface, which is why Hermes' stock `tts.provider: openai` needs no plugin:
  only a `base_url` pointing at the Mac.
- Telemetry off (`DO_NOT_TRACK`, `DISABLE_TELEMETRY`, `HF_HUB_DISABLE_TELEMETRY`,
  `GRADIO_ANALYTICS_ENABLED=False`); models cached in the `speaches_hf-hub-cache` volume.

### 2.2 kokoro-fastapi (`:8880`)

Docker, image `ghcr.io/remsky/kokoro-fastapi-cpu:latest`. Secondary TTS; Speaches' Kokoro path
is what production uses.

### 2.3 gpt-live bridge (`:8899`) — the piece that makes voice feel conversational

Native Python 3 process, **not** containerised, supervised by launchd
(`~/Library/LaunchAgents/com.hermes.gptlive.bridge.plist`, `RunAtLoad`, `KeepAlive` true,
logs to `bridge.log` / `bridge.err.log`).

The Hermes gateway treats it as an OpenAI-compatible live endpoint
(`voice.gpt_live.base_url = http://michaelacstudio.darknet:8899/v1`). Its job:

1. Accept the session/WebRTC handshake from the gateway.
2. Capture mic audio, run VAD with a 900 ms silence threshold.
3. Transcribe through Speaches **while the user is still speaking**.
4. Wait `SETTLE_MS=5000` to confirm the turn actually ended.
5. Generate the reply from LM Studio (`LLM_URL=127.0.0.1:1234/v1`).
6. Speak it via Speaches TTS (`af_heart`, speed 1.2), streaming frames back.
7. Emit a delegation when the turn needs real tool work — the bridge is a conversational
   front-end, **not** an agent brain.

Runtime configuration is entirely in the plist environment (see `mac-services/`), so tuning is
a plist edit + `launchctl kickstart`, no rebuild.

> **Why a bridge instead of the stock path?** The stock `gpt-live` mode targets OpenAI's
> cloud `gpt-live-1` (~$0.05/min, audio leaves the building). Pointing `voice.gpt_live.base_url`
> at a local endpoint keeps the whole loop on the Mac. See §5 for the failure mode this creates
> if the key is missing.

### 2.4 Desktop app patches — the VAD fix

Upstream Hermes Desktop hardcodes its end-of-speech detection and **ignores** the documented
`voice.silence_duration` / `voice.silence_threshold` keys that the CLI and TUI honour:

`apps/desktop/src/app/chat/composer/hooks/use-voice-conversation.ts`
```ts
await handle.start({ silenceLevel: 0.075, silenceMs: 1_250, idleSilenceMs: 12_000, ... })
```

Effect: any pause > 1.25 s mid-thought cuts the recording, fires a partial transcript, and audio
spoken during the transcribe/reply gap is dropped. Raising `voice.silence_duration` fixed
CLI/TUI but never the desktop — that mismatch *is* the bug.

| Patch | Target | What it does |
|---|---|---|
| `0002-desktop-use-configured-voice-vad-tuning.patch` | `use-voice-conversation.ts` | reads `voice.silence_duration` (s → ms) and `voice.silence_threshold` (int16 RMS → browser float 0.02–0.3) from `GET /api/config`; falls back to the old literals if absent |
| `0003-desktop-streaming-transcription.patch` | `use-voice-conversation.ts`, `use-mic-recorder.ts` | `rotate()` re-starts MediaRecorder on the same mic stream so the mic is never released mid-utterance; transcribes a segment every `voice.stream_segment_seconds`; tail-only transcription + `joinTranscript()` (word-then-character overlap strip) at submit |
| `0001-...-OPTIONAL-UNDEPLOYED.patch` | server-side `/api/audio/voice-config` | proposed upstream shape; **not deployed** (needs a gateway image rebuild) |

Apply order **0002 then 0003** — 0003 edits a file 0002 has already touched. Both patches are
revision-sensitive: update the checkout to `main` first.

Revert paths, least to most invasive: (1) `voice.stream_transcribe: false` (config only,
instant); (2) run `/Applications/Hermes.app`, which is never patched; (3) `git checkout` the two
hook files and rebuild.

### 2.5 Semantic endpointing — researched, benchmarked, **not yet implemented**

The measured successor to the settle-timer. Model: pipecat Smart Turn v3.2, ONNX int8, ~8 M
params. Full study + raw JSON in `research/semantic-endpointing/`.

| Question | Measured answer (Mac Studio M3 Ultra) |
|---|---|
| Needs a GPU? | **No.** ~8.7 MB int8, 14–17 ms per turn decision on 4 CPU threads (+4.5 ms Whisper featurizer), run once per VAD pause — not per frame |
| CoreML / ANE? | **Slower** — 34.7 ms int8 vs 9.3 ms on 8 CPU threads, plus a 1.5 s session build. Do not use the GPU path |
| Accuracy (900 labelled clips) | 85.8% overall; COMPLETE recall 95.8%, INCOMPLETE 76.6%; median p 0.984 vs 0.012 |
| Why it matters | today's pure-VAD rule calls **every** ≥900 ms pause an end-of-turn (100% false-COMPLETE on mid-turn pauses). At threshold 0.7 the model is wrong on ~20.8% → ~4× fewer premature cutoffs, and `SETTLE_MS` can drop 5000 → ~600 ms (~4.4 s faster per turn) |
| Placement | in-process in `bridge.py`, native Mac, CPU, 4 threads |

The measured implementation is the work that is left: benchmark scripts and validation results
exist, the integration into `bridge.py` does not.

---

## 3. Config surface (all gateway-side, no rebuild to tune)

Live values, from the serving profile's `config.yaml`:

```yaml
tts:
  provider: openai
  openai:
    model: speaches-ai/Kokoro-82M-v1.0-ONNX
    voice: af_heart
    base_url: http://michaelacstudio.darknet:8000/v1
    api_key: local
    speed: 1.2
voice:
  voice_chat_mode: gpt-live
  gpt_live:
    model: local-live
    voice: af_heart
    base_url: http://michaelacstudio.darknet:8899/v1
    api_key: local
  max_recording_seconds: 600
  auto_tts: true
  client_direct: false        # force RELAY — audio goes to the Mac, not to a cloud API
  beep_enabled: true
  silence_threshold: 120      # mic sensitivity, int16 RMS; lower = quieter speech counts
  silence_duration: 8         # seconds of quiet before the turn submits
  stream_transcribe: true     # patch 0003 master switch; false = stock behavior
  stream_segment_seconds: 2   # streaming capture segment length, clamped 1–6
```

Tuning without a rebuild: dashboard → Settings → Voice for the `silence_*` pair;
`hermes config set` for `stream_*` (not in the dashboard schema). **The desktop caches voice
config per session — Cmd+Q before expecting a new value to take effect.**

Threshold mapping in patch 0002: `level = clamp(0.02, 0.3, threshold / 32767 * 12.5)`
(200 → ≈0.076 ≈ old default; 120 → ≈0.046, more sensitive to quiet speech).
`silenceMs = duration * 1000`, `idleSilenceMs = max(silenceMs, 12000)`.

**Secrets:** this repo carries no credentials. `api_key: local` is a placeholder the local
services ignore, and the engine addresses are the LAN DNS name `michaelacstudio.darknet`.

---

## 4. Deployment & verification

Full operating runbooks are in `docs/`. Deploying the desktop patches:

```sh
cd ~/.hermes/hermes-agent
git fetch && git checkout main && git pull --ff-only
git apply .../0002-desktop-use-configured-voice-vad-tuning.patch
git apply .../0003-desktop-streaming-transcription.patch
cd apps/desktop && npm install --no-audit --no-fund
npm run build                                    # vite renderer FIRST
env CSC_IDENTITY_AUTO_DISCOVERY=false npm run builder -- --mac -c.mac.identity=-
osascript -e 'quit app "Hermes"'
open apps/desktop/release/mac-arm64/Hermes.app
```

### Gotchas that cost real time (do not rediscover these)

1. **Codesigning fails over SSH.** `electron-builder` finds Michael's *Apple Development* cert
   and dies with `errSecInternalComponent` — the login keychain is only unlocked in a GUI
   session. Build ad-hoc (`CSC_IDENTITY_AUTO_DISCOVERY=false`, `-c.mac.identity=-`). Do **not**
   try to unlock the keychain.
2. **`npm run builder` alone produces an empty app.** The renderer lives in `dist/`, generated
   by `npm run build` (vite). Skip it and `app.asar` has no app code — the bundle looks fine and
   does nothing. Always `build` *then* `builder`.
3. **Patches are revision-sensitive.** Apply against `main`; `git apply --3way` as a fallback.
4. **Verifying the patch actually shipped:** the renderer is stored **unpacked** at
   `Hermes.app/Contents/Resources/app.asar.unpacked/dist/assets/*.js`. Minification renames
   identifiers (`getHermesConfig` → 0 hits) but keeps string/property names — grep for the
   config-key literals instead: `stream_segment_seconds`, `stream_transcribe`, `silence_duration`.
5. **Mic permission binds to the code-signing identity** — re-grant after every ad-hoc rebuild.
6. **Never ship this as `curl … | bash`.** Michael rejected that shape for the Mac; transfer over
   the verified SSH channel and review first.

### Verification assets in this repo

| Script | What it proves |
|---|---|
| `mac-services/selftest_client.py` | bridge handshake + TTS out (expects connected, ~281 audio frames, peak RMS ~1985) |
| `mac-services/selftest_speech.py` | mic → VAD → Whisper → delegation, transcript exact incl. the wake word |
| `mac-services/regress_two_utterances.py` | two-utterance regression on the bridge |
| `research/semantic-endpointing/validate.py` | smart-turn accuracy against the 900-clip labelled set |
| `verification/mac-voice-conformance-test.sh` | end-to-end conformance sweep across all services |

Measured live checks (2026-09-26): Speaches `/health` → `200`; Kokoro TTS → Whisper STT
roundtrip 100% accurate; bridge handshake OK with a 1365-byte answer SDP; gateway resolves the
Mac DNS base_url with no OpenAI regression.

---

## 5. Known gaps / traps

- **Missing `voice.gpt_live.base_url` silently sends audio to OpenAI.** `tools/voice_live.py::
  _resolve_credentials()` falls back to `DEFAULT_LIVE_BASE_URL = https://api.openai.com/v1`, so
  the gateway POSTs the SDP offer to the cloud with a placeholder key and returns
  `401 {"code": "missing_authorization"}`. That error shape is **OpenAI's**, not the bridge's —
  a bridge-side failure shows up in `bridge.err.log` instead. Diagnose by error shape.
- **Leaked bridge sessions** are cleared with
  `launchctl kickstart -k gui/$(id -u)/com.hermes.gptlive.bridge` → expect `sessions:0`.
- **`moa.enabled` must stay `false`** — re-enabling re-introduces a ~2 m 23 s stall in the live path.
- **Semantic endpointing is not implemented** (§2.5) — the settle timer is still in charge.
- **Patch 0001 is undeployed** — server-side voice config would need a gateway image rebuild.
- **The desktop VAD bug is still upstream.** File it; delete the local patches once a release
  contains the fix (check that `silenceMs: 1_250` is gone from `main`). Related upstream threads:
  RFC #77111 (duplex voice provider ABC), #96928 (streaming STT).
- **faster-whisper is CPU-only on Apple Silicon** (no MPS/Metal) — irrelevant here since the
  engines run in Docker on CPU by design, but do not expect a Metal speedup.

---

## 6. Repository layout

```
README.md                     this file
docs/                         operating runbooks (SSH access, gpt-live 502 triage, VAD reapply, endpointing)
mac-services/                 the Mac stack: bridge.py, launchd plist, container inspect, selftests
desktop/patches/              desktop VAD + streaming-transcription patches
desktop/                      deploy scripts and the end-to-end Mac build runbook
config/                       voice/tts/stt config surface (redacted example)
research/semantic-endpointing/ benchmark scripts, raw results, verdict, integration plan
verification/                 conformance suite + recorded expected results
```

## Provenance

Built and verified on `michaelacstudio.darknet` (Mac Studio M3 Ultra, macOS 26.3, arm64) and the
DarkAgent homelab cluster, 2026-09-14 → 2026-09-26. The `bridge.py` currently on the Mac matches
the archived copy by md5 `211a3b33f91920fc87532427e05a5ef6`.
