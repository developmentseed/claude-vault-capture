#!/usr/bin/env python3
"""Measure the token/cost delta of transcript tool-enrichment.

Background. The curator used to see only text blocks; render_transcript() now
surfaces tool activity ([TOOL]/[OUT]/[ERROR]). This script quantifies what that
costs, per session, using the *real* production renderer so the number stays
re-checkable as the caps/budget evolve.

Method. For every Claude Code transcript still on disk under ~/.claude/projects
(or the dirs passed as argv), load it through curate._load_transcript, then
compare two assemblies:
  - baseline: text-only ("[ROLE]: content"), i.e. the pre-enrichment behaviour
  - enriched: render_transcript() with the current env knobs (L2.5 by default:
    CAPTURE_SUCCESS_HEAD_CHARS=200, CAPTURE_TOOL_CHARS_BUDGET=30000)
Tokens are estimated as chars // 4 (the same heuristic as is_above_token_limit);
input cost uses claude-sonnet-4-6 at $3/M. Output tokens are unchanged by
enrichment, so the *total* per-session cost rises less than the input delta.

This is a read-only measurement: it makes no network calls and writes nothing.

Run:
  .venv/bin/python3 eval/experiments/tool_enrichment_cost.py
  .venv/bin/python3 eval/experiments/tool_enrichment_cost.py <sid-or-glob> ...
"""

from __future__ import annotations

import glob
import os
import pathlib
import statistics
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "hooks"))

import curate  # noqa: E402

INPUT_PER_MTOK = 3.0  # claude-sonnet-4-6 input $/M
TOKEN_GUARD = int(os.environ.get("CAPTURE_MAX_EST_TOKENS", "50000"))


def _baseline_text(messages: list[dict]) -> str:
    """Pre-enrichment assembly: role-prefixed text-only content."""
    role = {"user": "[USER]", "assistant": "[ASSISTANT]"}
    return "\n".join(
        f"{role.get(m.get('role', ''), '[UNKNOWN]')}: {m.get('content', '')}"
        for m in messages
    )


def _est(chars: int) -> tuple[int, float]:
    tok = chars // 4
    return tok, tok * INPUT_PER_MTOK / 1_000_000


def _discover(args: list[str]) -> list[str]:
    if args:
        out = []
        for a in args:
            if os.path.sep in a or a.endswith(".jsonl"):
                out.extend(glob.glob(os.path.expanduser(a)))
            else:  # treat as a session-id prefix
                out.extend(
                    glob.glob(os.path.expanduser(f"~/.claude/projects/*/{a}*.jsonl"))
                )
        return sorted(set(out))
    return sorted(glob.glob(os.path.expanduser("~/.claude/projects/*/*.jsonl")))


def main() -> None:
    paths = _discover(sys.argv[1:])
    if not paths:
        print("no transcripts found", file=sys.stderr)
        sys.exit(1)

    rows = []
    for p in paths:
        try:
            msgs = curate._load_transcript(p)
        except Exception:
            continue
        if not msgs:
            continue
        base = len(_baseline_text(msgs))
        enr = len(curate.render_transcript(msgs))
        rows.append((pathlib.Path(p).name[:8], base, enr))

    print(f"{'session':9} | {'baseline':>16} | {'enriched':>16} | {'Δ':>10}")
    print("-" * 62)
    over = 0
    for sid, base, enr in rows:
        bt, bc = _est(base)
        et, ec = _est(enr)
        flag = ""
        if et > TOKEN_GUARD:
            flag = "  ⚠ over guard"
            over += 1
        print(
            f"{sid:9} | {bt:>6}t ${bc:0.4f} | {et:>6}t ${ec:0.4f} | "
            f"${ec - bc:+0.4f}{flag}"
        )

    if rows:
        avg_base = statistics.mean(r[1] for r in rows)
        avg_enr = statistics.mean(r[2] for r in rows)
        _, bc = _est(int(avg_base))
        _, ec = _est(int(avg_enr))
        max_enr_tok = max(_est(r[2])[0] for r in rows)
        print(
            f"\n{len(rows)} sessions | avg baseline ${bc:0.4f} → enriched ${ec:0.4f} "
            f"(+${ec - bc:0.4f}, {100 * (ec - bc) / bc if bc else 0:+.0f}% input)"
        )
        print(
            f"max enriched session: {max_enr_tok} tok (guard={TOKEN_GUARD}); "
            f"{over} session(s) over guard"
        )
        print("output tokens unchanged → total-cost increase is smaller than the above")


if __name__ == "__main__":
    main()
