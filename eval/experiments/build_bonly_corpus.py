#!/usr/bin/env python3
"""Assemble the Path-A-null / Path-B-captured ("B-only") regression corpus.

Purpose
-------
The 4-week eval showed Path A (Sonnet) returns null on ~41% of eligible
sessions *by design* — curation-system-prompt.md Rule 5 biases toward null
"because the raw baseline (Path B) always captures". The open question before
retiring Path B is: of the sessions where only Path B captured, how many held
content Path A *should* have curated? This script builds the corpus needed to
answer that, with zero API calls and zero side effects on the live pipeline.

For each B-only session it records:
  - identity (session_id, date, project, original skip_reason_a)
  - the original transcript path (if still on disk) + faithful size metrics
  - the Haiku "evidence" (title/tags/body) already sitting in Inbox/raw, so a
    human can judge keepability without re-reading the whole transcript
  - a transparent `draft_guess` (NOT ground truth) and a `keepable` field left
    as "TODO" — labelling keepability is a human-owned acceptance decision
    (ai-engineering Principle 5), not something this script invents.

Outputs (both under eval/state/experiments/, which is gitignored because the
bodies embed scrubbed session content, some of it personal):
  - bonly-corpus.json  — machine-readable, consumed by bonly_replay.py
  - bonly-corpus.md    — human labelling worksheet

Run:  .venv/bin/python3 eval/experiments/build_bonly_corpus.py
"""

from __future__ import annotations

import glob
import json
import os
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
HOOKS = REPO / "hooks"
sys.path.insert(0, str(HOOKS))

import curate  # noqa: E402  (faithful reuse of the production loader)
import scrub as scrub_mod  # noqa: E402

LOG_PATH = REPO / "eval" / "state" / "log.md"
OUT_DIR = REPO / "eval" / "state" / "experiments"
PROJECTS = pathlib.Path(os.path.expanduser("~/.claude/projects"))

# skip_reason_a values that mean "never reached the model" — excluded from the
# corpus because they carry no signal about Path A's null *judgment*.
PRE_MODEL_SKIPS = {"excluded_command", "threshold", "token_limit", "duplicate"}

# Transparent heuristic for draft_guess only. Tags Haiku attached that tend to
# mark a durable artifact. This is a hint to speed up human labelling, never a
# substitute for it.
DURABLE_HINTS = {
    "runbook",
    "spec",
    "design-review",
    "architecture",
    "decision",
    "debugging",
    "incident",
    "plan",
    "migration",
    "gotcha",
    "performance",
}


