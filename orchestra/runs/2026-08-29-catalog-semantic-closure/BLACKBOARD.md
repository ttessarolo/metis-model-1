# Catalog semantic closure blackboard

## Objective

Close the semantic queue on the canonical `play-demo` tenant for `users`,
`video_pg`, `smart_index` and `user_session`, then prove the global five-catalog
retrieval surface without changing model weights or the Metis grammar.

## Preflight

- FACT — Model 1 baseline and writable repository:
  `main@453a99700bfdc4a498a5fa0e6428738290e7d3d6`.
- FACT — Canonical tenant baseline and authorized catalog target:
  `play-demo/main@f18819fc5fddd3a92dec34ab9ae928db51b621ce`.
- FACT — Metis grammar/compiler checkout is read-only. The pinned semantic
  grammar remains `0b41a25d4d5eeac88975e43e18e4bc3123d51667`.
- DECISION — Writable tenant paths are only `catalogs/users.metis`,
  `catalogs/user_session.metis`, `catalogs/smart_index.metis` and
  `catalogs/video_pg.metis`. Model 1 writes are limited to this run, the catalog
  completion plan and bounded tests/code only if the current resolver contract
  needs them.
- STOP — Credentials, `.env`, Keychain, live services, raw tenant payloads,
  reserved sources, model payloads, training, downloads and every other
  repository are excluded.
- DECISION — L0 frontier owns meanings, aliases, privacy, cross-catalog
  ambiguity, integration and promotion. Delegates perform read-only mechanical
  censuses and cannot edit, commit, push or promote.

## Denominator

- FACT — The queue has `54` top-level fields: `users=9`, `video_pg=40`,
  `smart_index=3`, `user_session=2`.
- FACT — `users` also contains `10` annotatable object subfields. The semantic
  gate therefore covers `64` Field nodes, not only the top-level roster.
- DECISION — Completion requires four reviewed Catalog nodes, all 64 Field
  nodes disposed, explicit domain policy, zero unsafe alias collisions, real
  schema-2 retrieval probes and byte-identical runtime/endpoint IR.

## Active status

`SEMANTIC_CATALOG_READY`

## Evidence wire

- DONE — L71 closed the read-only `users`/`user_session` census:
  `users top=9 nested=10 out=19 distinct=19 gaps=0`; `user_session in=2 out=2
  distinct=2 gaps=0`. Identifiers and fingerprint bags are privacy-sensitive
  technical features, not value vocabularies to enumerate or suggest.
- DONE — L72 closed the mirror census: `video_pg in=40 out=40 distinct=40
  gaps=0`; every field has an exact same-name `@video` counterpart. The only
  declared cardinality divergence is `genere_mcm` (`video` scalar,
  `video_pg` multi); PostgreSQL driver checks are `19/19 PASS`.
- DONE — L73 closed the global read-only census: five catalogs, `167`
  top-level fields, `177` including the ten object subfields, `41` shared-name
  groups. `fingerprint`, `title` and `user_id` require catalog-scoped
  resolution; the forty `video`/`video_pg` pairs are intentional mirror
  ambiguity, not global field identity.
- FIX — The canonical tenant candidate now carries reviewed `label`/`means`/
  `aka` for the four queued Catalog nodes and every queued Field node, including
  all ten `users` subfields. Privacy prose explicitly forbids enumerating or
  suggesting user/session identifiers and fingerprint tokens.
- FACT — Live schema-2 replay on the candidate reports `catalogs=5 reviewed=5`,
  `fields in=177 out=177 distinct=177 gaps=0`, `reviewed=177`, `draft=0`,
  `unannotated=0`. Domain disposition is `inline=26 enum=23 open=41 none=87`.
- FACT — `@video` finite evidence remains `49` fields / `1792` ValueItem with
  `reviewed=1782 draft=10 unannotated=0`; no literal or value-set was added to
  another catalog and no value entered model weights.
- DECISION — `video_pg` does not copy any of the 1,792 `@video` values. Its
  twelve genuinely open fields say `open`; ten scalar/range fields remain
  `none`; the eighteen finite same-name domains are supplied by an explicit
  fail-closed semantic-to-execution projection from canonical `@video`. The
  projection must prove the complete 40-field roster, types, modifiers, domain
  sizes and the sole `genere_mcm` cardinality exception before a value can be
  grounded for PostgreSQL execution.
