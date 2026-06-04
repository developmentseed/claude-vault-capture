#!/usr/bin/env bash
# SessionEnd hook entry point — returns in <200ms; all model work is backgrounded.
set -euo pipefail

HOOKS_LOG="$HOME/.claude/hooks.log"

# Resolve the repo from this script's own location so the checkout can live anywhere.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(dirname "$SCRIPT_DIR")"
CURATE="$REPO/hooks/curate.py"
VENV_PYTHON="$REPO/.venv/bin/python3"

# Load per-user config (CAPTURE_VAULT_DIR and any optional flags) written by
# install.sh. Gitignored, so each user's vault path stays out of version control.
if [[ -f "$REPO/capture.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$REPO/capture.env"
    set +a
fi

# Read hook JSON from stdin
HOOK_JSON=$(cat)

# Extract fields
TRANSCRIPT_PATH=$(echo "$HOOK_JSON" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('transcript_path',''))" 2>/dev/null || true)
SESSION_ID=$(echo "$HOOK_JSON" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('session_id',''))" 2>/dev/null || true)
CWD=$(echo "$HOOK_JSON" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('cwd',''))" 2>/dev/null || true)

# Guard: if we couldn't parse the fields, bail silently
if [[ -z "$SESSION_ID" || -z "$TRANSCRIPT_PATH" ]]; then
    exit 0
fi

# Guard: refuse to run unconfigured. install.sh writes CAPTURE_VAULT_DIR into
# capture.env; without it we have no destination, so log a marker and exit cleanly.
if [[ -z "${CAPTURE_VAULT_DIR:-}" ]]; then
    mkdir -p "$(dirname "$HOOKS_LOG")"
    printf 'CAPTURE_NOT_CONFIGURED\t%s\tCAPTURE_VAULT_DIR unset — run install.sh\n' \
        "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$HOOKS_LOG"
    exit 0
fi

# Claude Code sanitizes its environment before spawning hooks, so credentials are
# often absent even when the desktop app has them. Fall back to token files.
if [[ "${CAPTURE_USE_SUBSCRIPTION:-}" == "1" ]]; then
    # Subscription mode: the Claude Agent SDK authenticates with this OAuth token
    # (generate it once with `claude setup-token`).
    if [[ -z "${CLAUDE_CODE_OAUTH_TOKEN:-}" && -f "$HOME/.claude_vault_oauth_token" ]]; then
        # SC2155: export masks cat's exit code on purpose — a token-read hiccup must
        # not abort this close-path hook under `set -e`; curate.py handles missing creds.
        # shellcheck disable=SC2155
        export CLAUDE_CODE_OAUTH_TOKEN="$(cat "$HOME/.claude_vault_oauth_token")"
    fi
elif [[ -z "${ANTHROPIC_API_KEY:-}" && -f "$HOME/.claude_vault_token" ]]; then
    # shellcheck disable=SC2155  # see rationale above: don't abort the close path
    export ANTHROPIC_API_KEY="$(cat "$HOME/.claude_vault_token")"
fi

# Ground-truth marker BEFORE backgrounding (pre-log crash gap detection)
mkdir -p "$(dirname "$HOOKS_LOG")"
printf 'SESSION_END_RECEIVED\t%s\t%s\n' "$SESSION_ID" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$HOOKS_LOG"

# Background curate.py — detached, stdout/stderr → hooks.log
nohup "$VENV_PYTHON" "$CURATE" "$TRANSCRIPT_PATH" "$SESSION_ID" "$CWD" \
    >>"$HOOKS_LOG" 2>&1 &

exit 0
