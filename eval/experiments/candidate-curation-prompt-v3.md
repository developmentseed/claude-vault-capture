# Path A — Curation Prompt (claude-sonnet-4-6) — RECALL-TUNED, TYPE-DISCIPLINED (v3)

<!-- EXPERIMENTAL VARIANT v3 — not wired into the pipeline. Keeps v2's removal of
the `devlog-snippet` catch-all (which fixed v1's 25%-precision legal/process
flood), but corrects v2's over-suppression: v2's "don't stretch plan-tuning into
an artifact" wording nulled real architecture DECISIONS that arose from
design/plan reviews (3 of v2's 4 misses). v3 keeps the four-type discipline but
explicitly admits a design/plan review that reaches a concrete technical
conclusion as a `decision`. Targets the recall/precision sweet spot. -->

You receive the full text of a Claude Code session. Extract the **single most durable artifact** the session produced — but only if it is genuinely one of four substantive types: a **decision**, **runbook**, **gotcha**, or **spec**. When the session clearly produced one, extract it; don't hedge toward null out of caution. A design review, plan review, code review, or architecture discussion that reaches a **concrete technical conclusion** (a chosen approach, an identified risk and its mitigation, a sequencing decision) IS a `decision` — capture it. Return **exactly** `null` (lowercase, no quotes, no JSON) when the session produced none of the four types — for example pure exploration that reached no technical conclusion, venting, trivial Q&A, personal correspondence, or incremental editing of a document.

## Artifact types

- **decision** — an architectural or tech-stack choice made with clear reasoning
- **runbook** — a repeatable procedure: steps to deploy, debug, or recover
- **gotcha** — a non-obvious constraint, footgun, or env-specific quirk that bit the user
- **spec** — a well-formed requirement or design doc produced during the session

There are exactly **four** types and **no catch-all**. If the session's output doesn't clearly fit decision, runbook, gotcha, or spec, return `null`. Note: a plan/design review that *reaches a technical conclusion* is a `decision` and should be captured — only null a review that produced no decision. Reserve null for personal correspondence, document editing, and exploration with no technical takeaway.

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
