# Review — `tasks/plan.md` and `tasks/todo.md`

Reviewer: Claude · Date: 2026-05-01 · Plan: [`tasks/plan.md`](plan.md) · Todo: [`tasks/todo.md`](todo.md) · Spec: [`.github/SPEC-claude-docs-refactor.md`](../.github/SPEC-claude-docs-refactor.md)

**Verdict.** The plan is structurally sound but has **3 critical issues** that would cause the first install to misbehave or silently no-op. Recent in-flight changes to `install.sh`, `eval/run-install-smoke.sh`, and `.github/SPEC.md` invalidate several of the plan's assumptions. Fix critical findings before starting T1.

## Critical

### C1 — Marker-block insertion order is wrong

**Files:** `tasks/plan.md` Phase 2 (T2 + T3), `tasks/todo.md` T2 + T3.

`install.sh:144-147` (`inject_skill_patch`, first-install branch) inserts new blocks **immediately after the anchor line**, not after the previous END marker. Two patches sharing the same anchor land in **install-order-reversed** order in the file.

Concretely, on a fresh install with both proposed patches added:
1. `daily-devlog.step-9.5.md` injects → file becomes: `<anchor>\n[9.5]\n…`.
2. `daily-devlog.documents-link.md` injects (still anchored at `after-confirmation-step`) → file becomes: `<anchor>\n[9.6]\n[9.5]\n…`.

