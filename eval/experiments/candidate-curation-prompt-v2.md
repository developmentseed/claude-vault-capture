# Path A — Curation Prompt (claude-sonnet-4-6) — RECALL-TUNED, TYPE-DISCIPLINED (v2)

<!-- EXPERIMENTAL VARIANT v2 — not wired into the pipeline. Differs from the v1
candidate by ONE lever: the `devlog-snippet` catch-all type is removed. v1
(recall-only) captured 24/24 at 25% precision because `devlog-snippet` became a
dump for legal/process sessions (11 of 18 noise items). v2 keeps v1's recall
framing but forces every capture into a substantive type — decision, runbook,
gotcha, or spec — or null. Tests whether type discipline gives high recall on
real engineering artifacts WITHOUT the low-precision flood. -->

You receive the full text of a Claude Code session. Extract the **single most durable artifact** the session produced — but only if it is genuinely one of four substantive types: a **decision**, **runbook**, **gotcha**, or **spec**. When the session clearly produced one, extract it; don't hedge toward null out of caution. Return **exactly** `null` (lowercase, no quotes, no JSON) when the session produced none of those four — for example pure exploration, venting, trivial Q&A, incremental document editing, or reviewing/tuning a plan without a standalone reusable takeaway.

## Artifact types

- **decision** — an architectural or tech-stack choice made with clear reasoning
- **runbook** — a repeatable procedure: steps to deploy, debug, or recover
- **gotcha** — a non-obvious constraint, footgun, or env-specific quirk that bit the user
- **spec** — a well-formed requirement or design doc produced during the session

There are exactly **four** types and **no catch-all**. If the session's output doesn't clearly fit decision, runbook, gotcha, or spec, return `null` — do not stretch a session of incremental edits, correspondence, or plan-tuning into an artifact.

## Output format

Return **valid JSON only** — no prose, no markdown fences.

When returning an artifact:
```json
{
  "title": "Short human title (max 80 chars, no | ]] [[ # `)",
  "type": "decision|runbook|gotcha|spec",
  "body": "<the artifact itself — the runbook steps, the decision rationale, the gotcha description>",
  "source_links": ["https://github.com/org/repo/pull/123"],
  "tags": ["topic1", "topic2"]
}
```

When no artifact is warranted:
```
null
```

## Rules

1. Body is the **artifact itself** — not a transcript recap or summary.
2. Source links: include only URLs explicitly mentioned in the session. Leave empty array if none.
3. Tags: 2–5 lowercase topic tags derived from content. Never include `claude-code` or `curated` (added by the capture tool).
4. Title must not contain `|`, `]]`, `[[`, `#`, or backtick.
5. If the session clearly produced one of the four types, **prefer extracting it** over null — this path is the sole capture, so don't drop real artifacts out of caution. But never invent or stretch a type to avoid null: a session containing no decision, runbook, gotcha, or spec is `null`, however much effort it contained.
