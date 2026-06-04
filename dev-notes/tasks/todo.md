# TODO — `/vault-save` → `claude-docs/` refactor

Plan: [`tasks/plan.md`](plan.md) · Spec: [`.github/SPEC-claude-docs-refactor.md`](../.github/SPEC-claude-docs-refactor.md)

Each top-level task is a vertical slice. Sub-tasks are unchecked work items inside the slice. Acceptance criteria block task completion — do not check the parent until every AC is satisfied and the verification steps in `plan.md` pass.

---

## Phase 1 — Foundation

### [ ] T1 — `/vault-save` writes to `claude-docs/` with `summary` + `description`

- [ ] Add `sanitize_summary(s: str, max_len: int = 140) -> str` to `hooks/curate.py` next to `sanitize_title`. Same rule set; only the length cap differs.
- [ ] Extend `tests/test_frontmatter.py` with a `TestSanitizeSummary` class mirroring `TestSanitizeTitle`. Cover: pipe / `]]` / `[[` / `#` / backtick stripping, control char stripping, internal whitespace collapse, leading/trailing strip, 140-char truncation, normal summary unchanged, deterministic output.
- [ ] Update `skill-patches/vault-save.md`:
  - Wrap entire content in `<!-- BEGIN claude-vault-capture: vault-save -->` / `<!-- END claude-vault-capture: vault-save -->` markers (C2: needed so `inject_skill_patch` can replace on reinstall).
  - Change destination from `~/Obsidian/loics_vault/Inbox/auto/` to `~/Obsidian/loics_vault/claude-docs/`.
  - Add Step 2c — Infer `summary`: one sentence, ≤140 chars, prose; sanitize same as title; self-check character count before writing.
  - Add Step 2d — Infer `description`: 1–3 short paragraphs; YAML literal block scalar (`description: |`); keep content lines consecutively indented (no blank lines that would terminate the block); must not contain a literal `---` line.
  - Update Step 4 (Write the file) — frontmatter now includes `summary` and `description: |` between `title` and `type`.
  - Update Step 5 (Confirm) — message reads `Saved to claude-docs/<filename>`.
- [ ] Update `install.sh` (C2):
  - Step 1: add `mkdir -p "$VAULT/claude-docs"`.
  - §5b: replace the if-not-exists copy block with `inject_skill_patch "$VAULT_SAVE_SKILL" "$VAULT_SAVE_PATCH" "<!-- BEGIN claude-vault-capture: vault-save -->" "<!-- END claude-vault-capture: vault-save -->" ""`. Ensures updates propagate on reinstall.
  - End of script: print reminder `Migration: run eval/migrate-claude-docs.sh once to move existing /vault-save files out of Inbox/auto/.`
- [ ] Extend `tests/test_frontmatter.py` with `TestDescriptionYaml` (I1): assemble frontmatter containing a multi-paragraph `description` value and round-trip through `yaml.safe_load`; assert the `description` key holds the full multi-paragraph string (not a truncated or broken scalar).
- [ ] Update `eval/run-install-smoke.sh`: add `assert "claude-docs/ created" "[ -d '$FAKE_VAULT/claude-docs' ]"` after the existing directory assertions.
- [ ] Run `pytest tests/` — all green.
- [ ] Run `bash eval/run-install-smoke.sh` — all green.
- [ ] Run `bash install.sh` against the real env.
- [ ] Manual: invoke `/vault-save` on a Claude-generated document; verify file at `~/Obsidian/loics_vault/claude-docs/YYYY-MM-DD-<slug>.md` with both `summary` (≤140) and `description` populated.

**🛑 CP-1 — review with user before continuing.**

---

## Phase 2 — Consume side

### [ ] T2 — `/daily-devlog` step 9.6: auto-link today's `claude-docs/`

- [ ] Update `skill-patches/daily-devlog.step-9.5.md` (C1): extend the existing marker block with a step 9.6 sub-step. No new patch file, no new `inject_skill_patch` call. Sub-step content:
  - Scan `~/Obsidian/loics_vault/claude-docs/*.md` where frontmatter `created` matches today's date.
  - In today's devlog (`notes_daily/YYYY-MM-DD.md`), locate or create `## Documents Created`. Append `- [[<stem>|<title>]] — <summary>` per file.
  - In each linked `claude-docs/` file, locate or create `## Referenced in`. Append `- [[<devlog-stem>|<date> devlog]]`.
  - Idempotent: check whether the exact bullet already exists before appending.
  - Failure isolation: a write error on one file does not stop the rest.
- [ ] Update `eval/run-install-smoke.sh`:
  - Assert the step 9.5 block content includes a `claude-docs/` scan reference (grep for `claude-docs` within the `BEGIN claude-vault-capture: step 9.5` … `END` range in `$FAKE_DAILY_SKILL`).
  - Assert idempotency on second install (exactly one `step 9.5` BEGIN marker).
- [ ] Run `bash eval/run-install-smoke.sh` — all green.
- [ ] Run `bash install.sh` against the real env.
- [ ] Manual: save a document via `/vault-save` → run `/daily-devlog` → today's devlog gets `## Documents Created` section with the link; the saved file's `## Referenced in` has the devlog backlink.
- [ ] Manual idempotency: re-run `/daily-devlog` on the same day → no duplicate bullets.

### [ ] T3 — `/weekly-recap` step 8.5: auto-link the week's `claude-docs/`

