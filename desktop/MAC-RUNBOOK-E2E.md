# Hermes Desktop Voice VAD Patch — End-to-End Runbook (Mac)

**Purpose:** Fix Hermes Desktop cutting off speech mid-thought. The desktop
voice loop hardcodes a 1.25-second silence cutoff and ignores the configured
`voice.silence_duration` (8s on this profile). This patch makes the desktop
read the configured value, so pausing mid-sentence no longer submits a
partial transcript.

**Target machine:** Michael's Mac (M3 Ultra). **Nothing on the swarm servers
changes.** This is entirely Mac-local work plus one rebuild of the desktop
app.

**Patch file:** `desktop-vad-0002-use-voice-conversation.patch`
(canonical: DarkAgent knowledge base
`runbooks/assets/desktop-vad-0002-use-voice-conversation.patch`; working
copy: swarm `/workspace/desktop-vad-patch/`).

---

## STEP 0 — Preconditions (verify before anything)

```bash
# 0.1  Locate the desktop checkout. Expected: ~/.hermes/hermes-agent
ls -d ~/.hermes/hermes-agent/apps/desktop 2>/dev/null \
  && echo "CHECKOUT OK" \
  || echo "CHECKOUT NOT AT EXPECTED PATH — find it:"
find ~ -maxdepth 5 -type d -name "desktop" -path "*hermes*apps*" 2>/dev/null

# 0.2  Node + npm present (build needs them)
node --version && npm --version    # Node 18+ required by electron-builder toolchain

# 0.3  Repo is clean-ish and current
cd ~/.hermes/hermes-agent          # (or the path found in 0.1)
git status --short                 # note any local changes; patch expects pristine file
git log --oneline -1
```

**If the checkout is elsewhere:** substitute the real path everywhere below.
If `git status` shows local edits to
`apps/desktop/src/app/chat/composer/hooks/use-voice-conversation.ts`,
stop and reconcile (stash or commit) before continuing.

## STEP 1 — Get the patch file onto the Mac

Copy `desktop-vad-0002-use-voice-conversation.patch` to `~/vad.patch` by
whatever channel you have (scp from the swarm workspace, AirDrop, or paste
from the knowledge base asset). Verify it transferred intact:

```bash
wc -l ~/vad.patch        # expect 48 lines
head -3 ~/vad.patch      # expect '--- a/apps/desktop/...' header
```

## STEP 2 — Update checkout and apply the patch

```bash
cd ~/.hermes/hermes-agent
git pull --ff-only

# dry run first — silence means clean:
git apply --check ~/vad.patch && echo "APPLY CHECK: CLEAN"

# apply for real:
git apply ~/vad.patch

# verify the patch landed — expect EXACTLY these two lines (~14 and ~245):
grep -n getHermesConfig apps/desktop/src/app/chat/composer/hooks/use-voice-conversation.ts
```

**Expected output:**
```
14:import { getHermesConfig } from '@/api/config'
245:        const config = await getHermesConfig()
```

**Failure handling:**
- `git apply --check` errors → upstream changed the file. Do NOT force.
  Report the error text back to DarkAgent (the patch needs regenerating
  against the new file — or upstream already fixed it; check
  `grep -n "silenceMs: 1_250" apps/desktop/src/app/chat/composer/hooks/use-voice-conversation.ts`
  — if empty, upstream fixed it and NO patch is needed).
- `git pull` refuses (local changes) → `git stash && git pull --ff-only && git stash pop`.

## STEP 3 — Rebuild the desktop app

```bash
cd ~/.hermes/hermes-agent/apps/desktop
npm install          # skip if node_modules exists and is current; first run takes a while
npm run dist:mac     # several minutes; final artifact:
```

**Success:** `apps/desktop/release/mac-arm64/Hermes.app` updated (check
timestamp: `ls -la apps/desktop/release/mac-arm64/ | grep Hermes` — run from
repo root; or `stat -f '%Sm' apps/desktop/release/mac-arm64/Hermes.app` from
repo root).

**If the build fails on TypeScript:** paste the error to DarkAgent — expected
worst case is a one-line type annotation tweak in the same file. Do not edit
anything else.

## STEP 3.5 — Apply the streaming patch (0003) — start transcoding while you talk

Patch `0003-desktop-streaming-transcription.patch` (applies ON TOP of 0002;
same two files: it edits `use-mic-recorder.ts` and continues
`use-voice-conversation.ts`). What it does:

- Rotates the microphone recorder every `voice.stream_segment_seconds`
  (default 2 s) **without releasing the mic stream**, transcribing each closed
  segment immediately → **transcription starts ~2 s into speech instead of
  after you stop**.
- Caches each segment's transcript as it completes.
- At end-of-speech only the small tail is transcribed, then joined with the
  cached text (overlap de-duplicated) → the long "convert after the pause"
  dead zone mostly disappears.
- If a segment's transcription fails, the audio is retried at submit, so
  nothing is dropped.

```bash
cd ~/.hermes/hermes-agent
git apply --check ~/vad3.patch && echo "0003 CHECK: CLEAN"
git apply ~/vad3.patch
node --experimental-strip-types --check apps/desktop/src/app/chat/composer/hooks/use-voice-conversation.ts && echo "syntax OK"
cd apps/desktop && npm run dist:mac
# Cmd+Q, reopen release/mac-arm64/Hermes.app
```

**Config (gateway, no rebuild — already set on DarkAgent):**

| Key | Value | Meaning |
|---|---|---|
| `voice.stream_transcribe` | `true` | master switch; `false` = old single-shot behavior |
| `voice.stream_segment_seconds` | `2` | segment length (clamped 1–6 s) |

