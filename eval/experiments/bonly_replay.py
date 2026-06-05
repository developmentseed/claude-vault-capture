#!/usr/bin/env python3
"""Replay the B-only corpus through current vs candidate Path-A prompts.

Answers the experiment's question: does the recall-tuned candidate prompt
recover keepable sessions that the current (precision-biased) prompt nulls,
without turning genuinely low-signal sessions into noise?

Faithful replay: each session is loaded and scrubbed through the exact
production code path (`curate._load_transcript` + `scrub.scrub` + the
run_capture role-join), then run through Path A's real transport
(`curate._invoke_model`) and parsed with the real `_strip_fences` + null/JSON
logic — the only varied input is the system prompt.

SAFETY
------
- Default is a DRY RUN: prints the plan and an API-cost estimate, makes NO
  network calls. Set CAPTURE_EXPERIMENT_LIVE=1 to actually call the model.
- Writes only under eval/state/experiments/ (gitignored). Never touches the
  vault Inbox, log.md, session-index.tsv, or the production prompt.
- Each session costs 2 Sonnet calls (current + candidate). ~24 sessions ≈ 48
  calls. The dry run prints the dollar estimate before you commit.

Run:
  .venv/bin/python3 eval/experiments/bonly_replay.py            # dry run + cost
  CAPTURE_EXPERIMENT_LIVE=1 .venv/bin/python3 eval/experiments/bonly_replay.py
"""

from __future__ import annotations

import json
import os
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
HOOKS = REPO / "hooks"
sys.path.insert(0, str(HOOKS))

import curate  # noqa: E402
import scrub as scrub_mod  # noqa: E402

EXP_DIR = REPO / "eval" / "state" / "experiments"
CORPUS = EXP_DIR / "bonly-corpus.json"
CURRENT_PROMPT = REPO / "prompts" / "curation-system-prompt.md"
# Candidate prompt + output tag are overridable so successive variants (v1, v2,
# …) can be scored without clobbering each other's results.
TAG = os.environ.get("CANDIDATE_TAG", "v1")
CANDIDATE_PROMPT = pathlib.Path(__file__).parent / os.environ.get(
    "CANDIDATE_PROMPT_FILE", "candidate-curation-prompt.md"
)


def _scrubbed_text(transcript_path: str) -> str:
    transcript = curate._load_transcript(transcript_path)
    role_map = {"user": "[USER]", "assistant": "[ASSISTANT]"}
    raw_text = "\n".join(
        f"{role_map.get(m.get('role', ''), '[UNKNOWN]')}: {m.get('content', '')}"
        for m in transcript
    )
    scrubbed, _ = scrub_mod.scrub(raw_text)
    return scrubbed


def _run_prompt(system_prompt: str, scrubbed: str) -> dict:
    """Mirror _call_path_a's parse logic, parameterised on the system prompt."""
    text, tin, tout = curate._invoke_model(
        curate.MODEL_A, curate.MAX_TOKENS_A, system_prompt, scrubbed
    )
    raw = curate._strip_fences(text)
    cost = curate._estimate_cost_a(tin, tout)
    if raw.lower() == "null":
        return {"outcome": "null", "tokens_out": tout, "cost_usd": cost}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {
            "outcome": "malformed_json",
            "tokens_out": tout,
            "cost_usd": cost,
            "raw_head": raw[:200],
        }
    return {
        "outcome": "artifact",
        "title": data.get("title"),
        "type": data.get("type"),
        "tokens_out": tout,
        "cost_usd": cost,
    }


def _dry_run(corpus: list[dict]) -> None:
    rec = [c for c in corpus if c["transcript_recoverable"]]
    tok = sum((c["size"] or {}).get("est_tokens", 0) for c in rec)
    # 2 calls per session (current + candidate); output is small (~300 tok like prod).
    est_in = tok * 2
    est_out = len(rec) * 2 * 300
    est_cost = curate._estimate_cost_a(est_in, est_out)
    print("DRY RUN — no API calls made. Set CAPTURE_EXPERIMENT_LIVE=1 to execute.\n")
    print(f"  replay-usable sessions : {len(rec)}")
    print(
        f"  model calls            : {len(rec) * 2}  (current + candidate per session)"
    )
    print(f"  est. input tokens      : ~{est_in:,}")
    print(f"  est. output tokens     : ~{est_out:,}")
    print(f"  est. API cost          : ~${est_cost:.2f}  (Sonnet $3/M in, $15/M out)")
    labelled = sum(1 for c in rec if c.get("keepable") in ("yes", "no"))
    print(f"\n  keepable labels set    : {labelled}/{len(rec)}")
    if labelled < len(rec):
        print("  ⚠ Unlabelled rows will still replay, but recall/precision scoring")
        print("    needs labels — fill `keepable:` in bonly-corpus.md / .json first.")


