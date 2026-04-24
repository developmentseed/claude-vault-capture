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
FAKE_DAILY_SKILL="$FAKE_CLAUDE/skills/daily-devlog/SKILL.md"
FAKE_WEEKLY_SKILL="$FAKE_CLAUDE/skills/weekly-recap/SKILL.md"
FAKE_START_DATE="$TMP/start-date.txt"

mkdir -p "$FAKE_CLAUDE/skills/daily-devlog" "$FAKE_CLAUDE/skills/weekly-recap" "$FAKE_VAULT"

# Stub settings.json
cat > "$FAKE_SETTINGS" <<'EOF'
{
  "hooks": {
    "SessionEnd": []
  }
}
EOF

# Stub SKILL.md files with required anchor comments
cat > "$FAKE_DAILY_SKILL" <<'EOF'
# Daily Devlog Skill

## Step 9: Confirmation
Confirm with user.
<!-- anchor: after-confirmation-step -->

## Step 10: Write
Write the devlog.
EOF

cat > "$FAKE_WEEKLY_SKILL" <<'EOF'
# Weekly Recap Skill

## Step 5: Gather data
Collect data.
<!-- anchor: before-recap-writing -->

## Step 6: Write
Write the recap.
EOF

echo "=== First install ==="
FAKE_HOME="$FAKE_HOME" FAKE_VAULT="$FAKE_VAULT" FAKE_SETTINGS="$FAKE_SETTINGS" \
    FAKE_DAILY_SKILL="$FAKE_DAILY_SKILL" FAKE_WEEKLY_SKILL="$FAKE_WEEKLY_SKILL" \
    FAKE_START_DATE_PATH="$FAKE_START_DATE" \
    bash "$INSTALL" --smoke-test-mode 2>&1 | sed 's/^/  /'

assert "settings.json has hook entry" "python3 -c \"
import json
with open('$FAKE_SETTINGS') as f:
    d = json.load(f)
hooks = d.get('hooks', {}).get('SessionEnd', [])
assert any(h.get('name') == 'claude-vault-capture' for h in hooks), 'hook not found'
\""

assert "daily-devlog SKILL.md has step-9.5 markers" \
    "grep -q 'BEGIN claude-vault-capture: step 9.5' '$FAKE_DAILY_SKILL'"

assert "weekly-recap SKILL.md has step-5.5 markers" \
    "grep -q 'BEGIN claude-vault-capture: step 5.5' '$FAKE_WEEKLY_SKILL'"

assert "eval/state/ dir created" "[ -d '$ROOT/eval/state' ]"

assert "eval/.gitignore contains state/" "grep -q 'state/' '$ROOT/eval/.gitignore' 2>/dev/null"

# ── Second install (idempotency) ──────────────────────────────────────────────
echo ""
echo "=== Second install (idempotency) ==="
FAKE_HOME="$FAKE_HOME" FAKE_VAULT="$FAKE_VAULT" FAKE_SETTINGS="$FAKE_SETTINGS" \
    FAKE_DAILY_SKILL="$FAKE_DAILY_SKILL" FAKE_WEEKLY_SKILL="$FAKE_WEEKLY_SKILL" \
    FAKE_START_DATE_PATH="$FAKE_START_DATE" \
    bash "$INSTALL" --smoke-test-mode 2>&1 | sed 's/^/  /'

assert "settings.json has exactly one hook entry after re-run" "python3 -c \"
import json
with open('$FAKE_SETTINGS') as f:
    d = json.load(f)
hooks = d.get('hooks', {}).get('SessionEnd', [])
names = [h.get('name') for h in hooks]
assert names.count('claude-vault-capture') == 1, f'expected 1, got {names.count(\"claude-vault-capture\")}'
\""

assert "daily-devlog has exactly one step-9.5 BEGIN marker" \
    "[ \$(grep -c 'BEGIN claude-vault-capture: step 9.5' '$FAKE_DAILY_SKILL') -eq 1 ]"

assert "weekly-recap has exactly one step-5.5 BEGIN marker" \
    "[ \$(grep -c 'BEGIN claude-vault-capture: step 5.5' '$FAKE_WEEKLY_SKILL') -eq 1 ]"

# ── Summary ────────────────────────────────────────────────────────────────────
echo ""
echo "Results: $PASS passed, $FAIL failed"
[[ $FAIL -eq 0 ]]
