#!/bin/bash
# Update the checkout to latest main, apply the two voice patches, build side-by-side.
# Does NOT touch /Applications/Hermes.app.
set -uo pipefail
export PATH="/opt/homebrew/bin:$PATH"
REPO="$HOME/.hermes/hermes-agent"
HOOKS="$REPO/apps/desktop/src/app/chat/composer/hooks"
BK="$HOME/vad-deploy/backup"
P2="$HOME/vad-deploy/0002-desktop-use-configured-voice-vad-tuning.patch"
P3="$HOME/vad-deploy/0003-desktop-streaming-transcription.patch"

cd "$REPO" || { echo "FAIL: no checkout"; exit 1; }

echo "== 0. current state =="
git rev-parse --abbrev-ref HEAD 2>/dev/null
git log --oneline -1
git status --porcelain | head -5

echo "== 1. back up local edits =="
mkdir -p "$BK"
cp -p "$HOOKS/use-voice-conversation.ts" "$BK/use-voice-conversation.local.ts" 2>/dev/null && echo "backed up conversation hook"
cp -p "$HOOKS/use-mic-recorder.ts" "$BK/use-mic-recorder.local.ts" 2>/dev/null && echo "backed up recorder hook"

echo "== 2. move to latest main =="
git checkout -- apps/desktop/src/app/chat/composer/hooks/use-voice-conversation.ts 2>/dev/null
git fetch origin --tags 2>&1 | tail -3
git checkout main 2>/dev/null || git switch main 2>/dev/null || echo "(already on main)"
git pull --ff-only 2>&1 | tail -4
echo "now at: $(git log --oneline -1)"

echo "== 3. apply patches =="
git apply --check "$P2" && echo "0002: check OK" || { echo "FAIL: 0002 check"; exit 1; }
git apply "$P2" || { echo "FAIL: 0002 apply"; exit 1; }
git apply --check "$P3" && echo "0003: check OK" || { echo "FAIL: 0003 check"; exit 1; }
git apply "$P3" || { echo "FAIL: 0003 apply"; exit 1; }
echo -n "getHermesConfig markers: "; grep -c getHermesConfig "$HOOKS/use-voice-conversation.ts"
echo -n "rotate markers:          "; grep -c rotate "$HOOKS/use-mic-recorder.ts"
echo -n "joinTranscript markers:  "; grep -c joinTranscript "$HOOKS/use-voice-conversation.ts"

echo "== 4. install deps (root workspace) =="
npm install --no-audit --no-fund 2>&1 | tail -4

echo "== 5. build desktop =="
cd "$REPO/apps/desktop" || { echo "FAIL: no apps/desktop"; exit 1; }
[ -d node_modules ] || npm install --no-audit --no-fund 2>&1 | tail -4
npm run dist:mac 2>&1 | tail -30

echo "== 6. artifact =="
APP="$REPO/apps/desktop/release/mac-arm64/Hermes.app"
if [ -d "$APP" ]; then
  echo "BUILD_OK $APP"
  echo -n "mtime: "; stat -f '%Sm' "$APP"
  echo -n "patched bundle contains getHermesConfig: "; grep -c getHermesConfig "$APP/Contents/Resources/app.asar" 2>/dev/null
else
  echo "BUILD_MISSING"
fi