# Path B — Raw Baseline Prompt (claude-haiku-4-5-20251001)

You receive the full text of a Claude Code session. Summarize what happened — factual, terse, under 60 lines. Always return a summary; never return null.

## Output format

Return **valid JSON only** — no prose, no markdown fences.

```json
{
  "title": "Short topic line (max 80 chars, no | ]] [[ # `)",
  "body": "## What happened\n- bullet\n- bullet\n\n## Outputs\n- bullet\n\n## Source\n- link",
  "source_links": ["https://github.com/org/repo/pull/123"],
  "tags": ["topic1", "topic2"]
}
```

## Rules

1. `## What happened`: 5–10 factual bullets — what was worked on, decided, or tried.
2. `## Outputs`: files changed, PRs opened, commands run that mattered.
3. `## Source`: only URLs explicitly mentioned in the session. Omit section if none.
4. Tags: 2–5 lowercase topic tags. Never include `claude-code` or `raw`.
5. Title must not contain `|`, `]]`, `[[`, `#`, or backtick.
6. Keep body under ~60 lines total. Be terse.
