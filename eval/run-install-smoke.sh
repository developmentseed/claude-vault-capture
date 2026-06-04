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
FAKE_CONFIG="$TMP/capture.env"
FAKE_GLOBAL_CLAUDE_MD="$FAKE_CLAUDE/CLAUDE.md"

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

## Step 6: Write
Write the recap.

## Step 7: Summary
After writing, display a summary.
<!-- anchor: after-recap-writing -->
EOF

echo "=== First install ==="
FAKE_HOME="$FAKE_HOME" FAKE_VAULT="$FAKE_VAULT" FAKE_SETTINGS="$FAKE_SETTINGS" \
    FAKE_DAILY_SKILL="$FAKE_DAILY_SKILL" FAKE_WEEKLY_SKILL="$FAKE_WEEKLY_SKILL" \
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

assert "daily-devlog SKILL.md has step-9.5 markers" \
    "grep -q 'BEGIN claude-vault-capture: step 9.5' '$FAKE_DAILY_SKILL'"

assert "skill placeholders substituted (no __VAULT_DIR__ left)" \
    "! grep -q '__VAULT_DIR__' '$FAKE_DAILY_SKILL'"

assert "skill patch contains resolved vault path" \
    "grep -qF '$FAKE_VAULT/Inbox/auto/' '$FAKE_DAILY_SKILL'"

assert "vault-save skill installed with substituted path" \
    "grep -qF '$FAKE_VAULT/claude-docs/' '$FAKE_CLAUDE/skills/vault-save/SKILL.md'"

assert "weekly-recap SKILL.md has step 8 markers" \
    "grep -q 'BEGIN claude-vault-capture: step 8' '$FAKE_WEEKLY_SKILL'"

assert "eval/state/ dir created" "[ -d '$ROOT/eval/state' ]"

assert "eval/.gitignore contains state/" "grep -q 'state/' '$ROOT/eval/.gitignore' 2>/dev/null"

# ── Second install (idempotency) ──────────────────────────────────────────────
echo ""
echo "=== Second install (idempotency) ==="
# Simulate a user who added an extra var to capture.env (per the README); the
# re-run must preserve it while still refreshing CAPTURE_VAULT_DIR.
echo 'CAPTURE_USE_SUBSCRIPTION=1' >> "$FAKE_CONFIG"
FAKE_HOME="$FAKE_HOME" FAKE_VAULT="$FAKE_VAULT" FAKE_SETTINGS="$FAKE_SETTINGS" \
    FAKE_DAILY_SKILL="$FAKE_DAILY_SKILL" FAKE_WEEKLY_SKILL="$FAKE_WEEKLY_SKILL" \
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

assert "daily-devlog has exactly one step-9.5 BEGIN marker" \
    "[ \$(grep -c 'BEGIN claude-vault-capture: step 9.5' '$FAKE_DAILY_SKILL') -eq 1 ]"

assert "weekly-recap has exactly one step 8 BEGIN marker" \
    "[ \$(grep -c 'BEGIN claude-vault-capture: step 8' '$FAKE_WEEKLY_SKILL') -eq 1 ]"

# ── Third install: optional skill without anchor must not fail ────────────────
echo ""
echo "=== Third install (skill missing anchor → graceful skip) ==="
NOANCHOR_HOME="$TMP/home2"
NOANCHOR_CLAUDE="$NOANCHOR_HOME/.claude"
NOANCHOR_DAILY="$NOANCHOR_CLAUDE/skills/daily-devlog/SKILL.md"
NOANCHOR_WEEKLY="$NOANCHOR_CLAUDE/skills/weekly-recap/SKILL.md"
mkdir -p "$NOANCHOR_CLAUDE/skills/daily-devlog" "$NOANCHOR_CLAUDE/skills/weekly-recap"
echo '{"hooks":{"SessionEnd":[]}}' > "$NOANCHOR_CLAUDE/settings.json"
printf '# Daily\nNo anchor here.\n' > "$NOANCHOR_DAILY"
printf '# Weekly\nNo anchor here.\n' > "$NOANCHOR_WEEKLY"

set +e
FAKE_HOME="$NOANCHOR_HOME" FAKE_VAULT="$TMP/vault2" FAKE_SETTINGS="$NOANCHOR_CLAUDE/settings.json" \
    FAKE_DAILY_SKILL="$NOANCHOR_DAILY" FAKE_WEEKLY_SKILL="$NOANCHOR_WEEKLY" \
    FAKE_START_DATE_PATH="$TMP/start-date2.txt" FAKE_CONFIG="$TMP/capture2.env" \
    FAKE_GLOBAL_CLAUDE_MD="$NOANCHOR_CLAUDE/CLAUDE.md" \
    bash "$INSTALL" --smoke-test-mode >/dev/null 2>&1
NOANCHOR_RC=$?
set -e

assert "install succeeds despite missing anchor" "[ $NOANCHOR_RC -eq 0 ]"
assert "daily skill left unpatched when anchor absent" \
    "! grep -q 'BEGIN claude-vault-capture: step 9.5' '$NOANCHOR_DAILY'"
assert "vault-save skill still installed without anchors" \
    "[ -f '$NOANCHOR_CLAUDE/skills/vault-save/SKILL.md' ]"

# ── Summary ────────────────────────────────────────────────────────────────────
echo ""
echo "Results: $PASS passed, $FAIL failed"
[[ $FAIL -eq 0 ]]
