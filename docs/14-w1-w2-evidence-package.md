# W1/W2 evidence package

## Status and purpose

This document defines the smallest evidence package that can move the current
30-task slice toward W1/W2 sealing. It does not declare the project complete.
L68 Phase A is accepted only as `BROKER_DESIGN_ACCEPTED_PAYLOAD_FREE`; it gives
no production, semantic, data, or training credit.

The current local census is exact but not sealed:

| Evidence surface | Current observation | Interpretation |
|---|---:|---|
| Allocated tasks | `30/30` (`5` each for F-1 through F-6) | inventory closure only |
| Build inputs/assets | `201/201`, distinct paths/OIDs, `gaps=0` | sourceability closure only |
| Leakage groups | `1 < 563` | correlated whole-tenant slice; no population claim |
| Rights/legal review | `0/201` reviewed | every asset remains pending human/legal decision |
| Task-specific oracle execution | `0/30` | intended oracle fields are not results |
| F-4/F-5/F-6 evidence | `0/15` tasks, `0/75` oracle cells | future work, not current evidence |

The future benchmark target is `600` tasks and at least `563` genuinely
independent leakage groups. A future target of `25` protected role receipts is
`10` for F-4 (`observed` and `proposed`), `10` for F-5 (`legacy` and
`canonical`) and `5` for F-6 (`explained source`). This is a planning target
only; it is not evidence until a protected Phase-B runner produces
independently verified receipts.

## Required sidecar contracts

The computed manifests remain immutable inputs. The package adds sidecars; it
does not rewrite them or silently change their status.

The frozen `benchmark-plan.json` still contains the historical labels
`dependency_closure_not_computed` and `pending_dependency_closure`. They are
retained as immutable planning history, not current truth. The L69 sidecars and
the computed closure are the canonical current reading:
`computed_not_sealed_evidence_only` with one correlated leakage group.

### W1 task blocker sidecar

One record for each of the 30 allocated tasks, keyed by `task_id`, must contain:

- family, mode, source path and source blob OID copied from the allocation;
- dependency-closure status and leakage-group status;
- required oracle cells, each with `status`, `authority`, `receipt_ref`, and
  `observed_at` (or an explicit `not_run` reason);
- runtime, ambient-time, mutation-parent, golden-IR, migration-pair and
  human-adjudication dependencies where applicable;
- a fail-closed `seal_eligible` boolean derived from the complete record.

No sidecar may claim an oracle result from compiler-clean output, an adapter
authored `matched=true`, a policy-only receipt, or a synthetic broker receipt.
Missing fields are blockers, not null successes.

### W2 rights/provenance sidecar

One record for each of the 201 assets, keyed by `path` and `blob_oid`, must
contain:

- source revision, provenance parents and dependency closure;
- sensitivity, owner/rights basis, permitted use scope and external-distribution
  decision;
- whether the value was derived locally or requires human/legal review;
- reviewer identity, decision timestamp, evidence reference and status;
- a content and manifest hash over the complete ordered roster.

The current manifest's `internal`, `local_training_and_evaluation_only`, and
`legal_review=not_performed` values are observations, not legal approvals.

## Seal gate

W1/W2 may be marked sealed only when all of the following are independently
recomputed from immutable manifests and sidecars:

1. tasks `in=30 out=30 distinct=30 gaps=0` and assets `in=201 out=201
   distinct=201 gaps=0`;
2. every task has a closed dependency record and every applicable oracle has an
   independently grounded result or an explicit exclusion approved by the
   frontier;
3. every asset has a rights/sensitivity decision, with human/legal evidence
   where local derivation cannot establish it;
4. leakage groups are computed from the full provenance/dependency closure and
   meet the ratified benchmark requirement, or the report remains explicitly
   non-population and unsealed;
5. the sidecar roster, schema, tool version, source revision and hashes are
   reproducible in a second read-only verification.

The package must fail closed on any count mismatch, unresolved rights record,
unexecuted required oracle, shared ancestry, self-certifying target, or hash
drift. A green structural census cannot promote the slice.

## Dependency order and authorizations

The shortest honest path is:

1. finish and independently validate the W1 blocker and W2 rights sidecars;
2. obtain explicit **Phase-B privileged authorization** for the protected OS
   broker, runner, anchor store and public-synthetic execution receipts;
3. obtain separate **data/human-review authorization** for rights adjudication,
   source use, new independent benchmark authoring and any materialization;
4. seal W1/W2 only after those sidecars and leakage closure pass;
5. extend typed semantic oracles and protected receipts for F-4/F-5/F-6;
6. establish W3, baseline A/B and O-003; only then obtain separate **training
   authorization** for a bounded QLoRA run.

These are three independent authorizations. Orchestra capacity, a passing
static test, or L68 Phase-A acceptance never implies any of them.

## Permanent Orchestra method

L0 is the frontier coordinator and owns architecture, semantic judgment,
leakage, gates and the final verdict. Kimi and Qwen are team frontiers: each
receives a disjoint roster, delegates bounded mechanical work, validates its
returns, and writes arithmetic and STOPs to the shared board. Internal lanes
may perform deterministic census and formatting only. L0 inspects the diff,
reruns the relevant gates, and independently recomputes at least one claim from
each team before accepting it. `in=N out=N distinct=N gaps=0` is required for
every closed roster.

## Current stop rules

- no Metis checkout writes, secrets, live/private data, external upload, model
  download or training in this package;
- no W1/W2 seal from `computed_not_sealed`, one correlated leakage group, or an
  unperformed legal review;
- no semantic credit from compiler-clean output, adapter-authored matches,
  policy-only receipts or synthetic receipts;
- no F-4/F-5/F-6 target is evidence until its independent typed oracle and
  protected receipt are present;
- any roster/hash mismatch, rights ambiguity, leakage closure failure or
  unverified authority stops the wave.

## Acceptance commands

The frontier must run, record exact output and independently inspect the diff:

```sh
python3 -m json.tool manifests/slice-30-closure.json >/dev/null
python3 -m json.tool manifests/slice-30-assets.json >/dev/null
uv run pytest tests/test_w1_blockers.py tests/test_w2_rights.py tests/test_w1_seal.py
make validate
make lint
make format-check
git diff --check
```

The six dedicated sidecar validators are now part of `make validate`. L69
acceptance recorded `31/31` sidecar tests and foundation `36` passes with `0`
errors. This accepts the deterministic evidence package only; it does not alter
the explicit `unsealed_evidence_only` verdict. `make check` remains subject to
the active no-Node/no-production STOP and must not be laundered as a green
result when it cannot run safely.

## Ownership

This document and the matching L69 brief are the only writer-owned surfaces for
this lane. The manifests, broker contract, source checkout, model artifacts and
training state remain read-only and off-limits.
