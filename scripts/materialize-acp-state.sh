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

# The CLI's ``resolveToken`` reads persisted credentials from the OS keyring
# (with a file fallback on Linux when no keyring is available). Setting
# ACP_ACCESS_TOKEN/ACP_REFRESH_TOKEN as env vars is only honored by ``acp
# configure`` itself as a flag fallback — so we must call it once at startup
# to persist the tokens where subsequent CLI commands will look for them.
if [ -n "${ACP_ACCESS_TOKEN:-}" ] && [ -n "${ACP_REFRESH_TOKEN:-}" ] \
   && [ -n "${ACP_OWNER_WALLET:-}" ] && command -v acp >/dev/null 2>&1; then
    echo "[materialize-acp-state] running \`acp configure\` (headless) to persist tokens"
    if acp configure \
         --token "$ACP_ACCESS_TOKEN" \
         --refresh-token "$ACP_REFRESH_TOKEN" \
         --wallet "$ACP_OWNER_WALLET" >/dev/null 2>&1; then
        echo "[materialize-acp-state] acp configure OK"
    else
        echo "[materialize-acp-state] acp configure failed — CLI backend will not authenticate"
    fi
    # Pin the active agent so all subsequent CLI reads/writes target it.
    active_wallet=$(sed -n 's/.*"activeWallet"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$CONFIG_DIR/config.json" 2>/dev/null | head -n 1)
    if [ -n "$active_wallet" ]; then
        active_id=$(sed -n "s/.*\"$active_wallet\":.*\"id\":[[:space:]]*\"\([^\"]*\)\".*/\1/p" "$CONFIG_DIR/config.json" 2>/dev/null | head -n 1)
        if [ -n "$active_id" ]; then
            acp agent use --agent-id "$active_id" >/dev/null 2>&1 || true
            echo "[materialize-acp-state] active agent pinned to $active_id"
        fi
    fi
fi

exec "$@"
