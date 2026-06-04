# Plan: Add useful end-to-end tests

## Context

The current suite (133 tests, `tests/`) is strong on **pure functions** — scrubbing,
frontmatter/slug/filename, threshold, dedup, guards, fence-stripping, transcript
loading, log-schema validation, and concurrent appends. But it has **zero coverage**
of the three things that actually run in production:

1. **The CLI entry point `main()`** — argv parsing, credential guards, the real
   transcript-file → `_load_transcript` → `run_capture` → written vault files → log
   → index flow. `main()` is never invoked by any test.
2. **The shell hook `hooks/session-end-capture.sh`** — stdin JSON parse, credential
   fallback, the `SESSION_END_RECEIVED` ground-truth marker, and the <200 ms
   backgrounding contract. Completely untested.
3. **The new subscription mode** (`_invoke_via_subscription`, just added) — only
   ever exercised by the manual run we did by hand.

A secondary finding: `eval/fixtures/mock-responses.json` (keyed by fixture name,
with `path_a`/`path_b` artifacts) is **dead** — no code loads it. `run-fixtures.sh`
in its default `CAPTURE_MOCK_SDK=1` mode doesn't inject mocks, so both paths raise
`RuntimeError`, get swallowed, and the script prints `PASS` while writing and
validating nothing — an actively misleading green signal. We resurrect the asset
**and** fix the runner.

**Outcome:** deterministic, offline E2E coverage of `main()`, the shell hook, and
the skip/guard paths, plus one opt-in live test that exercises the real subscription
path end-to-end.

> Review corrections applied (do not regress these): the with-secrets split,
> malformed_haiku assertions, credential-guard tests, and `run-fixtures.sh` are
> **required**, not optional. Rationale is inline in each section.

## Approach

### 0. Shared test scaffolding — `tests/conftest.py` (modify)

Add reusable pytest fixtures (the centerpiece the other suites build on):

