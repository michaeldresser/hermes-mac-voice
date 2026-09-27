# HANDOFF — own this, and publish it

**From:** swarmcontrol (DarkAgent)
**To:** dev
**Subject:** the Mac local-first TTS/STT voice system for Hermes Desktop — source of truth + GitHub publication
**Requested by:** Michael
**Correlation:** mac-voice-handoff-20260926

---

## 1. What you are being handed

The complete, working **local-first TTS/STT voice stack that runs on the Mac Studio** for
Hermes Desktop. It is live in production right now — this is not a proposal or a sketch. What
does not exist yet is a repository: the code currently lives as unversioned files on the Mac
(`~/gpt-live-bridge/`, `~/vad-deploy/`, `~/smart-turn-bench/`) plus patches and runbooks in the
DarkAgent workspace. **You are taking ownership and putting it on GitHub.**

Read `README.md` first — it is the authoritative description of the architecture, every component,
the config surface, the deployment gotchas, and the known gaps. This file is the *work order*.

## 2. The ask (in priority order)

1. **Create the repo and push this tree.** Suggested name `hermes-mac-voice` on Michael's GitHub
   account — same account and same pattern as the `file-drop` handoff you already have. If the
   repo should have a different name or owner, say so before creating it rather than guessing;
   this is the one decision I cannot make for you.
2. **Make the repo verifiably identical to the running system.** §4 below gives you exact hashes.
   If your copy's hashes don't match, stop and tell me — do not "fix" the difference silently.
3. **Decide the two structural questions in §3** and tell me your call.
4. **Triage the open work in §5** into issues. The semantic-endpointing one is the real feature.

## 3. Two decisions that need your engineering judgement (not my call)

**a. The desktop patches are an upstream contribution, not our code.**
`desktop/patches/0002` and `0003` patch `hermes-agent`'s desktop app
(`apps/desktop/src/app/chat/composer/hooks/`). Upstream ignores its own documented
`voice.silence_*` config on the desktop surface while honouring it in CLI/TUI — that is a genuine
bug, and the evidence is in `docs/`. Choose: keep them as patch files in this repo (today's
state), or prepare them as an upstream issue + PR against `hermes-agent`. I lean toward
**patch files here + a filed upstream issue**, because the patch is revision-sensitive and will
rot; but you own this call and the repo layout should follow it.

**b. `bridge.py` currently has no version control at all.**
It is a 25 KB hand-evolved file deployed on the Mac via launchd. This repo should become its
source of truth, which means the repo needs a deploy path back to the Mac — otherwise the next
edit happens on the Mac again and you have re-created the problem. **Recommendation:** add a
small `scripts/deploy-bridge.sh` that copies `bridge.py` + the plist to the Mac over the verified
SSH channel and `launchctl kickstart`s the job. Note the standing constraint: never publish or run
anything on the Mac as `curl … | bash`; transfer files and review first.

## 4. Verify your copy before you commit anything

The bundle you received was built from the live Mac; the Mac side computed the hash, and it
matched independently after transfer:

| Artifact | Value |
|---|---|
| `voice-handoff-mac.tar.gz` sha256 | `b8690e8947cf36830fff1679d3afab561b17f3a369aeea43b369fe4b6ad802f9` |
| `bridge.py` md5 (live Mac copy) | `211a3b33f91920fc87532427e05a5ef6` |
| `bridge.py` size | 25 111 bytes, mtime 2026-09-17 00:41 |
| Files in the Mac export | 27 |

Re-verify the live side yourself:

```sh
SSH="ssh -i /run/secrets/darkagent_node_ssh_private_key -o IdentitiesOnly=yes \
     -o UserKnownHostsFile=/run/secrets/darkagent_node_ssh_known_hosts \
     -o StrictHostKeyChecking=yes -o BatchMode=yes swarm@<darkagent-node>"
# then, from a node with the Mac key:
ssh -i /run/secrets/mac_ssh_private_key -o IdentitiesOnly=yes \
    -o UserKnownHostsFile=/run/secrets/mac_ssh_known_hosts \
    -o StrictHostKeyChecking=yes michael@192.168.1.2 \
  'md5 ~/gpt-live-bridge/bridge.py; /usr/local/bin/docker ps --format "{{.Names}}|{{.Status}}"'
```

Expect `bridge.py` md5 `211a3b33…` and containers `speaches` + `kokoro-tts` both `Up` (Speaches
`(healthy)`).

## 5. Open items — turn these into issues

| # | Item | State | Notes |
|---|---|---|---|
| 1 | **Semantic endpointing in `bridge.py`** (pipecat Smart Turn v3.2, ONNX int8, in-process, CPU 4 threads) | measured, **not implemented** | The actual feature. 85.8% accuracy on 900 labelled clips; lets `SETTLE_MS` go 5000 → ~600 ms (~4.4 s faster per turn) and cuts premature cutoffs ~4×. No GPU needed; CoreML is *slower*. Bench + validation in `research/semantic-endpointing/` |
| 2 | Desktop VAD upstream bug | open | patch exists here, bug still in upstream `main`; related threads RFC #77111, #96928 |
| 3 | Patch 0001 (server-side voice config) | written, **undeployed** | needs a gateway image rebuild; proposed upstream design only |
| 4 | Streaming-transcription word clipping | known trade-off | ~2 s segment boundary can clip a word; `joinTranscript()` strips overlap but a word split at the cut is unrecoverable |
| 5 | Repo needs a deploy path (see §3b) | missing | otherwise the Mac drifts again |

## 6. Publish-safety check before you push

Do this yourself, don't take my word for it:

- `config/gateway-config.redacted.yaml` was filtered — confirm no keys/tokens survive in it or
  anywhere else (`grep -rniE 'api[_-]?key|token|secret|password|bearer' .`).
- No SSH private keys, no `known_hosts`, no `.env`.
- Do **not** commit the bridge/service logs (`bridge.log`, `bridge.err.log`, `*.log` — the Mac
  side has 355 KB of error log that is noise) or `.venv/` trees.
- The engine addresses are LAN DNS names (`michaelacstudio.darknet`) and `api_key: local` is an
  ignored placeholder — those are intended and safe. Flag it if you disagree.

## 7. Environment facts you will need

- **Mac:** `michaelacstudio.darknet` / `192.168.1.2`, Mac Studio M3 Ultra, macOS 26.3, arm64.
  SSH: `ssh -i /run/secrets/mac_ssh_private_key -o KnownHostsFile=/run/secrets/mac_ssh_known_hosts
  michael@192.168.1.2` (runbook in `docs/mac-ssh-access.md`). Docker CLI is `/usr/local/bin/docker`.
- **Serving profile config** (`/hermes-home/config.yaml` on the cluster) holds the live `tts:` and
  `voice:` blocks — that is the file that made this work, and losing `voice.gpt_live.base_url`
  silently routes audio to `api.openai.com` (see README §5).
- **LM Studio** on the Mac at `:1234/v1` is the live model brain the bridge talks to.
- Everything is Mac-local: audio never leaves the box in either voice mode.

## 8. What I need back

1. Repo URL once pushed (with the commit hash you pushed).
2. Your calls on §3a and §3b.
3. Any hash mismatch or publish-safety finding from §4/§6 — immediately, before pushing.
4. Confirmation of what you are *not* taking on, if anything in §5 is out of scope for you.

Ask me for anything missing; I have the live environment and can pull more evidence. If you need
to see a file I did not include, tell me which one and I will fetch it from the Mac rather than
have you guess at its contents.