- [ ] Update `skill-patches/weekly-recap.step-8.md` (C1+C3): extend the existing marker block (`BEGIN claude-vault-capture: step 8`, anchor `after-recap-writing`) with a step 8.5 sub-step. No new patch file, no new `inject_skill_patch` call. Sub-step content:
  - Scan `claude-docs/*.md` where frontmatter `created` falls within the recap's date range.
  - In recap note (`notes_weekly/YYYY-Www.md`), locate or create `## Documents Created`. Append `- [[<stem>|<title>]] — <summary>` per file.
  - In each linked `claude-docs/` file, locate or create `## Referenced in`. Append `- [[<recap-stem>|week of <start-date> recap]]`. If a devlog backlink already exists, append the recap backlink as a second bullet — never replace.
  - Idempotent + failure isolation as per T2.
- [ ] Update `eval/run-install-smoke.sh`:
  - Assert the step 8 block content includes a `claude-docs/` scan reference (grep for `claude-docs` within the `BEGIN claude-vault-capture: step 8` … `END` range in `$FAKE_WEEKLY_SKILL`).
  - Assert idempotency on second install (exactly one `step 8` BEGIN marker).
- [ ] Run `bash eval/run-install-smoke.sh` — all green.
- [ ] Run `bash install.sh` against the real env.
- [ ] Manual: save a document → run `/weekly-recap` → recap gets `## Documents Created`; saved file's `## Referenced in` has the recap backlink.
- [ ] Manual: a file that was linked from `/daily-devlog` (T2) earlier in the week now has *two* bullets in `## Referenced in` (devlog + recap), in that order.

**🛑 CP-2 — full e2e exercise with user before continuing.**

---

## Phase 3 — Migration

### [ ] T4 — One-time migration script for existing exports

- [ ] Create `eval/migrate-claude-docs.sh` (S1: placed in `eval/` next to existing shell helpers, not a new `scripts/` directory):
  - `set -euo pipefail`; paths from `$HOME`.
  - Optional `--dry-run` flag: prints planned moves without executing.
  - Walks `~/Obsidian/loics_vault/Inbox/auto/*.md`. For each file, parse frontmatter using inline `python3 -c` with stdlib regex: extract the slice between the first two `---` lines, then `re.search(r'^source:\s*(.+?)\s*$', slice, re.MULTILINE)`. No `import yaml` / PyYAML dependency (I2). If `source == "claude-code-export"`, plan a move to `~/Obsidian/loics_vault/claude-docs/<basename>`.
  - Collision: destination exists → log skip, leave source untouched, exit code stays 0.
  - Malformed frontmatter → log warning, skip, exit code stays 0.
  - Final summary line: `Moved N files to claude-docs/. Skipped M files (S already at destination, P malformed).`
- [ ] Create `tests/test_migrate_claude_docs.py`:
  - Test 1: mixed seed (one export, one curated, one no-source) → only export moves.
  - Test 2: re-run after Test 1 → no-op (file count stable on both sides, no errors).
  - Test 3: pre-seeded collision in `claude-docs/` → source stays put, destination unchanged.
  - Test 4: malformed frontmatter file → skipped, warning logged, others still process.
  - Test 5: `--dry-run` flag → no actual moves, but exit 0 and prints planned-move lines.
- [ ] Run `pytest tests/test_migrate_claude_docs.py` — all green.
- [ ] Manual: `bash eval/migrate-claude-docs.sh --dry-run` against the real vault → review planned moves.
- [ ] Manual (after CP-3): `bash eval/migrate-claude-docs.sh` → execute. Verify counts match expectation.

**🛑 CP-3 — review dry-run output with user before executing the real move.**

---

## Phase 4 — Spec consolidation

### [ ] T5 — Fold deltas into `.github/SPEC.md`

- [ ] Pre-step (I3): run `grep -n 'Inbox/auto' .github/SPEC.md CLAUDE.md` to enumerate every destination reference that needs updating before opening any editor.
- [ ] Update `.github/SPEC.md`:
  - §2.3 `/vault-save`: change all `Inbox/auto/` destination references to `claude-docs/`. Add `summary` and `description` to the frontmatter schema description.
  - §2.3 `/daily-devlog`: describe the updated step 9.5 block (which now includes the `claude-docs/` scan sub-step); no separate step 9.6 section needed.
  - §2.3 `/weekly-recap`: describe the updated step 8 block (which now includes the `claude-docs/` scan sub-step); no separate step 8.5 section needed.
  - §3 Project structure: add `claude-docs/` under `~/Obsidian/loics_vault/`; add `eval/migrate-claude-docs.sh`; note that `daily-devlog.step-9.5.md` and `weekly-recap.step-8.md` are the (now-extended) patch files.
  - §3 Install strategy: mention the new mkdir and the updated vault-save marker approach.
  - §4 Output format: keep the shared schema for pipeline outputs; add a separate `/vault-save` frontmatter sub-section showing `summary` and `description`.
  - §7 Boundaries: reflect "no `curate.py` writes to `claude-docs/`" and the auto-link rules (idempotent, failure-isolated, append-only).
- [ ] Update `CLAUDE.md` (project): skill integrations section reflects updated step 9.5 / step 8 patch content and the `claude-docs/` path.
- [ ] Delete `.github/SPEC-claude-docs-refactor.md`.
- [ ] Read `.github/SPEC.md` end-to-end → confirm it stands alone with no leftover `Inbox/auto/` or refactor-era references.

**🛑 CP-4 — final review of the canonical spec.**

---

## Pre-existing items flagged (separate cleanup, not in this refactor)

- **S3 — Smoke test stale `name` assertion.** `eval/run-install-smoke.sh:82` asserts `h.get('name') == 'claude-vault-capture'` but `install.sh:80-83` writes the hook entry without a `name` field. Run `bash eval/run-install-smoke.sh` before starting T1 to confirm the current baseline (is it actually broken?). Fix separately.
- **S2 — Token-limit default hardcoding.** `hooks/curate.py:204` hardcodes `"50000"` as the fallback string, previously derived from `CAPTURE_MAX_EST_TOKENS`. If the constant changes the env-override default goes stale. Fix separately.
