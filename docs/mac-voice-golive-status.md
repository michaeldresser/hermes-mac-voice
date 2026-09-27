# GO-LIVE STATUS — Mac voice for DarkAgent (2026-09-14 ~23:15Z)

## LIVE NOW

- **TTS: ✅ live through the gateway.** `text_to_speech_tool(provider=openai)`
  → Mac Speaches Kokoro → MP3 delivered. Verified 23:11Z.
- **STT: ✅ live** (gateway startup order replicated: dotenv load → import).
  Transcription of a real speech sample returned **100%-accurate text**
  ("Deploy the swarm controller to staging and verify the checkpoint before
  restarting the gateway services tonight.") — perfect roundtrip with the
  Mac's own Kokoro TTS. Large-v3-turbo is picking up the ops vocabulary
  flawlessly.

## Final topology (all DNS-based, no IP locking)

```
Mac mic → Hermes Desktop ──▶ DarkAgent gateway (:9419)
                             ├─ STT: POST michaelacstudio.darknet:8000/v1/audio/transcriptions
                             │        model=deepdml/faster-whisper-large-v3-turbo-ct2
                             └─ TTS: POST michaelacstudio.darknet:8000/v1/audio/speech
                                      model=speaches-ai/Kokoro-82M-v1.0-ONNX voice=af_heart
       remote agents (LLM-RQ routes) ◀── text only ──▶
Mac speakers ◀── gateway relays audio back to Desktop ──┘
```

Single server on the Mac (Speaches :8000) does BOTH STT and TTS.
Kokoro-FastAPI on :8880 is also up and can serve as a TTS alternate.

## Config applied

- `.env`: STT_OPENAI_BASE_URL=http://michaelacstudio.darknet:8000/v1 (line 432)
- config.yaml: stt.enabled/provider=openai + model deepdml/…-turbo-ct2 +
  api_key placeholder; tts.provider=openai + Kokoro model/af_heart/base_url +
  api_key placeholder; voice.client_direct: false
- Gateway restarted (PID 20126) — dotenv loader confirmed exporting
  STT_OPENAI_BASE_URL at startup (functional test, not just /proc).

## Notes discovered during go-live

- Speaches model registry has no Systran turbo; used
  deepdml/faster-whisper-large-v3-turbo-ct2 (standard CT2 turbo conversion).
- Speaches requires the exact installed model id in each request — Hermes'
  `stt.openai.model` now carries it.
- api_key placeholders (`mac-voice-local`) required by Hermes' credential
  chain; Speaches ignores them. If the Mac service is ever exposed beyond
  LAN, replace with a real token (conformance test checks auth).
- /proc/PID/environ shows exec-time env only; dotenv mutations are runtime —
  functional verification is the reliable check.

## Desktop VAD smoking gun (2026-09-15)

Desktop `use-voice-conversation.ts` HARDCODES the voice loop VAD — it does NOT
read `voice.silence_duration`/`voice.silence_threshold` from config:

```ts
// VAD tuning mirrors `tools.voice_mode` defaults so the browser loop matches the CLI.
await handle.start({ silenceLevel: 0.075, silenceMs: 1_250, idleSilenceMs: 12_000, ... })
```

So desktop speech pauses get cut off after **1.25 s** regardless of our config
(8s). This explains the "rigid loop / mid-thought cutoff" complaint; config
changes never applied to the desktop loop. Fix path: upstream PR to read the
profile's voice config (values already flow via gateway REST) with hardcoded
values as fallback; interim option is a tiny post-update re-appliable patch on
the Mac. Fork rejected (drift risk). Semantic endpointing (pipecat smart-turn
v3, ONNX, Mac-local) remains the bigger ChatGPT-style upgrade, opt-in via a
`voice.turn_detection` config later.

## Go-live debugging log (2026-09-14 23:15 – 2026-09-15 00:05)

1. **23:15 — desktop voice failed "Microphone access denied"**: known upstream
   bug #43788 — the running desktop Electron bundle is ad-hoc signed, so TCC
   binds the mic grant to a ghost identity. Michael updated the desktop
   (post-Aug-26 builds carry the stable-signing fix series #73681/#95091/
   #95125/#95283) — mic then worked.
2. **23:25 — STT 401 from real OpenAI with placeholder key**: gateway process
   had started at 23:18:55, the exact second of the .env edit → import-time
   `STT_OPENAI_BASE_URL` read the pre-edit (commented) value. Also
   `hermes gateway restart` no-op'd (PID unchanged). Fix: kill -9 the
   process; s6 supervisor respawned fresh.
3. **23:56 — 401 recurred from the DESKTOP side**: desktop held a stale
   client-direct voice config (base_url default + placeholder key); gateway
   logs showed zero /api/audio hits, proving the desktop was calling OpenAI
   directly, not relaying. Hardening: `stt.openai.base_url` now ALSO set at
   config level (belt-and-braces with the env var), so every resolution path
   — gateway import, voice-config client-direct, relay — points at the Mac.
   Gateway restarted fresh (PID 22704, 00:01:45); functional re-check green.
4. Desktop-side requirement: fully QUIT Hermes Desktop (Cmd+Q) and reopen —
   voice config is cached per session; a window close may not clear it.

## Remaining

- Michael: live voice test from Hermes Desktop (click voice button, talk).
  The desktop→gateway audio relay endpoints call the exact functions proven
  above. `/voice on` on desktop; client_direct=false forces relay through
  the gateway, which now points at the Mac.
- Watchdog cron 9ee49698e9d0 can be removed once Research thread
  reconciliation is no longer wanted (Research still silent; results already
  self-executed and integrated).
