# L62 source-bundle revision repin

## Objective

Remove the last provenance ambiguity before real W3 capsule materialization.
The existing `project.revision` value
`4ec625fcec8a9c41423bc048688d17775e57353c` is the L23 handoff baseline, but
the production worker and accepted source boundary were frozen later in
`5a5d817bb3df817fbd5d47b7bc4edd4517f8d9b7`.

This wave is constants-only. It does not materialize any bundle or capsule,
execute the real runner, register a source authority, access the live Metis
checkout, build data, train, or claim accuracy.

Current project HEAD at wave open:
`291e338f59d52645ba09fa5fcbe86cdc0b42bc04`.

## Ratified semantics

1. `project.revision` and the qualification `project_revision` mean exactly the
   Git revision from which the source-bundle file roster is selected. For v2
   that revision is
   `5a5d817bb3df817fbd5d47b7bc4edd4517f8d9b7`.
2. The future source bundle must be a path-exact subset of `git archive` for
   that revision. Every source-bundle row remains independently bound by path,
   type, mode, size and SHA-256. The authority digest is supplied externally.
3. The bridge and qualifier are not identified by `project.revision`. Their
   executing bytes remain independently measured and hash-bound by the
   launcher/qualifier identity. The re-pin therefore points to a strict
   ancestor and creates no self-referential commit cycle.
4. The Kimi ratification report SHA-256
   `a810598d9b62143f6172a4faa58f91879d4ac19f097cc19255a6ce43356fb83a`
   and frozen candidate/registry hashes remain unchanged. They bind the three
   ratified semantic rows, not the later harness implementation commit.
5. The external authority instance remains outside Git. Only its schema and
   verifier are committed.

## Writable roster

One sequential writer only:

1. `runtime/w3_bridge_gate.py`
2. `runtime/w3_qualifier.py`
3. `schemas/w3-production-authority.schema.json`
4. `schemas/w3-qualification.schema.json`
5. `tests/test_w3_bridge_gate.py`
6. `tests/test_w3_qualifier.py`
7. `tests/test_contracts.py`

L0 alone may update this brief, the active blackboard and session ledger.

Off limits: `runtime/w3_production_worker.py`, `src/metis_model1/oracles.py`,
`src/metis_model1/contracts.py`, the two frozen candidate/registry manifests,
all source authority declarations, every artifact/model/data payload and the
Metis checkout.

## Required implementation

1. Add tests first that require the exact source revision in both manual
   authority validators, the production qualification report and both schemas.
   The former L23 baseline must be rejected after canonical re-hash.
2. Replace only the four executable/schema occurrences of the old revision:
   bridge constant, qualifier constant, production-authority schema const and
   qualification-report schema const. Historical brief references stay intact.
3. Recompute the qualifier SHA-256 after formatting and update the bridge pin.
   No other runtime or contract behavior may change.
4. Re-run the safe-only qualifier/bridge/contracts surface, the historical
   executable mutation matrix, schema validation, static gates and the
   repository-wide `make check` against a temporary pinned Metis checkout.
5. Freeze exact hashes and obtain a fresh independent frontier audit plus
   read-only Kimi and Qwen review before opening real materialization.

## STOP conditions

- Any source-bundle byte that cannot be reproduced from
  `5a5d817bb3df817fbd5d47b7bc4edd4517f8d9b7` stops the later materialization.
- Any edit outside the writable roster, semantic-manifest drift, authority
  registration, live Metis access/write, payload in Git or weakened non-claim
  stops this wave.
- A green schema-only or compile-only result is insufficient.
- Real source/dependency/capsule materialization and runner execution remain a
  separate explicitly opened wave after L62 acceptance.
