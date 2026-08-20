# Kimi K3 accuracy-99 audit — frontier acceptance record

## Identity

- External team: Kimi Code CLI `0.36.1`, model alias `kimi-code/k3`.
- Protocol activity: `metis-model1-accuracy99-pilot`.
- Wrapper session: `20260820-183033`, resumable session
  `session_43a913e8-6af5-493b-98a3-9b54429eeda8`.
- Wall time: 558 seconds; wrapper exit code: 0.
- Source report:
  `/Users/tommasotessarolo/Developer/ai-multi-team-orchestra/runs/metis-model1-accuracy99-pilot/artifacts/kimi-accuracy99-audit.md`.
- Source report SHA-256:
  `c5463bc0a75c6c568960c4c2dd7d410c03acf66346df542bcb7e18f7ad0c04bb`.
- Wilson output SHA-256:
  `8a73c633bba75cb8caa4a8c82da89a657b670505c34c6744b4d7e41f55c4ee76`.
- Thirty-source verification output SHA-256:
  `e8e8579c87d7d406462857c1434f36e65e18c250370058397182c24c0e92c016`.

This tracked record is a frontier review of the ignored external report. It
does not copy external runtime artifacts into Git and does not promote a model
or benchmark.

## Accepted findings

1. The allocated smoke roster closes as
   `in=30 out=30 task_ids=30 paths=30 blob_oids=30 matches=30 gaps=0` at
   `metis@a2dde2b191f6b78c2003d74875560da782470968`. L0 independently
   recomputed the same result with read-only Git object queries.
2. A two-sided 95% Wilson lower bound of 0.99 requires 381/381 successes in the
   all-success case, at least 563 observations to tolerate one failure and at
   least 726 observations to tolerate two failures.
3. The pre-registered target was therefore raised from 400 to 600 tasks before
   any candidate result. At 600 tasks, 599/600 passes the lower-bound gate and
   598/600 fails it. The gate permits at most one failure.
4. The 99% claim is global only. The planned 80–110 observations per family
   cannot support a per-family 99% confidence claim; every family still needs
   its numerator, denominator, interval and separate floor reported.
5. The current evidence population is one tenant. No cross-tenant or general
   Metis-product 99% claim is permitted without a genuinely held-out tenant.
6. Structural parse/link/validate/compile entrypoints exist, but task-specific
   semantic, patch-minimality, diagnostic-mutation and blind-human oracles do
   not. The allocated 30 tasks are a smoke roster, not a sealed benchmark.
7. Metis is a whole-program DSL. Static text analysis can prove source
   identity, but cannot prove authoritative per-task dependency closure;
   Langium linking is required.
8. `tooling/package.json` is `private: true` and `UNLICENSED`. The user has
   authorized local training for this wave, but no external upload,
   redistribution or publication is authorized or inferred.

## Reconciliation of the external STOP

Kimi correctly stopped when
`docs/12-accuracy-99-execution-plan.md` appeared during its read-only lane.
L0 identifies that file as its own concurrent, authorized, pre-candidate
contract write in the Model 1 repository. Kimi did not create or modify it.
The event is therefore reconciled as a valid concurrency stop followed by a
frontier writer-identity check, not as repository contamination.

The external report's final prose says that the Metis checkout had "three
pre-existing untracked paths". The exact preflight and post-run status contains
four entries: `tmp/` plus three `tooling/*.vsix.sha256` files. This is a report
counting error. The before/after status is otherwise identical, so the
read-only Metis invariant holds.

## Frontier verdict

`ACCEPTED_WITH_CORRECTIONS` for benchmark arithmetic, source identity,
oracle-gap analysis and dependency ordering. This acceptance does not close
O-003 and does not authorize W5. The next legal transition is:

1. compute dependency closure read-only;
2. classify rights and sensitivity for the complete closure;
3. build and polarity-test missing task oracles;
4. seal the 30-task smoke roster;
5. build contamination-safe W3 data and run A/B;
6. ratify O-003/O-005/O-006;
7. only then run the bounded QLoRA pilot and paired B/D evaluation.
