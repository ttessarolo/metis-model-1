# Accuracy uplift: catalog-domain maintenance contract

Status: **PIN REFRESH ACTIVE — executable implementation pinned; Model 1 refresh pending**.

This document narrows the current accuracy wave without stopping the work that
does not depend on the incoming catalog grammar.  It is forward-looking: the
historical 0.43 benchmark, W1 sidecars, and the delivered B12-v4 evidence remain
immutable.

## 1. Boundary being changed

Catalog field definitions continue to carry the structural schema: field name,
type, and similarity profiles.  Domain values are retrieval data, not weight
truth.  Metis revision `1f7eaae9d803edc90f51ff492ea443f18570015e`
(tree `346ddce27270287c8a3781bced77bf75c5318c11`) pins the lexical surface in
`docs/design/catalog-values/spec.md`: bounded external domains use
`keyword enum(N)`, open live-index domains use `keyword open`, and tiny stable
domains retain `keyword values [ ... ]`.  Tenant thresholds are
`settings/catalog { inline-max, enum-max }`; their system defaults are compiler
settings, not model constants.  External storage is one
`catalogs/<catalog>.values.metis` value-set per catalog, with per-field
`reflected` or `editorial` ownership and per-field retrieval.

Metis revision `5e112f9148f40e7e792052e896c5a9efe8eaf0a2` (tree
`41c7a2b6890fa42d8123bd93f6560d0b9bfae8af`) is the executable implementation
pin. It is published on `origin/main` and binds grammar, validator, compiler/IR,
resolver, synchronization, retrieval CLI, semantic tests, settings, package
lock and Node runtime in `manifests/catalog-maintenance-pin-v1.json`. Model 1
still does not materialize catalog-domain truth until its own retrieval receipt
and affected semantic-oracle refresh are complete.

Consequences:

- the legacy inline materialized-value surface is forbidden as canonical truth
  in new prompts, datasets, oracles, and final-test tasks;
- tenant thresholds are looked up from tenant settings and are never embedded
  as numeric model constants;
- tenant-specific domain values remain in per-field retrieval or the live
  index; they never become supervised weight truth;
- the adapter-off B12-v4 behavior baseline is not invalidated by the planning
  note because no fine-tuned adapter or catalog-value dataset was produced.

## 2. Work partition while Model 1 refresh is pending

The wave remains active.  The following work may proceed now:

- design and freeze non-catalog D18 tasks;
- design non-catalog T30 tasks and their oracle truth;
- implement the F-6 structural claim evaluator and non-catalog F-6 fixtures;
- design the missing F-4 wire/golden and F-5 migration-pair authority seams;
- implement and verify the Model 1 adapter for the pinned offline
  `catalog:describe` / `catalog:values` contract.

The following work waits for Model 1 retrieval and oracle refresh:

- catalog-domain prompt or expected-output truth;
- catalog-domain oracle truth;
- materialization of catalog-domain D18, train, dev, or T30 slots;
- any catalog truth derived from the specification without executable
  grammar/retrieval/oracle evidence.

No model output is observed for this accuracy wave until the complete T30,
including the reserved catalog-domain slots, is sealed before output.  This is
a contamination guard, not a stop to task and oracle construction.

## 3. Frozen wave arithmetic

| Split | Total | F-1 | F-2 | F-3 | F-4 | F-5 | F-6 |
|---|---:|---:|---:|---:|---:|---:|---:|
| Diagnostic D18 | 18 | 3 | 3 | 3 | 3 | 3 | 3 |
| Train, conditional | 64 | 10 | 12 | 12 | 12 | 10 | 8 |
| Dev, conditional | 16 | 3 | 3 | 3 | 3 | 2 | 2 |
| Final test T30 | 30 | 5 | 5 | 5 | 5 | 5 | 5 |

D18 may guide only failure categories.  No D18 task, parent, template,
identifier, AST, IR, or expected output may be derived into train, dev, or T30.
Train uses at least 16 semantic roots and at most four derivations per root.
Train, dev, and T30 roots are mutually disjoint.  T30 is never used for
checkpoint selection.

The catalog-domain construct reserves at least one F-1 and one F-6 slot in both
D18 and T30.  These slots remain unmaterialized until the implementation pin
and refresh gates are complete.  Coverage may expand after the refresh; it may
not be removed.

The read-only tenant checkout is one construct-census lineage.  It contributes
zero examples and zero independent accuracy denominator units.

## 4. Upstream pin transition

The lexical surface remains pinned by the exact specification blob at revision
`1f7eaae9...`. The implementation pin has advanced to `5e112f91...` only after
the later revision and tree bound all of the following executable evidence:

1. grammar;
2. validator behavior;
3. compiler behavior;
4. normalized IR contract;
5. per-field retrieval contract;
6. semantic oracle;
7. tenant threshold setting keys.

L0 verified the live remote ref, all `18/18` Git blobs, exact Node 22 and
node_modules identities, and `5/5` typecheck/catalog probes from a Git archive
under deny-write/deny-network sandboxing. This is a
`verified_local_cooperative` result: it binds exact Git objects and bounded
probes on the cooperative local host, but is not resistant to a concurrent
hostile process running as the same user and is not a general untrusted-code
sandbox. The next state transition is Model 1 retrieval refresh, followed by
affected oracle truth, reserved-task materialization and the complete
maintenance seal. Old benchmark and delivery evidence remain historical and
unchanged.

## 5. Model decision path

The ratified O-010 order is mandatory:

1. pin and diff the upstream revision;
2. refresh retrieval;
3. regenerate affected oracles;
4. seal the maintenance benchmark before model outputs;
5. run the Qwen3.8 base plus refreshed retrieval baseline; B12-v4 is historical
   adapter-off evidence, not a fine-tuned adapter;
6. return `NO_INITIAL_TRAIN` from D18 when at least 17/18 tasks are semantically
   correct, every family reaches 2/3, and critical, invented-symbol and recurring
   failure counts are all zero;
7. consider one bounded initial micro-QLoRA only after at least three correctable
   semantic failures across at least two independent roots, with dev-only
   checkpoint selection and no T30 feedback.

All D18 and T30 tasks, their truth, oracle/retrieval receipts, provenance and
genealogy must exist and hash-match a sealed roster before any model output is
observed. Counters and status flags alone never constitute a seal. T30 is run
once only as final local confirmation: at least 29/30 overall and 4/5 per family,
with zero vetoes, may support `MODEL1_USABLE_LOCAL`; its outcomes cannot reopen
training or checkpoint selection. These are observed-local denominators, not a
population Accuracy-99 claim.

A full successor is considered only if the normalized AST/IR or verified
semantic contract changes, or if refreshed retrieval plus a compatible bounded
delta still fails the semantic or replay gates.

## 6. Current non-claims

This planning contract records an executable upstream implementation pin. It is
not yet a Model 1 retrieval/oracle refresh, dataset authorization, model
evaluation, training authorization, accuracy claim, or promotion verdict.