**Test E — streaming is live:**
Speak a long sentence with a deliberate 3–4 s pause in the middle, then finish.
PASS = the chat bubble appears **almost immediately after you stop** (tail-only
transcription), with the full text intact — no 2–3 s silence-then-convert gap.

**Test F — escape hatch:**
Set `voice.stream_transcribe: false` in config → Cmd+Q → reopen → behavior
returns to the pre-0003 single-shot path (proves the switch works).

**Known trade-offs (report if they bite):** segment boundaries can clip a word
(~2 s cadence); the join de-duplicates repeated boundary words but cannot
recover a word split exactly at the cut. Lowering `stream_segment_seconds`
(1–1.5) reduces clipping risk; raising it reduces STT load.

## STEP 4 — Swap the running app


1. Quit Hermes Desktop **completely**: Cmd+Q (not just closing the window —
   the app keeps a background process).
2. Open the fresh build:
   ```bash
   open ~/.hermes/hermes-agent/apps/desktop/release/mac-arm64/Hermes.app
   ```
3. If macOS prompts for **Microphone access: Allow.** (Ad-hoc signing
   changes identity on each build, so the TCC grant must be re-made. If no
   prompt appears and voice later says "access denied", reset and re-grant:
   ```bash
   tccutil reset Microphone com.nousresearch.hermes
   ```
   then reopen the app and approve the prompt.)

## STEP 5 — Configuration check (no rebuild needed, ever)

The patch reads the live profile config at each voice session. Current
DarkAgent profile values (verify/change on the dashboard
`https://darkagent-dashboard.darknetinternal.link` → Settings → Voice):

| Key | Value | Meaning |
|---|---|---|
| `voice.silence_duration` | **8** seconds | pause before the turn submits |
| `voice.silence_threshold` | **120** | mic sensitivity (lower = quieter speech counts) |

Confirm what the desktop will read (from the swarm, or ask DarkAgent):

```
silence_duration: 8
silence_threshold: 120
```

No desktop rebuild is ever needed to change these — dashboard edit →
Cmd+Q → next voice session uses the new values (config cache TTL ≈60s).

## STEP 6 — Tests (in order; report results per test)

**Setup:** voice conversation running on the desktop connected to the
DarkAgent profile.

### Test A — mid-sentence pause no longer cuts off (THE fix)
Say: *"Deploy the swarm controller to staging [pause 3–4 seconds] and verify
the checkpoint before restarting the gateway tonight."*
- **PASS:** recording holds through the pause; the chat bubble shows the
  WHOLE sentence as one message.
- **FAIL:** it submits "Deploy the swarm controller to staging" alone at
  ~1.25s → the running app is still the old build. Re-check STEP 3/4
  (fully quit and relaunch), and re-run the STEP 2 grep.
- **FAIL (cutoff happens but longer than before):** patch is live but the
  pause exceeded 8s. Either speak sooner or raise Silence Duration.

### Test B — turn-end still works
Finish a thought and stay silent. **PASS:** submits after ~8s and the reply
begins. If 8s feels sluggish when done talking, lower Silence Duration to
5–6 (but keep it above your longest natural mid-thought pause from Test A).

### Test C — config actually drives the behavior (proves no-rebuild tuning)
Dashboard → Settings → Voice → Silence Duration → **12** → Cmd+Q → reopen →
repeat Test A with a 6–7s pause. **PASS:** holds through the longer pause.
Then set it back to your preferred value (8 is the current choice).

### Test D — regressions
- Talk over the agent while it replies → playback cuts and what you said is
  submitted (barge-in must still work — the patch doesn't touch it).
- Say "stop" alone → conversation ends.

## STEP 7 — Report back to DarkAgent

For each test: PASS/FAIL + what actually happened (which words landed in
which message, roughly how long the pause was). DarkAgent will correlate
gateway logs and, if Test A fails, diagnose from the timing.

---

## REVERT (return to stock)

```bash
cd ~/.hermes/hermes-agent
git checkout -- apps/desktop/src/app/chat/composer/hooks/use-voice-conversation.ts
cd apps/desktop && npm run dist:mac
# Cmd+Q, reopen the fresh app
```

Do this only when (a) upstream ships the real fix — confirm by checking
`grep -n "silenceMs: 1_250" .../use-voice-conversation.ts` against a freshly
pulled `main` (empty = fixed upstream, safe to revert) — or (b) you want the
old 1.25s behavior back for some reason.

## UPSTREAM TRACKING (DarkAgent's side, informational)

- Bug: desktop loop hardcodes `silenceLevel 0.075 / silenceMs 1250 /
  idleSilenceMs 12000`, contradicting documented `voice.silence_*` config
  honored by CLI/TUI. Evidence file sha at patch time:
  `55978c42847469ee0cefdb92b477887617665efd`.
- Related upstream threads: #77111 (duplex voice RFC), #96928 (streaming STT).
- When upstream merges a fix: verify on `main`, then run REVERT, and delete
  the patch from the knowledge base (`runbooks/desktop-voice-vad-patch.md`
  records the full history).

## KNOWN NON-ISSUES (don't chase these)

- "Microphone access denied" right after rebuild → TCC re-grant (STEP 4.3),
  not a patch problem.
- Voice config changes not taking effect → session cache; Cmd+Q first.
- TTS speed changes not visible in dashboard schema → `tts.openai.speed` has
  no UI field; it still works via config (DarkAgent manages that key).
- STT/TTS latency or accuracy → that's the Mac Speaches service
  (`michaelacstudio.darknet:8000`), unrelated to this patch.