- FACT — Candidate parser/validator reports `29` documents and zero errors.
  Against tenant baseline `f18819f`, field roster is `177/177`, technical
  type/modifier drift is zero, runtime context is byte-identical
  (`sha256:4b238459...`), and all ten endpoint IR artifacts are byte-identical
  (`sha256:340315a0...`).
- FACT — Current upstream focused gates are green: TypeScript typecheck, R8
  semantic/runtime invariant, semantic surface, catalog describe/values,
  semantic schema 2, sync rewrite/merge, object fields, KV, PostgreSQL driver
  `19/19`, and formatter idempotence.
- DONE — Global alias audit is closed: within-catalog Field `aka` collisions
  are `0`; the `25` cross-catalog shared alias surfaces are all intentional
  `video`/`video_pg` mirror pairs. The `41` shared technical leaf names remain
  catalog-scoped; `fingerprint`, `title` and `user_id` never select a catalog
  globally.
- FIX — The first live execution replay exposed a fail-open not covered by the
  delegated synthetic test: a draft ValueItem still resolved by exact literal.
  L0 changed the resolver so draft/unannotated values remain in the immutable
  audit roster but cannot ground, and added a negative downstream test.
- FIX — L73-R found that the first execution receipt was not accepted by the
  V2 projection boundary and that its self-hash alone did not authenticate
  external inputs. L0 now emits both the standard V2 receipt and a distinct
  execution-policy receipt; promotion requires an independent binding check
  over source, execution describe, refs, modifier exception, domain
  dispositions and result. A rehashed-tamper test and a nested-field roster
  test are green.
- DONE — Live `video -> video_pg` replay is closed:
  `source_fields=113 execution_fields in=40 out=40 distinct=40 gaps=0`,
  `finite_fields=18`, `values in=521 out=521 reviewed=514 draft=7 gaps=0`, one
  modifier exception and 18 explicit finite-to-none dispositions. Projection
  SHA-256 is
  `adde34cb70dee35008604ca8733151a3a75488ae0407fe78e92ccd4931f9d622`.
- DONE — Live grounding proves `mood Romantico`, `tipologia Film` and
  `Italia 1 -> I1`; `title` yields retrieval-owned lazy lookup; draft code
  `FT` yields `unsupported`. The derived execution index is
  `in=562 out=562 distinct=562 gaps=0` (`40` fields, `521` values).
- FACT — Final actual-tenant invariant against `f18819f` is parser/validator
  clean on `29` documents; runtime context is byte-identical at
  `4b238459546f087a2a7aa365b9f12ab2fca48bc9931b872042da8487cfed5f8a`;
  endpoint IR roster is `10/10` with zero byte drift.
- DONE — Canonical tenant promotion is committed and pushed on
  `play-demo/main@6d6ce2cb00c941cb2700dccdd6c7f7a644dc55b8`; remote `main` resolves to
  the same commit and the checkout is clean.
- DECISION — The durable projection policy is pinned in
  `manifests/catalog-semantic-execution-play-demo-video-pg-v1.json`. It carries
  no catalog values and makes the 18 dispositions, sole modifier exception,
  expected denominators and draft quarantine reviewable.
- DONE — Semantic queue closure is exactly: catalogs
  `in=5 out=5 distinct=5 gaps=0`, fields
  `in=177 out=177 distinct=177 gaps=0`, all Catalog and Field nodes reviewed,
  no catalog value copied into model weights and no retraining authorized.
- DONE — Repository promotion gate `make check` completed with exit code zero:
  foundation `85` passes / `0` errors, pilot contracts valid, lint and format
  clean, full harness `2188 passed, 2 skipped`. The historical W5 readiness
  remains blocked by its pre-existing dataset/leakage/authority decisions and
  is not being relabeled as semantic catalog work.
- RISK — The tenant contains versioned demo persona identifiers while its
  documentation describes a stricter local-only boundary. No identifier is
  copied by this wave; classification/remediation is a separate tenant privacy
  decision and must not be hidden by semantic annotations.
