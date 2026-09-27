# Mac local ChatGPT-style voice (gpt-live) — status & root cause, 2026-09-20

## Verdict

**The local stack works. The break was DarkAgent's own `config.yaml` — now fixed and
verified.** The desktop was never at fault for the 401.

## What was actually broken

`/hermes-home/config.yaml` had lost the entire `tts:` block and `voice.gpt_live.base_url`.
With `voice.gpt_live.base_url` absent, `tools/voice_live.py::_resolve_credentials()`
falls back to `DEFAULT_LIVE_BASE_URL = https://api.openai.com/v1`. The gateway
therefore POSTed the WebRTC SDP offer to **api.openai.com** with the placeholder key.

Signature in `/hermes-home/logs/agent.log`:

```
tools.voice_live: GPT-Live session creation failed: 401 {
  "code": "missing_authorization",  ... }   # OpenAI's own error shape
```

Timestamps: 2026-09-18 21:05, 2026-09-19 17:17, 2026-09-20 17:51 — all **before** the
config was restored (config written 20:28, gateway restarted 20:40). The bridge has no
auth layer at all, so a 401 could never have come from it.

## Verified working 2026-09-20 22:2x UTC

| Check | Result |
|---|---|
| Speaches health `:8000/health` | `OK` |
| Kokoro TTS → Whisper STT roundtrip | 100% accurate, exact sentence back |
| LM Studio `:1234` | `qwen/qwen3.6-35b-a3b` loaded |
| Bridge code on Mac vs workspace copy | identical md5 `211a3b33f91920fc87532427e05a5ef6` |
| Bridge handshake + TTS out (`selftest_client.py`) | connected, 281 audio frames, peak RMS 1985 → speech heard |
| Mic→VAD→Whisper→delegation (`selftest_speech.py`) | transcript exact incl. "DarkAgent", 1 delegation emitted |
| Gateway `tools.voice_live.create_webrtc_session()` with live config | base_url → `http://michaelacstudio.darknet:8899/v1`, `sess_105cde6e8367`, answer SDP 1365 B |
| Leaked bridge sessions | cleared via launchd kickstart → `sessions:0` |

Resolved config: `voice.gpt_live = {model: local-live, voice: af_heart,
base_url: http://michaelacstudio.darknet:8899/v1, api_key: local}`,
`voice.client_direct: false`, `voice.voice_chat_mode: gpt-live`.

## Still open — the "rigid / cuts me off" half

The desktop conversation loop **still hardcodes VAD** upstream v0.17.6:

`apps/desktop/src/app/chat/composer/hooks/use-voice-conversation.ts:246-248`
```ts
silenceLevel: 0.075, silenceMs: 1_250, idleSilenceMs: 12_000,
```

Nothing in `apps/desktop/src/` reads `voice.silence_duration` / `voice.silence_threshold`.
Michael's running app is `/Applications/Hermes.app` v0.17.6 (built 2026-09-20 16:04); the
checkout at `~/.hermes/hermes-agent` is **clean** — the VAD patch is NOT applied.

→ Mid-sentence cutoffs after 1.25 s of pause are a desktop-app issue, NOT a config issue.
Fix = apply `desktop-vad-patch/0002-…patch`, rebuild `npm run dist:mac`, Cmd+Q and relaunch.

## Test procedure after any change

1. Michael: fully quit Hermes Desktop (Cmd+Q) — voice config is cached per session.
2. Reopen, start voice. Speak a sentence with a deliberate mid-thought pause.
3. Watch the bridge live: `ssh michael@192.168.1.2 'tail -f ~/gpt-live-bridge/bridge.err.log'`
   Expect: `user said: …` → `settled turn: …` → `delegating to Hermes …` → spoken reply.

## Ops notes

- Clear leaked sessions: `ssh michael@192.168.1.2 'launchctl kickstart -k gui/$(id -u)/com.hermes.gptlive.bridge'`
- Gateway 401-shape triage: OpenAI error JSON = gateway used the default base_url (config
  problem). Bridge has no auth; a bridge-side failure shows in `bridge.err.log`.
- `moa.enabled: false` — re-enabling MoA would re-introduce the ~2m23s stall seen on 09-17.
- 2026-09-21T00:35:03.150428+00:00 — PASS health: Speaches OK; bridge OK, sessions=0. PASS config: tts/stt present, enabled STT, both local :8000/v1; live base_url http://michaelacstudio.darknet:8899/v1. PASS gateway: PID 146 environment resolution returns Mac DNS base_url, no OpenAI regression. PASS SSH: pinned fingerprint verified (known_hosts stored in runtime scratch, not /tmp). Desktop validation outstanding: last 60 bridge log lines contain no attempts after 2026-09-20 22:30 UTC (Mac EDT; last session 22:28:08 UTC); earlier delegation timed out at 22:25:07 UTC. Known desktop 1.25s VAD issue remains separate. Next: Cmd+Q Hermes Desktop, relaunch, start voice mode and test. No bridge or gateway changes.
