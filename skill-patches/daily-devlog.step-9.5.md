## Step 9.5 — Inbox sweep (vault capture eval)

Before scanning for artifacts, check for scrub failures:
- Read `~/DevDS/claude-vault-capture/eval/state/scrub-failures.md` for lines dated today.
- If any exist, display prominently: `⚠ N scrub rule(s) failed today — review eval/state/scrub-failures.md`
- A failing scrub rule means secrets may have flowed through unredacted. Do not promote artifacts from a session that overlaps with a scrub failure window without first reviewing the raw content.

Then scan `Inbox/auto/` and `Inbox/raw/` for files whose frontmatter `created` date matches today's date.

If files are found, display them as:
```
### Captured Artifacts (N curated, M raw)
- [path] — [description from frontmatter]
```

Offer: **"Promote any of these inline into today's note?"** — default no.

**On promotion (user approves):**
1. Today's devlog note stem: `notes_daily/YYYY-MM-DD` (derived from today's date, not file listing).
2. In today's devlog note, locate or create a `## Captured Knowledge` section. Append: `- [[<artifact-stem>|<title>]] (<source>)`. The title is pre-sanitized by curate.py — the wikilink is safe as-is.
3. In the artifact file (at its `Inbox/` path), locate or create a `## Referenced in` section. Append: `- [[<devlog-stem>|<date> devlog]]`.
4. If either write fails, log the failure and continue — partial links are acceptable; blocked promotions are not.
5. The artifact file is **NOT moved** — it stays in `Inbox/` and remains eligible for the next weekly sweep.
