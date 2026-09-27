---
title: DarkAgent → Michael's Mac SSH access (verified)
status: active
updated: 2026-09-16
scope: Mac-side operations from the DarkAgent runtime (voice patches, builds)
---

# DarkAgent → Michael's Mac SSH access (verified 2026-09-16)

## What works

DarkAgent's container can log into the Mac directly. Verified end to end on
2026-09-16 (hostname, tooling, checkout recon, patch apply, full app build).

```sh
KH=/tmp/mac_known_hosts
cp /run/secrets/darkagent_node_ssh_known_hosts "$KH" 2>/dev/null; chmod 600 "$KH"
ssh-keyscan -t ed25519 192.168.1.2 >> "$KH"        # /run/secrets file is READ-ONLY

ssh -i /run/secrets/darkagent_node_ssh_private_key \
    -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes \
    -o UserKnownHostsFile="$KH" -o ConnectTimeout=10 \
    michael@192.168.1.2 'hostname'
```

Returns `MichaelacStudio.darknet` (macOS 26.3, arm64).

## Access facts

- **Account/address:** `michael@192.168.1.2` (also `MichaelacStudio.darknet`).
- **Key:** the container's existing `swarm-key`
  (`SHA256:LY2ZmEKFyKC6wARkt9wWohUQP4pqxy2EMqqR25ajY8o`) — already trusted by the
  swarm nodes too. Public half:
  `ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIHphtTl724oELrcMLBG8awnzYOoSjbh8z/wdaTinV10s swarm-key`
- **Mac host key:** `SHA256:eg6N5mrhsXgG+yPnLrzTLgDwutuWe8BWufjJ/1/bndE` (ED25519) —
  independently confirmed from the container and from swarm1.
- **`authorized_keys` restriction on the Mac:** `from="192.168.0.0/23"` — the
  swarm nodes live on `192.168.0.58/23` (same L2 as the Mac's `192.168.1.x`),
  so a narrower `192.168.1.0/24` rule REFUSES swarm-sourced connections. If the
  Mac is ever re-keyed, keep the /23.
- **swarm1 does not hold this key** (`/home/swarm/.ssh/` has only `id_ed25519` +
  `id_rsa`), and its own key is not authorized on the Mac. Only the DarkAgent
  container's `swarm-key` is. No node key distribution is needed.

## Gotchas (all hit for real)

1. **Read-only known-hosts secret.** `/run/secrets/darkagent_node_ssh_known_hosts`
   cannot be appended to; copy it to `/tmp` and add the Mac's key there.
2. **Non-interactive PATH.** `node`/`npm` are NOT on PATH over SSH. Use
   `/opt/homebrew/bin` explicitly (`export PATH=/opt/homebrew/bin:$PATH`), or
   `zsh -lc` — but note the Mac had no Node at all until installed via
   `brew install node` (2026-09-16, Homebrew already present, no sudo needed).
3. **Topology.** The app Michael launches is `/Applications/Hermes.app`
   (v0.17.3, ad-hoc signed). The source checkout is
   `~/.hermes/hermes-agent` — building there produces a DIFFERENT bundle at
   `apps/desktop/release/mac-arm64/Hermes.app`. Decide explicitly which one you
   are patching; default to side-by-side (option B) and leave
   `/Applications/Hermes.app` untouched.
4. **Single-instance / shared state.** Both bundles share bundle id
   `com.nousresearch.hermes` and `~/Library/Application Support/Hermes`, so the
   running app must be quit (Cmd+Q) before launching a different build —
   otherwise the new instance may not start (or the old one just gets focus).
5. **Never pipe remote scripts into a shell.** Michael explicitly rejected
   `curl … | bash` for this Mac: transfer files over the verified SSH channel
   (`scp` with the pinned known-hosts) and review before running.

## Related

- [[desktop-voice-vad-patch]] — the voice/VAD override that motivated this
  access path, including the build recipe and signing workaround.