## Step 9.5 — Inbox triage (vault capture eval)

Before scanning for artifacts, check for scrub failures:
- Read `~/DevDS/claude-vault-capture/eval/state/scrub-failures.md` for lines dated today.
- If any exist, display prominently: `⚠ N scrub rule(s) failed today — review eval/state/scrub-failures.md`
- A failing scrub rule means secrets may have flowed through unredacted. Do not promote artifacts from a session that overlaps with a scrub failure window without first reviewing the raw content.

Scan `~/Obsidian/loics_vault/Inbox/auto/` and `~/Obsidian/loics_vault/Inbox/raw/` for files whose frontmatter `created` date matches today's date. If none are found, skip this step silently.

If files are found, display:
```
### Captured Artifacts (N curated, M raw)
- [path] — [description from frontmatter]
```

If there are more than 5 items, offer a bulk preamble first:
`N items from today. [p]roceed item by item / [s]kip all (leave in Inbox)`
Otherwise proceed item by item directly.

**For each item prompt:** `[p]romote / [d]elete / [s]kip (stay in Inbox)`
- **Promote** → ask target folder (`work/<project>/`, `notes_patterns/`, `notes_runbooks/`, etc.), move the file to that folder, record outcome.
- **Delete** → remove the file.
- **Skip** → leave in place (will surface again in the weekly recap's catchup pass).

**On promotion, write backlinks.** Today's devlog stem: `notes_daily/YYYY-MM-DD` (derived from today's date).
1. In today's devlog note, locate or create a `## Captured Knowledge` section. Append: `- [[<artifact-stem>|<title>]] (<source>)`. The title is pre-sanitized by curate.py — the wikilink is safe as-is.
2. In the artifact file at its **new** location, locate or create a `## Referenced in` section. Append: `- [[<devlog-stem>|<date> devlog]]`.
3. If either write fails, log the failure and continue — partial links are acceptable; blocked promotions are not.

**Miss-rate check** (when promoting a raw file — track count in memory, written at end):
- Read `~/DevDS/claude-vault-capture/eval/state/session-index.tsv`.
  Format: `<session_id>\t<path_a_or_null>\t<path_b_or_null>\t<date>` — one line per captured session.
- Find the line whose first column matches this file's `session_id` frontmatter field.
- If `path_a` is anything other than `null` — curated sibling was captured. No miss.
- If `path_a` is `null`, or no matching line exists — this is a miss. Increment the in-memory miss counter.
- If `eval/state/session-index.tsv` does not exist — log a warning and skip (do not count as a miss).

**After triage**, append today's counts as a new line to `eval/state/metrics.md`:
`type\tdate\tinbox_count\tpromoted\tdeleted\tskipped\tmisses\tno_capture_sessions`
Where `type` is `daily`, `inbox_count` is the total number of files found in Inbox for today (before any action was taken), and `no_capture_sessions` is always `0` for daily rows (this column exists to unify the schema with weekly rows).
