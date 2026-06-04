## Step 9.5 — Inbox triage (vault capture eval)

**Target date.** Throughout this step, use the *target date* parsed in step 1 — the date this devlog is being written for (today by default, or the backfill date when an argument was given). Do **not** assume the calendar "today": use the target date for every date comparison and every stem below.

Before scanning for artifacts, check for scrub failures:
- Read `__REPO_DIR__/eval/state/scrub-failures.md` for lines dated on the target date.
- If any exist, display prominently: `⚠ N scrub rule(s) failed on <target-date> — review eval/state/scrub-failures.md`
- A failing scrub rule means secrets may have flowed through unredacted. Do not promote artifacts from a session that overlaps with a scrub failure window without first reviewing the raw content.

Scan `__VAULT_DIR__/Inbox/auto/` and `__VAULT_DIR__/Inbox/raw/` for files whose frontmatter `created` date matches the target date. If none are found, skip this step silently.

If files are found, display:
```
### Captured Artifacts (N curated, M raw)
- [path] — [description from frontmatter]
```

**Offer a triage mode first — default to high-value only and recommend it:**
`N items from <target-date>. [h]igh-value only (recommended) / [a]ll items one by one / [s]kip all (leave in Inbox)`
- **High-value only** (default) — assess each item from its frontmatter `description`, `source`, and tags, and surface *only* the items worth keeping (concrete decisions, reusable patterns/runbooks, durable project context). Leave low-value items (routine chatter, one-off debugging with no reusable outcome, near-duplicates) in Inbox without prompting. Then run the per-item prompt below on each surfaced item.
- **All items one by one** — run the per-item prompt below on every item regardless of assessed value.
- **Skip all** — leave everything in Inbox (surfaces again in the weekly recap's catchup pass).
With a single item you may skip the mode offer and run the per-item prompt directly.

**For each surfaced item prompt:** `[p]romote / [d]elete / [s]kip (stay in Inbox)`
- **Promote** → ask target folder (`work/<project>/`, `notes_patterns/`, `notes_runbooks/`, etc.), move the file to that folder, record outcome.
- **Delete** → remove the file.
- **Skip** → leave in place (will surface again in the weekly recap's catchup pass).

**On promotion, write backlinks.** The devlog stem: `notes_daily/YYYY-MM-DD` (derived from the target date).
1. In the target date's devlog note, locate or create a `## Captured Knowledge` section. Append: `- [[<artifact-stem>|<title>]] (<source>)`. The title is pre-sanitized by curate.py — the wikilink is safe as-is.
2. In the artifact file at its **new** location, locate or create a `## Referenced in` section. Append: `- [[<devlog-stem>|<date> devlog]]`.
3. If either write fails, log the failure and continue — partial links are acceptable; blocked promotions are not.

**Miss-rate check** (when promoting a raw file — track count in memory, written at end):
- Read `__REPO_DIR__/eval/state/session-index.tsv`.
  Format: `<session_id>\t<path_a_or_null>\t<path_b_or_null>\t<date>` — one line per captured session.
- Find the line whose first column matches this file's `session_id` frontmatter field.
- If `path_a` is anything other than `null` — curated sibling was captured. No miss.
- If `path_a` is `null`, or no matching line exists — this is a miss. Increment the in-memory miss counter.
- If `eval/state/session-index.tsv` does not exist — log a warning and skip (do not count as a miss).

**After triage**, append the target date's counts as a new line to `eval/state/metrics.md`:
`type\tdate\tinbox_count\tpromoted\tdeleted\tskipped\tmisses\tno_capture_sessions`
Where `type` is `daily`, `date` is the target date, `inbox_count` is the total number of files found in Inbox for the target date (before any action was taken), and `no_capture_sessions` is always `0` for daily rows (this column exists to unify the schema with weekly rows).
