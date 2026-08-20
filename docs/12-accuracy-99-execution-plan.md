# Accuracy-99 execution plan

Status: **pre-registered proposal, before candidate results**.

## 1. What 99% means

The target is not loss, parser accuracy or compile-clean. It is variant D —
Qwen3.8 with the current context and the same compiler/repair loop used by the
base comparator — producing an end-to-end semantically correct result within
two repair cycles on the complete frozen benchmark.

A task is successful only when every applicable structural oracle passes, its
semantic or blind-human oracle passes, unrelated regions are preserved, no
invented identifier is accepted, and the task completes inside the declared
tool budget. Tool failures count as failures. Impossible or underspecified
requests succeed only through the expected refusal or request for context.

The pre-registered denominator is 600 tasks. The initial 400-task proposal was
superseded before candidate results after the independent Kimi K3 audit showed
that one failure would make the 99% lower-bound claim impossible:

| Family | Tasks | Reason |
|---|---:|---|
| F-1 authoring | 100 | high-impact construction coverage |
| F-2 minimal editing | 110 | critical patch correctness |
| F-3 diagnostic repair | 110 | critical compiler/fix behavior |
| F-4 review/explanation | 110 | critical semantic-error detection |
| F-5 migration/canonicalization | 90 | version and legacy behavior |
| F-6 structural explanation | 80 | AST/IR grounding without dominating the mix |
| **Total** | **600** | complete denominator |

The operational gate requires at least 99% observed success and a two-sided 95%
Wilson lower bound of at least 99%. With 600 trials, 599/600 has lower bound
about 99.062% and passes; 598/600 has lower bound about 98.793% and fails. The
smallest denominator that can tolerate exactly one failure at this threshold is
563.

Task-level Wilson evidence is not automatically a population claim when tasks
share ancestry. The population claim additionally requires at least 563
distinct leakage groups or a pre-registered cluster-aware alternative. The
current 30-source allocation cannot support that claim. Per-family Wilson lower
bounds at 80-110 all-success tasks are only about 95.4-96.6%, so 99% is a global
claim with per-family breakdown, not a per-family confidence claim. Evidence
from the single current tenant cannot be extrapolated to other tenants.

## 2. Dependency-ordered steps

### Step 0 — Boundary and technical qualification

Status: completed.

- Metis checkout fixed read-only at `a2dde2b...`;
- Qwen3.8 checkpoint/runtime fixed and technically qualified;
- training artifacts stay outside Git;
- Kimi K3 and internal delegated lanes operate through blackboards and return
  evidence to the frontier coordinator.

### Step 1 — Seal the 30-task smoke slice

For each allocated source:

1. resolve source blob and dependency closure at the pinned commit;
2. classify local-use sensitivity separately from external distribution;
3. materialize an exact task request and expected result;
4. execute every applicable structural and semantic oracle;
5. assign an immutable leakage group;
6. seal only when `in=30 out=30 distinct=30 gaps=0` and all blockers are closed.

This slice authorizes smoke evaluation only. It never becomes the promotion
benchmark by changing its label.

### Step 2 — Freeze benchmark v1

Create 600 reviewed tasks before generating related training examples. The
benchmark must include common, rare, composite, impossible and compile-clean but
semantically wrong cases. Entire provenance families remain held out. Every
task receives a checksum, oracle evidence, difficulty and access policy.

If 563 independent leakage groups cannot be created honestly, retain the
600-task observed target but mark the population-level 99% claim blocked.

Current sourceability evidence is decisive for the repository-only strategy:
the pinned commit has 199 tracked `.metis` files, but 197 belong to one
whole-program tenant. The remaining files are an isolated v0.42 diagnostic
demo and a generated template. This is three syntactic roots and at most two
defensible ancestry roots, so new or independently sourced material is required
before Step 2 can close.

### Step 3 — Build W3 dataset pipeline

Implement deterministic generators for author/edit/repair first, followed by
review/migration/explanation. Every candidate example is rejected unless it has:

