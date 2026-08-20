# BRIEF — final adversarial integration and W5-readiness audit

Repository under review:
`/Users/tommasotessarolo/Developer/metis-model-1`.

Read-only Metis evidence checkout:
`/Users/tommasotessarolo/Developer/ares-matioska/metis`.

Read completely before work:

1. `/Users/tommasotessarolo/Developer/metis-model-1/AGENTS.md`
2. `/Users/tommasotessarolo/Developer/metis-model-1/orchestra/runs/2026-08-20-accuracy-99-pilot/BLACKBOARD.md`
3. `/Users/tommasotessarolo/Developer/metis-model-1/orchestra/runs/2026-08-20-accuracy-99-pilot/SESSIONS.md`
4. `/Users/tommasotessarolo/Developer/metis-model-1/docs/11-feasibility-and-risks.md`
5. `/Users/tommasotessarolo/Developer/metis-model-1/docs/12-accuracy-99-execution-plan.md`
6. every schema, manifest, source module and test named by the active board.

Both repositories are READ-ONLY for this lane. Do not edit, format, generate,
checkout, clean, commit, create worktrees, start training, download models or
remove artifacts. Do not read `.env`, credentials, keychains, private keys,
raw production payloads or live ARES data. The only permitted writes are the
wrapper-provided ignored activity blackboard, journal and artifacts/report.

Fixed state expected at dispatch:

- Model 1 baseline HEAD:
  `ad7a1169104c22fa8736b7463a93f65ea9f670f8`, with authorized dirty work in
  the current repository.
- Metis HEAD: `a2dde2b191f6b78c2003d74875560da782470968`.
- Metis has exactly four pre-existing untracked status entries: `tmp/` and
  three `tooling/metis-dsl-*.vsix.sha256` files. Any delta is a STOP.
- Target model remains Qwen3.8 only; all executed training in this wave used
  public synthetic data and is technical evidence, not Metis accuracy.

## Unit 1 — exact contract and denominator census

Independently validate every tracked schema/instance pair and recompute:

- target total 600, family sum 600, maximum one failure;
- Wilson 95% lower bounds for 600/600, 599/600 and 598/600;
- minimum denominator/groups needed to tolerate one failure at lower bound 0.99;
- closure `tasks=30/30`, build inputs `201/201`, distinct paths/OIDs and gaps;
- asset classification `201/201`, direct per-record policy and manifest hash;
- current distinct leakage groups versus required minimum.

Try to falsify the population claim by changing labels without changing
ancestry. Cosmetic task multiplication must not count as independence.

## Unit 2 — fail-closed implementation review

Audit all code and adversarial tests in `src/metis_model1` and `tests`. Try to
bypass, at minimum:

1. dataset materialization with a draft, negative, pending/failed oracle,
   mismatched assistant target, cross-split parent or leakage group;
2. evaluator with missing/duplicated variants, mixed prompt/config/runtime,
   malformed evidence hashes, incomplete family oracles, invented identifier,
   another critical veto, conditional denominator or claimed success that
   disagrees with computed end-to-end outcomes;
3. closure and asset registers with poisoned OIDs, duplicate paths, changed
   classification or self-hash drift;
4. hyperparameter/storage policies with duplicate grid members, budget drift,
   unqualified settings, non-atomic publication or automatic deletion.

Distinguish a valid synthetic pipeline from a real W3 dataset. Report any path
by which `make check`, `validate-pilot` or `assess-w5` could incorrectly call W5
ready.

## Unit 3 — executed technical evidence and readiness

Read the sequence-1024 ignored reports/manifests without changing them. Verify
hashes and arithmetic for:

- fixture: raw 7,414; prefix 20; completion 7,394; batch 1,024; retained
  completion 1,004;
- rank 8 step 1 and resume step 2 finite loss/peak/checkpoint manifests;
- rank 16 step 1 finite loss/peak/checkpoint manifest;
- O-005 four-config/700-step/32-GiB budget;
- O-006 40-GiB per-run, 100-GiB preflight, 60-GiB reserve and no automatic
  deletion.

Confirm these results do not establish Metis semantic uplift. Recompute the
current W5 blockers from the decision register and the actual tracked data.
O-003, missing independent benchmark population, missing real W3 dataset and
missing A/B baseline must remain fail-closed where applicable.

## Gates and output

Run gates directly, never through a pipeline. At minimum run `make check`,
`uv run metis-model1 validate-pilot --json`, and
`uv run metis-model1 assess-w5 --json`; the last command is expected to return
non-zero while W5 is blocked, so capture its exit code explicitly without
laundering it.

Compare exact `git status --short` and HEAD for both repositories before and
after. Any changed status line is a STOP.

Write one report in the wrapper activity artifacts directory named
`kimi-final-integration-audit.md`. End with the four protocol sections and wire
tags. Include ranked P0/P1/P2 findings, exact commands/counts, and what cannot
be established. A clean verdict is accepted only after adversarial mutations
and independent recomputation, not because the project tests call themselves
green.
