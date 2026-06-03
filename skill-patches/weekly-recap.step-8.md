### 8. Inbox catchup & weekly metrics (vault capture eval)

The recap is written. Now surface any inbox items not yet triaged during the week's daily devlogs.

**Step 8a — Catchup triage:**
1. List every file in `~/Obsidian/loics_vault/Inbox/auto/` and `~/Obsidian/loics_vault/Inbox/raw/` whose frontmatter `created` date falls within the recap's date range. These are items skipped or missed during daily triage.
2. If none remain, skip to step 8b.
3. If items remain, tell the user: "The recap is done. N inbox items from this week were not triaged yet."
   Offer a triage mode — default to high-value only and recommend it:
   `[h]igh-value only (recommended) / [a]ll items one by one / [s]kip all (leave in Inbox)`
   - **High-value only** (default) — assess each item from its frontmatter `description`, `source`, and tags, and surface *only* the items worth keeping (concrete decisions, reusable patterns/runbooks, durable project context). Leave low-value items (routine chatter, one-off debugging with no reusable outcome, near-duplicates) in Inbox without prompting.
   - **All items one by one** — present every item regardless of assessed value.
   - **Skip all** — leave everything in Inbox.
4. **Present each surfaced item one at a time.** For each item show: source, tags, one-line description from frontmatter.
   Prompt: `[p]romote / [d]elete / [s]kip (stay in Inbox)`
   - **Promote** → ask target folder (`work/<project>/`, `notes_patterns/`, `notes_runbooks/`, etc.), move the file, record outcome.
   - **Delete** → remove file.
   - **Skip** → leave in place.
5. **On promotion, write backlinks.** Recap stem: `notes_weekly/YYYY-Www` (ISO week, zero-padded — e.g. `notes_weekly/2026-W14`).
   - In the recap note, append to `## Captured Knowledge` (create if absent): `- [[<artifact-stem>|<title>]] (<source>, moved to <target-folder>)`.
   - In the artifact at its **new** location, append to `## Referenced in` (create if absent): `- [[<recap-stem>|week of <start-date> recap]]`. If a devlog backlink already exists, add the recap backlink as a second bullet — do not replace.
   - Link-write failures log and continue; do not undo the file move.
6. **Miss-rate check** (when promoting a raw file):
   - Read `~/DevDS/claude-vault-capture/eval/state/session-index.tsv`.
     Format: `<session_id>\t<path_a_or_null>\t<path_b_or_null>\t<date>` — one line per captured session.
   - Find the line whose first column matches this file's `session_id` frontmatter field.
   - If `path_a` is anything other than `null` — no miss.
   - If `path_a` is `null`, or no matching line exists — this is a miss. Increment the week's in-memory miss counter.
   - If `eval/state/session-index.tsv` does not exist — log a warning and skip (do not count as a miss).

**Step 8b — Consolidate daily promotions into recap:**
For each daily note in the week's date range (skip days where the file doesn't exist), read its `## Captured Knowledge` section and collect wikilinks added by step 9.5. Append them to the recap's `## Captured Knowledge` section (create if absent) as:
`- [[<artifact-stem>|<title>]] (<source>) — promoted <YYYY-MM-DD>`
Skip entries that are already in the recap (from the catchup pass above).

**Step 8c — Weekly metrics rollup:**
1. Read `eval/state/metrics.md`. Sum the `daily`-type rows (promoted, deleted, skipped, misses) for lines whose date falls within the recap's date range.
2. Read `eval/state/log.md`. Count for the week:
   - Total log entries
   - Threshold-skipped entries (`skip_reason_a == "threshold"`)
   - No-capture sessions: entries where both `path_a` and `path_b` are `null` AND `skip_reason_a NOT IN ("threshold", "excluded_command")`
3. Append a weekly summary row to `eval/state/metrics.md`:
   `type\tweek\tinbox_count\tpromoted\tdeleted\tskipped\tmisses\tno_capture_sessions`
   Where `type` is `weekly` and `inbox_count` is the sum of `inbox_count` from the week's daily rows.
4. **25% crash alarm:** compute `ratio = no_capture_sessions / (total_log_entries − threshold_skipped_entries − excluded_command_entries)`. Threshold and excluded-command skips are excluded from both numerator and denominator — they are expected behaviour, not failure. If `ratio > 0.25`, note this prominently — it likely indicates a crashing `curate.py` or misconfigured `$ANTHROPIC_API_KEY`.
5. If `eval/state/session-index.tsv` does not exist — log a warning in the recap and skip the miss check for all sessions this week.