- source, generator and parent hashes;
- split and leakage group assigned before derivation;
- sensitivity and local-use policy;
- applicable oracle results;
- no benchmark ancestor;
- text, structural and genealogical dedup results.

Pilot volume is 3,000-8,000 accepted examples. Payloads remain under ignored
local storage; Git contains only schema, code, manifest, report and checksums.

### Step 4 — Establish A/B baseline

Run the frozen 30-task smoke set with identical prompt, context, sampling,
reasoning mode and two-cycle budget:

- A: base, no context/compiler loop;
- B: base plus current context/compiler loop.

Publish numerator, denominator, family breakdown, failures and latency. Baseline
variance and failure taxonomy complete the evidence required for O-003.

### Step 5 — Ratify W5 controls

- O-003: absolute Accuracy-99 gate plus paired B/D uplift and tolerances fixed
  before candidate results;
- O-005: bounded rank/alpha/LR/seed grid selected from dev evidence and memory
  qualification, never from frozen results;
- O-006: atomic local artifact layout with immutable run/config/dataset hashes,
  retention and rollback.

Any 1,024/2,048-token configuration receives its own backward/memory probe; it
does not inherit the sequence-128 W4 result.

Current status: O-005 and O-006 are ratified. The 1,024-token public-synthetic
path passed rank-8 step 1, rank-8 resume to step 2 and rank-16 step 1 with
finite loss and 94.43-95.04 GB peak Metal. The bounded four-configuration grid
and 32 GiB sweep checkpoint cap are fixed before candidate results. O-003
remains open because the frozen independent denominator and baseline variance
do not yet exist, so W5 remains blocked.

### Step 6 — Execute bounded QLoRA pilot

Run one screening seed per pre-registered configuration, select on dev only,
then repeat the finalist with at least three seeds. Record finite gradients,
memory, throughput, checkpoint/resume, adapter hash and dev score by checkpoint.
Stop on instability or if the gain is only syntactic.

### Step 7 — Internal test and B/D decision

Evaluate B and D on identical internal-test tasks. Advance only when D improves
B semantically, has no critical veto and does not exceed the general-regression
budget. Diagnose dataset/oracle/task-formulation failures before increasing
iterations.

### Step 8 — Candidate and frozen benchmark

Freeze the finalist identity and run A/B/C/D once on benchmark v1. The result is:

- `TARGET_99_CONFIRMED` only if every absolute, confidence, independence,
  leakage, semantic and regression gate passes;
- `OBSERVED_99_ONLY` if task-level accuracy passes but the population/confidence
  contract does not;
- `REWORK` when evidence identifies a repairable dataset/oracle gap;
- `REJECT` when the adapter hypothesis fails or critical regressions remain.

### Step 9 — Iterate toward 99 without benchmark training

Failures on dev/internal test may drive new training groups. Frozen failures are
reported and reserved for the next benchmark version; their targets do not feed
the current candidate. Each iteration must add semantic coverage, not cosmetic
paraphrases.

## 3. Current feasibility

Technical training feasibility is high for the executed sequence-128 long run
and the bounded sequence-1024 rank-8/rank-16 probes. Achieving a defensible 99%
semantic result is substantially harder and currently unproven: the available
slice supplies one rather than 563 independent leakage groups. The next
estimate-changing evidence is independently sourced, oracle-sealed data plus
paired B/D results; no loss curve is promoted into an accuracy forecast.

## 4. Immediate execution state

The active board is
[`orchestra/runs/2026-08-20-accuracy-99-pilot/BLACKBOARD.md`](../orchestra/runs/2026-08-20-accuracy-99-pilot/BLACKBOARD.md).
It records Kimi K3, internal delegated lanes, exact stop rules and every gate
that must close before W5 training can produce product evidence. The run also
records the Git-anchor remediation and K3's resumed parent-lineage correction.
The current wave is complete with W5 blocked; no semantic training result or
99% accuracy claim has been produced.
