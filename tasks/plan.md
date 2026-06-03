# Plan — `/vault-save` → `claude-docs/` refactor

Status: draft · Owner: loic · Spec: [`.github/SPEC-claude-docs-refactor.md`](../.github/SPEC-claude-docs-refactor.md)

## Summary

Move `/vault-save` outputs out of `Inbox/auto/` into a top-level `claude-docs/` folder; add `summary` (≤140 chars) and `description` (free-form) frontmatter fields; surface saved docs from `/daily-devlog` and `/weekly-recap` as auto-linked "Documents Created" entries; provide a one-time migration script for existing exports.

The refactor splits along a single axis: deliberate user-authored documents (`claude-docs/`, no triage) vs. speculative session captures (`Inbox/auto/`, triage required). The split exists to honor the user's intent when they invoke `/vault-save` — those documents are pre-approved by definition.

## Architecture before / after

```
BEFORE                                       AFTER
~/Obsidian/loics_vault/                      ~/Obsidian/loics_vault/
  Inbox/                                       Inbox/
    auto/  ◄── Path A captures                   auto/  ◄── Path A captures (unchanged)
           ◄── /vault-save outputs                raw/   ◄── Path B captures (unchanged)
    raw/   ◄── Path B captures                 claude-docs/  ◄── /vault-save outputs (NEW)
                                               (no Inbox triage; auto-linked from devlog/recap)
```

**Boundary the refactor enforces:** `curate.py` owns `Inbox/auto/` and `Inbox/raw/`; `/vault-save` owns `claude-docs/`. No cross-folder writes.

## Dependency graph

```
spec (.github/SPEC-claude-docs-refactor.md) — DONE
  │
  ▼
T1: /vault-save destination + summary/description fields
  │ [foundational — adds claude-docs/ dir, summary field used by T2/T3]
  │
  ├──────────────┬─────────────────┐
  ▼              ▼                 ▼
T2: daily       T3: weekly        T4: migration script
   auto-link       auto-link        [independent of T2/T3 at runtime;
   step 9.6        step 8.5          only requires claude-docs/ from T1]
  │              │                 │
  └──────┬───────┴────────┬────────┘
         ▼                ▼
        Manual end-to-end verification (Phase 5 checkpoint)
         │
         ▼
T5: spec consolidation
   [folds T1-T4 deltas into .github/SPEC.md;
    deletes the refactor scaffolding spec]
```

## Slicing rationale

Each task is a **vertical slice**: skill patch + installer wiring + tests + manual e2e check. After each task lands, a complete user-visible behavior works end-to-end.

- **T1 alone**: user can invoke `/vault-save` and see files land in `claude-docs/` with summary + description. (No links yet, but the destination shift works.)
- **T2 alone (after T1)**: today's saved docs surface in `/daily-devlog` with backlinks.
- **T3 alone (after T1)**: the week's saved docs surface in `/weekly-recap` with backlinks. T2 and T3 are siblings — implementable in either order or in parallel.
- **T4 alone (after T1)**: existing `Inbox/auto/` exports move into `claude-docs/`. Independent of T2/T3.
- **T5**: documentation cleanup. Pure spec edit.

Horizontal alternatives rejected:
- "Update all skill patches first, then installer, then tests" — leaves the system in a state where nothing works end-to-end until the last task. Hard to verify incrementally.
- "Write all tests first" — TDD at the slice boundary, not the milestone boundary, gives faster feedback.

## Phase breakdown

### Phase 1 — Foundation (T1)

**Goal.** `/vault-save` writes to `claude-docs/<filename>.md` with `summary` (≤140 chars) and `description` (multi-paragraph YAML literal block) in frontmatter. `claude-docs/` exists in the vault. No daily/weekly integration yet.

