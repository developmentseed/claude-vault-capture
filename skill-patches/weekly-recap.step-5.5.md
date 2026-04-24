<!-- BEGIN claude-vault-capture: step 5.5 -->
## Step 5.5 — Inbox sweep (vault capture eval)

Before writing the recap, triage any captured artifacts from the eval window.

1. List every file in `~/Obsidian/loics_vault/Inbox/auto/` and `~/Obsidian/loics_vault/Inbox/raw/` whose frontmatter `created` date falls within the recap's date range.
2. For each file show: source (`claude-code-curated` or `claude-code-raw`), tags, one-line description from frontmatter.
3. If there are more than 10 files, offer a bulk preamble first:
   `N items to review. [p]roceed item by item / [s]kip all (leave in Inbox) / [d]elete all raw`
   Apply the chosen bulk action and exit the loop; otherwise proceed item by item.
4. For each item prompt: `[p]romote / [d]elete / [s]kip (stay in Inbox)`
   - **Promote** → ask target folder (`work/<project>/`, `notes_patterns/`, `notes_runbooks/`, etc.), move the file, record outcome.
   - **Delete** → remove file.
   - **Skip** → leave in place.
5. **On promotion, write backlinks.** Recap note stem is `notes_weekly/YYYY-Www` (ISO week, zero-padded — e.g. `notes_weekly/2026-W14`). The artifact title from frontmatter is already sanitized by `curate.py`, so the wikilink `[[<artifact-stem>|<title>]]` is safe to emit as-is.
   - In the recap note, append to `## Captured Knowledge` (create the section if absent): `- [[<artifact-stem>|<title>]] (<source>, moved to <target-folder>)`.
   - In the artifact file at its **new** location, append to `## Referenced in` (create if absent): `- [[<recap-stem>|week of <start-date> recap]]`.
   - If the artifact already has a `## Referenced in` entry from a prior devlog promotion, append the recap backlink as a second bullet — do not replace.
   - Link-write failures log and continue; do not undo the file move or count the promotion as failed.
6. **Miss-rate check** (when promoting a raw file):
   - Read `~/DevDS/claude-vault-capture/eval/state/session-index.tsv`.
     Format: `<session_id>\t<path_a_or_null>\t<path_b_or_null>\t<date>` — one line per captured session.
   - Find the line whose first column matches this file's `session_id` frontmatter field.
   - If the second column (`path_a`) is anything other than `null` — curated sibling was captured. No miss.
   - If `path_a` is `null`, or no matching line exists — this is a miss (false-negative on the curation filter). Increment the week's miss count in `eval/state/metrics.md`.
   - If `eval/state/session-index.tsv` does not exist — log a warning in the recap and skip the miss check for this session (do not count as a miss).
7. Append weekly counts to `eval/state/metrics.md`: week, path, captured, promoted, deleted, skipped, misses, no-capture-sessions.
   - **No-capture session** (per SPEC §2.2): a `log.md` entry where both `path_a` and `path_b` are `null` AND `skip_reason_a != "threshold"`. Threshold skips are expected behaviour and are excluded.
   - **25% crash alarm:** compute `ratio = no_capture_sessions / (total_log_entries − threshold_skipped_entries)`. If `ratio > 0.25`, note this prominently — it likely indicates a crashing `curate.py` or misconfigured `$ANTHROPIC_API_KEY`. Threshold skips are excluded from both numerator and denominator so dilution from short debugging sessions doesn't mask real failures.

<!-- END claude-vault-capture: step 5.5 -->
