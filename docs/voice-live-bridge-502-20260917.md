---
title: Mac GPT-Live voice bridge — architecture, verified state, 502 forensics
status: active
updated: 2026-09-17
scope: Hermes Desktop GPT-Live voice (DarkAgent gateway ↔ Mac bridge), 502 triage
owner: DarkAgent
---

# Mac GPT-Live voice bridge

## Topology (verified 2026-09-17)

```
Hermes Desktop (Mac, ~/.hermes/hermes-agent build)
  ├─ renderer POST /api/audio/voice-live/session  ─► Caddy
  │     darkagent-dashboard.darknetinternal.link → reverse_proxy http://darkagent_darkagent:9419
  │        → `hermes dashboard` (Dashboard host, tui_gateway) → tools/voice_live.py:create_webrtc_session()
  │        → POST {voice.gpt_live.base_url}/live/sessions  (= http://192.168.1.2:8899/v1/live/sessions)
  ─ WebRTC media (mic + speaker) ──► bridge on the Mac: /Users/michael/gpt-live-bridge/bridge.py
        STT/TTS: Speaches on the Mac (127.0.0.1:8000, faster-whisper-small / Kokoro af_heart)
        delegation: emits session.delegation.created → desktop turns it into a Hermes turn,
        Hermes' answer returns as session.commentary.append → bridge speaks it (Kokoro)
```

- launchd unit `com.hermes.gptlive.bridge` (user LaunchAgent), KeepAlive, logs
  `/Users/michael/gpt-live-bridge/bridge.log` (uvicorn/access) + `bridge.err.log` (app).
- DarkAgent gateway config: `voice.voice_chat_mode: gpt-live`, `voice.gpt_live.base_url: http://192.168.1.2:8899/v1`,
  `api_key: local`, `voice.client_direct: false`. The gateway only performs the SDP exchange; media is desktop↔bridge.
- Bridge log lines to read: `new session …`, `first mic frame: … ch=(FL, FR)`, `user said: …`,
  `delegating to Hermes …`, `speaking Hermes reply (n chars)`, `STT empty (utterance Xs)`, `delegation … timed out`.

## Verified state 2026-09-17 02:0x–02:2x UTC (bridge restarted clean)

- `curl http://127.0.0.1:8899/healthz` (from the Mac) → `{"ok":true,"sessions":0}` after
  `launchctl kickstart -k gui/$(id -u)/com.hermes.gptlive.bridge` cleared a stale session from the
  previous selftest (sessions leaked: selftest sessions are never closed by the client).
- Server-side SDP exchange proven from inside the DarkAgent container with the gateway's own config
  (`/tmp/voice_live_test.py`, offer generated on the Mac with the bridge venv):

  ```sh
  # offer on the Mac (bridge venv, aiortc) → /tmp/offer.sdp, then pull it into the container
  scp -i /run/secrets/darkagent_node_ssh_private_key -o IdentitiesOnly=yes -o BatchMode=yes \
      -o StrictHostKeyChecking=yes -o UserKnownHostsFile=/tmp/mac_known_hosts \
      michael@192.168.1.2:/tmp/offer.sdp /tmp/offer.sdp
  # run with the dashboard's env so config resolution matches the live process
  tr '\0' '\n' < /proc/147/environ > /tmp/dash_env.txt
  # → "OK session: sess_… answer_sdp_len: 2300", close 200
  ```
- Bridge access log shows the gateway (source IP **192.168.0.58** = swarm1, where the DarkAgent
  container runs) POSTing `/v1/live/sessions` → `200 OK`, so the container→Mac:8899 hop is open.

## 502 triage — what each hop leaves behind

| Hop | Failure visible as | Where it shows up |
|---|---|---|
| Desktop → Caddy | 502 with empty/Bad Gateway text; chat WS unaffected | Caddy has **no access log** for this host (`darkagent-dashboard…` has no `log` block) — *nothing server-side* |
| Caddy → `darkagent_darkagent:9419` | 502 "Bad Gateway" | container restart / DNS re-resolve window (seen 2026-09-16 22:22 UTC during the native4 deploy) |
| Dashboard route `/api/audio/voice-live/session` | 502 = `RuntimeError` caught at `web_routers/audio.py` **only** (any RuntimeError in the handler path becomes 502), 503 = missing key, 500 = anything else | `log.exception` only for the 500/`http_failure` path; the 502 branch logs **nothing** |
| Gateway → bridge | 502 to the client, and a bridge access line with a non-200 status | `bridge.log` |
| Bridge → Speaches/Hermes | no transcript / no reply, but the session exists | `bridge.err.log` |

