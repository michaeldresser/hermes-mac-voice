#!/bin/bash
# Deploy the Hermes Desktop voice patches (0002 already applied; this applies 0003)
# and build the app SIDE-BY-SIDE. Does NOT touch /Applications/Hermes.app.
set -uo pipefail
export PATH="/opt/homebrew/bin:$PATH"
REPO="$HOME/.hermes/hermes-agent"
HOOKS="$REPO/apps/desktop/src/app/chat/composer/hooks"

cd "$REPO" || { echo "FAIL: no checkout at $REPO"; exit 1; }

echo "== 1. toolchain =="
for i in $(seq 1 90); do command -v node >/dev/null 2>&1 && break; sleep 5; done
node -v || { echo "FAIL: node not available"; exit 1; }
npm -v

echo "== 2. patch state =="
git -C "$REPO" status --porcelain
if grep -q "joinTranscript" "$HOOKS/use-voice-conversation.ts"; then
  echo "0003: already applied"
else
  git -C "$REPO" apply "$HOME/vad-deploy/0003-desktop-streaming-transcription.patch" \
    || { echo "FAIL: 0003 did not apply"; exit 1; }
  echo "0003: applied"
fi
echo -n "recorder rotate(): "; grep -c "rotate" "$HOOKS/use-mic-recorder.ts"
echo -n "joinTranscript():  "; grep -c "joinTranscript" "$HOOKS/use-voice-conversation.ts"

echo "== 3. install deps (root workspace) =="
if [ -f package.json ]; then npm install --no-audit --no-fund 2>&1 | tail -4; fi

echo "== 4. build desktop =="
cd "$REPO/apps/desktop" || { echo "FAIL: no apps/desktop"; exit 1; }
[ -d node_modules ] || npm install --no-audit --no-fund 2>&1 | tail -4
npm run dist:mac 2>&1 | tail -30

echo "== 5. artifacts =="
ls -la "$REPO/apps/desktop/release/mac-arm64/" 2>/dev/null | tail -5
APP="$REPO/apps/desktop/release/mac-arm64/Hermes.app"
if [ -d "$APP" ]; then
  echo "BUILD_OK $APP"
  echo -n "bundle mtime: "; stat -f '%Sm' "$APP"
else
  echo "BUILD_MISSING"
fi