---
title: Mac SSH Access — Cluster-Wide Fleet Key
updated: 2026-09-25
status: active
---

# Mac SSH Access — Cluster-Wide Fleet Key

Any Hermes agent, on any swarm node, can reach Michael's Mac Studio with the key
below. The key is delivered as a **Docker Swarm secret**, not from a profile
volume, so it travels with the service instead of being pinned to one node.

## The canonical transport

```bash
ssh -i /run/secrets/mac_ssh_private_key \
    -o IdentitiesOnly=yes \
    -o BatchMode=yes \
    -o UserKnownHostsFile=/run/secrets/mac_ssh_known_hosts \
    -o StrictHostKeyChecking=yes \
    -o ConnectTimeout=10 \
    michael@192.168.1.2 '<command>'
```

* Host: `192.168.1.2` (`MichaelacStudio.darknet`) — the Mac's active wired IP.
* User: `michael`
* No password is ever needed; no credential entry is required.

## Objects

| Object | Kind | Detail |
|---|---|---|
| `mac_ssh_private_key` | swarm secret | ed25519 private key, comment `swarm-fleet-mac` |
| `mac_ssh_known_hosts` | swarm secret | pinned host keys for 192.168.1.2 (rsa/ecdsa/ed25519) |
| `mac-ssh-ed25519.pub` | Mac-side | `ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAILmxtsg7oGbCvdHmRIjIuLx4c92UC717YUDcqNyf90Ak swarm-fleet-mac` |
| fingerprint | — | `SHA256:s4oYYiUeRp+bUTXQ0J6Mh7snjkfpaZtB15P738sXNoE` |

Mac-side authorization in `michael@192.168.1.2:~/.ssh/authorized_keys`:

```
from="192.168.0.0/23" ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAILmxtsg7oGbCvdHmRIjIuLx4c92UC717YUDcqNyf90Ak swarm-fleet-mac
```

The `from=` restriction admits any host on the 192.168.0.0/23 homelab network,
which covers all current swarm nodes.

## Why it is built this way

Agent profile homes (`/hermes-home`, i.e. `/srv/swarm-local/darkagent/volumes/home`)
are **node-local** bind mounts. A key stored in a profile `.ssh/` therefore only
exists on the single node that happens to run the agent. Because agents are
movable (`placement.strategy: service-group-node`, `movable: true`), that made Mac
access depend on placement — the failure mode this design removes.

Swarm secrets are distributed by the cluster's raft store and materialized at
`/run/secrets/` in every task that declares them, on whichever node that task
runs. That is the same mechanism already used for `darkagent_node_ssh_private_key`.

## Rollout state

Services mounting the key (verified in `TaskTemplate.ContainerSpec.Secrets`):

* `darkagent_darkagent` — live consolidated agent host
* `hermes-dev_agent`, `hermes-cashmonies_agent`, `hermes-krystal_hermes-krystal`
* `hermes-research_agent`, `hermes-research_background-agent`

Declared in managed source
`/mnt/darknaspro-smb-dockerserver-staging/swarmctl/control/services/<stack>/docker-compose.swarm.yml`
as a service-level secret (`uid/gid 10000`, `mode 0400`) plus a top-level
`external: true` entry, then applied with `swarmctl update <stack>`.

**Not covered, by policy:** `darkagent-green` and `hermes-research-green` declare
"mount production messaging, Plane, swarmctl, SSH, or vault credentials" as a
blocked action. Do not add the Mac key there without an explicit policy change.

## Adding a new stack

1. Add to the agent service's `secrets:` block:
   ```yaml
       - source: mac_ssh_private_key
         target: mac_ssh_private_key
         uid: '10000'
         gid: '10000'
         mode: 256
       - source: mac_ssh_known_hosts
         target: mac_ssh_known_hosts
         uid: '10000'
         gid: '10000'
         mode: 256
   ```
2. Add under the top-level `secrets:` block:
   ```yaml
     mac_ssh_private_key:
       external: true
     mac_ssh_known_hosts:
       external: true
   ```
3. `swarmctl validate .../swarmctl.yaml`, then `swarmctl update <stack>`, then
   confirm with `docker service inspect <stack>_<svc> --format '{{range .Spec.TaskTemplate.ContainerSpec.Secrets}}{{.SecretName}} {{end}}'`.
4. Log the mutation with `/hermes-home/bin/swarmctl-log`.

## Rotation

Swarm secrets are immutable. To rotate: generate a new key, append its public key
to the Mac's `authorized_keys`, create `mac_ssh_private_key_v2` /
`mac_ssh_known_hosts_v2`, point the composes at them, `swarmctl update` each
stack, then remove the old public key from the Mac.

## Pitfalls

* Never test this path with `-o StrictHostKeyChecking=no`: that skips host
  verification and hides the real failure. Use the known-hosts secret.
* The Mac's `/Users/michael/.ssh` is `drwx------`; only the `michael` user can
  read `authorized_keys`.
* `swarmctl validate` takes the **manifest** path (`swarmctl.yaml`), not the
  compose path. Passing the compose returns `apiVersion must be swarmctl/v1`.
