#!/usr/bin/env bash
# SessionEnd hook entry point — returns in <200ms; all model work is backgrounded.
set -euo pipefail

HOOKS_LOG="$HOME/.claude/hooks.log"
CURATE="$HOME/DevDS/claude-vault-capture/hooks/curate.py"

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

# Ground-truth marker BEFORE backgrounding (pre-log crash gap detection)
mkdir -p "$(dirname "$HOOKS_LOG")"
printf 'SESSION_END_RECEIVED\t%s\t%s\n' "$SESSION_ID" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$HOOKS_LOG"

# Background curate.py — detached, stdout/stderr → hooks.log
nohup "$CURATE" "$TRANSCRIPT_PATH" "$SESSION_ID" "$CWD" \
    >>"$HOOKS_LOG" 2>&1 &

exit 0