The user-visible reading order ends up `9.6 → 9.5` — exactly the opposite of `tasks/plan.md` Phase 2 ordering claim ("step 9.5 BEGIN line < step 9.6 BEGIN line"). Same problem on the weekly side (the anchor moved to the end of the file in the recent smoke-test diff, but it's still a single anchor shared by two blocks).

**Fix.** Recommended: collapse — don't add a separate patch file. Extend the existing `skill-patches/daily-devlog.step-9.5.md` to include the new claude-docs scan as a sub-step inside the same marker block. Same for weekly. Reasons:

- Single marker block per skill = single patch file = simpler installer, no ordering brittleness.
- Both blocks are conceptually "claude-vault-capture's contribution to this skill" — splitting them invents an artificial boundary.
- Updates remain atomic per skill.

If the separation is desired (independent update cadence), the alternative is to modify `inject_skill_patch` to support "insert after the last marker block at this anchor" — adds complexity for marginal benefit.

### C2 — `install.sh` won't propagate `vault-save.md` updates

**Files:** `install.sh:182-188` (added in the in-flight diff), `tasks/plan.md` T1, `tasks/todo.md` T1.

The recent install.sh change made the vault-save skill copy **skip if the destination already exists**:

```bash
if [[ ! -f "$VAULT_SAVE_SKILL" ]]; then
    cp "$VAULT_SAVE_PATCH" "$VAULT_SAVE_SKILL"
else
    echo "vault-save skill already installed — skipping (modify manually to update)"
fi
```

After T1 modifies `skill-patches/vault-save.md` (changing destination to `claude-docs/`, adding `summary`/`description`), running `bash install.sh` will print "skipping" and the live `~/.claude/skills/vault-save/SKILL.md` stays on the old version. T1 will appear to install successfully but `/vault-save` will keep writing to `Inbox/auto/` without `summary`/`description`.

This is asymmetric with how `daily-devlog/SKILL.md` and `weekly-recap/SKILL.md` are handled — those use `inject_skill_patch` which always replaces between markers.

**Fix.** Two options:

- **(Preferred)** Make `vault-save/SKILL.md` use the same marker-bounded approach as the other skills. Wrap the patch content in `<!-- BEGIN claude-vault-capture: vault-save -->` … `<!-- END … -->` markers and use `inject_skill_patch` for it. This preserves any user edits outside the markers and propagates updates inside them. T1 owns this change.
- **(Quick fix)** Drop the `if-not-exists` guard — always overwrite. Loses the "preserve user customization" benefit but matches T1's intent.

T1's todo list must include this install.sh fix; otherwise CP-1 manual verification will pass on a fresh machine but silently fail on the user's actual machine where the skill is already installed.

### C3 — Plan references obsolete marker name `step 5.5`

**Files:** `tasks/plan.md` Phase 2 (T3), `tasks/todo.md` T3.

The recent `install.sh` diff renamed the weekly-recap patch:

- File: `weekly-recap.step-5.5.md` → `weekly-recap.step-8.md`.
- Marker: `BEGIN claude-vault-capture: step 5.5` → `BEGIN claude-vault-capture: step 8`.
- Anchor: `before-recap-writing` → `after-recap-writing`.

The plan's T3 ordering check ("step 5.5 BEGIN before step 8.5 BEGIN") and todo's smoke assertion ("step 5.5 precedes step 8.5") both reference the dead name. The new marker name should be `step 8`. The proposed `docs-link-8.5` marker name still reads sensibly next to `step 8`, so the naming itself is fine — only the comparison string is wrong.

**Fix.** If C1 is resolved by collapsing into the existing patch (recommended), this issue evaporates. If kept separate, update all references in `tasks/plan.md` and `tasks/todo.md` to `step 8`.

## Important

### I1 — `description` rendering risk under-mitigated

**Files:** `tasks/plan.md` "Risks" table, `tasks/todo.md` T1.

The plan flags YAML literal-block fragility but the mitigation is "skill patch shows a concrete example". That's necessary but not sufficient — the failure mode is silent (Obsidian renders nothing, frontmatter parsing fails). Stronger mitigations:

- Skill explicitly tells Claude to validate the description by re-parsing the YAML mentally (or instructs to keep it on a single line if uncertain).
- Add a test case in `tests/test_frontmatter.py` that round-trips a multi-paragraph description through a stdlib YAML-block parser to confirm shape. Even better if the migration script's parser (which has to read frontmatter anyway) shares this code.

### I2 — Migration script's YAML parsing approach is unspecified

**Files:** `tasks/plan.md` T4, `tasks/todo.md` T4.

The plan says "parse frontmatter (inline `python3 -c`)" but doesn't specify how. `PyYAML` is not currently a project dependency (curate.py uses string-templated frontmatter). Inline `python3 -c` with `yaml.safe_load` would add a hidden dependency. Pure-stdlib options:

- Regex on the frontmatter slice between the first two `---` lines for `^source:\s*(.+?)\s*$` with `re.MULTILINE`. Sufficient for the migration's needs (only reading `source`, no nested structure).
- A minimal hand-rolled parser. Overkill.

**Fix.** Specify in T4: "frontmatter parsing uses stdlib regex on the slice between the first two `---` lines; reads only the `source:` field. No PyYAML dependency."

### I3 — T5 spec consolidation must absorb the recently-added vault-save section

**Files:** `tasks/plan.md` T5, `tasks/todo.md` T5, `.github/SPEC.md:140-171` (in-flight changes).

`.github/SPEC.md` recently gained a full `/vault-save` section (around line 140) that says "Writes to `Inbox/auto/`". The plan's T5 lists "§2.3 `/vault-save`: change destination references" but doesn't enumerate every spot. Also missing from the T5 checklist:

- The pipeline skip-reasons table now includes `duplicate` (CLAUDE.md:57). The migration script doesn't change this, but if the consolidated spec ever describes skip reasons, ensure parity.
- `.github/SPEC.md:240-249` project-structure block lists `~/.claude/skills/vault-save/SKILL.md` and `CLAUDE.md` global injection — these stay correct, but the `Inbox/auto/` mention near line 145 needs surgery.

**Fix.** Update `tasks/todo.md` T5 to enumerate every `Inbox/auto/` mention currently in `.github/SPEC.md` and `CLAUDE.md`. A `grep -n 'Inbox/auto' .github/SPEC.md CLAUDE.md` on the canonical files would catch them all — pre-implementation discovery for T5.

## Suggestions

### S1 — `scripts/` introduces a new top-level directory for one file

**Files:** `tasks/plan.md` T4 file list, `.github/SPEC.md` §3 project structure.

The repo today has `eval/` for evaluation helpers (`run-fixtures.sh`, `run-install-smoke.sh`). The plan adds `scripts/migrate-claude-docs.sh`. Consider placing it in `eval/` instead, or in a new `bin/` — but a one-file `scripts/` folder is a weak abstraction. Lowest-friction: put it in `eval/` next to the other shell helpers. The `eval/` name is somewhat misleading for a one-shot migration, but the existing convention wins over inventing a new folder.

### S2 — Pre-existing token-limit regression unrelated to this refactor

**File:** `hooks/curate.py:204` (in-flight diff).

```python
limit = int(os.environ.get("CAPTURE_MAX_EST_TOKENS", "50000"))
```

Was previously `str(CAPTURE_MAX_EST_TOKENS)`. Now hardcodes the literal `"50000"` — if the constant `CAPTURE_MAX_EST_TOKENS` ever changes, this default goes stale. Out of scope for the refactor; flag for separate cleanup in the same backlog as S3.

### S3 — Pre-existing smoke-test stale assertion

**File:** `eval/run-install-smoke.sh:82,109` (already noted in plan).

Smoke test asserts `h.get('name') == 'claude-vault-capture'` but `install.sh:80-83` writes the new entry shape without `name`. Either smoke is broken on `main` today, or there's a parallel in-flight change to the hook entry shape that adds `name`. Worth a quick `bash eval/run-install-smoke.sh` baseline run before T1 to confirm starting state.

### S4 — Plan's "Pre-existing observations" section is now incomplete

**File:** `tasks/plan.md` "Pre-existing observations".

Currently lists only the smoke-test stale assertion (S3 above). Add: token-limit hardcoding (S2), and acknowledge the `duplicate` skip_reason addition is consistent with the plan's intent (no conflict — pipeline-internal, doesn't touch `claude-docs/`).

## Action items before starting T1

1. **C1** — decide: collapse into existing patches (recommended) vs. keep separate with installer fix.
2. **C2** — add a step in T1's todo list to convert `vault-save.md` install to the marker-bounded approach (or at minimum, drop the `if-not-exists` skip).
3. **C3** — if keeping separate marker blocks, search-and-replace `step 5.5` → `step 8` in `tasks/plan.md` and `tasks/todo.md`.
4. **I2** — specify "stdlib regex, reads `source:` only" in T4's todo.
5. **I3** — add a `grep -n 'Inbox/auto' .github/SPEC.md CLAUDE.md` discovery step at the top of T5's todo.
6. Run `bash eval/run-install-smoke.sh` once now to baseline the current state (verify S3 isn't a real problem the refactor would inherit).

The vertical-slicing structure, checkpoint placement, and out-of-scope discipline are all in good shape. Once the critical items are corrected, the plan is ready to execute.
