#!/usr/bin/env bash
# Idempotent installer for claude-vault-capture.
# Safe: backs up files before modifying; validates JSON; uses marker-bounded blocks.
set -euo pipefail

REPO="$HOME/DevDS/claude-vault-capture"

# ── Smoke-test mode: accept overrides via env vars ────────────────────────────
SMOKE="${1:-}"
if [[ "$SMOKE" == "--smoke-test-mode" ]]; then
    CLAUDE_DIR="${FAKE_HOME:-$HOME}/.claude"
    VAULT="${FAKE_VAULT:-$HOME/Obsidian/loics_vault}"
    SETTINGS="${FAKE_SETTINGS:-$CLAUDE_DIR/settings.json}"
    DAILY_SKILL="${FAKE_DAILY_SKILL:-$CLAUDE_DIR/skills/daily-devlog/SKILL.md}"
    WEEKLY_SKILL="${FAKE_WEEKLY_SKILL:-$CLAUDE_DIR/skills/weekly-recap/SKILL.md}"
    START_DATE_FILE="${FAKE_START_DATE_PATH:-$REPO/eval/state/start-date.txt}"
else
    CLAUDE_DIR="$HOME/.claude"
    VAULT="$HOME/Obsidian/loics_vault"
    SETTINGS="$CLAUDE_DIR/settings.json"
    DAILY_SKILL="$CLAUDE_DIR/skills/daily-devlog/SKILL.md"
    WEEKLY_SKILL="$CLAUDE_DIR/skills/weekly-recap/SKILL.md"
    START_DATE_FILE="$REPO/eval/state/start-date.txt"
fi

GLOBAL_CLAUDE_MD="${FAKE_GLOBAL_CLAUDE_MD:-$CLAUDE_DIR/CLAUDE.md}"

HOOK_CMD="\$HOME/DevDS/claude-vault-capture/hooks/session-end-capture.sh"

# ── 1. Create required directories ───────────────────────────────────────────
echo "Creating directories..."
mkdir -p "$VAULT/Inbox/auto" "$VAULT/Inbox/raw" "$VAULT/claude-docs"
mkdir -p "$REPO/eval/state"
mkdir -p "$REPO/eval/fixtures/expected"

# ── 2. Eval state gitignore ───────────────────────────────────────────────────
EVAL_GITIGNORE="$REPO/eval/.gitignore"
if ! grep -qxF 'state/' "$EVAL_GITIGNORE" 2>/dev/null; then
    echo 'state/' >> "$EVAL_GITIGNORE"
    echo "Added state/ to eval/.gitignore"
fi

# ── 3. Vault gitignore (if vault is a git repo) ───────────────────────────────
if git -C "$VAULT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    VAULT_GITIGNORE="$VAULT/.gitignore"
    if ! grep -qxF 'Inbox/raw/' "$VAULT_GITIGNORE" 2>/dev/null; then
        echo 'Inbox/raw/' >> "$VAULT_GITIGNORE"
        echo "Added Inbox/raw/ to vault .gitignore"
    fi
fi

# ── 4. Register SessionEnd hook in settings.json ─────────────────────────────
echo "Updating $SETTINGS..."
if [[ ! -f "$SETTINGS" ]]; then
    echo '{"hooks": {"SessionEnd": []}}' > "$SETTINGS"
fi

# Backup
cp "$SETTINGS" "${SETTINGS}.bak"

python3 - "$SETTINGS" "$HOOK_CMD" <<'PYEOF'
import json, sys

settings_path = sys.argv[1]
hook_cmd = sys.argv[2]

with open(settings_path) as f:
    data = json.load(f)

data.setdefault("hooks", {}).setdefault("SessionEnd", [])
hooks = data["hooks"]["SessionEnd"]

# New format: {"matcher": "", "hooks": [{"type": "command", "command": "..."}]}
# Idempotency: remove any existing entry whose inner command matches ours.
def _is_our_entry(h):
    inner = h.get("hooks", [])
    return any(c.get("command") == hook_cmd for c in inner if isinstance(c, dict))

hooks[:] = [h for h in hooks if not _is_our_entry(h)]
hooks.append({
    "matcher": "",
    "hooks": [{"type": "command", "command": hook_cmd}]
})

