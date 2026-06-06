# Tool-enrichment A/B — findings

**Question.** Surfacing tool activity ([TOOL]/[OUT]/[ERROR]) to the curator raises input
~+$0.015/session (measured, `tool_enrichment_cost.py`). Is the *quality* gain worth it,
or do we need more data before committing?

**Method.** The 6 engineering sessions whose transcripts survive were re-curated through
the **current** production path (`render_transcript` → `scrub` → `_call_path_a`, same
prompt, Sonnet via subscription) and each new artifact laid beside the note already in
the vault — which was produced by the pre-enrichment, text-only pipeline. Harness:
`enrichment_quality_ab.py` (dry-run by default; `CAPTURE_EXPERIMENT_LIVE=1` to call).
Raw comparisons in gitignored `eval/state/experiments/enrichment_ab/`.

## Result: 3 clear wins, 2 slight, 1 mixed, 0 regressions

| session | old type | new type | verdict | what enrichment added |
|---|---|---|---|---|
| 41e06f8f | gotcha | gotcha | **win** | verbatim broken regex + the replacement `_CODE_FENCE_RE` block, line numbers, exact `_log_error(...)` |
| 20f24265 | devlog-snippet | runbook | **win** | copy-pasteable `uv lock --upgrade-package idna`, `pip-audit`, the actual convert-delegation code diff |
| f3730e22 | devlog-snippet | gotcha | **win** | 3 durable constraints (memory plateau, zombie-container `docker` cmds, benign `%s` warning); run telemetry demoted |
| 13ca1e63 | devlog-snippet | devlog-snippet | slight | recovered the Issue #217 source URL |
| 272e8fdd | devlog-snippet | decision | slight | fix-at-source rationale + non-obvious `pyproj.CRS.to_cf()` / lazy `.rio` import gotcha |
| 23cf9e07 | gotcha | gotcha | mixed | gained exact `gh run view … --log-failed`; **dropped** the mypy arg-type point the old note had |

The wins concentrate where the fix/command/diff lived in tool I/O — content the text-only
pipeline could not see (79–94 % of those sessions). The `devlog-snippet`→durable reframing
(f3730e22, 272e8fdd) confirms the paired prompt tweak.

## Caveats (honest)

- **Not strictly dominant.** 23cf9e07 dropped a finding the old note kept — more input can
  shift the model's attention. Net-neutral there, but enrichment is not free upside on
  every note.
- **Doesn't cure hallucination.** 41e06f8f's new note muddled a derived percentage —
  enrichment surfaces ground truth but the model can still miscompute.
- **Output grows too.** Richer notes are longer, adding output cost ($15/M) on top of the
  measured +$0.015 input. That is the value being purchased, but the total delta exceeds
  the input figure alone.
- **n = 6, subscription replay.** The cost_usd in the raw dumps is inflated by Claude
  Code's ~22k-token harness overhead and is not comparable to API-mode billing.

## Conclusion

Keep enrichment. The signal is clear on the highest-value session types (gotchas/runbooks
whose signal is in commands/diffs/errors) with zero regressions. Further data would only
refine edges (e.g. whether longer outputs occasionally drop a point); it would not change
the direction.
