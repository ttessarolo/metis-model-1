# Accuracy uplift: catalog-domain maintenance contract

Status: **PIN REFRESH ACTIVE — lexical surface pinned; implementation pending**.

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

That revision is a documentation/specification pin, not yet an implementation
pin.  Grammar, validator, compiler, resolver, synchronization, retrieval CLI,
and semantic-oracle evidence remain pending.  Model 1 therefore records the
surface without materializing catalog-domain truth.

Consequences:

- the legacy inline materialized-value surface is forbidden as canonical truth
  in new prompts, datasets, oracles, and final-test tasks;
- tenant thresholds are looked up from tenant settings and are never embedded
  as numeric model constants;
- tenant-specific domain values remain in per-field retrieval or the live
  index; they never become supervised weight truth;
- the adapter-off B12-v4 behavior baseline is not invalidated by the planning
  note because no fine-tuned adapter or catalog-value dataset was produced.

## 2. Work partition while implementation is pending

The wave remains active.  The following work may proceed now:

- design and freeze non-catalog D18 tasks;
- design non-catalog T30 tasks and their oracle truth;
- implement the F-6 structural claim evaluator and non-catalog F-6 fixtures;
- design the missing F-4 wire/golden and F-5 migration-pair authority seams;
- monitor the upstream repository read-only for the implementation revision.

The following work waits for one verified implementation revision:

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

The lexical surface is pinned by the exact specification blob at revision
`1f7eaae9...`; this closes surface selection only.  The implementation state may
advance only when one later upstream Metis revision and tree bind all of the
following executable evidence:

1. grammar;
2. validator behavior;
3. compiler behavior;
4. normalized IR contract;
5. per-field retrieval contract;
6. semantic oracle;
7. tenant threshold setting keys.

After that implementation pin is observed, Model 1 updates its executable source
pin, refreshes retrieval, regenerates the affected oracle truth, materializes
the reserved tasks, and seals the complete maintenance benchmark.  Old
benchmark and delivery evidence remain historical and unchanged.

## 5. Model decision path

The ratified O-010 order is mandatory:

1. pin and diff the upstream revision;
2. refresh retrieval;
3. regenerate affected oracles;
4. seal the maintenance benchmark before model outputs;
5. run the existing adapter-off behavior baseline and any existing adapter that
   is actually present;
6. return `NO_RETRAIN` when semantic and critical gates remain green;
7. consider one bounded delta QLoRA only after at least three correctable
   semantic failures across at least two independent roots, with dev-only
   checkpoint selection and no T30 feedback.

A full successor is considered only if the normalized AST/IR or verified
semantic contract changes, or if refreshed retrieval plus a compatible bounded
delta still fails the semantic or replay gates.

## 6. Current non-claims

This planning contract records a lexical specification pin.  It is not an
executable upstream implementation pin, dataset authorization, model evaluation,
training authorization, accuracy claim, or promotion verdict.
