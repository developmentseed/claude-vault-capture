# claude-vault-capture

Automatically turn your [Claude Code](https://claude.ai/code) sessions into notes in your [Obsidian](https://obsidian.md) vault. When a session ends, a background job summarizes it and drops a markdown file into your vault's `Inbox/` — so the decisions, runbooks, and gotchas you worked through don't evaporate when you close the terminal.

Nothing runs synchronously on session close (the hook returns in well under 200 ms); all model work is backgrounded. Secrets are scrubbed before anything is sent to a model and again before anything is written to disk.

Two summaries are written per qualifying session:

- **`Inbox/auto/`** — a *curated* artifact (Sonnet): a single decision, runbook, gotcha, or spec — or nothing, if the session was low-signal.
- **`Inbox/raw/`** — a *raw* baseline (Haiku): always a short factual bullet summary.

> Why two? The author runs a 4-week A/B eval comparing how often each path produces something worth keeping. If you just want capture, both paths are useful as-is — see [The eval](#the-eval-optional) to opt out of one.

## Prerequisites

- Claude Code CLI, installed and in use
- Python 3.11+ and [`uv`](https://docs.astral.sh/uv/)
- An Obsidian vault (any location — you'll point the installer at it)
- An `ANTHROPIC_API_KEY`, **or** a Claude Max subscription (see [below](#using-your-claude-max-subscription-instead-of-an-api-key))

## Install

Clone anywhere — the hook locates itself, so the path is up to you:

```bash
git clone https://github.com/lhoupert/claude-vault-capture
cd claude-vault-capture
uv sync                                   # create .venv/ and install dependencies
./install.sh --vault ~/path/to/YourVault  # register the hook + point it at your vault
```

If you omit `--vault`, the installer reads `CAPTURE_VAULT_DIR`, reuses a previous
choice from `capture.env`, or prompts you. Your vault path is written to a
gitignored `capture.env` and never committed.

The installer is idempotent — safe to re-run after updates. It:
- Creates `<vault>/Inbox/{auto,raw}/` and `<vault>/claude-docs/`
- Registers the `SessionEnd` hook in `~/.claude/settings.json`
- Writes `capture.env` with your `CAPTURE_VAULT_DIR`
- Installs the `/vault-save` skill and its auto-trigger

To use your Max subscription instead of an API key, also install the Agent SDK:

```bash
uv sync --extra subscription
```

## Verify it's working

After your next Claude Code session ends, check:

```bash
# Hook fired?
grep SESSION_END_RECEIVED ~/.claude/hooks.log | tail -5

# What happened? (run from the repo)
tail -1 eval/state/log.md | python3 -m json.tool

# Files written?
ls "$(grep -E '^CAPTURE_VAULT_DIR=' capture.env | cut -d= -f2- | tr -d '\"')"/Inbox/auto/
```

Sessions are silently skipped when: fewer than 3 user turns, under 1500 chars of user content, a command listed in `CAPTURE_EXCLUDED_COMMANDS` was used (empty by default — see [Consuming captures](#consuming-captures-the-inbox-contract)), or the session is already indexed.

## Tests

```bash
uv run pytest          # 155 tests, no network, no API key needed
```

A 156th test makes real model calls and is skipped unless `CAPTURE_LIVE_TESTS=1`.
The installer has its own smoke test: `bash eval/run-install-smoke.sh`.

If you plan to contribute, install the git hooks so the same checks CI runs
(ruff, shellcheck, zizmor, tests) run locally first:

```bash
uv run pre-commit install          # one-time
uv run pre-commit run --all-files  # run them all now
```

## Configuration

| Env var | Default | Effect |
|---|---|---|
| `CAPTURE_VAULT_DIR` | — | **Required.** Your Obsidian vault path. Set by `install.sh` (via `--vault`/prompt) into `capture.env`, which the hook sources. |
| `ANTHROPIC_API_KEY` | — | Required in API-key mode; falls back to `~/.claude_vault_token` |
| `CAPTURE_USE_SUBSCRIPTION` | — | Set to `1` to bill model calls to your Claude Max subscription (see below) |
| `CLAUDE_CODE_OAUTH_TOKEN` | — | Subscription auth; falls back to `~/.claude_vault_oauth_token` |
| `CAPTURE_MAX_EST_TOKENS` | `50000` | Token ceiling before skipping (~200 KB transcript) |
| `CAPTURE_MOCK_SDK` | — | Set to `1` to skip API calls and use fixture responses |
| `CAPTURE_EXCLUDED_COMMANDS` | — | Comma-separated slash commands whose sessions are not captured (e.g. `/my-journal,/my-recap`). Empty by default |

Extra variables (e.g. `CAPTURE_USE_SUBSCRIPTION=1`) can be added to `capture.env` —
the hook sources the whole file before launching the worker.

### Using your Claude Pro or Max subscription instead of an API key

By default the two model calls hit the metered Messages API (`ANTHROPIC_API_KEY`).
Set `CAPTURE_USE_SUBSCRIPTION=1` to route them through the Claude Code runtime
(via the [Claude Agent SDK](https://docs.claude.com/en/api/agent-sdk/overview))
and bill them to your Pro or Max subscription instead. Works the same on either
plan — both share the rolling rate limit noted in the trade-offs below.

**1. Install the transport and turn the flag on**

```bash
uv sync --extra subscription                 # installs claude-agent-sdk (the `claude` CLI must also be installed)
echo 'CAPTURE_USE_SUBSCRIPTION=1' >> capture.env
```

**2. Generate a long-lived OAuth token**

Run this in a *normal terminal* — it opens a browser (or prints a URL to open),
so it can't complete from inside a non-interactive shell:

```bash
claude setup-token        # authorize in the browser; it prints a token starting with sk-ant-oat01-…
```

**3. Make the token available to the hook**

The hook authenticates with `CLAUDE_CODE_OAUTH_TOKEN`, falling back to the file
`~/.claude_vault_oauth_token`. Choose one of:

*Option A — plaintext file (simplest):*

```bash
umask 077 && printf '%s\n' '<token>' > ~/.claude_vault_oauth_token
```

*Option B — macOS Keychain (recommended; no plaintext token on disk):*

Store the token in your login Keychain once, then let `capture.env` resolve it
at hook time. `capture.env` is sourced with `set -a`, so the export reaches the
backgrounded worker.

```bash
# Store it once. -A lets the background hook read it without a GUI prompt:
security add-generic-password -U -a "$(id -un)" -s claude-vault-oauth -w '<token>' -A

# Point capture.env at the Keychain item:
cat >> capture.env <<'EOF'
export CLAUDE_CODE_OAUTH_TOKEN="$(security find-generic-password -s claude-vault-oauth -w 2>/dev/null)"
EOF
```

The lookup is by service name only (no `-a` on read) so it still works even
though Claude Code strips `$USER` from the hook environment; `2>/dev/null` plus
the export's masked exit code mean a Keychain miss can never abort the
sub-200 ms close path. Rotate the token later with the same
`security add-generic-password -U …` command, and revert to API-key mode by
removing the two subscription lines from `capture.env`.

**Verify it worked:** after your next session ends, `tail ~/.claude/hooks.log`
should show a normal capture with no `CLAUDE_CODE_OAUTH_TOKEN not set` line, and
the new `eval/state/log.md` entry will carry an *estimated* `cost_usd`.

**Trade-offs:** background captures draw from the *same* rolling rate limit as
your interactive Claude Code usage; the `claude` CLI must be installed; and
`cost_usd` in the eval log becomes an *estimated* API-equivalent (not billed).
Token counts still come from the SDK's result message. `max_tokens` has no
equivalent in this mode — output length is governed by the runtime.

## Consuming captures: the Inbox contract

This project is a capture *engine*. Triaging captured artifacts into structured
vault folders (promoting, backlinking, weekly rollups) is intentionally **out of
scope** — it's left to separate extensions that build on the stable, documented
interface below. Keeping triage in an external extension means it can be wired to
your own skills and vault layout without coupling them to the capture engine.

An extension consumes:

**Outputs** (the captured artifacts) in your vault:
- `Inbox/auto/` — curated artifacts; `Inbox/raw/` — raw summaries.
- Filenames: `YYYY-MM-DD-<slug>-<sid8>.md`. Frontmatter includes `session_id`,
  `created` (date), `source`, `type`, and `tags`.

**Read-only runtime state** in the repo's gitignored `eval/state/`:
- `session-index.tsv` — `<session_id>\t<path_a_or_null>\t<path_b_or_null>\t<date>`.
- `log.md` — per-session JSON-lines (skip reasons, costs, token counts).
- `scrub-failures.md` — dated lines when a scrub rule failed.

Extensions **read** these; they should never write into `eval/state/` (keep their own
state elsewhere). To stop the pipeline from archiving an extension's own workflow
sessions, set **`CAPTURE_EXCLUDED_COMMANDS`** (comma-separated slash commands) in
`capture.env` — empty by default, so the public pipeline captures everything.

The `/vault-save` skill (on-demand export of a Claude-generated document to your
vault) is always installed.

## The eval (optional)

The two paths exist to compare curated-vs-raw kept-rates over ~4 weeks. If you
only want one, edit `hooks/curate.py`: Path A is `_call_path_a` (curated), Path B
is `_call_path_b` (raw). Per-session costs and skip reasons land in
`eval/state/log.md` (gitignored JSON-lines):

```bash
jq -r '[.date, .skip_reason_a, .skip_reason_b, .cost_usd_a, .cost_usd_b] | @tsv' eval/state/log.md
```

See `.github/SPEC.md` for the full specification and decision log.

## Project structure

```
hooks/
  session-end-capture.sh   # entry point — self-locating, returns in <200ms
  curate.py                # full pipeline (scrub → filter → API → write → log)
  scrub.py / scrub_rules.py # secret scrubber (no network, pure stdlib)
prompts/
  curation-system-prompt.md  # Path A — Sonnet, may return null
  raw-baseline-prompt.md     # Path B — Haiku, always summarizes
skill-patches/             # /vault-save skill + its global auto-trigger
eval/
  fixtures/                # test transcripts and mock API responses
  state/                   # runtime-only (gitignored): log.md, session-index.tsv
dev-notes/                 # historical design notes (not user docs)
.github/SPEC.md            # specification and decision log
```

## License

[MIT](LICENSE) © Loïc Houpert
