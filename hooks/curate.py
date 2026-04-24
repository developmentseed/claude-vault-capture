#!/usr/bin/env python3
"""curate.py — sessionEnd hook worker.

Usage: curate.py <transcript_path> <session_id> <cwd>

Runs both Path A (curated, sonnet) and Path B (raw baseline, haiku) in parallel,
writes artifacts to Obsidian Inbox dirs, and appends to the eval state log.

All errors go to stderr / ~/.claude/hooks.log — never to the user's terminal.
"""
import sys
import os
import json
import re
import pathlib
import fcntl
import threading
import datetime
import unicodedata
import subprocess
from concurrent.futures import ThreadPoolExecutor, Future
from typing import Any

# ── constants ──────────────────────────────────────────────────────────────────

CAPTURE_MAX_EST_TOKENS: int = int(os.environ.get("CAPTURE_MAX_EST_TOKENS", "50000"))

EXCLUDED_COMMANDS: list[str] = ["/daily-devlog", "/weekly-recap"]

VAULT_DIR = pathlib.Path.home() / "Obsidian" / "loics_vault"
LOG_PATH = pathlib.Path.home() / "DevDS" / "claude-vault-capture" / "eval" / "state" / "log.md"
INDEX_PATH = pathlib.Path.home() / "DevDS" / "claude-vault-capture" / "eval" / "state" / "session-index.tsv"
HOOKS_LOG = pathlib.Path.home() / ".claude" / "hooks.log"

MOCK_RESPONSES_PATH = (
    pathlib.Path(__file__).parent.parent / "eval" / "fixtures" / "mock-responses.json"
)

MODEL_A = "claude-sonnet-4-6"
MODEL_B = "claude-haiku-4-5-20251001"
MAX_TOKENS_A = 2000
MAX_TOKENS_B = 800
TIMEOUT_SECONDS = 30

LOG_REQUIRED_KEYS = [
    "schema_version", "timestamp", "date", "session_id",
    "path_a", "path_b", "skip_reason_a", "skip_reason_b",
    "tokens_in_a", "tokens_out_a", "tokens_in_b", "tokens_out_b",
    "cost_usd_a", "cost_usd_b", "redactions",
]

_LOG_LOCK = threading.Lock()

# ── title sanitization ─────────────────────────────────────────────────────────

_BAD_CHARS_RE = re.compile(r"[\|\[\]#`\x00-\x1f\x7f]")
_MULTI_SPACE_RE = re.compile(r"\s+")


def sanitize_title(title: str) -> str:
    """Strip chars unsafe in Obsidian wikilinks; collapse whitespace; truncate to 120."""
    # Remove dangerous chars (pipe, brackets, hash, backtick, control chars)
    s = _BAD_CHARS_RE.sub(" ", title)
    # Collapse whitespace runs
    s = _MULTI_SPACE_RE.sub(" ", s)
    # Strip leading/trailing
    s = s.strip()
    # Truncate at 120
    return s[:120]


# ── slug generation ────────────────────────────────────────────────────────────

