#!/usr/bin/env bash
# Install smoke test — runs install.sh against tmp dirs, no writes to ~/.claude/.
# Asserts all post-install invariants and idempotency.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$SCRIPT_DIR/.."
INSTALL="$ROOT/install.sh"

PASS=0
FAIL=0

assert() {
    local desc="$1"
    local condition="$2"
    if eval "$condition" >/dev/null 2>&1; then
        echo "  PASS: $desc"
        PASS=$((PASS + 1))
    else
        echo "  FAIL: $desc"
        FAIL=$((FAIL + 1))
    fi
}

# ── Setup tmp tree ────────────────────────────────────────────────────────────
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

FAKE_HOME="$TMP/home"
FAKE_VAULT="$TMP/vault"
FAKE_CLAUDE="$FAKE_HOME/.claude"
FAKE_SETTINGS="$FAKE_CLAUDE/settings.json"
FAKE_START_DATE="$TMP/start-date.txt"
FAKE_CONFIG="$TMP/capture.env"
FAKE_GLOBAL_CLAUDE_MD="$FAKE_CLAUDE/CLAUDE.md"

mkdir -p "$FAKE_CLAUDE/skills" "$FAKE_VAULT"

# Stub settings.json
cat > "$FAKE_SETTINGS" <<'EOF'
{
  "hooks": {
    "SessionEnd": []
  }
}
EOF

echo "=== First install ==="
FAKE_HOME="$FAKE_HOME" FAKE_VAULT="$FAKE_VAULT" FAKE_SETTINGS="$FAKE_SETTINGS" \
    FAKE_START_DATE_PATH="$FAKE_START_DATE" FAKE_CONFIG="$FAKE_CONFIG" \
    FAKE_GLOBAL_CLAUDE_MD="$FAKE_GLOBAL_CLAUDE_MD" \
    bash "$INSTALL" --smoke-test-mode 2>&1 | sed 's/^/  /'

assert "settings.json has hook entry" "python3 -c \"
import json
with open('$FAKE_SETTINGS') as f:
    d = json.load(f)
hooks = d.get('hooks', {}).get('SessionEnd', [])
assert any(
    any(c.get('command', '').endswith('session-end-capture.sh') for c in h.get('hooks', []))
    for h in hooks
), 'hook not found'
\""

assert "claude-docs/ directory created" "[ -d '$FAKE_VAULT/claude-docs' ]"

assert "capture.env written with vault path" \
    "grep -qF 'CAPTURE_VAULT_DIR=\"$FAKE_VAULT\"' '$FAKE_CONFIG'"

assert "vault-save skill installed with substituted path" \
    "grep -qF '$FAKE_VAULT/claude-docs/' '$FAKE_CLAUDE/skills/vault-save/SKILL.md'"

assert "vault-save placeholders substituted (no __VAULT_DIR__ left)" \
    "! grep -q '__VAULT_DIR__' '$FAKE_CLAUDE/skills/vault-save/SKILL.md'"

assert "eval/state/ dir created" "[ -d '$ROOT/eval/state' ]"

assert "eval/.gitignore contains state/" "grep -q 'state/' '$ROOT/eval/.gitignore' 2>/dev/null"

# ── Second install (idempotency) ──────────────────────────────────────────────
echo ""
echo "=== Second install (idempotency) ==="
# Simulate a user who added an extra var to capture.env (per the README); the
# re-run must preserve it while still refreshing CAPTURE_VAULT_DIR.
echo 'CAPTURE_USE_SUBSCRIPTION=1' >> "$FAKE_CONFIG"
FAKE_HOME="$FAKE_HOME" FAKE_VAULT="$FAKE_VAULT" FAKE_SETTINGS="$FAKE_SETTINGS" \
    FAKE_START_DATE_PATH="$FAKE_START_DATE" FAKE_CONFIG="$FAKE_CONFIG" \
    FAKE_GLOBAL_CLAUDE_MD="$FAKE_GLOBAL_CLAUDE_MD" \
    bash "$INSTALL" --smoke-test-mode 2>&1 | sed 's/^/  /'

assert "re-install preserves user-added capture.env vars" \
    "grep -qx 'CAPTURE_USE_SUBSCRIPTION=1' '$FAKE_CONFIG'"

assert "re-install keeps exactly one CAPTURE_VAULT_DIR line" \
    "[ \$(grep -c '^CAPTURE_VAULT_DIR=' '$FAKE_CONFIG') -eq 1 ]"

assert "settings.json has exactly one hook entry after re-run" "python3 -c \"
import json
with open('$FAKE_SETTINGS') as f:
    d = json.load(f)
hooks = d.get('hooks', {}).get('SessionEnd', [])
count = sum(
    1 for h in hooks
    if any(c.get('command', '').endswith('session-end-capture.sh') for c in h.get('hooks', []))
)
assert count == 1, f'expected 1 hook, got {count}'
\""

# ── Summary ────────────────────────────────────────────────────────────────────
echo ""
echo "Results: $PASS passed, $FAIL failed"
[[ $FAIL -eq 0 ]]
