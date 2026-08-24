# L69 — W1/W2 evidence package and F-4/F-5/F-6 readiness

## Status

EVIDENCE PACKAGE ACCEPTED — UNSEALED. This bounded wave after L68 Phase A's
payload-free acceptance is complete. It does not claim W1/W2 sealed,
production execution, semantic accuracy, or a completed Model 1. Kimi returned
`ACCEPT_PACKAGE_DESIGN`; Qwen established read-only F-4/F-5/F-6 facts but
exhausted its provider quota before a final verdict, so no Qwen acceptance
credit is claimed. L0 and an internal frontier-led audit replayed the complete
sidecars and gates independently.

## Grounded current state

- tasks: `30/30`, six families, five allocated tasks per family;
- sources/assets: `201/201`, distinct paths and blob OIDs, `gaps=0`;
- leakage: `1` correlated whole-tenant group, below the required `563`;
- rights/legal: `0/201` reviewed;
- task-specific oracle execution: `0/30`;
- F-4/F-5/F-6: `0/15` tasks with executed evidence and `0/75` oracle cells
  executed;
- protected role receipts: future target `25`, not evidence;
- L68: `BROKER_DESIGN_ACCEPTED_PAYLOAD_FREE`, with no production or training
  credit.

The target `25` means F-4 `10` (`observed` plus `proposed` for five tasks), F-5
`10` (`legacy` plus `canonical` for five tasks) and F-6 `5` (`explained source`
for five tasks). It must never be reported as current coverage.

## Work packages and writer roster

The tracked package has two documents and six schema/manifest sidecar contracts
created in this explicitly opened local writer wave:

1. `docs/14-w1-w2-evidence-package.md` — package contract and gate (this lane);
2. this brief — mandate and acceptance record (this lane);
3. W1 task-blocker sidecar — one record for each of 30 tasks;
4. W2 rights/provenance sidecar — one record for each of 201 assets;
5. W1 oracle roster — 30 tasks and 160 explicitly unexecuted cells;
6. W1 leakage assignment — one correlated group and no population claim;
7. W1 held-out map — six allocated families bound to the future 600-task
   target;
8. W1 benchmark seal — deterministic references and an obligatory
   `unsealed_evidence_only` verdict.

The sidecar writer roster is disjoint by record type: one writer may enumerate
the 30 task records, a second may enumerate the 201 asset records, and a
frontier reviewer validates both. No writer may modify the frozen manifests,
broker contract, Metis checkout, model payloads or training state.

Every returned roster must state `in=N out=N distinct=N gaps=0`; the frontier
must recompute at least one count and inspect the final bytes before acceptance.

## Sidecar minimum fields

The task sidecar is keyed by `task_id` and carries family/mode/source identity,
dependency and leakage status, every applicable oracle cell, runtime/ambient
time/mutation/golden-IR/migration/human dependencies, receipt authority and a
derived `seal_eligible` value. The rights sidecar is keyed by path and blob OID
and carries provenance, sensitivity, rights basis, permitted scope,
external-distribution decision, reviewer evidence, and a complete-roster hash.

`not_run`, `not_reviewed`, and `computed_not_sealed` are explicit blocking
states. They are never coerced to success by omission or by a local hash.

## Dependency-ordered path

1. Generate the two sidecars locally from immutable inputs, then validate them
   in a separate read-only pass.
2. Request and receive a distinct Phase-B privileged authorization; prove the
   protected broker, runner, key isolation, CAS anchor and public-synthetic
   execution boundary.
3. Request and receive a distinct data/human-review authorization; adjudicate
   rights and create genuinely independent benchmark candidates.
4. Seal W1/W2 only after dependency closure, rights decisions, oracle evidence,
   leakage groups and hashes pass their fail-closed gates.
5. Implement and audit typed F-4/F-5/F-6 oracles and collect the target `25`
   protected receipts.
6. Freeze W3, establish baseline A/B and ratify O-003.
7. Request a distinct training authorization, then run only the authorized
   bounded QLoRA experiment and its regression gates.

The three authorizations are independent: privileged OS work; data and
human/legal review; training. None is implied by model availability, Orchestra
capacity, static tests, or L68 Phase A.

## Orchestra protocol

L0 remains the sole frontier coordinator for architecture, semantic truth,
leakage, security gates and promotion. Kimi and Qwen act as frontier masters
for disjoint teams, delegate mechanical sub-rosters, validate the returned
work, and report only checked arithmetic to the shared activity board. L0 then
reruns the relevant commands, recomputes one claim per team and accepts or
rejects the handoff. A delegated lane cannot promote, authorize privilege,
download payloads, start training, publish or change another repository.

## Stop conditions

Stop immediately on any Metis write, secret/live-data access, external upload,
model download, training start, unresolved rights record, unexecuted required
oracle, leakage-group inflation, self-certifying target, synthetic receipt used
as production evidence, protected-authority mismatch, or roster/hash drift.

## Acceptance commands

The evidence-package handoff is checked with:

```sh
uv run pytest tests/test_w1_blockers.py tests/test_w2_rights.py tests/test_w1_seal.py
make validate
make lint
make format-check
git diff --check
```

The accepted replay produced sidecar tests `31/31`, foundation `36` passes and
`0` errors, task roster `in=30 out=30 distinct=30 gaps=0`, asset roster
`in=201 out=201 distinct=201 gaps=0`, and all six semantic validators green.
No command may label the package sealed while the current status remains one
group, `0/201` legal review, `0/160` oracle cells and `0/30` task-specific
oracle executions.

## Maximum honest outcome

This wave produced a reproducible, semantically validated evidence package and
an explicit red seal. It did not close the project, reopen production W3, prove
semantic accuracy, or authorize training. Those claims require the
dependency-ordered gates above.
