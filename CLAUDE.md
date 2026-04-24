# claude-vault-capture — agent context

Automatically captures Claude Code sessions into an Obsidian vault on `SessionEnd`. Two parallel paths run on every qualifying session: **Path A** (Sonnet, curated artifact or null → `Inbox/auto/`) and **Path B** (Haiku, always summarizes → `Inbox/raw/`). The 4-week eval compares kept-rates to decide which to keep.

## How to run tests

```bash
uv run pytest          # all 105 tests, no network
CAPTURE_MOCK_SDK=1 uv run pytest -k failure_isolation   # specific test with mock SDK
```

No test requires a live Anthropic API key. `CAPTURE_MOCK_SDK=1` substitutes `eval/fixtures/mock-responses.json`.

## Architecture

```
session-end-capture.sh  →  curate.py (backgrounded, nohup)
                               │
                  scrub → excluded_cmd? → threshold? → token_limit? → dedup?
                               │
                        parallel API calls (ThreadPoolExecutor, 2 workers)
                        Path A: Sonnet → strip fences → parse JSON (or null)
                        Path B: Haiku  → strip fences → parse JSON
                               │
                        scrub outputs → sanitize title → write files → log
```

**Key files:**
- `hooks/session-end-capture.sh` — entry point; reads stdin JSON, logs `SESSION_END_RECEIVED`, backgrounds `curate.py`. Returns in <200ms.
- `hooks/curate.py` — full pipeline. All imports at function scope for fast startup.
- `hooks/scrub.py` + `hooks/scrub_rules.py` — pure stdlib secret scrubber; runs twice (before API call, after).
- `prompts/curation-system-prompt.md` / `prompts/raw-baseline-prompt.md` — the only model-facing prompts; every change is a commit.
- `eval/state/log.md` — JSON-lines eval log (gitignored); `eval/state/session-index.tsv` — dedup index.

## Invariants — never violate these

- **<200ms on the close path.** All model work is backgrounded. Nothing synchronous on `SessionEnd`.
- **Per-path failure isolation.** A Path A exception must not prevent Path B from writing, and vice versa. Catch at `future.result()`, not inside the worker.
- **Scrub runs twice.** On the transcript before any API call; on each model output before writing to disk.
- **Title is always sanitized** before it appears in a filename, frontmatter, or wikilink.
- **Fence-stripping before JSON parsing.** Models sometimes wrap JSON in ` ```json…``` ` despite prompt instructions. `_strip_fences()` is applied to every model response before `json.loads()`.
- **No writes outside `Inbox/`.** Promotions to structured vault folders happen only via explicit user approval in skill patches.
- **`eval/state/` is gitignored.** Runtime state is never committed.

## Pipeline skip reasons (for log.md)

| skip_reason | when |
|---|---|
| `excluded_command` | user turn starts with `/daily-devlog` or `/weekly-recap` |
| `threshold` | < 3 user turns OR < 1500 chars of user content |
| `token_limit` | `len(scrubbed_text) // 4 > CAPTURE_MAX_EST_TOKENS` (default 50 000) |
| `model_returned_null` | Path A only — Sonnet returned the literal string `null` |
| `malformed_json` | model response isn't valid JSON even after fence-stripping |
| `timeout` | API call exceeded 30 s |
| `error:<ExcType>` | any other exception |

## Environment

- Python 3.14, venv at `.venv/`. Run via `uv run` or `.venv/bin/python3`.
- `ANTHROPIC_API_KEY` must be set. If absent in hook env, `session-end-capture.sh` reads `~/.claude_vault_token` as fallback.
- `CAPTURE_MOCK_SDK=1` — skip real API calls; use `eval/fixtures/mock-responses.json`.
- `CAPTURE_MAX_EST_TOKENS` — override token ceiling (default 50 000).

## What NOT to do

- Don't add synchronous work to `session-end-capture.sh` — it must return in <200ms.
- Don't add model calls to the scrubber — it's pure stdlib, no network.
- Don't log to the user's terminal — errors go to `~/.claude/hooks.log` via stderr.
- Don't write outside `Inbox/` from `curate.py`.
- Don't change `eval/state/log.md` schema without bumping `schema_version`.
- Don't add a model call without updating cost estimates in `_estimate_cost_a/b` and §8 of the spec.
