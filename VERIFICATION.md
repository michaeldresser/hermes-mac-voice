# Verification Report
Generated: 2026-09-27T00:02:03.518988

## Bundle provenance
- SHA256 of tarball: e253df3cc4ebd3d7afbf35ed9ba359d229339f9b8b1b5d7a4ddb360756c71afc
- Bundle extracted to: /workspace/mac-voice-handoff

## SHA256 verification
Expected: e253df3cc4ebd3d7afbf35ed9ba359d229339f9b8b1b5d7a4ddb360756c71afc
Result: MATCH (verified via sha256sum)

## File inventory (paths + sizes + mtimes)

| Path | Size (bytes) | mtime (epoch) |
|------|--------------|---------------|
| .gitignore | 338 | 1790455772.0 |
| HANDOFF.md | 7193 | 1790455742.0 |
| README.md | 17293 | 1790455731.0 |
| mac-services/bridge.py | 25111 | 1790455747.0 |
| mac-services/com.hermes.gptlive.bridge.plist | 1333 | 1790455747.0 |
| mac-services/docker-inspect.json | 21532 | 1790455747.0 |
| mac-services/regress_two_utterances.py | 2679 | 1790455747.0 |
| mac-services/requirements.txt | 45 | 1790455747.0 |
| mac-services/selftest_client.py | 4634 | 1790455747.0 |
| mac-services/selftest_speech.py | 5046 | 1790455747.0 |
| desktop/MAC-RUNBOOK-E2E.md | 10712 | 1790455747.0 |
| desktop/deploy-main.sh | 2478 | 1790455747.0 |
| desktop/deploy-side-by-side.sh | 1656 | 1790455747.0 |
| desktop/install-voice-patch.ready.sh | 3529 | 1790455747.0 |
| desktop/install-voice-patch.sh | 3365 | 1790455747.0 |
| desktop/patches/0001-voice_client_config-expose-voice-silence-tuning.patch | 1554 | 1790455747.0 |
| desktop/patches/0002-desktop-use-configured-voice-vad-tuning.patch | 2287 | 1790455747.0 |
| desktop/patches/0003-desktop-streaming-transcription.patch | 14327 | 1790455747.0 |
| config/gateway-config.redacted.yaml | 5876 | 1790455747.0 |
| config/voice-config.example.yaml | 4604 | 1790455772.0 |
| research/tts-quality-options-2026-09-26.md | 8590 | 1790455791.0 |
| research/semantic-endpointing/bench-results.json | 3427 | 1790455747.0 |
| research/semantic-endpointing/bench.py | 4754 | 1790455747.0 |
| research/semantic-endpointing/discriminate.py | 2530 | 1790455747.0 |
| research/semantic-endpointing/mac-voice-semantic-endpointing-bench.md | 5458 | 1790455747.0 |
| research/semantic-endpointing/official-results.json | 873 | 1790455747.0 |
| research/semantic-endpointing/official.py | 4310 | 1790455747.0 |
| research/semantic-endpointing/sanity-results.json | 382 | 1790455747.0 |
| research/semantic-endpointing/sanity.py | 4013 | 1790455747.0 |
| research/semantic-endpointing/validate.py | 5315 | 1790455747.0 |
| research/semantic-endpointing/validation-results.json | 165396 | 1790455747.0 |
| docs/darkagent-mac-ssh.md | 3444 | 1790455750.0 |
| docs/desktop-vad-fix-kit.md | 2983 | 1790455747.0 |
| docs/desktop-voice-vad-patch.md | 14758 | 1790455747.0 |
| docs/mac-ssh-access.md | 4591 | 1790455750.0 |
| docs/mac-voice-20260920-status.md | 4285 | 1790455747.0 |
| docs/mac-voice-architecture.md | 5450 | 1790455747.0 |
| docs/mac-voice-dns-config.md | 1791 | 1790455747.0 |
| docs/mac-voice-engine-research-selfexecuted.md | 4844 | 1790455747.0 |
| docs/mac-voice-golive-status.md | 5296 | 1790455747.0 |
| docs/mac-voice-gptlive-fix-20260920.md | 5543 | 1790455750.0 |
| docs/mac-voice-research-tracking.md | 11482 | 1790455747.0 |
| docs/mac-voice-semantic-endpointing-20260920.md | 3032 | 1790455747.0 |
| docs/mac-voice-server-design.md | 9600 | 1790455747.0 |
| docs/voice-live-bridge-502-20260917.md | 7999 | 1790455750.0 |
| verification/mac-voice-conformance-test.sh | 5462 | 1790455747.0 |

## Bridge.py md5 verification
File: mac-services/bridge.py
Bundle md5: 211a3b33f91920fc87532427e05a5ef6
Expected: 211a3b33f91920fc87532427e05a5ef6
Result: MATCH

## Live Mac comparison
Live Mac reachable: True
Live bridge.py not accessible in expected locations.

## Discrepancies
None