**Files touched:**
- `skill-patches/vault-save.md` — UPDATE: change destination from `Inbox/auto/` to `claude-docs/`; add Step 2c (infer summary), Step 2d (infer description); update Step 4 (write) to render the new fields; update Step 5 (confirm message).
- `install.sh` — UPDATE: add `mkdir -p "$VAULT/claude-docs"` to step 1; convert `vault-save` install (§5b) from if-not-exists copy to marker-bounded `inject_skill_patch` using `<!-- BEGIN/END claude-vault-capture: vault-save -->` markers (C2: ensures updates propagate on reinstall, consistent with how daily/weekly patches are handled); add post-install reminder about migration script.
- `skill-patches/vault-save.md` — UPDATE (installer metadata only): wrap content in `<!-- BEGIN claude-vault-capture: vault-save -->` / `<!-- END claude-vault-capture: vault-save -->` markers so `inject_skill_patch` can replace between them on every `install.sh` run.
- `eval/run-install-smoke.sh` — UPDATE: assert `claude-docs/` directory created in fake vault.
- `hooks/curate.py` — UPDATE (small): factor out a `sanitize_summary(s, max_len=140)` helper alongside `sanitize_title`. Same rule set, different length cap. (Keeps the shared sanitization logic in one place; the migration script's parser will reuse it.)
- `tests/test_frontmatter.py` — EXTEND: add `TestSanitizeSummary` mirroring `TestSanitizeTitle`, with the 140-char cap and otherwise-identical rules.

**Why touch curate.py.** The skill itself is markdown-only, but the sanitization rule must live somewhere testable. Putting `sanitize_summary` next to `sanitize_title` in `curate.py` keeps the rule set discoverable and unit-tested. The skill instructs Claude to apply the same rule conceptually; no code path in the SessionEnd pipeline uses summary/description, so this is a pure helper export.

**Acceptance criteria.**
- `pytest tests/test_frontmatter.py` — all existing tests pass; new `TestSanitizeSummary` passes (8+ test cases mirroring title sanitization); new `TestDescriptionYaml` passes (round-trips a multi-paragraph description through `yaml.safe_load` to confirm the literal-block scalar is well-formed).
- `eval/run-install-smoke.sh` — passes; new assertion `[ -d "$FAKE_VAULT/claude-docs" ]` is present and green.
- Manual: invoke `/vault-save` on any Claude-generated document → file at `~/Obsidian/loics_vault/claude-docs/YYYY-MM-DD-<slug>.md`; opening in Obsidian shows `summary` and `description` in the Properties panel; `summary` ≤ 140 chars; `description` is a YAML literal block.
- Manual: nothing landed in `Inbox/auto/`.

**Verification steps.**
1. `pytest tests/`
2. `bash eval/run-install-smoke.sh`
3. `bash install.sh` (real install)
4. Test `/vault-save` on a fresh document
5. `ls ~/Obsidian/loics_vault/claude-docs/` shows the new file
6. `cat` that file → verify frontmatter fields

**Risk.** Low. Skill-only change for the user-facing path; the curate.py addition is a pure helper with no call sites in the existing pipeline.

---

### Phase 2 — Consume side (T2 + T3, can be parallel)

**Goal.** `/daily-devlog` and `/weekly-recap` automatically surface `claude-docs/` files in the relevant date range, render them as wikilinks with their `summary`, and append a `## Referenced in` backlink in each linked file.

#### T2 — daily-devlog auto-link (step 9.6)

**Files touched:**
- `skill-patches/daily-devlog.step-9.5.md` — UPDATE: extend the existing marker block with a step 9.6 sub-step (scan `claude-docs/` for `created == today`, render `## Documents Created` section, append backlinks to each file's `## Referenced in`). No new `inject_skill_patch` call needed — the existing `after-confirmation-step` call already installs this file. (C1: two patches sharing the same anchor would land in reversed order on first install; single block avoids ordering brittleness.)
- `eval/run-install-smoke.sh` — UPDATE: assert the step 9.5 block content includes the `claude-docs/` scan sub-step; assert idempotency.

**Acceptance criteria.**
- Smoke test: step 9.5 marker block present exactly once; content includes the `claude-docs/` scan.
- Smoke test re-run: idempotent (content stable, no duplication).
- Manual: save a document via `/vault-save` today → run `/daily-devlog` → today's devlog has a `## Documents Created` section with `- [[<stem>|<title>]] — <summary>`. Open the linked file → its `## Referenced in` section has `- [[notes_daily/YYYY-MM-DD|<date> devlog]]`.
- Manual: re-running `/daily-devlog` on the same day must not duplicate the bullet (idempotency on the link writes).

#### T3 — weekly-recap auto-link (step 8.5)

**Files touched:**
- `skill-patches/weekly-recap.step-8.md` — UPDATE: extend the existing marker block (anchor `after-recap-writing`, marker `step 8`) with a step 8.5 sub-step (scan `claude-docs/` for the recap's date range, render `## Documents Created`, append backlinks). No new `inject_skill_patch` call needed. (C1 + C3: the plan previously referenced both a dead `step 5.5` marker name and a `before-recap-writing` anchor that no longer exists; collapsing into the existing block makes both issues moot.)
- `eval/run-install-smoke.sh` — UPDATE: assert the step 8 block content includes the `claude-docs/` scan sub-step; assert idempotency.

**Acceptance criteria.**
- Smoke test: step 8 marker block present exactly once; content includes the `claude-docs/` scan.
- Smoke test re-run: idempotent.
- Manual: save a document → run `/weekly-recap` for the current week → recap has `## Documents Created` linking the file. Linked file's `## Referenced in` has the recap backlink.
- Manual: a file that was already linked from a devlog (T2) accumulates the recap backlink as a second bullet — the devlog backlink is preserved.

**Verification steps (T2 + T3 together).**
1. `pytest tests/` — no regressions.
2. `bash eval/run-install-smoke.sh` — passes with new assertions.
3. `bash install.sh` (real install) — apply patches.
4. Save a fresh document, run `/daily-devlog`, then run `/weekly-recap`. Inspect both notes and the doc's `## Referenced in` section.

**Risk.** Medium. The skills run inside Claude conversations, not as deterministic code — verification is observational. Mitigation: clear, prescriptive patch language ("locate or create the section", "append exactly", "do not duplicate") plus a manual e2e dry-run before declaring done.

---

### Phase 3 — Migration (T4)

**Goal.** Existing `/vault-save` outputs in `Inbox/auto/` (identifiable by `source: claude-code-export` in frontmatter) move to `claude-docs/`. Pipeline-generated artifacts (`source: claude-code-curated`) stay put.

**Files touched:**
- `eval/migrate-claude-docs.sh` — NEW. Bash + inline `python3 -c` for frontmatter parsing (stdlib regex on the slice between the first two `---` lines; reads only the `source:` field; no PyYAML dependency). Dry-run flag (`--dry-run`) prints planned moves without executing. (S1: placed in `eval/` next to existing shell helpers rather than a one-file `scripts/` directory.)
- `tests/test_migrate_claude_docs.py` — NEW. Unit tests against tmp `Inbox/auto/` and `claude-docs/` trees.
- `.github/SPEC-claude-docs-refactor.md` — REFERENCE only (no edit needed; spec already documents the migration).

**Acceptance criteria.**
- Test: seed a tmp `Inbox/auto/` with three files (export / curated / no-source). Run migration. Assert: only the export file moved; the other two are untouched in `Inbox/auto/`; `claude-docs/` contains exactly one file.
- Test: re-run idempotency. Second run is a no-op (no errors, no double-moves, exit 0).
- Test: collision handling. Pre-seed `claude-docs/<basename>` to match an `Inbox/auto/` file. Assert: the source file stays in `Inbox/auto/`; destination unchanged; script logs the skip; exit 0.
- Test: malformed frontmatter (missing `---`, unparseable YAML). Assert: file is skipped (not moved), warning logged, script does not crash.
- Manual: run on the real vault — verify counts match expectations (compare `grep -l 'source: claude-code-export' Inbox/auto/*.md` count with files now in `claude-docs/`).

**Verification steps.**
1. `pytest tests/test_migrate_claude_docs.py` — all green.
2. `bash eval/migrate-claude-docs.sh --dry-run` (against the real vault) — prints planned moves, makes none.
3. Inspect the planned moves; if sensible, `bash eval/migrate-claude-docs.sh` (no flag) — execute.
4. Verify counts and spot-check a moved file.

**Risk.** Medium-low. The script touches the user's actual vault (`mv`), but it's bounded by frontmatter and has dry-run. The biggest risk is misclassifying a file's `source` field — guarded by the unit tests.

---

### Phase 4 — Spec consolidation (T5)

**Goal.** The canonical spec at `.github/SPEC.md` reflects the new state (claude-docs/ folder, summary/description fields, step 9.6, step 8.5). The refactor scaffolding spec is deleted.

**Pre-step (I3).** Before editing, run `grep -n 'Inbox/auto' .github/SPEC.md CLAUDE.md` to enumerate every destination reference that needs updating. This catches mentions added after the refactor spec was written (e.g., the `/vault-save` section added around line 140 of `.github/SPEC.md`).

**Files touched:**
- `.github/SPEC.md` — UPDATE: §2.3 (`/vault-save`), §3 (project structure — add `claude-docs/`, add `eval/migrate-claude-docs.sh`, add the two updated skill-patch files), §4 (frontmatter shared schema or separate vault-save schema). Add sub-sections for the updated step 9.5 / step 8 content; remove the now-dead `step 5.5` and `step 9.6`/`step 8.5` as separate sections (they live inside the existing blocks).
- `.github/SPEC-claude-docs-refactor.md` — DELETE.
- `CLAUDE.md` (project) — UPDATE: skill integrations section reflects updated step 9.5 / step 8 patch content and the new `claude-docs/` path.

**Acceptance criteria.**
- `.github/SPEC.md` self-contained: a fresh reader can understand `claude-docs/` without referring to the refactor spec.
- No dead references to `Inbox/auto/` for `/vault-save` content in either SPEC.md or CLAUDE.md.
- Refactor spec file removed from the tree.

**Risk.** Low. Documentation-only.

---

## Checkpoints (human review gates)

- **CP-1 (after T1)**: review `tasks/plan.md` (this file) and the implementation diff. Run `/vault-save` once on a real document — does the new location and frontmatter feel right? If `summary` quality is poor, tune the skill instructions before continuing.
- **CP-2 (after T2 + T3)**: end-to-end manual exercise — save 2-3 documents over a day, run `/daily-devlog`, then run `/weekly-recap` covering that day. Are the links correct? Does the `## Documents Created` section read well? Are backlinks bidirectional in Obsidian?
- **CP-3 (after T4)**: dry-run the migration on the real vault. Spot-check the planned moves before executing.
- **CP-4 (after T5)**: read `.github/SPEC.md` end-to-end. Does it stand alone? Are there any leftover refactor-era references?

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Skill instructions don't reliably produce `summary` ≤ 140 chars | Skill patch enforces the cap explicitly; sanitization at write time would clip silently — instead, prescribe in the skill that Claude must self-check the count before writing. Add an example with a too-long summary getting trimmed in the skill text. |
| `description: \|` YAML block scalar is fragile to indentation mistakes | Skill patch shows a concrete example and instructs Claude to keep `description` on consecutive indented lines (no blank lines that would terminate the block). Add `TestDescriptionYaml` in `tests/test_frontmatter.py` that round-trips a multi-paragraph description through `yaml.safe_load` to confirm correct block-scalar shape. Manual e2e verification opens the file in Obsidian Properties panel. |
| Migration script misidentifies a file's `source` field due to malformed frontmatter | Test case for malformed YAML; script skips files it can't parse and logs a warning. |
| Daily/weekly skill changes silently regress on a future install (a future skill upgrade overwrites the patch) | Marker-bounded blocks already handle this; the installer replaces only between markers. Smoke test asserts ordering and idempotency. |
| `claude-docs/` becomes a dumping ground over time | Out of scope for v1. If volume warrants, revisit folder hierarchy in a later spec. |

## Out of scope

Explicit non-goals so the implementation stays narrow:

- No changes to `curate.py`'s pipeline writes (still `Inbox/auto/` for Path A, `Inbox/raw/` for Path B).
- No changes to the secret scrubber. `/vault-save` still bypasses it.
- No automated migration on `install.sh`. User runs `eval/migrate-claude-docs.sh` once, manually.
- No "save again, replacing" mode for `/vault-save`. Filename collisions still suffix with `-2`, `-3`, …
- No folder hierarchy under `claude-docs/`. Flat for v1.
- No `description` rendering in backlinks — backlinks use `summary` only. `description` lives in frontmatter for Obsidian/Dataview consumption.
- No new `source` value. Existing `claude-code-export` is preserved post-migration; it answers "where did this come from?", not "which folder is this in?".

## Pre-existing observations (not in scope of this refactor)

- **S3 — Smoke test stale assertion.** `eval/run-install-smoke.sh:82` asserts `h.get('name') == 'claude-vault-capture'` but `install.sh:80-83` writes the hook entry without a `name` field. Baseline the smoke test with `bash eval/run-install-smoke.sh` before starting T1 to confirm whether this is already broken (action item from the review). Not addressed here — flag for separate cleanup.
- **S2 — Token-limit hardcoding.** `hooks/curate.py:204` hardcodes `"50000"` as the default token ceiling string, previously derived from `CAPTURE_MAX_EST_TOKENS`. If the constant changes the default goes stale. Not addressed here — flag alongside S3 for separate cleanup.

## Implementation order

1. T1 — Foundation
2. CP-1
3. T2, T3 — Consume side (sequential or parallel; no inter-dependency)
4. CP-2
5. T4 — Migration
6. CP-3
7. T5 — Consolidation
8. CP-4

Each numbered step is a stop point: a green test suite, a passing smoke test, and a clean working tree before moving on. No half-merged states.

---

*Plan supersedes itself on completion. After CP-4, this file moves to `tasks/done/plan-claude-docs-refactor.md` for archival or is deleted alongside the refactor spec — at user's preference.*
