# Catalog Semantics planning blackboard

## Objective

Surgically reconcile the Metis Brain/VSIX plan and the active grammar board so
that tenant-owned semantic grounding has one implementable contract, without
touching the grammar code already owned by the Metis team.

## Scope and authorization

- FACT — Model 1 planning baseline is clean
  `main@bd0be01f7def692a0d1f8127c98167ef500dac56`, aligned with origin/main.
- FACT — Metis operational snapshot for this reconciliation is
  `main@96fcaec4d2038fbf939bf548ac2baeefc2920287`, ahead one commit of
  `origin/main@856950001f112c8f5b6e677f2489ff6f1d8a725e`, with the grammar team's
  declared dirty set still in progress.
- FACT — The user authorized updating the tracked plan and writing the required
  delta directly on the active grammar and Model 1 boards.
- STOP — This reconciliation changes documentation/boards only. It does not
  modify the grammar/tooling files already owned by the separate active lane,
  start training, download a model, mutate tenant data, commit or push.
- STOP — Existing Metis `tmp/` and VSIX checksum artifacts remain untouched.
- STOP — Credentials, `.env`, live payloads and user records remain forbidden.

## Evidence

- FACT — Current `catalog:describe` exposes technical field/domain structure and
  `catalog:values` exposes canonical literals, but neither exposes structured
  labels, descriptions, aliases or predicate meaning.
- FACT — `///` comments are hidden tokens and cannot attach semantic identity to
  the former bare STRING value literals; the in-comment mini-schema is not a
  viable primary contract.
- FACT — The tracked demo fixture contains eight catalogs: `video`, `users`,
  `user_session`, `user_clusters`, `unified_clusters`, `link`, `trending` and
  `smart_index`. The canonical users catalog is `@users`; its backing index is
  named `utenti`.
- FACT — `video.metis` is explicitly a partial demonstration of the larger real
  catalog, so a definitive enrichment wave requires a fresh authorized census.

## Decisions

- DECISION — Catalog and field descriptions live in the authoritative catalog
  `.metis` file; finite value descriptions live with the associated inline,
  list or external value-set literal.
- DECISION — No semantic sidecar is a primary source. A derived compact index is
  allowed only when deterministic and rebuildable from the `.metis` sources.
- DECISION — **SUPERSEDES the former `/// @semantic` decision:** semantics are
  first-class optional grammar attributes. Catalog receives `label|means|aka`;
  Field and ValueItem receive `means|aka`; ListEntry keeps `.str` and receives
  `means|aka` additively.
- DECISION — Review state is derived once: no `means` → `unannotated`;
  `means draft` → `draft`; `means` without draft → `reviewed`. Validator rejects
  `aka` without `means` and Catalog `label` without `means`.
- DECISION — A frontier model bootstraps `means draft` from key, type, catalog,
  finite values, comments and validated usages where the R5 ambiguity test says
  description adds information. A separate frontier review identifies
  tautologies and collisions; the newsroom promotes by removing `draft`.
- DECISION — Giulia can edit the same source descriptions at any time. Review
  state and source evidence remain explicit; no opaque numeric confidence is an
  authority.
- DECISION — `@video` and `@users` are the first enrichment priority. The
  closure gate inventories every tracked node but requires descriptions only
  where R5 or the frozen benchmark needs them; filler aliases/descriptions are
  prohibited.
- DECISION — Truly open domains use the engine-owned, tenant-aware,
  fail-closed `exact_on_demand` policy, not executable instructions in `means`
  and not a fictional pre-description of every live value.
- DECISION — Inline/value-set sync is a structural merge: exact-literal
  survivors are byte-identical, new values are `unannotated`, removals are
  reported, and add+remove is not inferred as rename without an authoritative
  explicit map.
- DECISION — The tenant remains automatic from the workspace. Brain asks which
  `@catalog` to use only when multiple explicit compatible candidates remain;
  one candidate is auto-selected, zero candidates yield unsupported metadata.

## Canonical gates in the reconciled plan

- `FULL_CORPUS_GRAMMAR_COMPAT`
- `CATALOG_SEMANTICS_ARTIFACT_INVARIANT`
- `SEMANTIC_CATALOG_CENSUS_VALID`
- `SEMANTIC_VALUE_COVERAGE_VALID`
- `SEMANTIC_DESCRIPTION_REVIEW_VALID`
- `REFLECTED_SEMANTICS_PRESERVED`
- `OPEN_LOOKUP_POLICY_VALID`
- `SEMANTIC_CONTRACT_FRESH`
- `SEMANTIC_GROUNDING_SAFE`
- `CATALOG_AMBIGUITY_SAFE`
- `EDITORIAL_TRACEABILITY_VALID`

The former standalone `SEMANTIC_IN_SOURCE_VALID` and
`SEMANTIC_ANNOTATION_PARSE_VALID` gates are superseded by the grammar plus the
validator; they must not remain as a second annotation contract.

## Open items

- OPEN — The grammar team must close Catalog `label`, ListEntry semantics,
  validator rules, structural sync, expanded R8 and full-corpus compatibility
  before claiming `SEMANTIC_GRAMMAR_SURFACE_FROZEN`.
- OPEN — Re-census the complete authorized tenant catalogs before frontier
  enrichment; the tracked `video` draft is not a complete production roster.
- OPEN — Brain and VSIX remain STANDBY until the grammar commit is promoted,
  owners/write sets are disjoint and the requested lane receives explicit GO.

## Review evidence