def _live_run(corpus: list[dict]) -> None:
    rec = [c for c in corpus if c["transcript_recoverable"]]
    cur_prompt = CURRENT_PROMPT.read_text()
    cand_prompt = CANDIDATE_PROMPT.read_text()
    results = []
    for i, c in enumerate(rec, 1):
        sid = c["session_id"][:8]
        print(f"[{i}/{len(rec)}] {sid} {c['date']} …", flush=True)
        scrubbed = _scrubbed_text(c["transcript_path"])
        try:
            cur = _run_prompt(cur_prompt, scrubbed)
        except Exception as exc:  # noqa: BLE001 — record, don't abort the batch
            cur = {"outcome": f"error:{type(exc).__name__}"}
        try:
            cand = _run_prompt(cand_prompt, scrubbed)
        except Exception as exc:  # noqa: BLE001
            cand = {"outcome": f"error:{type(exc).__name__}"}
        results.append(
            {
                "session_id": c["session_id"],
                "date": c["date"],
                "keepable": c.get("keepable"),
                "current": cur,
                "candidate": cand,
            }
        )
    (EXP_DIR / f"bonly-results-{TAG}.json").write_text(json.dumps(results, indent=2))
    _scorecard(results)


def _scorecard(results: list[dict]) -> None:
    n = len(results)
    cur_art = sum(1 for r in results if r["current"]["outcome"] == "artifact")
    cand_art = sum(1 for r in results if r["candidate"]["outcome"] == "artifact")
    flipped = [
        r
        for r in results
        if r["current"]["outcome"] == "null" and r["candidate"]["outcome"] == "artifact"
    ]
    cost = sum(
        r["current"].get("cost_usd", 0) + r["candidate"].get("cost_usd", 0)
        for r in results
    )

    lines = [
        f"# B-only replay scorecard — {TAG}",
        f"_candidate prompt: {CANDIDATE_PROMPT.name}_",
        "",
        f"- sessions replayed: **{n}**",
        f"- current prompt produced an artifact:   **{cur_art}/{n}**  "
        f"(these were all null/error in production)",
        f"- candidate prompt produced an artifact: **{cand_art}/{n}**",
        f"- null→artifact flips (candidate recovered): **{len(flipped)}**",
        f"- replay API cost: ${cost:.2f}",
        "",
    ]

    labelled = [r for r in results if r["keepable"] in ("yes", "no")]
    if labelled:
        keep = [r for r in labelled if r["keepable"] == "yes"]
        cand_recall = sum(1 for r in keep if r["candidate"]["outcome"] == "artifact")
        # precision: of candidate's new artifacts, how many were labelled keepable
        new_art = [r for r in labelled if r["candidate"]["outcome"] == "artifact"]
        good = sum(1 for r in new_art if r["keepable"] == "yes")
        lines += [
            "## Scored against human labels",
            f"- labelled keepable: **{len(keep)}/{len(labelled)}**",
            f"- candidate recall (keepable recovered): **{cand_recall}/{len(keep)}**"
            if keep
            else "- no keepable labels",
            f"- candidate precision (new artifacts that were keepable): "
            f"**{good}/{len(new_art)}**"
            if new_art
            else "- candidate captured nothing new",
            "",
        ]
    else:
        lines += [
            "## Scoring",
            "_No `keepable` labels set — only the null→artifact flip count is",
            "meaningful. Label bonly-corpus.md and re-run to score recall/precision._",
            "",
        ]

    lines += ["## null→artifact flips", ""]
    for r in flipped:
        a = r["candidate"]
        lines.append(
            f"- `{r['session_id'][:8]}` {r['date']} → "
            f"**{a.get('type')}**: {a.get('title')}  (keepable={r['keepable']})"
        )

    out = EXP_DIR / f"bonly-scorecard-{TAG}.md"
    out.write_text("\n".join(lines) + "\n")
    print(f"\nWrote scorecard → {out}")
    print(
        f"  current artifacts: {cur_art}/{n} · candidate: {cand_art}/{n} · "
        f"flips: {len(flipped)} · cost ${cost:.2f}"
    )


def main() -> None:
    if not CORPUS.exists():
        sys.exit("corpus not found — run build_bonly_corpus.py first")
    corpus = json.loads(CORPUS.read_text())
    if os.environ.get("CAPTURE_EXPERIMENT_LIVE") == "1":
        _live_run(corpus)
    else:
        _dry_run(corpus)


if __name__ == "__main__":
    main()
