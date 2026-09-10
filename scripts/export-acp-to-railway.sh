#!/usr/bin/env bash
# One-shot helper: extract the local acp CLI state (config + signer keystore
# + Keychain tokens) and print the `railway variables --set` command that
# ships it to production. Run this on the machine where `acp configure` +
# `acp agent add-signer` were done — typically your laptop.
#
# Nothing is written to disk beyond the encoded blobs. Nothing is uploaded
# by this script — it only prints the commands you run yourself.
#
# Usage:
#   bash scripts/export-acp-to-railway.sh
#
# Prereqs:
#   * acp CLI authenticated locally (`acp agent whoami` works)
#   * railway CLI logged in and linked to the target service
#   * macOS Keychain (this script asks the OS for the tokens)
set -euo pipefail

die() { printf '\n[error] %s\n' "$*" >&2; exit 1; }

CONFIG_JSON="${HOME}/.config/acp/config.json"
[ -f "$CONFIG_JSON" ] || die "config.json not found at $CONFIG_JSON — run \`acp configure\` first"

# macOS: signer-keys.json lives under Application Support/acp-cli
# Linux: it lives under $XDG_CONFIG_HOME/acp-cli
if [ -f "${HOME}/Library/Application Support/acp-cli/signer-keys.json" ]; then
    SIGNER_KEYS="${HOME}/Library/Application Support/acp-cli/signer-keys.json"
elif [ -f "${XDG_CONFIG_HOME:-$HOME/.config}/acp-cli/signer-keys.json" ]; then
    SIGNER_KEYS="${XDG_CONFIG_HOME:-$HOME/.config}/acp-cli/signer-keys.json"
else
    die "signer-keys.json not found — run \`acp agent generate-signer-key\` first"
fi

OWNER_WALLET=$(/usr/bin/python3 -c "import json; print(json.load(open('$CONFIG_JSON'))['ownerWallet'])")
ACTIVE_WALLET=$(/usr/bin/python3 -c "import json; print(json.load(open('$CONFIG_JSON'))['activeWallet'])")

echo "Detected owner wallet:  $OWNER_WALLET" >&2
echo "Detected active agent:  $ACTIVE_WALLET" >&2
echo "Signer keystore:        $SIGNER_KEYS" >&2
echo "" >&2

# Keychain lookups (Keychain will prompt for permission on the first call)
echo "Reading access/refresh tokens from macOS Keychain (you'll be prompted to allow access)..." >&2
ACCESS_TOKEN=$(/usr/bin/security find-generic-password -s "acp-auth" -a "access-token-${OWNER_WALLET}" -w 2>/dev/null || true)
[ -z "$ACCESS_TOKEN" ] && ACCESS_TOKEN=$(/usr/bin/security find-generic-password -s "acp-auth" -a "access-token" -w 2>/dev/null || true)
REFRESH_TOKEN=$(/usr/bin/security find-generic-password -s "acp-auth" -a "refresh-token-${OWNER_WALLET}" -w 2>/dev/null || true)
[ -z "$REFRESH_TOKEN" ] && REFRESH_TOKEN=$(/usr/bin/security find-generic-password -s "acp-auth" -a "refresh-token" -w 2>/dev/null || true)

[ -n "$ACCESS_TOKEN" ] || die "no access token found in Keychain — try \`acp configure\` again"
[ -n "$REFRESH_TOKEN" ] || die "no refresh token found in Keychain — try \`acp configure\` again"

# Base64 encode the two files (single-line, no wrap)
CONFIG_B64=$(/usr/bin/base64 -i "$CONFIG_JSON" | tr -d '\n')
SIGNER_B64=$(/usr/bin/base64 -i "$SIGNER_KEYS" | tr -d '\n')

echo "" >&2
echo "=====================================================================" >&2
echo "Paste the following into your terminal to update Railway env vars." >&2
echo "Railway will auto-redeploy when the variables change." >&2
echo "=====================================================================" >&2
echo ""

cat <<EOF
railway variables \\
  --set "ACP_STATE_CONFIG_B64=${CONFIG_B64}" \\
  --set "ACP_STATE_SIGNER_KEYS_B64=${SIGNER_B64}" \\
  --set "ACP_ACCESS_TOKEN=${ACCESS_TOKEN}" \\
  --set "ACP_REFRESH_TOKEN=${REFRESH_TOKEN}" \\
  --set "ACP_OWNER_WALLET=${OWNER_WALLET}" \\
  --set "VIRTUALS_BACKEND=cli"
EOF
