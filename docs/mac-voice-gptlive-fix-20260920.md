---
title: Local ChatGPT-style voice (Mac Speaches + gpt-live bridge) — 401 root cause and fix
status: active
updated: 2026-09-20
scope: DarkAgent gateway voice.gpt_live config loss, bridge verification, desktop VAD gap
owner: DarkAgent
---

# Mac local ChatGPT-style voice — diagnosis and fix

Companion to [[voice-live-bridge-502-20260917]] (bridge internals) and
[[desktop-voice-vad-patch]] (desktop cutoffs).

## Rule 1: a 401 shaped like OpenAI's error means the gateway used the DEFAULT base_url

`tools/voice_live.py::_resolve_credentials()`:

```python
base_url = str(live.get("base_url") or DEFAULT_LIVE_BASE_URL).strip().rstrip("/")
# DEFAULT_LIVE_BASE_URL = "https://api.openai.com/v1"
```

The Mac bridge exposes **no auth layer at all** — it cannot return 401. So when
`agent.log` shows

```
tools.voice_live: GPT-Live session creation failed: 401
  {"code": "missing_authorization", "message": "You didn't provide an API key…"}
```

the gateway is talking to **api.openai.com**, which means `voice.gpt_live.base_url` was
missing/empty in the config the gateway loaded. Do not debug the bridge, the desktop, or
its mic — check the config first. Confirm with the resolution probe below.

## Rule 2: verify with the gateway's own code path, not curl

```python
# run with the gateway's env (tr '\0' '\n' < /proc/<gateway_pid>/environ)
import sys; sys.path.insert(0, "/opt/hermes")
from tools.voice_live import create_webrtc_session, _live_section, _resolve_credentials
k, b = _resolve_credentials(_live_section())      # b must be http://michaelacstudio.darknet:8899/v1
create_webrtc_session(open("/tmp/offer.sdp").read())   # → session id + non-empty answer SDP
```

Generate the SDP offer on the Mac with the bridge venv (`aiortc`, dummy audio track) and
`scp` it in — same technique as the 09-17 entry. A 200 from curl proves nothing here: the
fallback to api.openai.com is invisible to curl.

## Rule 3: config loss looks like "the service died" but is not

On 2026-09-20 the whole `tts:` block and `voice.gpt_live.base_url` were absent from
`/hermes-home/config.yaml` while Speaches, LM Studio and the bridge were all healthy.
Always diff the live config against the last-known-good `*.bak-*` before touching
services. The gateway only picks up provider/base_url changes on **process restart**
(it has since been restarted after the fix; the restore itself needs no bridge change).

## Rule 4: the bridge is unauthenticated and DNS-addressed — health first

- `curl http://michaelacstudio.darknet:8899/healthz` → `{"ok":true,"sessions":N}`.
- `sessions` counts **leaked** sessions: selftest/aborted clients never send `session.close`.
  A non-zero count is cosmetic but clear it anyway — `launchctl kickstart -k
  gui/$(id -u)/com.hermes.gptlive.bridge` (verified → `sessions:0`).
- `bridge.err.log` silence is meaningful: the pipeline logs on every detected utterance.
  No new lines during a user attempt = the desktop never reached the bridge.

## Rule 5: identify the MODE before naming a cutoff fix — the knob lives in a different place per mode

**Chained mode** (`voice_chat_mode: chained`) — the desktop runs its own conversation loop and
**hardcodes** `use-voice-conversation.ts`: `silenceLevel 0.075 / silenceMs 1250 /
idleSilenceMs 12000`, ignoring `voice.silence_*`. Verify before promising a knob:
`grep -rn "silence_duration" apps/desktop/src/` → empty = still hardcoded. Fix = desktop patch
+ rebuild ([[desktop-voice-vad-patch]]).

**gpt-live mode** (`voice_chat_mode: gpt-live`) — the desktop ships raw mic audio over WebRTC and
**the bridge does all turn detection**. The desktop's 1.25s hardcode is NOT in play, so a desktop
rebuild changes nothing here. Knobs are the bridge's env vars, set in
`~/gpt-live-bridge/com.hermes.gptlive.bridge.plist` (defaults in `bridge.py`):

| Env | Default | Meaning |
|---|---|---|
| `SILENCE_MS` | 900 | silence that closes one utterance |
| `SETTLE_MS` | 5000 | quiet before the utterance is delegated to Hermes — the "reasonably done talking" pause; each new utterance re-arms it |
| `SPEECH_RMS` | 450 | int16 RMS counted as speech |
| `BARGE_IN_RMS` | 900 | interruption threshold while the bridge speaks |
| `MIN_UTTERANCE_MS` / `MAX_UTTERANCE_MS` | 350 / 180000 | utterance bounds |

Change them in the plist, then
`launchctl kickstart -k gui/$(id -u)/com.hermes.gptlive.bridge` — **no desktop rebuild needed**.
Confirmed live 2026-09-20 (`SETTLE_MS=5000`, `SILENCE_MS=900`). True ChatGPT-style fluid
turn-taking beyond VAD tuning = semantic endpointing (pipecat smart-turn ONNX, Mac-local), still
an open upgrade.

Do not promise a desktop rebuild as the fix for gpt-live cutoffs — check the mode first.

## Full-stack verification set (all must pass)

| Layer | Command | Pass looks like |
|---|---|---|
| STT+TTS engine | Kokoro TTS → Whisper transcription of the same sentence | exact text back |
| Bridge handshake/TTS out | `selftest_client.py http://127.0.0.1:8899` | connected, 200+ frames, peak RMS > 300 |
| Mic→delegation | `selftest_speech.py http://127.0.0.1:8899 /tmp/speech-test.wav` | transcript + `session.delegation.created` |
| Gateway credentials | `resolve` probe above | host = Mac, not api.openai.com |
| Gateway session create | `create_webrtc_session(offer)` | session id + answer SDP |
| Desktop (Michael's hands) | Cmd+Q, relaunch, speak with a pause | `user said → delegating → spoken reply` in `bridge.err.log` |

Only the last row requires the user; rows 1–5 are fully DarkAgent-verifiable.