with open(settings_path, "w") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
PYEOF

# Validate JSON
if ! python3 -m json.tool "$SETTINGS" >/dev/null 2>&1; then
    echo "ERROR: settings.json invalid after modification — restoring backup"
    cp "${SETTINGS}.bak" "$SETTINGS"
    exit 1
fi
echo "Hook registered in settings.json"

# ── 5. Inject skill patches ───────────────────────────────────────────────────
inject_skill_patch() {
    local skill_file="$1"
    local patch_file="$2"
    local begin_marker="$3"
    local end_marker="$4"
    local anchor="$5"

    if [[ ! -f "$skill_file" ]]; then
        echo "WARNING: $skill_file not found — skipping skill patch"
        return
    fi

    # Verify anchor exists
    if ! grep -qF "$anchor" "$skill_file"; then
        echo "ERROR: anchor '$anchor' not found in $skill_file"
        echo "Add the anchor comment to $skill_file first (see SPEC.md §3)"
        exit 1
    fi

    # Backup
    cp "$skill_file" "${skill_file}.bak"

    local patch_content
    patch_content=$(<"$patch_file")

    if grep -qF "$begin_marker" "$skill_file"; then
        # Replace between markers (preserves content outside markers)
        python3 - "$skill_file" "$begin_marker" "$end_marker" "$patch_content" <<'PYEOF'
import sys, re
path, begin, end, content = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
text = open(path).read()
new_block = f"{begin}\n{content}\n{end}"
# Replace existing marker block
pattern = re.escape(begin) + r".*?" + re.escape(end)
updated = re.sub(pattern, new_block, text, flags=re.DOTALL)
open(path, "w").write(updated)
PYEOF
    else
        # First install: insert after anchor line
        python3 - "$skill_file" "$anchor" "$begin_marker" "$end_marker" "$patch_content" <<'PYEOF'
import sys
path, anchor, begin, end, content = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5]
lines = open(path).readlines()
out = []
for line in lines:
    out.append(line)
    if anchor in line:
        out.append(f"\n{begin}\n{content}\n{end}\n")
open(path, "w").write("".join(out))
PYEOF
    fi
    echo "Patched $skill_file"
}

DAILY_PATCH="$REPO/skill-patches/daily-devlog.step-9.5.md"
WEEKLY_PATCH="$REPO/skill-patches/weekly-recap.step-8.md"
VAULT_SAVE_PATCH="$REPO/skill-patches/vault-save.md"
VAULT_SAVE_TRIGGER_PATCH="$REPO/skill-patches/global-claude-md.vault-save-trigger.md"

if [[ -f "$DAILY_PATCH" ]]; then
    inject_skill_patch \
        "$DAILY_SKILL" \
        "$DAILY_PATCH" \
        "<!-- BEGIN claude-vault-capture: step 9.5 -->" \
        "<!-- END claude-vault-capture: step 9.5 -->" \
        "<!-- anchor: after-confirmation-step -->"
else
    echo "WARNING: $DAILY_PATCH not found — skipping daily-devlog patch"
fi

if [[ -f "$WEEKLY_PATCH" ]]; then
    inject_skill_patch \
        "$WEEKLY_SKILL" \
        "$WEEKLY_PATCH" \
        "<!-- BEGIN claude-vault-capture: step 8 -->" \
        "<!-- END claude-vault-capture: step 8 -->" \
        "<!-- anchor: after-recap-writing -->"
else
    echo "WARNING: $WEEKLY_PATCH not found — skipping weekly-recap patch"
fi

