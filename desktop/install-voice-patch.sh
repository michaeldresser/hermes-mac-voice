#!/usr/bin/env bash
# Hermes Desktop voice fixes — one-shot installer (VAD config + streaming STT).
# Runs entirely on the Mac. Rebuilds the desktop app from your existing checkout.
# Safe to re-run: it detects an already-patched tree and just rebuilds.
set -uo pipefail

PATCH_0002_URL="__PATCH_0002_URL__"
PATCH_0003_URL="__PATCH_0003_URL__"

say()  { printf '\n\033[1m== %s\033[0m\n' "$*"; }
warn() { printf '\033[33m!! %s\033[0m\n' "$*"; }
die()  { printf '\033[31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

TARGET="apps/desktop/src/app/chat/composer/hooks/use-voice-conversation.ts"

say "Finding the Hermes checkout"
REPO=""
for cand in "$HOME/.hermes/hermes-agent" "$HOME/hermes-agent" "$HOME/src/hermes-agent" "$HOME/code/hermes-agent"; do
  if [ -f "$cand/$TARGET" ]; then REPO="$cand"; break; fi
done
if [ -z "$REPO" ]; then
  FOUND=$(find "$HOME" -maxdepth 5 -type f -name "use-voice-conversation.ts" -path "*composer/hooks*" 2>/dev/null | head -1)
  [ -n "${FOUND:-}" ] || die "could not find the desktop checkout (use-voice-conversation.ts)"
  REPO=$(printf '%s' "$FOUND" | sed 's#/apps/desktop/src/app/chat/composer/hooks/use-voice-conversation.ts##')
fi
echo "   checkout: $REPO"
cd "$REPO" || die "cannot cd into $REPO"

command -v git >/dev/null 2>&1 || die "git not installed"
command -v npm >/dev/null 2>&1 || die "npm not installed (install Node.js first)"

say "Downloading patches"
TMP=$(mktemp -d)
curl -fsSL "$PATCH_0002_URL" -o "$TMP/0002.patch" || die "download failed (0002)"
curl -fsSL "$PATCH_0003_URL" -o "$TMP/0003.patch" || die "download failed (0003)"
echo "   $(wc -l < "$TMP/0002.patch" | tr -d ' ') + $(wc -l < "$TMP/0003.patch" | tr -d ' ') lines"

if grep -q "getHermesConfig" "$TARGET" 2>/dev/null; then
  say "Patches already present — skipping apply"
else
  say "Applying patches"
  if ! git apply --check "$TMP/0002.patch" 2>/dev/null; then
    warn "patch does not apply cleanly against this checkout — updating it first"
    git pull --ff-only || warn "git pull failed (continuing with current tree)"
  fi
  git apply "$TMP/0002.patch" || die "0002 failed to apply — paste this output back to DarkAgent"
  git apply "$TMP/0003.patch" || die "0003 failed to apply — paste this output back to DarkAgent"
  echo "   0002 + 0003 applied"
fi

say "Verifying"
grep -n "getHermesConfig" "$TARGET" | head -2 || die "patch verification failed"
grep -q "rotate" "apps/desktop/src/app/chat/composer/hooks/use-mic-recorder.ts" && echo "   streaming recorder: present" || warn "streaming recorder: MISSING"

say "Building the desktop app (this takes a few minutes)"
cd apps/desktop || die "no apps/desktop directory"
[ -d node_modules ] || { echo "   installing dependencies..."; npm install || die "npm install failed"; }
npm run dist:mac || die "build failed — paste the error back to DarkAgent"

APP="$REPO/apps/desktop/release/mac-arm64/Hermes.app"
say "Done"
if [ -d "$APP" ]; then
  echo "   built: $APP"
  echo
  echo "   Next: press Cmd+Q on the running Hermes (fully quit it), then:"
  echo "     open \"$APP\""
  echo "   Grant microphone permission if macOS asks."
else
  warn "build finished but $APP not found — check the release/ directory"
fi
echo
echo "   Tuning (gateway config, no rebuild): voice.silence_duration (8s),"
echo "   voice.stream_segment_seconds (2s), voice.stream_transcribe (true|false)."
