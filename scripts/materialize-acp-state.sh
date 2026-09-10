#!/bin/sh
# Container startup: rebuild the acp CLI's on-disk state from env vars.
#
# Runs before praetor-server. Reads two base64-encoded blobs — the CLI's
# public config and its signer keystore — and writes them to the paths the
# CLI expects on Linux:
#
#   ACP_STATE_CONFIG_B64      -> $ACP_CONFIG_DIR/config.json
#                                 (falls back to ~/.config/acp/config.json)
#   ACP_STATE_SIGNER_KEYS_B64 -> $XDG_CONFIG_HOME/acp-cli/signer-keys.json
#                                 (default: ~/.config/acp-cli/signer-keys.json)
#
# The access + refresh tokens are read straight from env vars by the CLI
# itself (ACP_ACCESS_TOKEN, ACP_REFRESH_TOKEN, ACP_OWNER_WALLET) — no file
# needed for those.
#
# Set VIRTUALS_BACKEND=cli on Railway so Praetor's SDK auto-detect prefers
# the CLI path.
set -eu

CONFIG_DIR="${ACP_CONFIG_DIR:-$HOME/.config/acp}"
SIGNER_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/acp-cli"

if [ -n "${ACP_STATE_CONFIG_B64:-}" ]; then
    mkdir -p "$CONFIG_DIR"
    printf '%s' "$ACP_STATE_CONFIG_B64" | base64 -d > "$CONFIG_DIR/config.json"
    chmod 600 "$CONFIG_DIR/config.json"
    echo "[materialize-acp-state] wrote $CONFIG_DIR/config.json"
fi

if [ -n "${ACP_STATE_SIGNER_KEYS_B64:-}" ]; then
    mkdir -p "$SIGNER_DIR"
    printf '%s' "$ACP_STATE_SIGNER_KEYS_B64" | base64 -d > "$SIGNER_DIR/signer-keys.json"
    chmod 600 "$SIGNER_DIR/signer-keys.json"
    echo "[materialize-acp-state] wrote $SIGNER_DIR/signer-keys.json"
fi

exec "$@"