def _read_log() -> list[dict]:
    rows = []
    with open(LOG_PATH, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line.startswith("{"):
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return rows


def _bonly_rows(rows: list[dict]) -> list[dict]:
    return [
        r
        for r in rows
        if not r["path_a"]
        and r["path_b"]
        and r.get("skip_reason_a") not in PRE_MODEL_SKIPS
    ]


def _find_transcript(session_id: str) -> str | None:
    hits = glob.glob(str(PROJECTS / "*" / f"{session_id}.jsonl"))
    return hits[0] if hits else None


def _transcript_size(path: str) -> dict:
    """Reproduce run_capture's transcript→scrubbed_text normalization exactly."""
    transcript = curate._load_transcript(path)
    role_map = {"user": "[USER]", "assistant": "[ASSISTANT]"}
    raw_text = "\n".join(
        f"{role_map.get(m.get('role', ''), '[UNKNOWN]')}: {m.get('content', '')}"
        for m in transcript
    )
    scrubbed, _ = scrub_mod.scrub(raw_text)
    return {
        "messages": len(transcript),
        "chars": len(scrubbed),
        "est_tokens": len(scrubbed) // 4,
    }


def _parse_raw_file(vault_raw: pathlib.Path, rel_path: str) -> dict:
    """Pull Haiku's title/tags/body from the Inbox/raw artifact as evidence."""
    fname = rel_path.split("/")[-1]
    full = vault_raw / fname
    if not full.exists():
        return {"present": False, "title": None, "tags": [], "body": None}
    text = full.read_text(encoding="utf-8")
    fm, _, body = (
        text.partition("\n---\n") if text.startswith("---") else ("", "", text)
    )
    # frontmatter is the block between the first two '---' fences
    parts = text.split("---", 2)
    fm = parts[1] if len(parts) >= 3 else ""
    body = parts[2] if len(parts) >= 3 else text
    title = _fm_value(fm, "title")
    tags = _fm_tags(fm)
    return {"present": True, "title": title, "tags": tags, "body": body.strip()}


def _fm_value(fm: str, key: str) -> str | None:
    m = re.search(rf"^{re.escape(key)}:\s*(.+)$", fm, re.MULTILINE)
    return m.group(1).strip() if m else None


def _fm_tags(fm: str) -> list[str]:
    raw = _fm_value(fm, "tags") or ""
    return [t.strip() for t in raw.strip("[]").split(",") if t.strip()]


def _draft_guess(skip_reason_a: str | None, size: dict | None, tags: list[str]) -> str:
    """Transparent hint, NOT ground truth. See module docstring."""
    if skip_reason_a and skip_reason_a.startswith("error:"):
        return "transport-failure (not a null judgment)"
    if size and size["est_tokens"] < 400:
        return "likely-thin"
    if any(t in DURABLE_HINTS for t in tags):
        return "likely-keepable"
    return "uncertain"


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    vault_dir = os.environ.get("CAPTURE_VAULT_DIR")
    if not vault_dir:
        # Fall back to capture.env so the script works outside the hook env.
        env = REPO / "capture.env"
        if env.exists():
            m = re.search(r'CAPTURE_VAULT_DIR="?([^"\n]+)"?', env.read_text())
            vault_dir = m.group(1) if m else None
    if not vault_dir:
        sys.exit("CAPTURE_VAULT_DIR unset and not found in capture.env")
    vault_raw = pathlib.Path(vault_dir) / "Inbox" / "raw"

    rows = _bonly_rows(_read_log())
    corpus = []
    for r in rows:
        sid = r["session_id"]
        tpath = _find_transcript(sid)
        size = _transcript_size(tpath) if tpath else None
        evidence = _parse_raw_file(vault_raw, r["path_b"])
        corpus.append(
            {
                "session_id": sid,
                "date": r["date"],
                "skip_reason_a": r.get("skip_reason_a"),
                "transcript_path": tpath,
                "transcript_recoverable": tpath is not None,
                "size": size,
                "haiku_title": evidence["title"],
                "haiku_tags": evidence["tags"],
                "haiku_body": evidence["body"],
                "draft_guess": _draft_guess(
                    r.get("skip_reason_a"), size, evidence["tags"]
                ),
                "keepable": "TODO",  # human-owned label: yes | no
            }
        )

    recoverable = [c for c in corpus if c["transcript_recoverable"]]
    (OUT_DIR / "bonly-corpus.json").write_text(json.dumps(corpus, indent=2))
    _write_worksheet(OUT_DIR / "bonly-corpus.md", corpus, recoverable)

    print(f"B-only sessions:        {len(corpus)}")
    print(f"  transcript recoverable: {len(recoverable)}  (usable for replay)")
    print(f"  unrecoverable:          {len(corpus) - len(recoverable)}")
    print(
        f"\nWrote:\n  {OUT_DIR / 'bonly-corpus.json'}\n  {OUT_DIR / 'bonly-corpus.md'}"
    )
    print("\nNext: review bonly-corpus.md, set each `keepable:` to yes/no, then run")
    print("      the replay harness (Phase 2) to score current vs candidate prompt.")


def _write_worksheet(
    path: pathlib.Path, corpus: list[dict], recoverable: list[dict]
) -> None:
    lines = [
        "# B-only regression corpus — labelling worksheet",
        "",
        "Sessions where Path A (Sonnet) returned null/errored and only Path B (Haiku)",
        "captured. Question per row: **should Path A have curated this?** Set `keepable`",
        "to `yes` (Path A wrongly dropped durable content) or `no` (null was correct).",
        "",
        f"- Total B-only: **{len(corpus)}**  ·  replay-usable (transcript on disk): "
        f"**{len(recoverable)}**",
        "- `draft_guess` is a heuristic hint, not ground truth — override freely.",
        "",
        "---",
        "",
    ]
    for i, c in enumerate(corpus, 1):
        rec = "✅ recoverable" if c["transcript_recoverable"] else "❌ transcript gone"
        size = c["size"]
        size_s = f"{size['messages']} msgs · ~{size['est_tokens']} tok" if size else "—"
        lines += [
            f"## {i}. {c['haiku_title'] or '(untitled)'}",
            f"- session: `{c['session_id'][:8]}` · {c['date']} · {rec} · {size_s}",
            f"- original skip_reason_a: `{c['skip_reason_a']}`",
            f"- tags: {', '.join(c['haiku_tags']) or '—'}",
            f"- draft_guess: **{c['draft_guess']}**",
            "- keepable: **TODO**  ← set to yes / no",
            "",
            "<details><summary>Haiku evidence (what content existed)</summary>",
            "",
            (c["haiku_body"] or "(no body)")[:1500],
            "",
            "</details>",
            "",
        ]
    path.write_text("\n".join(lines))


if __name__ == "__main__":
    main()
