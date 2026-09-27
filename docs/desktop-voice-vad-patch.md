---
title: Desktop voice VAD patch — reapply, revert, upstream tracking
status: active
updated: 2026-09-15
scope: Hermes Desktop (Mac) voice conversation loop; no server-side changes
owner: DarkAgent
---

# Desktop voice VAD patch — reapply, revert, upstream tracking

## Problem (why this exists)

Hermes Desktop's voice conversation loop hardcodes its end-of-speech
detection and ignores the documented `voice.silence_duration` /
`voice.silence_threshold` config keys (which the CLI and TUI loops honor):

`apps/desktop/src/app/chat/composer/hooks/use-voice-conversation.ts`
(upstream main, file sha `55978c42847469ee0cefdb92b477887617665efd` as of
2026-09-15):

```ts
// VAD tuning mirrors `tools.voice_mode` defaults so the browser loop matches the CLI.
await handle.start({ silenceLevel: 0.075, silenceMs: 1_250, idleSilenceMs: 12_000, ... })
```

Effect on the Mac: any pause > 1.25 s mid-thought cuts the recording,
fires a partial transcript, and speech during the transcribe/reply gap is
dropped. Raising `voice.silence_duration` in config (dashboard Settings →
Voice) fixed CLI/TUI but never the desktop — that mismatch is the bug.

Patch assets (canonical copies in this runbook's `assets/` dir; working
copies also in `/workspace/desktop-vad-patch/` on the DarkAgent workspace
mount):

- `assets/desktop-vad-0002-use-voice-conversation.patch` — THE patch.
  Desktop-only. Makes the loop read `voice.silence_duration` (seconds → ms)
  and `voice.silence_threshold` (int16 RMS → browser float level) from
  `getHermesConfig()` (`GET /api/config` — same endpoint the dashboard
  Settings page uses, present on every gateway). Falls back to the old
  hardcoded values (0.075 / 1250 / 12000) whenever the config response lacks
  the keys or the fetch fails, so behavior on unpatched/old/other gateways is
  unchanged.
- `assets/desktop-vad-0001-server-side-voice-config-OPTIONAL-UNDEPLOYED.patch`
  — optional server-side companion (expose a `voice` section on
  `/api/audio/voice-config`). NOT needed for the local fix; retained only as
  the proposed upstream design. It was NOT deployed: `/opt/hermes` on
  darkagent is a root-owned image layer (uid 10000, no sudo), so server-side
  file edits require an image rebuild, which we deliberately avoided.

## The mic override — general knowledge (read this first)

**Default Hermes Desktop behavior (upstream, unpatched):** the voice
conversation loop hardcodes its end-of-speech detection in
`apps/desktop/src/app/chat/composer/hooks/use-voice-conversation.ts`:

```ts
await handle.start({ silenceLevel: 0.075, silenceMs: 1_250, idleSilenceMs: 12_000, ... })
```

So any pause longer than **1.25 s** ends the turn, `voice.silence_duration` /
`voice.silence_threshold` are ignored on this surface (CLI/TUI honor them), and
transcription does not begin until after the turn ends — the "convert
everything after I stop" dead zone.

**What the override changes** (two files only, both desktop-side):

| Change | File | Effect |
|---|---|---|
| Read `voice.silence_*` from `GET /api/config` | `use-voice-conversation.ts` | pause window follows config; falls back to the old literals if absent |
| `rotate()` — segmented capture on the live mic stream | `use-mic-recorder.ts` | mic is never released mid-utterance |
| Transcribe each closed segment while the user speaks | `use-voice-conversation.ts` | transcription starts ~2 s in, cached in order |
| Tail-only transcription + `joinTranscript()` at submit | `use-voice-conversation.ts` | no post-pause dead zone; boundary words de-duplicated |

**Control surface (gateway config — no rebuild to change):**

| Key | Current | Meaning |
|---|---|---|
| `voice.silence_duration` | `8` | seconds of quiet before the turn submits |
| `voice.silence_threshold` | `120` | mic sensitivity (int16 RMS scale; lower = quieter speech counts) |
| `voice.stream_segment_seconds` | `2` | streaming capture segment length (clamped 1–6) |
| `voice.stream_transcribe` | `true` | master switch; `false` = exact stock behavior |

Change them in the dashboard (`darkagent-dashboard.darknetinternal.link` →
Settings → Voice for the `silence_*` pair) or `hermes config set` for the
`stream_*` pair (they are not in the dashboard schema). New values apply on the
next voice session — the desktop caches config per session, so Cmd+Q first.

**Revert paths, least to most invasive:** (1) `voice.stream_transcribe: false`
(instant, config only); (2) use `/Applications/Hermes.app`, which is never
patched; (3) `git checkout` the two hook files in the checkout and rebuild.

**Status at time of writing:** built and verified in the checkout's
side-by-side app (`~/.hermes/hermes-agent/apps/desktop/release/mac-arm64/
Hermes.app`); the installed `/Applications/Hermes.app` is untouched. Patches:
`assets/desktop-vad-0002-use-voice-conversation.patch` and
`assets/desktop-vad-0003-streaming-transcription.patch` (hashes recorded in
log.md). Deploy scripts: `assets/desktop-vad-deploy-main.sh`,
`assets/desktop-vad-deploy-side-by-side.sh`.