Consequence: a **peak-period 502 with no bridge POST and no gateway log line** is consistent with either
(a) the ingress/upstream connection or (b) any `RuntimeError` inside the dashboard handler — neither of
which writes a log today. When it recurs, capture the **client-side detail text** (the desktop's
`hermesApi` surfaces `502: <detail>`; `detail` names the failing layer) before retrying.

## 2026-09-17 — live session found the text-loss bug (root cause + fix)

Michael's 22:20 EDT session (`sess_b6f6461d7a59`) showed the failure precisely:

```
22:20:46  user said: Go through and identify the latest.            -> delegated ALONE
22:20:47  user said: All right, I'm going to provide you with a few hand-off documents for PCBs...
          queued utterance (delegation in flight)
22:20:49  user said: And I'll provide you with GitHub links, so I want you to upload just the critical files...
          queued utterance (delegation in flight)
22:22:16  delegation dg_eb6f28d3b1ab timed out with no commentary; releasing
22:22:16  delegating to Hermes (2 queued merged)          <- 90 s late, session long over
```

Two defects, both fixed in `bridge.py` (backup `bridge.py.bak-20260916-222627`):

| Defect | Fix |
|---|---|
| No coalescing: the VAD closes an utterance on 0.9 s of silence, so one dictation becomes fragments and only the first is delegated | `_schedule_coalesced_delegation()` waits `DELEGATION_COALESCE_S` (2.5 s) and merges fragments — regression: two sentences 0.95 s apart produced **2 transcripts → 1 delegation** (`delegating to Hermes (2 queued merged)`) |
| Queued utterances were held until the answer or a 90 s watchdog, then dropped — the user's actual instruction never reached Hermes | watchdog 90 s → `DELEGATION_TIMEOUT_S` (30 s); `flush_queue()` releases the queue when the mic track ends and when a transcript arrives after it (supersedes the stale in-flight delegation); `close()` now logs stranded utterances and cancels the mic/coalesce/watchdog tasks (fixes `Task was destroyed but it is pending!`) |

Latency root cause found the same night (why there was no answer inside 90 s): the desktop
turn ran `model=default provider=moa` and the **MoA reference fan-out to the two unloaded
local models stalled ~2 m 23 s** before the aggregator was even called
(`02:20:47` references resolved → `02:23:10` aggregator; turn total 185.6 s):

```
local/google/gemma-4-e4b      -> hangs (not loaded in LM Studio; direct LLM-RQ probe: no reply in 60 s)
local/nvidia/nemotron-3-nano-4b -> same
```

Fix applied (`hermes config set`, backed up as `config.yaml.bak-voice502-20260917`):
`moa.presets.default.reference_models.{1,2}.enabled = false` (the legacy top-level
`moa.reference_models` block is not a recognized key in this version — left untouched).
Reference slots are filtered by `enabled` in `agent/moa_loop.py` (lines 801/1298), and the
preset is cached per config-file signature, so the change lands on the next turn without a
gateway restart. Re-enable only after confirming those models actually serve.

Also observed: `hermes` CLI and the gateway log `[secrets:command] helper failed; code=1 …`
— DarkAgent is running the native4 image without the secrets helper, so no secrets resolve
(see [[discord-fleet-outage-20260916]]); voice turns log
`named custom provider 'LLM-RQ' has no resolvable api_key` as a result.

## Cleanup / ops

- Clear leaked sessions: `launchctl kickstart -k gui/$(id -u)/com.hermes.gptlive.bridge` (healthz → `sessions:0`).
- Manual user-facing config (no rebuild): dashboard `darkagent-dashboard.darknetinternal.link` →
  Settings → Voice; `stream_*` keys via `hermes config set`. Desktop caches config per session → Cmd+Q first.
- Related: [[desktop-voice-vad-patch]], [[darkagent-mac-ssh]], [[discord-fleet-outage-20260916]]
  (the native4 image lost the secrets helper → DarkAgent ran with no secrets resolved, which also
  logs `named custom provider 'LLM-RQ' has no resolvable api_key` during voice turns).