# Desktop voice VAD fix kit — v2: desktop-only patch, zero server changes (2026-09-15)

## REDESIGN after deployment attempt

Patch 0001 (server-side `voice_client_config.py`) is **dead**: `/opt/hermes` on
darkagent is a root-owned image layer, uid 10000 has no write access, no sudo.
Not fighting that — a better path exists that needs **no server change at all,
on any agent, ever**:

The desktop already has `getHermesConfig()` (`apps/desktop/src/api/config.ts`)
→ `GET /api/config` — the exact endpoint the dashboard Settings page uses,
present on every Hermes gateway. `voice.silence_duration` /
`voice.silence_threshold` are plain config keys already served by that
endpoint. The desktop patch can read VAD tuning straight from there.

## What this means for "do I patch every agent?"

**No. Server-side: nothing, anywhere.** The only patch is the desktop app on
Michael's Mac. Any gateway (darkagent, any future one) serves `/api/config`
with the `voice` block out of the box; a gateway whose config lacks the key
falls back to the current hardcoded values. Old behavior never breaks.

## Files

- `desktop-vad-patch/0002-desktop-use-configured-voice-vad-tuning.patch`
  — **v2, rewritten** to read from `getHermesConfig()` instead of
  `fetchVoiceClientConfig()`. Applies to current upstream `main`
  `use-voice-conversation.ts` (sha 55978c42…). Fallbacks preserved.
- `0001-…voice_client_config…patch` — kept for the record / upstream PR
  discussion (server-side exposure of the voice section remains the *nicer*
  upstream design — goes through the same voice-config fetch the desktop
  already caches — but is NOT needed for the local fix and NOT deployable here
  without an image rebuild).

## Michael's Mac-side steps (his hands)

```bash
cd ~/.hermes/hermes-agent            # his checkout (confirm path)
git pull --ff-only
git apply /workspace/desktop-vad-patch/0002-desktop-use-configured-voice-vad-tuning.patch
cd apps/desktop && npm install && npm run dist:mac
# Cmd+Q old app, open release/mac-arm64/Hermes.app, re-grant mic if asked
```

Tuning after install: dashboard → Settings → Voice → Silence Duration (seconds).
Desktop picks it up on the next voice session (config cache TTL ~60s).

Rollback: `git checkout -- apps/desktop/src/app/chat/composer/hooks/use-voice-conversation.ts`
→ rebuild.

## Upstream tracking (unchanged in intent)

- File the issue: desktop conversation loop hardcodes VAD (0.075 / 1250ms /
  12000ms), ignoring documented `voice.silence_*` config keys that CLI/TUI
  honor. Evidence in this file.
- PR proposal for upstream (their choice of shape): read config in
  `use-voice-conversation.ts` via existing `getHermesConfig()` (minimal), or
  extend `/api/audio/voice-config` with a `voice` section (cleaner long-term;
  server-side part is upstream's to ship since it requires image rebuilds).
- Watch releases for the fix; when shipped: `git checkout` the file, rebuild,
  done — fully stock again.