- **`mock_from_responses(monkeypatch)`** — factory that, given a fixture name, loads
  `eval/fixtures/mock-responses.json[name]` and monkeypatches `curate._call_path_a` /
  `curate._call_path_b`:
  - dict entry → **return it as-is** (entries already carry `tokens_in/out` and
    `cost_usd`, e.g. `mock-responses.json:9-11` — do **not** backfill them).
  - `null` for `path_a` → return `None` (run_capture maps this to
    `model_returned_null`; no usage data exists for a null, so don't synthesize any).
  - string entry for `path_b` (the `malformed_haiku` case) → raise
    `json.JSONDecodeError`, mirroring real `_call_path_b`. **Do not** attach a
    `.usage` attribute — the string carries no token data, so token preservation is
    not assertable here (it is already covered by `test_failure_isolation.py`).
  - Sets `CAPTURE_MOCK_SDK=1`.
  - Add a one-line docstring pointing to the existing inline-mock pattern in
    `tests/test_failure_isolation.py` so future readers know both exist and when to
    use which. (We are **not** migrating the inline tests — surgical change.)
- **`temp_vault(tmp_path)`** — creates `Inbox/auto`, `Inbox/raw`; returns paths for
  `vault_dir`, `log.md`, `session-index.tsv`.
- **`run_main(monkeypatch, temp_vault)`** — wraps `curate.run_capture` so any call
  (including from `main()`) injects the temp `vault_dir`/`log_path`/`index_path`,
  sets `sys.argv`, and invokes `curate.main()`. The wrapper — not monkeypatching the
  module constant — is required because `run_capture`'s defaults bind the real
  `~/Obsidian` path at def-time (`curate.py:513-515`); `main()` resolves
  `run_capture` as a module global at call time, so the wrapper is picked up. Keep
  that one-line justification as a comment in the fixture.
- **`pytest_configure`** — register a `live` marker so the opt-in test doesn't warn.

### 1. Full pipeline via `main()` — `tests/test_pipeline_e2e.py` (new)

Add realistic JSONL transcript fixtures under **`eval/fixtures/transcripts/<name>.jsonl`**
(new dir) mimicking the real Claude Code schema in `_load_transcript` / `_extract_text`
(`curate.py`) — lines like `{"type":"user","message":{"content":"…"}}`, with at least
one assistant turn using **list-of-blocks content including a `tool_use` block** to
verify block-filtering. Name them to match `mock-responses.json` keys. Each test
writes the `.jsonl`, runs `main()` via `run_main`, asserts on **actual written files**:

- **adr-worthy** (A+B): one file in `Inbox/auto/`, one in `Inbox/raw/`; filename
  matches `YYYY-MM-DD-<slug>-<sid8>.md`; frontmatter has `source:
  claude-code-curated`/`claude-code-raw`, correct `type`, `session_id`, `model`.
- **debugging-only** (`path_a: null`): no file in `Inbox/auto/`, one in `Inbox/raw/`;
  log `skip_reason_a == "model_returned_null"`, `path_b` non-null.
- **malformed-title**: written filename and frontmatter `title` are sanitized (no
  `|`, `[[`, `#`) — exercises `sanitize_title` end-to-end.
- **malformed_haiku** (`path_a` valid decision, `path_b` is a string): assert
  `skip_reason_b == "malformed_json"` **and Path A still writes its decision file**
  (real-pipeline failure isolation). Do **not** assert token preservation here — the
  string entry has no token data; that case is owned by `test_failure_isolation.py`.

**Scrubbing — two distinct stages, tested separately (review fix):**
- **Input scrub** (pre-API, `curate.py:534`, runs regardless of mocking): use the
  **with-secrets** JSONL fixture *containing the planted secrets*; assert the log
  entry's `redactions` counts are non-zero. This is real and unaffected by mocks.
- **Output scrub** (post-API, `curate.py:564-576`): the `with-secrets`
  mock body is already clean, so it proves nothing about output scrubbing. Add a
  **dedicated test with an inline mock** whose returned `body`/`title` contain a
  secret (e.g. a fake bearer token); assert the **written file** has it redacted.

### 2. Shell hook — `tests/test_session_end_hook.py` (new)

Subprocess tests of `hooks/session-end-capture.sh`, made hermetic via a temp `HOME`:
- Build `$TMP/DevDS/claude-vault-capture/hooks/curate.py` (empty stub) and an
  executable `$TMP/DevDS/claude-vault-capture/.venv/bin/python3` shell shim. The shim
  records its argv and a **fixed whitelist** of env vars —
  `CLAUDE_CODE_OAUTH_TOKEN`, `ANTHROPIC_API_KEY`, `CAPTURE_USE_SUBSCRIPTION` — to
  `$TMP/curate-invocation.txt`, then exits 0. **Security:** only those names, and all
  token files created in the test use **dummy** values, so no ambient real key is
  ever written to disk; temp `HOME` is cleaned up by `tmp_path`.
- **Happy path:** pipe valid hook JSON (`session_id`, `transcript_path`, `cwd`);
  assert (a) `SESSION_END_RECEIVED\t<sid>` in `$TMP/.claude/hooks.log`, (b) the shim
  recorded the 3 expected args, (c) exit 0, (d) wall-clock return < ~2 s (generous CI
  bound proving it backgrounds rather than blocks — not a literal 200 ms).
- **Guard:** JSON missing `session_id`/`transcript_path` → no marker line, exit 0.
- **Credential fallback:** with `CAPTURE_USE_SUBSCRIPTION=1` and a dummy
  `$TMP/.claude_vault_oauth_token`, the shim env shows `CLAUDE_CODE_OAUTH_TOKEN`; in
  default mode with a dummy `$TMP/.claude_vault_token`, it shows `ANTHROPIC_API_KEY`.

### 3. Edge-case skips + credential guards — in `tests/test_pipeline_e2e.py` (new section)

Drive `main()`/`run_capture` via `run_main`; assert **no files written** + correct
single log entry:
- empty transcript and assistant-only transcript → `threshold` (both paths).
- first user turn `/daily-devlog …` → `excluded_command`.
- **token_limit:** set `CAPTURE_MAX_EST_TOKENS=10` **and** use an *above-threshold*
  transcript (≥3 turns, ≥1500 chars) — threshold is checked before token_limit
  (`curate.py` order: scrub → excluded → threshold → token_limit → dedup), so a small
  transcript would trip `threshold` instead.
- **duplicate:** run capture twice against a shared `index_path`; second run logs
  `duplicate` for both paths and writes no new artifact.

**Credential guards (review fix — these guard the newest, untested code):**
- API mode, no `ANTHROPIC_API_KEY`, not mock, not subscription →
  `pytest.raises(SystemExit)` (code 0), no capture, no files.
- subscription mode, no `CLAUDE_CODE_OAUTH_TOKEN`, not mock → same.
- transcript path that doesn't exist → `_load_transcript` raises, `main()` exits 0
  gracefully, no files.

### 4. Opt-in live test — `tests/test_live_e2e.py` (new)

Gated by the existing `CAPTURE_LIVE_TESTS=1` convention + `@pytest.mark.live`,
**skipped by default** via `pytest.mark.skipif`. Reuses the atomic-write decision
transcript from our manual run so Path A yields a `decision`. With
`CAPTURE_USE_SUBSCRIPTION=1` and **no** `CAPTURE_MOCK_SDK`, runs the real pipeline
into a temp vault and asserts: both artifacts written **under `tmp_path`** (never
`~/Obsidian`), valid frontmatter, `skip_reason_*` is `null`, and `tokens_*` are
populated and non-trivial (regression guard for the cache-token summation in
`_invoke_via_subscription`). Docstring warns it spends Max quota and needs the
`claude` CLI logged in.

### 5. Fix `run-fixtures.sh` — `eval/run-fixtures.sh` (modify) — REQUIRED

Its current mock mode is an always-green no-op (validates nothing) — a false-confidence
liability that violates "don't trust, verify." Wire its default mock mode to load
`mock-responses.json` and inject `_call_path_a`/`_call_path_b` (same logic as the
`mock_from_responses` fixture), turning it into a real output check. If wiring proves
awkward in bash, the **minimum acceptable** fix is to make it **fail loudly** in mock
mode rather than print `PASS`. Do not leave the misleading green.

## Critical files

- `tests/conftest.py` — **modify**: shared fixtures (`mock_from_responses`,
  `temp_vault`, `run_main`), `live` marker registration.
- `tests/test_pipeline_e2e.py` — **new**: `main()` full-pipeline, two-stage scrub
  tests, edge-case skips, credential guards.
- `tests/test_session_end_hook.py` — **new**: shell hook subprocess tests.
- `tests/test_live_e2e.py` — **new**: opt-in live subscription E2E.
- `eval/fixtures/transcripts/*.jsonl` — **new**: realistic JSONL transcripts keyed
  to `mock-responses.json` (must include the planted secrets in the with-secrets one).
- `eval/run-fixtures.sh` — **modify (required)**: consume `mock-responses.json`, or
  fail loudly in mock mode.

## Reuse (don't reinvent)

- Mock source: `eval/fixtures/mock-responses.json` (resurrect; don't recreate data).
- Monkeypatch pattern: `tests/test_failure_isolation.py:_run_with_mocks` (token
  preservation on malformed JSON already lives here — don't duplicate it).
- Fixture loader pattern: `tests/test_scrub.py:load_fixture`.
- Real schema reference: `hooks/curate.py:_load_transcript` / `_extract_text`.
- Env conventions: `CAPTURE_MOCK_SDK`, `CAPTURE_LIVE_TESTS`,
  `CAPTURE_USE_SUBSCRIPTION`, `CAPTURE_MAX_EST_TOKENS`.
- Skip-reason invariant check: `tests/test_log_schema.py:_valid`.

## Verification

```bash
# Default: all deterministic tests pass, live test is skipped
.venv/bin/python3 -m pytest -q                       # expect 133 prior + new, live skipped

# Just the new E2E modules
.venv/bin/python3 -m pytest -q tests/test_pipeline_e2e.py tests/test_session_end_hook.py

# Opt-in live subscription E2E (spends Max quota; needs claude CLI logged in)
CAPTURE_LIVE_TESTS=1 .venv/bin/python3 -m pytest -q -m live tests/test_live_e2e.py

# Fixture runner now actually validates (or fails loudly), no longer always-green
bash eval/run-fixtures.sh
```

Per-axis success criteria:
- **Correctness:** input-scrub test shows non-zero redaction counts; output-scrub test
  shows a secret redacted in a written file; malformed_haiku writes Path A and skips
  Path B; credential-guard tests exit 0 with no files; duplicate run writes nothing.
- **Isolation:** no test touches real `~/Obsidian/loics_vault` or `eval/state/`; all
  outputs under `tmp_path`.
- **Offline:** no network access in the default suite; only the `live`-marked test
  makes real calls, and only when explicitly enabled.
- **No false greens:** `run-fixtures.sh` either validates real artifacts or fails.
