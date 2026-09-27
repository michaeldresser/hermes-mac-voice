# Mac ↔ Hermes voice integration — verified mechanics (2026-09-14)

Sources: live docs fetched today (`https://hermes-agent.nousresearch.com/docs/llms-full.txt`
→ local copy `/workspace/hermes-docs-llms-full-current.txt`, Voice Mode section,
plus the Hermes wiki desktop-app page under
`/workspace/artifacts/agentwikis-audit/pages/hermes/wiki/`). Supersedes the
deprecated `max-device-tts-stt-integration-plan.md`. Only keys/commands that
appear in the docs are used below.

## The rule that decides where STT/TTS runs

Desktop connected to a **remote gateway**:

- At voice-session start the desktop fetches the active profile's resolved
  STT/TTS settings (provider, model, language/voice, credential) from the
  gateway: `GET /api/audio/voice-config`, then calls providers **directly**
  from the Mac. Keys ride in desktop memory for the session only, never disk.
- **Client-direct wire support** (desktop → provider API, no audio via
  gateway): OpenAI (incl. Nous-managed audio), Groq, Mistral, DeepInfra (OpenAI-
  compatible shapes), xAI Grok STT, ElevenLabs STT + TTS. xAI via OAuth stays
  on relay.
- **Everything else — `stt.provider: local` (faster-whisper), `edge` TTS,
  command providers, plugins — falls back to the RELAY path**
  (`/api/audio/transcribe` + speech WebSocket) and therefore **runs on the
  gateway host, not on the Mac**.
- `voice.client_direct: false` forces relay for every provider. That is the
  only documented client-side knob.

So: with a remote profile, "local whisper" is local **to the gateway host**.
On-Mac on-device inference only happens when the desktop profile stays on its
local backend (desktop profiles can be local or remote per profile) or when
the gateway itself runs on the Mac.

## Topology A — STT/TTS fully on the Mac (local desktop profile)

Desktop profile stays on its local backend; agent brain is local.

```bash
pip install faster-whisper          # STT, no API key; ~150 MB model on first use
```

```yaml
stt:
  provider: "local"
  local:
    model: "base"        # tiny/base/small/medium/large-v3
tts:
  provider: "edge"       # free; or "neutts" (local, no key; device: cpu)
```

Constraints: faster-whisper is **CPU-only on Apple Silicon** (no MPS/Metal;
upstream requests #41659, #3491). base/small are fine on Mac Ultra CPU.
Reaching the remote agents (DarkAgent/Research) from this local brain happens
through Hermes Bus messages, not the live desktop chat session.

## Topology B — Remote brain, STT/TTS called from the Mac (client-direct)

Desktop profile points at the remote gateway (DarkAgent). The profile's STT/TTS
must be a client-direct-capable **cloud** provider:

```yaml
# on the gateway host, the profile Michael talks to
stt:
  provider: "groq"        # GROQ_API_KEY — free tier
  # or "openai" (VOICE_TOOLS_OPENAI_KEY/OPENAI_API_KEY), "mistral",
  # "xai", "elevenlabs", "deepinfra"
tts:
  provider: "elevenlabs"  # ELEVENLABS_API_KEY — client-direct TTS+STT
```

Audio hops: Mac → provider API → text → gateway. Nothing server-side carries
audio. Streaming TTS is sentence-by-sentence on every provider; barge-in and
the "stop" phrase work in both desktop voice modes.

## Topology C — Remote brain, STT/TTS on the gateway host (relay)

Profile keeps free/local providers; desktop relays audio to the gateway:

```yaml
stt:
  provider: "local"
  local:
    model: "base"
tts:
  provider: "edge"        # free, no key
```

Runs on the gateway host (homelab). Mac stays thin — no faster-whisper install
needed on the Mac. This is the zero-cost remote setup; the tradeoff is audio
crossing the LAN/WAN to the gateway.

## Integrating the lab's existing STT service (stt:8080)

Hermes has no built-in "custom STT URL" provider, but **command-type STT
providers** are the documented seam. On the gateway host:

```yaml
stt:
  provider: lab-whisper
  providers:
    lab-whisper:
      type: command
      # exact API shape of stt:8080 (beholder whisper server) must be verified first
      command: "curl -s -F file=@{input_path} http://stt:8080/inference -o {output_path}"
      format: txt
      timeout: 300
```

Notes from docs: placeholders `{input_path}/{output_path}/{language}/{model}`;
`format` = txt/json/srt/vtt; built-in names always win over same-name command
providers; command env has Hermes secrets scrubbed (`env_passthrough: [KEY]`
to pass specific vars); legacy single-command escape hatch =
`HERMES_LOCAL_STT_COMMAND`. Same pattern for TTS (`tts.providers.<name>:
type: command`) plus `warm_command`/`release_command` to preload/unload a
local TTS server (e.g. `curl -s localhost:5002/load?model={model}`).

## Full-duplex alternative (desktop): GPT-Live mode

```yaml
voice:
  voice_chat_mode: gpt-live   # chained (default) | gpt-live
  gpt_live:
    voice: marin
```

One WebRTC session desktop → OpenAI `gpt-live-1` (listens while speaking, no
tools; delegates real work to Hermes). Key stays on the gateway host
(`POST /api/audio/voice-live/session`); $0.05/min OpenAI billing; needs
`OPENAI_API_KEY`/`VOICE_TOOLS_OPENAI_KEY`/`voice.gpt_live.api_key`.

## Open items to verify on the installed stack

- `GET /api/audio/voice-config` + client-direct present in the running
  gateway/desktop build (docs are current; verify the deployed version).
- Exact HTTP API of `http://stt:8080` before writing the command provider.
- Whether ElevenLabs/Groq API keys exist in the vault for the cloud-provider
  topologies.
