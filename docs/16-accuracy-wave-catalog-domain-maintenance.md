# Accuracy uplift: catalog-domain maintenance contract

Status: **RETRIEVAL + ORACLE REFRESH COMPLETE — benchmark construction active**.

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
pin. It is published in the ancestry of `origin/main` and binds grammar, validator, compiler/IR,
resolver, synchronization, retrieval CLI, semantic tests, settings, package
lock and Node runtime in `manifests/catalog-maintenance-pin-v1.json`. Model 1
materializes catalog-domain truth only from the pinned public-synthetic
retrieval receipt and affected semantic-oracle goldens described below.

Consequences:

- the legacy inline materialized-value surface is forbidden as canonical truth
  in new prompts, datasets, oracles, and final-test tasks;
- tenant thresholds are looked up from tenant settings and are never embedded
  as numeric model constants;
- tenant-specific domain values remain in per-field retrieval or the live
  index; they never become supervised weight truth;
- the adapter-off B12-v4 behavior baseline is not invalidated by the planning
  note because no fine-tuned adapter or catalog-value dataset was produced.

## 2. Work partition after the Model 1 refresh

The broad D18/T30 accuracy wave is deliberately deferred. Its six-family
rosters, train/dev construction, and final-test materialization remain a
nonblocking accuracy backlog; they are not required to close this grammar
maintenance change and no model output is authorized for them.

The following work is postponed to a separately authorized broad-accuracy
wave and is not on the current critical path:

- design and freeze non-catalog D18 tasks;
- design non-catalog T30 tasks and their oracle truth;
- implement the F-6 structural claim evaluator and non-catalog F-6 fixtures;
- design the missing F-4 wire/golden and F-5 migration-pair authority seams;
- implement and verify the Model 1 adapter for the pinned offline
  `catalog:describe` / `catalog:values` contract.

The only active work is now replacement of the probe seal for the pinned
public-synthetic lineage:

- catalog-domain prompt or expected-output truth;
- catalog-domain oracle truth;
- a replacement Git pre-output seal for the separate eight-case probe.

Catalog truth derived from prose alone remains forbidden. Tenant payloads and
live-index values remain outside the dataset and outside this authorization.

The eight-case probe is non-statistical and non-promotional. Its result is a
maintenance diagnostic only: `8/8` semantic passes support `NO_RETRAIN` for
this grammar change, while failures identify repair work and never
auto-authorize training. The first freeze was revoked after the worker launcher
resolved away its virtualenv and stopped before model load. The replacement
seal must bind the virtualenv launcher, target, exact Python/MLX/MLX-VLM
versions and the sole fixed ignored run directory before any retry. The broad
D18/T30 wave remains unmaterialized and output-forbidden.

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

L0 verified that the live remote ref contains the exact pin, all `18/18` Git blobs, exact Node 22 and
node_modules identities, and `5/5` typecheck/catalog probes from a Git archive
under deny-write/deny-network sandboxing. This is a
`verified_local_cooperative` result: it binds exact Git objects and bounded
probes on the cooperative local host, but is not resistant to a concurrent
hostile process running as the same user and is not a general untrusted-code
sandbox.

The public-synthetic Model 1 refresh then executed `8/8` distinct retrieval
queries from the exact Git archive under the same sandbox. Its value-redacted
goldens cover describe, inline, list, editorial enum, reflected nested enum,
unsynchronized enum, open and none. The fixed fixture manifest is
`manifests/catalog-retrieval-public-synthetic-v1.json`; the observed receipt is
`manifests/catalog-retrieval-execution-v1.json`. Both validate against pinned
raw digests and exact output summaries/hashes. This is sufficient to open the
separate probe specification for this synthetic lineage; it is not tenant or
production authority. The prior run stopped at Python import before model
load, emitted no inference output and invalidated its freeze. The next state
transition is a replacement Git pre-output seal binding the cured runtime and
the single fixed evaluation directory. D18/T30 construction remains deferred
and old benchmark and delivery evidence remain historical and unchanged.

## 5. Model decision path

The ratified O-010 order is mandatory:

1. pin and diff the upstream revision;
2. refresh retrieval;
3. regenerate affected oracles;
4. seal the eight-case maintenance probe before its model outputs;
5. run the Qwen3.8 base plus refreshed retrieval baseline only for that sealed
   probe; B12-v4 is historical adapter-off evidence, not a fine-tuned adapter;
6. return `NO_RETRAIN` from the probe only when all 8/8 cases are semantically
   correct and critical, invented-value, legacy-inline, and retrieval-error
   counts are all zero;
7. treat any probe failure as diagnostic evidence only. It does not authorize
   a dataset, a checkpoint, a QLoRA run, or promotion. A future training wave
   still requires its own explicit authorization and the preregistered
   three-failures/two-roots condition.

The broad D18/T30 tasks, truth, oracle/retrieval receipts, provenance and
genealogy remain unmaterialized and cannot produce model output in this
maintenance wave. Counters and status flags alone never constitute a seal.
The probe's 8/8 result is not an independent accuracy denominator and cannot
support `MODEL1_USABLE_LOCAL` or any population Accuracy-99 claim.

A full successor is considered only if the normalized AST/IR or verified
semantic contract changes, or if refreshed retrieval plus a compatible bounded
delta still fails the semantic or replay gates.

## 6. Current non-claims

This planning contract records an executable upstream implementation pin plus
a locally replayed, value-redacted public-synthetic retrieval/oracle refresh.
The separate probe is not a tenant dataset and has no statistical or
promotional authority. Its replacement freeze is pending and model outputs
remain zero. The broad D18/T30 benchmark remains unmaterialized. This is not
tenant dataset authority, training authorization, an accuracy claim, external
execution attestation, or a promotion verdict.
