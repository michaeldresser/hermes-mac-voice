# Mac voice server — DNS-based configuration (2026-09-14 ~22:50Z)

## Gateway access details (discovered, not assumed)

- DNS name: **`michaelacstudio.darknet`** → 192.168.1.2 (reverse DNS from the
  known IP; forward resolution verified from this runtime; case-insensitive —
  use lowercase `michaelacstudio.darknet` to match the swarm's other DNS
  entries: swarm1.darknet, darknaspro.darknet).
- The name resolves through the same internal DNS the swarm uses, so gateway
  config should reference the **name, never the IP** (Michael's requirement:
  IP-locked config is wrong).
- Connectivity verified from the cluster to the Mac: LM Studio (1234) OPEN —
  the path works; voice ports 8880/8000 closed until the servers are installed.

# Configuration values (to apply after Mac servers are up) — APPLIED 2026-09-14 ~23:10Z

In gateway `~/.hermes/.env` (STT endpoint is env-only, import-time read):
```
STT_OPENAI_BASE_URL=http://michaelacstudio.darknet:8000/v1
```

In gateway `~/.hermes/config.yaml`:
```yaml
stt:
  enabled: true
  provider: openai
  openai:
    model: large-v3-turbo        # or the model id Speaches exposes
    api_key: <mac-voice-token>   # only if token auth is configured
tts:
  provider: openai
  openai:
    model: kokoro                # Kokoro-FastAPI model id
    voice: af_heart
    base_url: http://michaelacstudio.darknet:8880/v1
    api_key: <mac-voice-token>
voice:
  client_direct: false
```
Then: `hermes gateway restart` (required for the STT env read).

## Verification sequence after install

1. From cluster: `bash /workspace/mac-voice-conformance-test.sh http://michaelacstudio.darknet:8880 <token>` and same for :8000 (STT).
2. Gateway flip + restart (above).
3. Live desktop voice test (Michael's Hermes Desktop → gateway → Mac).