# ── 5b. Install / update vault-save skill ────────────────────────────────────
# vault-save is different from daily/weekly: the patch IS the full skill file,
# not an injection into a foreign SKILL.md. So we cp on first install and
# do a marker-bounded replace on updates.
if [[ -f "$VAULT_SAVE_PATCH" ]]; then
    VAULT_SAVE_SKILL="$CLAUDE_DIR/skills/vault-save/SKILL.md"
    mkdir -p "$(dirname "$VAULT_SAVE_SKILL")"
    VAULT_SAVE_BEGIN="<!-- BEGIN claude-vault-capture: vault-save -->"
    VAULT_SAVE_END="<!-- END claude-vault-capture: vault-save -->"
    if [[ ! -f "$VAULT_SAVE_SKILL" ]]; then
        cp "$VAULT_SAVE_PATCH" "$VAULT_SAVE_SKILL"
        echo "Created vault-save skill at $VAULT_SAVE_SKILL"
    elif grep -qF "$VAULT_SAVE_BEGIN" "$VAULT_SAVE_SKILL"; then
        # Marker-bounded replace (standard update path)
        patch_content=$(<"$VAULT_SAVE_PATCH")
        python3 - "$VAULT_SAVE_SKILL" "$VAULT_SAVE_BEGIN" "$VAULT_SAVE_END" "$patch_content" <<'PYEOF'
import sys, re
path, begin, end, content = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
text = open(path).read()
new_block = f"{begin}\n{content}\n{end}"
pattern = re.escape(begin) + r".*?" + re.escape(end)
updated = re.sub(pattern, new_block, text, flags=re.DOTALL)
open(path, "w").write(updated)
PYEOF
        echo "Updated vault-save skill at $VAULT_SAVE_SKILL"
    else
        # Old install without markers — overwrite to adopt marker format
        cp "$VAULT_SAVE_PATCH" "$VAULT_SAVE_SKILL"
        echo "Migrated vault-save skill to marker-bounded format at $VAULT_SAVE_SKILL"
    fi
else
    echo "WARNING: $VAULT_SAVE_PATCH not found — skipping vault-save skill creation"
fi

# ── 5c. Inject vault-save auto-trigger into global ~/.claude/CLAUDE.md ────────
if [[ -f "$VAULT_SAVE_TRIGGER_PATCH" ]]; then
    touch "$GLOBAL_CLAUDE_MD"

    BEGIN_MARKER="<!-- BEGIN claude-vault-capture: vault-save-trigger -->"
    END_MARKER="<!-- END claude-vault-capture: vault-save-trigger -->"
    TRIGGER_CONTENT=$(<"$VAULT_SAVE_TRIGGER_PATCH")

    cp "$GLOBAL_CLAUDE_MD" "${GLOBAL_CLAUDE_MD}.bak"

    if grep -qF "$BEGIN_MARKER" "$GLOBAL_CLAUDE_MD"; then
        # Replace existing marker block
        python3 - "$GLOBAL_CLAUDE_MD" "$BEGIN_MARKER" "$END_MARKER" "$TRIGGER_CONTENT" <<'PYEOF'
import sys, re
path, begin, end, content = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
text = open(path).read()
new_block = f"{begin}\n{content}\n{end}"
pattern = re.escape(begin) + r".*?" + re.escape(end)
updated = re.sub(pattern, new_block, text, flags=re.DOTALL)
open(path, "w").write(updated)
PYEOF
    else
        # First install: append at end with a blank line separator
        python3 - "$GLOBAL_CLAUDE_MD" "$BEGIN_MARKER" "$END_MARKER" "$TRIGGER_CONTENT" <<'PYEOF'
import sys
path, begin, end, content = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
text = open(path).read()
separator = "\n" if text.endswith("\n") else "\n\n"
block = f"{separator}{begin}\n{content}\n{end}\n"
open(path, "w").write(text + block)
PYEOF
    fi
    echo "Injected vault-save trigger into $GLOBAL_CLAUDE_MD"
else
    echo "WARNING: $VAULT_SAVE_TRIGGER_PATCH not found — skipping global CLAUDE.md update"
fi

# ── 6. Eval window anchor (first install only) ────────────────────────────────
if [[ ! -f "$START_DATE_FILE" ]]; then
    date +%Y-%m-%d > "$START_DATE_FILE"
    echo "Eval window started: $(cat "$START_DATE_FILE")"
fi

echo ""
echo "Install complete."
echo "  Hook: claude-vault-capture → $HOOK_CMD"
echo "  Vault: $VAULT"
echo "  Eval state: $REPO/eval/state/"
echo ""
echo "Migration: run eval/migrate-claude-docs.sh once to move existing /vault-save files out of Inbox/auto/."
