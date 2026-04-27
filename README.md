# claude-vault-capture

Automatic session capture from [Claude Code](https://claude.ai/code) into an Obsidian vault. On every session end, two parallel summaries are written to `Inbox/`:

- **`Inbox/auto/`** — curated artifact (Sonnet): a decision, runbook, gotcha, or spec — or nothing if the session was low-signal.
- **`Inbox/raw/`** — raw baseline (Haiku): always writes a factual bullet summary.

The 4-week eval compares kept-rates between the two paths to decide which approach to keep long-term.

## Prerequisites

- Claude Code CLI installed and in use
- Python 3.11+ and [`uv`](https://docs.astral.sh/uv/)
- Obsidian vault at `~/Obsidian/loics_vault/`
- `ANTHROPIC_API_KEY` — or store it in `~/.claude_vault_token` (the hook reads it from there if the env var is absent)
- The `/daily-devlog` and `/weekly-recap` skills installed in `~/.claude/skills/`

## Install

```bash
git clone https://github.com/lhoupert/claude-vault-capture ~/DevDS/claude-vault-capture
cd ~/DevDS/claude-vault-capture
uv sync
```

Before running the installer, add anchor comments to the skill files:

```bash
# In ~/.claude/skills/daily-devlog/SKILL.md — after the confirmation step:
# <!-- anchor: after-confirmation-step -->

# In ~/.claude/skills/weekly-recap/SKILL.md — after the recap writing step (step 7):
# <!-- anchor: after-recap-writing -->
```

Then install:

```bash
./install.sh
```

The installer is idempotent — safe to re-run after updates. It:
- Creates `~/Obsidian/loics_vault/Inbox/{auto,raw}/`
- Registers the `SessionEnd` hook in `~/.claude/settings.json`
- Patches both skill files with marker-bounded blocks (preserves your edits outside the markers)
- Writes `eval/state/start-date.txt` on first run (eval window anchor)

## Verify it's working

After your next Claude Code session ends, check:

```bash
# Hook fired?
grep SESSION_END_RECEIVED ~/.claude/hooks.log | tail -5

# What happened?
tail -1 ~/DevDS/claude-vault-capture/eval/state/log.md | python3 -m json.tool

# Files written?
ls ~/Obsidian/loics_vault/Inbox/auto/
ls ~/Obsidian/loics_vault/Inbox/raw/
```

Sessions are silently skipped when: < 3 user turns, < 1500 chars of user content, an excluded command was used (`/daily-devlog`, `/weekly-recap`), or the session is already in the index.

## Tests

```bash
uv run pytest          # 105 unit tests, no network, no API key needed
```

## Configuration

| Env var | Default | Effect |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Required; falls back to `~/.claude_vault_token` |
| `CAPTURE_MAX_EST_TOKENS` | `50000` | Token ceiling before skipping (~200 KB transcript) |
| `CAPTURE_MOCK_SDK` | — | Set to `1` to skip API calls and use fixture responses |

## Project structure

```
hooks/
  session-end-capture.sh   # entry point — must return in <200ms
  curate.py                # full pipeline (scrub → filter → API → write → log)
  scrub.py / scrub_rules.py # secret scrubber (no network, pure stdlib)
prompts/
  curation-system-prompt.md  # Path A — Sonnet, may return null
  raw-baseline-prompt.md     # Path B — Haiku, always summarizes
eval/
  fixtures/                # test transcripts and mock API responses
  state/                   # runtime-only (gitignored): log.md, session-index.tsv
.github/
  SPEC.md                  # full specification and decision log
```

## Monitoring during the eval

```bash
# Per-session costs and skip reasons
jq -r '[.date, .skip_reason_a, .skip_reason_b, .cost_usd_a, .cost_usd_b] | @tsv' \
  ~/DevDS/claude-vault-capture/eval/state/log.md

# Sessions that produced output in both paths
jq 'select(.path_a != null and .path_b != null)' \
  ~/DevDS/claude-vault-capture/eval/state/log.md
```

See `.github/SPEC.md` §9 for the full eval checklist (week 1, 2, 4 reviews).