_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*\n(.*)\n```\s*$", re.DOTALL)


def _strip_fences(text: str) -> str:
    """Strip optional markdown code fences the model sometimes wraps around JSON."""
    m = _CODE_FENCE_RE.match(text)
    return m.group(1) if m else text


def make_slug(title: str) -> str:
    """Derive a deterministic URL-safe slug from *title* (max 60 chars)."""
    # NFKD-normalize and strip non-ASCII
    s = unicodedata.normalize("NFKD", sanitize_title(title))
    s = s.encode("ascii", "ignore").decode("ascii")
    s = s.lower()
    # Replace runs of non-alnum with dash
    s = _NON_ALNUM_RE.sub("-", s)
    # Strip leading/trailing dashes
    s = s.strip("-")

    if not s:
        return "untitled"

    # Truncate to 60 at a dash boundary where possible
    if len(s) > 60:
        truncated = s[:60]
        # Walk back to last dash
        last_dash = truncated.rfind("-")
        if last_dash > 0:
            truncated = truncated[:last_dash]
        s = truncated.strip("-")

    return s or "untitled"


def make_filename(date_str: str, slug: str, session_id: str) -> str:
    """Return YYYY-MM-DD-<slug>-<sid8>.md"""
    sid8 = session_id[:8]
    return f"{date_str}-{slug}-{sid8}.md"


# ── frontmatter rendering ──────────────────────────────────────────────────────

def render_frontmatter(
    *,
    title: str,
    fm_type: str,
    project: str,
    tags: list[str],
    source: str,
    session_id: str,
    created: str,
    model: str,
    cost_usd: float | None,
    redactions: dict[str, int],
) -> str:
    """Render YAML frontmatter block. Title is sanitized inside here."""
    clean_title = sanitize_title(title)
    tags_yaml = "[" + ", ".join(tags) + "]"
    redact_yaml = "{" + ", ".join(f"{k}: {v}" for k, v in redactions.items()) + "}"
    cost_str = f"{cost_usd:.4f}" if cost_usd is not None else "null"
    return (
        f"---\n"
        f"title: {clean_title}\n"
        f"type: {fm_type}\n"
        f"project: {project}\n"
        f"tags: {tags_yaml}\n"
        f"source: {source}\n"
        f"session_id: {session_id}\n"
        f"created: {created}\n"
        f"model: {model}\n"
        f"cost_usd: {cost_str}\n"
        f"redactions: {redact_yaml}\n"
        f"---\n"
    )


# ── dedup ──────────────────────────────────────────────────────────────────────

def is_duplicate_session(
    session_id: str,
    *,
    index_path: pathlib.Path = INDEX_PATH,
) -> bool:
    """Return True if session_id already appears in the index TSV."""
    if not index_path.exists():
        return False
    with open(index_path, encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("#"):
                continue
            cols = line.rstrip("\n").split("\t")
            if cols and cols[0] == session_id:
                return True
    return False


# ── threshold check ────────────────────────────────────────────────────────────

def is_below_threshold(messages: list[dict]) -> bool:
    """< 3 user turns OR < 1500 chars of user content → True (skip)."""
    user_turns = [m for m in messages if m.get("role") == "user"]
    user_chars = sum(len(m.get("content", "")) for m in user_turns)
    return len(user_turns) < 3 or user_chars < 1500


def uses_excluded_command(
    messages: list[dict],
    excluded_commands: list[str] = EXCLUDED_COMMANDS,
) -> bool:
    """Return True if any user turn invokes an excluded slash command.

    Matches only when the command appears at the start of a line (possibly
    preceded by whitespace), so mentions of the command in prose are ignored.
    """
    patterns = [re.compile(r"(?m)^\s*" + re.escape(cmd) + r"(?:\s|$)") for cmd in excluded_commands]
    for msg in messages:
        if msg.get("role") != "user":
            continue
        text = msg.get("content", "")
        if any(p.search(text) for p in patterns):
            return True
    return False


# ── token guard ────────────────────────────────────────────────────────────────

def is_above_token_limit(text: str) -> bool:
    """True if estimated token count exceeds CAPTURE_MAX_EST_TOKENS."""
    limit = int(os.environ.get("CAPTURE_MAX_EST_TOKENS", str(CAPTURE_MAX_EST_TOKENS)))
    return len(text) // 4 > limit


# ── project derivation ─────────────────────────────────────────────────────────

def derive_project(cwd: str) -> str:
    """Return nearest git repo basename, or 'home' if not in a repo."""
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            return pathlib.Path(result.stdout.strip()).name
    except Exception:
        pass
    return "home"


# ── log building ───────────────────────────────────────────────────────────────

def build_log_entry(
    *,
    session_id: str,
    path_a: str | None,
    skip_reason_a: str | None,
    path_b: str | None,
    skip_reason_b: str | None,
    tokens_in_a: int | None,
    tokens_out_a: int | None,
    tokens_in_b: int | None,
    tokens_out_b: int | None,
    cost_usd_a: float | None,
    cost_usd_b: float | None,
    redactions: dict[str, int],
) -> dict:
    now = datetime.datetime.now(datetime.timezone.utc)
    return {
        "schema_version": 1,
        "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "date": now.strftime("%Y-%m-%d"),
        "session_id": session_id,
        "path_a": path_a,
        "path_b": path_b,
        "skip_reason_a": skip_reason_a,
        "skip_reason_b": skip_reason_b,
        "tokens_in_a": tokens_in_a,
        "tokens_out_a": tokens_out_a,
        "tokens_in_b": tokens_in_b,
        "tokens_out_b": tokens_out_b,
        "cost_usd_a": cost_usd_a,
        "cost_usd_b": cost_usd_b,
        "redactions": redactions,
    }


# ── concurrent-safe append ────────────────────────────────────────────────────

def append_log(entry: dict, *, log_path: pathlib.Path = LOG_PATH) -> None:
    """Append one JSON line to log_path with cross-process flock + in-process lock."""
    line = json.dumps(entry) + "\n"
    with _LOG_LOCK:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            fh.write(line)
            fh.flush()
            fcntl.flock(fh, fcntl.LOCK_UN)


def _append_index(
    session_id: str,
    path_a: str | None,
    path_b: str | None,
    date_str: str,
    *,
    index_path: pathlib.Path = INDEX_PATH,
) -> None:
    """Append one line to session-index.tsv, creating the file with header if absent."""
    index_path.parent.mkdir(parents=True, exist_ok=True)
    with _LOG_LOCK:
        with open(index_path, "a", encoding="utf-8") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            if fh.tell() == 0:
                fh.write("# schema_version: 1\n")
            fh.write(f"{session_id}\t{path_a or 'null'}\t{path_b or 'null'}\t{date_str}\n")
            fh.flush()
            fcntl.flock(fh, fcntl.LOCK_UN)


# ── API call stubs (overridable in tests) ─────────────────────────────────────

def _call_path_a(scrubbed_text: str, prompts_dir: pathlib.Path) -> dict | None:
    """Call claude-sonnet-4-6 with curation prompt. Returns artifact dict or None."""
    if os.environ.get("CAPTURE_MOCK_SDK") == "1":
        raise RuntimeError("CAPTURE_MOCK_SDK=1 but no mock injected — call monkeypatched version")

    import anthropic

    system_prompt = (prompts_dir / "curation-system-prompt.md").read_text()
    client = anthropic.Anthropic()
    msg = client.messages.create(
        model=MODEL_A,
        max_tokens=MAX_TOKENS_A,
        system=system_prompt,
        messages=[{"role": "user", "content": scrubbed_text}],
        timeout=TIMEOUT_SECONDS,
    )
    raw = _strip_fences(msg.content[0].text.strip())
    if raw.lower() == "null":
        return None
    data = json.loads(raw)
    data["tokens_in"] = msg.usage.input_tokens
    data["tokens_out"] = msg.usage.output_tokens
    data["cost_usd"] = _estimate_cost_a(msg.usage.input_tokens, msg.usage.output_tokens)
    return data


def _call_path_b(scrubbed_text: str, prompts_dir: pathlib.Path) -> dict:
    """Call claude-haiku with raw baseline prompt. Always returns dict."""
    if os.environ.get("CAPTURE_MOCK_SDK") == "1":
        raise RuntimeError("CAPTURE_MOCK_SDK=1 but no mock injected — call monkeypatched version")

    import anthropic

    system_prompt = (prompts_dir / "raw-baseline-prompt.md").read_text()
    client = anthropic.Anthropic()
    msg = client.messages.create(
        model=MODEL_B,
        max_tokens=MAX_TOKENS_B,
        system=system_prompt,
        messages=[{"role": "user", "content": scrubbed_text}],
        timeout=TIMEOUT_SECONDS,
    )
    raw = _strip_fences(msg.content[0].text.strip())
    data = json.loads(raw)
    data["tokens_in"] = msg.usage.input_tokens
    data["tokens_out"] = msg.usage.output_tokens
    data["cost_usd"] = _estimate_cost_b(msg.usage.input_tokens, msg.usage.output_tokens)
    return data


def _estimate_cost_a(tokens_in: int, tokens_out: int) -> float:
    # claude-sonnet-4-6: $3/M input, $15/M output
    return (tokens_in * 3 + tokens_out * 15) / 1_000_000


def _estimate_cost_b(tokens_in: int, tokens_out: int) -> float:
    # claude-haiku-4-5: $0.25/M input, $1.25/M output
    return (tokens_in * 0.25 + tokens_out * 1.25) / 1_000_000


# ── file writing ───────────────────────────────────────────────────────────────

def _write_artifact(
    path: pathlib.Path,
    *,
    title: str,
    fm_type: str,
    project: str,
    source: str,
    session_id: str,
    created: str,
    model: str,
    cost_usd: float | None,
    redactions: dict[str, int],
    tags: list[str],
    body: str,
    source_links: list[str],
) -> None:
    fm = render_frontmatter(
        title=title, fm_type=fm_type, project=project,
        tags=tags, source=source, session_id=session_id,
        created=created, model=model, cost_usd=cost_usd,
        redactions=redactions,
    )
    clean_title = sanitize_title(title)
    source_section = ""
    if source_links:
        source_section = "\n## Source\n" + "\n".join(f"- {l}" for l in source_links) + "\n"

    content = f"{fm}\n# {clean_title}\n{body}\n{source_section}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# ── main capture pipeline ─────────────────────────────────────────────────────

def run_capture(
    *,
    transcript: list[dict],
    session_id: str,
    cwd: str,
    vault_dir: str | pathlib.Path = VAULT_DIR,
    log_path: pathlib.Path = LOG_PATH,
    index_path: pathlib.Path = INDEX_PATH,
    date_str: str | None = None,
    prompts_dir: pathlib.Path | None = None,
) -> None:
    """Full capture pipeline: scrub → threshold → dedup → API calls → write → log."""
    import scrub as scrub_mod

    vault_dir = pathlib.Path(vault_dir)
    if prompts_dir is None:
        prompts_dir = pathlib.Path(__file__).parent.parent / "prompts"
    if date_str is None:
        date_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")

    # ── 1. scrub transcript ───────────────────────────────────────────────────
    raw_text = "\n".join(
        m.get("content", "") for m in transcript
    )
    scrubbed_text, redactions = scrub_mod.scrub(raw_text)

    # ── 2. excluded command check ─────────────────────────────────────────────
    if uses_excluded_command(transcript):
        entry = build_log_entry(
            session_id=session_id,
            path_a=None, skip_reason_a="excluded_command",
            path_b=None, skip_reason_b="excluded_command",
            tokens_in_a=None, tokens_out_a=None,
            tokens_in_b=None, tokens_out_b=None,
            cost_usd_a=None, cost_usd_b=None,
            redactions=redactions,
        )
        append_log(entry, log_path=log_path)
        return

    # ── 3. threshold check ────────────────────────────────────────────────────
    if is_below_threshold(transcript):
        entry = build_log_entry(
            session_id=session_id,
            path_a=None, skip_reason_a="threshold",
            path_b=None, skip_reason_b="threshold",
            tokens_in_a=None, tokens_out_a=None,
            tokens_in_b=None, tokens_out_b=None,
            cost_usd_a=None, cost_usd_b=None,
            redactions=redactions,
        )
        append_log(entry, log_path=log_path)
        return

    # ── 4. token-count guard ──────────────────────────────────────────────────
    if is_above_token_limit(scrubbed_text):
        entry = build_log_entry(
            session_id=session_id,
            path_a=None, skip_reason_a="token_limit",
            path_b=None, skip_reason_b="token_limit",
            tokens_in_a=None, tokens_out_a=None,
            tokens_in_b=None, tokens_out_b=None,
            cost_usd_a=None, cost_usd_b=None,
            redactions=redactions,
        )
        append_log(entry, log_path=log_path)
        return

    # ── 5. dedup check ────────────────────────────────────────────────────────
    if is_duplicate_session(session_id, index_path=index_path):
        return

    # ── 6. project derivation ─────────────────────────────────────────────────
    project = derive_project(cwd)

    # ── 7. parallel API calls (or mock) ──────────────────────────────────────
    result_a: dict | None = None
    result_b: dict | None = None
    skip_reason_a: str | None = None
    skip_reason_b: str | None = None
    tokens_in_a = tokens_out_a = None
    tokens_in_b = tokens_out_b = None
    cost_usd_a = cost_usd_b = None

    def call_a():
        return _call_path_a(scrubbed_text, prompts_dir)

    def call_b():
        return _call_path_b(scrubbed_text, prompts_dir)

    with ThreadPoolExecutor(max_workers=2) as executor:
        future_a: Future = executor.submit(call_a)
        future_b: Future = executor.submit(call_b)

    # Collect path A result
    try:
        result_a = future_a.result()
        if result_a is None:
            skip_reason_a = "model_returned_null"
        else:
            tokens_in_a = result_a.get("tokens_in")
            tokens_out_a = result_a.get("tokens_out")
            cost_usd_a = result_a.get("cost_usd")
    except json.JSONDecodeError:
        skip_reason_a = "malformed_json"
    except TimeoutError:
        skip_reason_a = "timeout"
    except Exception as exc:
        skip_reason_a = f"error:{type(exc).__name__}"

    # Collect path B result
    try:
        result_b = future_b.result()
        tokens_in_b = result_b.get("tokens_in")
        tokens_out_b = result_b.get("tokens_out")
        cost_usd_b = result_b.get("cost_usd")
    except json.JSONDecodeError:
        skip_reason_b = "malformed_json"
    except TimeoutError:
        skip_reason_b = "timeout"
    except Exception as exc:
        skip_reason_b = f"error:{type(exc).__name__}"

    # ── 8. scrub model outputs ────────────────────────────────────────────────
    if result_a:
        body_a, _ = scrub_mod.scrub(result_a.get("body", ""))
        result_a["body"] = body_a
    if result_b:
        body_b, _ = scrub_mod.scrub(result_b.get("body", ""))
        result_b["body"] = body_b

    # ── 9 & 10. sanitize title + write Path A ────────────────────────────────
    path_a_rel: str | None = None
    if result_a and skip_reason_a is None:
        title_a = sanitize_title(result_a.get("title", "untitled"))
        slug_a = make_slug(title_a)
        fname_a = make_filename(date_str, slug_a, session_id)
        rel_a = f"Inbox/auto/{fname_a}"
        full_path_a = vault_dir / "Inbox" / "auto" / fname_a
        _write_artifact(
            full_path_a,
            title=title_a,
            fm_type=result_a.get("type", "decision"),
            project=project,
            source="claude-code-curated",
            session_id=session_id,
            created=date_str,
            model=MODEL_A,
            cost_usd=cost_usd_a,
            redactions=redactions,
            tags=["claude-code", "curated"] + result_a.get("tags", []),
            body=result_a.get("body", ""),
            source_links=result_a.get("source_links", []),
        )
        path_a_rel = rel_a

    # ── 11. write Path B ─────────────────────────────────────────────────────
    path_b_rel: str | None = None
    if result_b and skip_reason_b is None:
        title_b = sanitize_title(result_b.get("title", "untitled"))
        slug_b = make_slug(title_b)
        fname_b = make_filename(date_str, slug_b, session_id)
        rel_b = f"Inbox/raw/{fname_b}"
        full_path_b = vault_dir / "Inbox" / "raw" / fname_b
        _write_artifact(
            full_path_b,
            title=title_b,
            fm_type="session-summary",
            project=project,
            source="claude-code-raw",
            session_id=session_id,
            created=date_str,
            model=MODEL_B,
            cost_usd=cost_usd_b,
            redactions=redactions,
            tags=["claude-code", "raw"] + result_b.get("tags", []),
            body=result_b.get("body", ""),
            source_links=result_b.get("source_links", []),
        )
        path_b_rel = rel_b

    # ── 12. append session index ─────────────────────────────────────────────
    _append_index(session_id, path_a_rel, path_b_rel, date_str, index_path=index_path)

    # ── 13. append log ───────────────────────────────────────────────────────
    entry = build_log_entry(
        session_id=session_id,
        path_a=path_a_rel, skip_reason_a=skip_reason_a,
        path_b=path_b_rel, skip_reason_b=skip_reason_b,
        tokens_in_a=tokens_in_a, tokens_out_a=tokens_out_a,
        tokens_in_b=tokens_in_b, tokens_out_b=tokens_out_b,
        cost_usd_a=cost_usd_a, cost_usd_b=cost_usd_b,
        redactions=redactions,
    )
    append_log(entry, log_path=log_path)


# ── CLI entry point ────────────────────────────────────────────────────────────

def _extract_text(content) -> str:
    """Flatten content that may be a string or a list of content blocks."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            block.get("text", "") if isinstance(block, dict) and block.get("type") == "text"
            else block if isinstance(block, str)
            else ""
            for block in content
        ]
        return "\n".join(p for p in parts if p)
    return ""


def _load_transcript(transcript_path: str) -> list[dict]:
    messages = []
    with open(transcript_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if obj.get("type") == "user" or obj.get("role") == "user":
                    raw = obj.get("message", {}).get("content", obj.get("content", ""))
                    messages.append({"role": "user", "content": _extract_text(raw)})
                elif obj.get("type") == "assistant" or obj.get("role") == "assistant":
                    raw = obj.get("message", {}).get("content", obj.get("content", ""))
                    messages.append({"role": "assistant", "content": _extract_text(raw)})
            except json.JSONDecodeError:
                continue
    return messages


def main():
    if len(sys.argv) < 4:
        print("Usage: curate.py <transcript_path> <session_id> <cwd>", file=sys.stderr)
        sys.exit(1)

    transcript_path, session_id, cwd = sys.argv[1], sys.argv[2], sys.argv[3]

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key and os.environ.get("CAPTURE_MOCK_SDK") != "1":
        _log_error("ANTHROPIC_API_KEY not set — skipping capture")
        sys.exit(0)

    try:
        transcript = _load_transcript(transcript_path)
    except Exception as exc:
        _log_error(f"Failed to load transcript {transcript_path!r}: {exc}")
        sys.exit(0)

    try:
        run_capture(transcript=transcript, session_id=session_id, cwd=cwd)
    except Exception as exc:
        _log_error(f"CURATE_ERROR session={session_id}: {exc}")
        sys.exit(0)


def _log_error(msg: str) -> None:
    ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
    print(f"{ts} {msg}", file=sys.stderr)


if __name__ == "__main__":
    main()