- DONE — Catalog roster audit: `in=8 out=8 distinct=8 gaps=0`; L0 independently
  reran the tracked declaration census and confirmed `@users` is distinct from
  its backing index label `utenti`.
- DONE — Native-source feasibility review: `in=4 out=4 distinct=4 gaps=0` for
  in-source placement, schema-1 compatibility, lazy retrieval and catalog-only
  ambiguity prompts. Two review-state/gate inconsistencies were corrected.
- DONE — Independent final plan review closed its original `P1=3 P2=2` roster
  after the union, stale clarification, `needs-review`, phase ordering,
  semantic-review and replay contracts were corrected. Final verdict `ACCEPT`.
- FACT — Document-only checks found balanced fenced blocks and no trailing
  whitespace. No product build or implementation gate is claimed by this plan.
- FACT — Literal `make check` was rerun after the surgical reconciliation.
  Foundation reached `passes=68 errors=1 files=410` and stopped on the
  pre-existing pinned-Node verification failure for the historical T30-v3 live
  semantic replay; no later check is represented as run or green.
- DONE — Surgical contract review: `in=3 out=3 distinct=3 gaps=0` delegated
  reviews covered plan consistency, Brain/VSIX protocol/apply safety and grammar
  board handoff. L0 reconciled the outputs and retained the single canonical
  wire state `unannotated|draft|reviewed`.
- FIX — The tracked Metis plan now records Catalog label, ListEntry semantics,
  selective R5 coverage, structural sync, full-corpus/R8 gates, strong request
  idempotency, semantic freshness, opaque proposal/apply references, native
  target preflight and CAS-protected rollback/undo.
- FIX — The active Metis grammar board now contains the exact G1/G2/G3 addendum
  and STOP conditions. No grammar/tooling source file was modified by L0.
- DONE — Final independent diff review: `in=3 out=3 distinct=3 gaps=0`, with
  `P1=0`. Plan/state review, Brain protocol/apply review and grammar-board
  handoff each returned `ACCEPT` after their original findings were closed.
- FACT — Reviewed document hashes at closure:
  `piano-metis-brain-vscode-chat.md=6f0e1279fdb12f5d19bc6ca652a7080e790fd41735e36f434674532a3d545819`;
  `catalog-semantics-grammar.md=92c027ecd807731d3ff18770741e7699b232b1ebf434166c8838f80c06308f40`.

## Terminal planning verdict

`CATALOG_SEMANTICS_PLAN_SURGICALLY_RECONCILED`

This verdict certifies the plan and board reconciliation only. It does not
claim that the grammar addendum, sync, annotations, retrieval schema 2,
semantic resolution, Model 1 inference or VSIX integration are implemented.

## `@video` semantic-grounding execution-plan addendum — 2026-08-27

- FACT — The confidential editorial-source roster was verified locally;
  identifiers, filenames, format, counts and hashes remain outside Git and are
  not cited by official documentation. The preliminary non-reserved catalog
  snapshot is planning evidence only, not a claim of live completeness.
- FACT — The observed grammar dirty set contains the first-class semantic
  surface, validator, formatter and extended R8 work, but G2 structural sync,
  G3 full-corpus/collision gate, retrieval schema 2 and the terminal
  `SEMANTIC_GRAMMAR_SURFACE_FROZEN` verdict are still absent.
- DECISION — P0-P3, P4A and P5 may start immediately on disjoint Model 1
  surfaces: source freeze, editorial ontology, constraint oracle, local census,
  schemas/fakes, security tests, preliminary crosswalk and benchmark
  preregistration.
- STOP — Canonical `.metis` annotation, annotated sync, P4B VSIX integration,
  definitive live census pin, schema-2 retrieval, Brain grounding and final
  paired evaluation wait for the promoted clean grammar SHA and their named
  gates. No training is authorized by the plan.
- FIX — Added `docs/24-video-catalog-semantic-grounding-wave.md` and linked it
  from `docs/README.md`. The plan specifies 15 execution phases, ten schemas,
  confidential-source/receipt separation, PIT-atomic read-only census, signed role
  attestation, field allowlists, frontier egress denial, reviewed constraint
  grounding, 64+32 benchmark design, candidate threshold ratification,
  CAS rollback, retention and a command/artifact/gate matrix.
- FACT — Post-plan `make check` reached `passes=68 errors=1 files=411` and
  stopped on the pre-existing pinned-Node verification failure for historical
  T30-v3. This does not block P0-P5 preparation but remains a hard final DoD
  blocker until `errors=0` and exit code zero.
- DONE — Independent final plan review:
  `in=3 out=3 distinct=3 gaps=0 P0=0 P1=0`. Grammar readiness, Model 1 plan
  integration and security/eval reviewers each returned `ACCEPT`; L0 closed
  the intermediate findings on atomicity, role authentication, egress, oracle
  authority, benchmark ratification and gate ownership.
- FACT — Document checks report `fences=38`, `headings=101 unique=101`,
  `trailing=0`; `git diff --check` is clean. Final plan SHA-256 is
  `eecc90a15e62ded1c2d761df1273e557197811296443b7ef68db0320b571e607`.

## Terminal `@video` planning verdict

`VIDEO_CATALOG_SEMANTIC_GROUNDING_PLAN_READY`

This verdict certifies the executable plan and its start/wait boundary. It does
not claim that any `PLANNED` entrypoint, live census, catalog annotation,
retrieval integration, evaluation or model-weight decision has been executed.
