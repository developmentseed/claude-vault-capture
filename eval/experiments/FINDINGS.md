# B-only experiment — findings

**Question.** The 6-week eval showed Path A (Sonnet, curated-or-null) returns null on
~41% of eligible sessions *by design* — `curation-system-prompt.md` Rule 5 biases
toward null "because the raw baseline (Path B) always captures". Before retiring Path B,
we asked: of the sessions where **only Path B captured** ("B-only"), how many held
content Path A *should* have curated, and can a prompt change recover them without
flooding the inbox?

**Method.** 34 B-only sessions from `log.md`; 24 had recoverable transcripts. Each was
replayed through the production Path A code path (`_load_transcript` → `scrub` →
`_invoke_model`), varying only the system prompt. 6 of 24 were human-labelled "keepable"
(a durable *engineering* artifact: decision/runbook/gotcha/spec). Scripts:
`build_bonly_corpus.py`, `bonly_replay.py`. Raw results in gitignored
`eval/state/experiments/`.

## Three prompt variants — the precision/recall frontier

| Variant | Lever vs production | Captured | Recall (keepable) | Precision |
|---|---|---|---|---|
| **v1** | recall framing; `devlog-snippet` de-rared | 24/24 | 6/6 | **25%** |
| **v2** | v1 + remove `devlog-snippet`; null plan-tuning | 2/24 | 2/6 | 100% |
| **v3** | v2 + admit "review→decision" as `decision` | 7/24 | 3/6 | 43% |

No variant reaches high recall **and** high precision.

## Why: signal and noise are structurally entangled

Per-session capture of the 6 keepable engineering sessions:

| session | type | v1 | v2 | v3 |
|---|---|:-:|:-:|:-:|
| 920a6a09 | gotcha (S3 glob) | ✓ | ✓ | ✓ |
| 4d9e81c4 | gotcha (OOM) | ✓ | ✓ | ✓ |
| 7b991e5f | decision (plan review) | ✓ | · | · |
| f1cd08b9 | decision (skills arch) | ✓ | · | ✓ |
| 7c0960c5 | decision (observability) | ✓ | · | · |
| 5afda4ff | gotcha (Dask hang) | ✓ | · | · |

- **Only the `gotcha` type captures reliably** across all variants. Gotchas are
  structurally distinct (a concrete bug + fix), so the model separates them cleanly.
- **`decision`-type keepers capture erratically.** They are design/plan reviews — and
  they are *structurally identical* to the noise (legal-document reviews, plan-tuning
  process sessions). v3's "review-that-reaches-a-conclusion = decision" rule was
  **domain-blind**: it pulled in 4 personal-legal/process reviews as false positives
  **while still missing** the engineering decisions (7b991e5f, 7c0960c5).
- The dominant noise class is **personal-legal correspondence** (14 of 24 B-only
  sessions are the SOLEA case). It mimics every substantive type, so no type rule
  excludes it. The only real discriminator is *domain*, which the prompt can't infer.
- **5afda4ff is out of scope**: its transcript is ~60k tokens, above the `token_limit`
  guard, so it would never reach Path A in production. It should not count against recall.

## Conclusion

You do **not** need both pipelines, and a tuned Path A cannot "absorb" Path B's recall
without flooding — because ~75% of what Path A nulls is personal-legal content that is
out of scope for the system's stated goal (durable *engineering* artifacts) and is
already handled by a dedicated workflow.

- **Path A's precision bias is correct** for the engineering-knowledge goal. None of
  v1/v2/v3 beats the current prompt's precision; do **not** adopt them.
- **Path B does not earn its keep as a curator** (near-zero promotion rate; raw files
  mostly deleted as duplicates). Its unique catches are largely out-of-scope legal
  sessions.
- The genuinely-missed engineering artifacts are few (~3 in scope over 6 weeks) and skew
  to the cleanly-separable **gotcha** type. The cheapest recovery is **retry-on-null**
  (the *unchanged* prompt non-deterministically nulled-then-captured 2–3 keepable
  sessions across runs — a single retry recovers some at zero precision cost), not a
  second model or a looser prompt.

**Caveat (depends on goal).** If the goal were "capture everything, including personal
correspondence," the redundant path flips: keep the cheap Haiku always-summariser
(Path B, $0.38/6wk) and drop the curated Path A. Either way the answer is *one path, not
two*.
