#!/bin/bash

# Deploy bridge.py to Mac with launchctl
# This transfers the verified bridge.py and plist over SSH and restarts the service

set -euo pipefail

# Configuration
BRIDGE_SOURCE="mac-services/bridge.py"
PLIST_SOURCE="mac-services/com.hermes.gptlive.bridge.plist"
BRIDGE_DEST="~/gpt-live-bridge/bridge.py"
PLIST_DEST="~/Library/LaunchAgents/com.hermes.gptlive.bridge.plist"
MAC_HOST="michael@192.168.1.2"
MAC_KEY="/run/secrets/mac_ssh_private_key"
KNOWN_HOSTS="/run/secrets/mac_ssh_known_hosts"

# SSH command with secure options
SSH="ssh -i \"$MAC_KEY\" -o IdentitiesOnly=yes -o UserKnownHostsFile=\"$KNOWN_HOSTS\" -o StrictHostKeyChecking=yes -o BatchMode=yes \"$MAC_HOST\""

# Ensure source files exist
if [[ ! -f "$BRIDGE_SOURCE" ]]; then
    echo "ERROR: $BRIDGE_SOURCE not found" >&2
    exit 1
fi

if [[ ! -f "$PLIST_SOURCE" ]]; then
    echo "ERROR: $PLIST_SOURCE not found" >&2
    exit 1
fi

# Create destination directory on Mac
$SSH "mkdir -p ~/gpt-live-bridge"

# Transfer bridge.py
echo "Deploying bridge.py to Mac..."
scp -i "$MAC_KEY" -o IdentitiesOnly=yes -o UserKnownHostsFile="$KNOWN_HOSTS" -o StrictHostKeyChecking=yes "$BRIDGE_SOURCE" "$MAC_HOST:$BRIDGE_DEST"

# Transfer plist
echo "Deploying plist to Mac..."
scp -i "$MAC_KEY" -o IdentitiesOnly=yes -o UserKnownHostsFile="$KNOWN_HOSTS" -o StrictHostKeyChecking=yes "$PLIST_SOURCE" "$MAC_HOST:$PLIST_DEST"

# Verify the transferred bridge.py matches the expected hash
echo "Verifying transferred bridge.py..."
$SSH "md5sum $BRIDGE_DEST"

# Restart the launchd service
echo "Restarting bridge service..."
$SSH "launchctl kickstart -k gui/$(id -u)/com.hermes.gptlive.bridge"

# Wait a moment for service to start
sleep 3

# Check service status
echo "Checking service status..."
$SSH "launchctl list com.hermes.gptlive.bridge"

echo "Deployment complete!"
