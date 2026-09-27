#!/bin/bash
# Conformance test for the Mac-hosted voice server.
# Usage: bash mac-voice-conformance-test.sh http://<mac-host>:<port> <bearer-token>
# Verifies the server speaks the EXACT dialect Hermes sends (captured in the mock relay test):
#   STT: POST /v1/audio/transcriptions  multipart: file, model, language, response_format=text [, prompt]
#        response: plain text body (whisper-1) or JSON {"text": ...}
#   TTS: POST /v1/audio/speech  JSON: {model, voice, input, response_format:"mp3"}
#        response: audio bytes (audio/mpeg or audio/wav)
set -euo pipefail
BASE="${1:?usage: mac-voice-conformance-test.sh <base-url> [bearer-token]}"
TOKEN="${2:-}"
AUTH=()
[ -n "$TOKEN" ] && AUTH=(-H "Authorization: Bearer $TOKEN")
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
PASS=0; FAIL=0

gen_wav() { python3 -c "
import wave,struct,math,sys
w=wave.open('$1','wb'); w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
w.writeframes(b''.join(struct.pack('<h',int(9000*math.sin(2*math.pi*350*i/16000)))for i in range(16000)))
w.close()"; }

echo "== 1. STT: multipart exactly as Hermes sends (file, model, language, response_format=text) =="
gen_wav "$TMP/test.wav"
HTTP=$(curl -s -o "$TMP/stt-body" -w "%{http_code}" --max-time 60 \
  -X POST "$BASE/v1/audio/transcriptions" "${AUTH[@]}" \
  -F "model=whisper-1" -F "language=en" -F "response_format=text" \
  -F "file=@$TMP/test.wav;filename=test.wav;type=audio/wav" 2>/dev/null || echo 000)
if [ "$HTTP" = "200" ]; then
  # plain-text OR {"text": ...} both acceptable
  if head -c 200 "$TMP/stt-body" | python3 -c "import json,sys; json.load(sys.stdin)" 2>/dev/null; then
    echo "   PASS ($HTTP, json response): $(head -c 120 "$TMP/stt-body")"; PASS=$((PASS+1))
  elif [ -s "$TMP/stt-body" ]; then
    echo "   PASS ($HTTP, text response): $(head -c 120 "$TMP/stt-body")"; PASS=$((PASS+1))
  else
    echo "   FAIL ($HTTP): empty body"; FAIL=$((FAIL+1))
  fi
else
  echo "   FAIL (HTTP $HTTP): $(head -c 200 "$TMP/stt-body")"; FAIL=$((FAIL+1))
fi

echo "== 2. STT: whisper-1 with JSON format (alternate path) =="
HTTP=$(curl -s -o "$TMP/stt2" -w "%{http_code}" --max-time 60 \
  -X POST "$BASE/v1/audio/transcriptions" "${AUTH[@]}" \
  -F "model=whisper-1" -F "response_format=json" -F "file=@$TMP/test.wav;filename=test.wav" 2>/dev/null || echo 000)
if [ "$HTTP" = "200" ] && head -c 200 "$TMP/stt2" | python3 -c "import json,sys; d=json.load(sys.stdin); sys.exit(0 if 'text' in d else 1)" 2>/dev/null; then
  echo "   PASS ($HTTP): $(head -c 120 "$TMP/stt2")"; PASS=$((PASS+1))
else echo "   FAIL (HTTP $HTTP): $(head -c 200 "$TMP/stt2")"; FAIL=$((FAIL+1)); fi

echo "== 3. TTS: JSON body exactly as Hermes sends (model, voice, input, response_format=mp3) =="
HTTP=$(curl -s -o "$TMP/tts.mp3" -w "%{http_code}" --max-time 120 \
  -X POST "$BASE/v1/audio/speech" "${AUTH[@]}" -H "Content-Type: application/json" \
  -d '{"model":"kokoro","voice":"af_heart","input":"Conformance test sentence for the Mac voice server.","response_format":"mp3"}' 2>/dev/null || echo 000)
CTYPE=$(curl -s -o /dev/null -w "%{content_type}" --max-time 5 "$BASE/health" 2>/dev/null || true)
if [ "$HTTP" = "200" ] && [ -s "$TMP/tts.mp3" ]; then
  # verify it's audio-ish (RIFF/WAVE header, MPEG sync, or ffd8/ogg) rather than a JSON error
  if head -c 64 "$TMP/tts.mp3" | grep -qa -e "RIFF" -e "ID3" -e "OggS" || \
     python3 -c "
b=open('$TMP/tts.mp3','rb').read(64)
import sys
sys.exit(0 if (b[:4]==b'RIFF' or b[:3]==b'ID3' or b[:4]==b'OggS' or (len(b)>2 and b[0]==0xFF and (b[1]&0xE0)==0xE0)) else 1)" 2>/dev/null; then
    echo "   PASS ($HTTP): $(stat -c%s "$TMP/tts.mp3") bytes, audio container verified"; PASS=$((PASS+1))
  else
    echo "   FAIL ($HTTP): body is not audio: $(head -c 150 "$TMP/tts.mp3")"; FAIL=$((FAIL+1))
  fi
else echo "   FAIL (HTTP $HTTP): $(head -c 200 "$TMP/tts.mp3")"; FAIL=$((FAIL+1)); fi

echo "== 4. TTS: streaming-ish longer input (multi-sentence, 300+ chars) =="
LONG=$(python3 -c "print(' '.join(['Sentence number %d tests streaming synthesis behavior.'%i for i in range(1,16)]))")
HTTP=$(curl -s -o "$TMP/tts2.mp3" -w "%{http_code}" --max-time 180 \
  -X POST "$BASE/v1/audio/speech" "${AUTH[@]}" -H "Content-Type: application/json" \
  -d "$(python3 -c "import json;print(json.dumps({'model':'kokoro','voice':'af_heart','input':'''$LONG''','response_format':'mp3'}))")" 2>/dev/null || echo 000)
if [ "$HTTP" = "200" ] && [ -s "$TMP/tts2.mp3" ]; then
  SZ=$(stat -c%s "$TMP/tts2.mp3")
  if [ "$SZ" -gt 20000 ]; then echo "   PASS ($HTTP): $SZ bytes for ~840 chars"; PASS=$((PASS+1))
  else echo "   WARN ($HTTP): only $SZ bytes for 840 chars — check quality"; PASS=$((PASS+1)); fi
else echo "   FAIL (HTTP $HTTP)"; FAIL=$((FAIL+1)); fi

echo "== 5. Auth honored (bad token must be rejected if auth configured) =="
HTTP=$(curl -s -o /dev/null -w "%{http_code}" --max-time 15 \
  -X POST "$BASE/v1/audio/speech" -H "Authorization: Bearer deliberately-wrong-token" \
  -H "Content-Type: application/json" -d '{"model":"kokoro","voice":"af_heart","input":"x","response_format":"mp3"}' 2>/dev/null || echo 000)
if [ "$HTTP" = "401" ] || [ "$HTTP" = "403" ]; then echo "   PASS ($HTTP): rejects bad token"; PASS=$((PASS+1))
elif [ "$HTTP" = "200" ]; then echo "   WARN (200): no auth enforced — fine on LAN-only binding, required if exposed"; PASS=$((PASS+1))
else echo "   FAIL ($HTTP)"; FAIL=$((FAIL+1)); fi

echo; echo "RESULT: $PASS passed, $FAIL failed"
[ "$FAIL" = "0" ]