**Never publish/run this as `curl … | bash`** — Michael rejected that shape for
the Mac (see [[darkagent-mac-ssh]]); transfer files over the verified SSH
channel and review first.

## Patch 0003 — streaming transcription (start transcribing while you speak)

Problem it solves: transcription used to begin only **after** end-of-speech,
so every turn paid the full STT pass (2–3 s on the Mac) *after* the pause —
the "convert after I stop" dead zone.

Design (all desktop-side; audio still never leaves the Mac):

- `use-mic-recorder.ts` gains `rotate()`: it stops the current MediaRecorder
  and **immediately starts a new one on the same mic stream** — the
  microphone is never released mid-utterance, so no audio is lost between
  segments.
- `use-voice-conversation.ts` rotates + transcribes a segment every
  `voice.stream_segment_seconds` (default 2 s) while the user is still
  talking, caching each segment's transcript in order.
- At end-of-speech only the final tail segment is transcribed; it is joined
  with the cached text via `joinTranscript()` (word-level then character-level
  overlap strip, so a boundary word isn't duplicated).
- Any segment whose transcript is still missing at submit (in flight or
  failed) is retried then, so nothing is dropped.

Config keys (gateway config, read per voice session via `GET /api/config`;
not in the dashboard schema — set with `hermes config set` or the file):

| Key | Default | Meaning |
|---|---|---|
| `voice.stream_transcribe` | `true` | master switch; `false` = old single-shot behavior (no rebuild) |
| `voice.stream_segment_seconds` | `2` | segment length, clamped 1–6 s |

DarkAgent profile values at time of writing: `stream_transcribe: true`,
`stream_segment_seconds: 2`.

Apply order: **0002 first, then 0003** (0003 edits the file 0002 already
touched, and the recorder file 0002 leaves alone).

Verification performed (in the workspace, before hand-off): `git apply
--check` clean on a 0002-applied tree; both patched files parse under
`node --experimental-strip-types --check`; `joinTranscript()` unit-tested
(word overlap, character overlap, empty sides, no overlap).

Known trade-offs / risks to watch when tuning:

- A segment boundary can clip a word (~2 s cadence). Lower
  `stream_segment_seconds` to 1–1.5 to reduce; raise it to cut STT load.
- Whisper can repeat boundary words; the join strips the longest matching
  overlap, but a word split exactly at the cut is unrecoverable.
- If MediaRecorder rotation were ever unsupported, `rotate()` resolves null
  and segments simply stop accumulating (the tail transcription path still
  runs); set `stream_transcribe: false` to return entirely to stock behavior.

## Verified Mac build & deploy path (2026-09-16, executed end to end)

Prereqs and exact sequence that worked (see [[darkagent-mac-ssh]] for the SSH
setup and its gotchas):

```sh
# 0. access (container -> Mac)
KH=/tmp/mac_known_hosts; cp /run/secrets/darkagent_node_ssh_known_hosts $KH; chmod 600 $KH
ssh-keyscan -t ed25519 192.168.1.2 >> $KH
SSH="ssh -i /run/secrets/darkagent_node_ssh_private_key -o IdentitiesOnly=yes -o BatchMode=yes \
     -o StrictHostKeyChecking=yes -o UserKnownHostsFile=$KH michael@192.168.1.2"

# 1. toolchain — the Mac had NO Node; Homebrew was already installed
$SSH '/opt/homebrew/bin/brew install node'          # -> node v26.8.2 / npm 11.19.1

# 2. checkout to latest main (patches are generated against main)
cd ~/.hermes/hermes-agent && git checkout -- <hooks…> && git fetch && git checkout main && git pull --ff-only

# 3. patches (0002 then 0003)
git apply ~/vad-deploy/0002-…patch && git apply ~/vad-deploy/0003-…patch

# 4. build renderer + package (see signing gotcha below)
cd apps/desktop && npm install --no-audit --no-fund
npm run build                                        # vite: dist/index.html + assets
env CSC_IDENTITY_AUTO_DISCOVERY=false npm run builder -- --mac -c.mac.identity=-
```

Artifacts land in `apps/desktop/release/`: `mac-arm64/Hermes.app` plus
`Hermes-<version>-mac-arm64.{dmg,zip}`.

### Gotchas that cost real time

1. **Codesigning fails over SSH.** `electron-builder` auto-discovers Michael's
   *Apple Development* cert and dies with `errSecInternalComponent` — the login
   keychain is unlocked only in a GUI session. Fix: build ad-hoc
   (`CSC_IDENTITY_AUTO_DISCOVERY=false` + `-c.mac.identity=-`). Do NOT try to
   unlock the keychain (needs Michael's password).
2. **`npm run builder` alone is not enough.** The renderer lives in `dist/`
   generated by `npm run build` (vite). Packaging without it produces a
   Hermes.app whose app.asar has NO app code (`dist/assets/*` missing) — the
   app looks built but is empty. Always: `build` then `builder`.
3. **Patches are revision-sensitive.** 0003 failed (hunk context) on the
   checkout's older revision; updating the checkout to `main` first made both
   patches apply cleanly.
4. **Verifying the patch actually shipped.** The renderer is stored UNPACKED at
   `Hermes.app/Contents/Resources/app.asar.unpacked/dist/assets/*.js`, not
   inside the packed asar. Minifiers rename identifiers (`getHermesConfig`,
   `joinTranscript` → 0 hits) but keep property/string names, so verify with
   config-key literals instead: `stream_segment_seconds`, `stream_transcribe`,
   `silence_duration` must each appear in `index-*.js`.

### Launch & test (side-by-side, default)

```sh
# quit the installed app first (same bundle id + shared app-support dir)
osascript -e 'quit app "Hermes"'
open ~/.hermes/hermes-agent/apps/desktop/release/mac-arm64/Hermes.app
```

Then in a voice conversation: speak a long sentence with a 3–4 s pause
mid-thought. Expect the message to land almost immediately after you stop
(tail-only transcription) and no mid-thought cutoff at 1.25 s.

Revert to stock: `git checkout` the two hook files in the checkout and rebuild,
or simply keep using `/Applications/Hermes.app` (never patched).

## Reapply (after each desktop update, until upstream merges a fix)

On Michael's Mac:

```sh
cd ~/.hermes/hermes-agent        # the desktop checkout (confirm path first)
git pull --ff-only
git apply /path/to/desktop-vad-0002-use-voice-conversation.patch
cd apps/desktop && npm install && npm run dist:mac
# quit the running app (Cmd+Q), then open apps/desktop/release/mac-arm64/Hermes.app
# re-grant microphone permission if macOS asks (ad-hoc signing changes identity)
```

If `git apply` fails with conflicts, upstream probably changed or already
fixed the block — check before forcing (`git apply --3way` as a fallback;
manual merge is acceptable but re-verify the fallback defaults remain).

After applying, tuning lives in config (no rebuild): dashboard →
Settings → Voice → Silence Duration (seconds) and Silence Threshold. The
desktop picks up new values on its next voice session (its config cache is
TTL'd ~60 s; a fresh session always re-fetches).

### Verify the patch is active

1. `grep -n "getHermesConfig" apps/desktop/src/app/chat/composer/hooks/use-voice-conversation.ts`
   → import + usage present.
2. Practical check: in a desktop voice conversation, pause mid-sentence for
   ~5 s — recording must NOT stop (old behavior cut at 1.25 s).

## Revert (upstream shipped the fix, or you want stock)

```sh
cd ~/.hermes/hermes-agent
git checkout -- apps/desktop/src/app/chat/composer/hooks/use-voice-conversation.ts
cd apps/desktop && npm run dist:mac
```

Before deciding "upstream fixed it", confirm the release notes or the current
`main` file no longer contains the hardcoded block (`silenceMs: 1_250`).

## Upstream tracking

- Issue to file (evidence above): desktop conversation loop hardcodes VAD,
  contradicting documented `voice.silence_*` config honored by CLI/TUI.
- Proposed upstream fix shapes: (a) minimal — read the keys via existing
  `getHermesConfig()` in the hook (what our patch does); (b) cleaner — extend
  `GET /api/audio/voice-config` with a `voice` section (see the OPTIONAL
  0001 asset) and read that in the hook. Server-side changes are upstream's
  to ship (they require image rebuilds for gateway deployments like ours).
- Re-check on each Hermes release (current at patch time: v2026.9.11);
  delete the local patch once a release includes the fix.
- Known related upstream threads: RFC #77111 (duplex voice provider ABC),
  #96928 (streaming STT to shrink the transcribe dead-zone).

## Context and constraints (do not lose these)

- Mac-only audio policy: all STT/TTS runs on the Mac (Speaches at
  `michaelacstudio.darknet:8000`; STT `Systran/faster-whisper-small`, TTS
  Kokoro `af_heart` speed 1.4). The desktop talks to the DarkAgent gateway in
  relay mode (`voice.client_direct: false`) — the gateway relays audio to the
  Mac; no other machine processes audio. The VAD patch does not touch this.
- Live config values at patch time (DarkAgent profile): `silence_duration: 8`
  s, `silence_threshold: 120`, TTS speed 1.4. Silence-duration mapping in the
  patch: `silenceMs = duration * 1000`, `idleSilenceMs = max(silenceMs, 12000)`.
  Threshold mapping: `level = clamp(0.02, 0.3, threshold / 32767 * 12.5)`
  (200 → ≈0.076 ≈ old default 0.075; 120 → ≈0.046, more sensitive to quiet
  speech).
- Desktop gotchas that apply regardless of this patch: desktop caches
  voice config per session (Cmd+Q to pick up config changes); macOS mic
  permission binds to the app's code-signing identity (upstream #43788 —
  re-grant after rebuilds on pre-fix builds).
- Bigger future upgrade (separate project, not in this patch): semantic
  end-of-turn detection (pipecat smart-turn v3, ONNX, ~8 M params, Mac-local)
  for ChatGPT-style "did he finish the thought?" behavior.
