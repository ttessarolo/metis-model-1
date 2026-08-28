# `@video` semantic-fuel materialization blackboard

## Objective

Materialize the editorial knowledge required by Metis Brain to map natural
language to exact `@video` fields and literals: build the private ontology and
constraint ledger, reconcile them with the versioned catalog/value-set census,
produce a semantic-only candidate patch in an isolated `play-demo` worktree,
compile and verify it, and build the derived semantic index and review bundle.

## Baselines and write boundary

- FACT — Model 1 authority starts at
  `main@7676d1f23ca907f56a2f2ff825ddabb45186b289`, aligned with
  `origin/main` and clean.
- FACT — Metis grammar/retrieval authority remains
  `0b41a25d4d5eeac88975e43e18e4bc3123d51667`, retrieval schema 2.
- FACT — `play-demo` source starts at clean
  `main@f8cc3fd43efc8ea9661c6f051b31e6a1291da1b0`, aligned with
  `origin/main`.
- DECISION — Tenant edits are allowed only in the dedicated
  `codex/video-semantic-fuel` worktree. The source checkout and `main` remain
  untouched until a distinct promotion decision.
- FACT — The isolated worktree is `<ISOLATED_PLAY_DEMO_WORKTREE>`, branch
  `codex/video-semantic-fuel`, created from exact `origin/main@f8cc3fd43efc8ea9661c6f051b31e6a1291da1b0`.
- STOP — Reserved source materials and extracted text never enter Git, logs, prompts
  for delegates, documentation, commit messages or public receipts. Public
  evidence uses opaque source IDs and hashes only.
- STOP — Delegates may inspect only versioned, non-reserved repositories. L0
  alone owns reserved-source reading, semantic synthesis and leakage review.
- STOP — No agent reads Keychain, `.env`, credentials or raw/live ARES data.
  Live OpenSearch reconciliation requires a credential-free capability broker
  or a signed sanitized receipt; until then it remains explicitly `BLOCKED`,
  never simulated by the versioned census.
- STOP — No training, adapter mutation, model download, remote frontier egress,
  canonical tenant promotion or OpenSearch write is authorized by this wave.

## Seven-point execution contract

| Point | Deliverable | Exit gate | Status |
|---|---|---|---|
| 1 | private editorial ontology from the reserved source roster | complete disposition/provenance/constraint roster; gaps zero or explicit | done |
| 2 | exact versioned census plus credential-free live-receipt slot | fields/domains/values/usages denominators; live status never inferred | versioned snapshot done; live slot blocked |
| 3 | concept-to-field/value crosswalk | every in-scope concept terminally mapped, absent or unsupported | done |
| 4 | candidate semantic patch in isolated `play-demo` worktree | technical literals/types unchanged; semantic-only diff | done on isolated branch |
| 5 | parser/linker/validator/formatter/compiler/R8/retrieval verification | exact pinned commands green; schema 1 invariant | done on exact branch commit |
| 6 | frontier review bundle and scoped promotion | no automatic removal of `draft`; critical ambiguity explicit | done for isolated branch; canonical main remains separate |
| 7 | deterministic Brain semantic index and handoff receipt | reproducible revision; grounding examples resolve or clarify | done offline; model benchmark remains separate |

## Evidence wire

Use `FACT`, `FIX`, `DONE`, `RISK`, `OPEN`, `STOP` and `Q`. A `DONE` requires
paths or receipts plus exact `in/out/distinct/gaps` denominators. Compile-clean
never substitutes for semantic review. Private evidence is referenced only by
opaque identity and sanitized counts.

## Execution evidence

- DONE — Private artifact boundary is `VALID`: contained owner-only root,
  ignored sentinel, no tracked collision, no symlink and Git status unchanged.
- DONE — Reserved source acquisition and freeze are `VALID` with
  `private_roster_complete=true`, `gaps=0` and no raw payload in public output.
- DONE — Local sandboxed extraction is `VALID`: `sources in=3 out=3
  distinct=3 gaps=0`, `units in=148 out=148 gaps=0`, all units page-scoped;
  the public receipt contains no source name, locator or text.
- DONE — Grammar/retrieval authority is pinned by the existing successor
  `manifests/video-semantic-toolchain-pin-v1.json`: Metis revision
  `0b41a25d4d5eeac88975e43e18e4bc3123d51667`, tree
  `0c47611239d98020fc3a68d1efff2e213ed9df96`, retrieval schema 2,
  `evidence in=15 out=15 distinct=15 gaps=0` and
  `probes in=7 out=7 distinct=7 gaps=0`. Historical catalog-maintenance pins
  remain immutable; no duplicate pin authority is introduced.
- DONE — The versioned `play-demo.video` census is closed at
  `fields in=113 out=113 distinct=113 gaps=0`: 59 keyword, 4
  search-as-you-type, 12 text, 12 number, 20 date and 6 boolean fields. Domain
  material is `inline values in=66 out=66`, plus five reflected external
  value-sets with `values in=297 out=297 distinct=297 gaps=0`. At the frozen
  preimage, all 113 fields and all 363 versioned finite values were unannotated.
- RISK — The versioned catalog contains 98 fields with no explicit domain
  classification and nine multi-valued fields without a materialized domain.
  The ontology/crosswalk must distinguish open, intentionally unenumerated and
  unsupported; no model may infer live membership from this absence.
- OPEN — Live OpenSearch reconciliation remains unavailable under the
  credential-free project boundary. Point 2 can close only for the exact
  versioned snapshot; the live-receipt slot stays `BLOCKED_NOT_EXECUTED` until
  a capability broker or signed sanitized receipt is supplied.
- FIX — The executable preflight found no ontology author, semantic patch
  renderer/applier or crosswalk/constraint-bound index. This wave supplied the
  missing bounded tools and tests. The older exact-match resolver remains only
  an offline smoke gate and is not an accuracy claim.
- DONE — A dedicated local inference preflight proved numeric IPv4 loopback
  connectivity while external numeric TCP and DNS were both denied by the
  macOS policy. A separate Ollama service is bound only to
  `127.0.0.1:11435`, cloud is disabled, and the already-present local model is
  bound by digest; no model download occurred. This is authoring assistance,
  not semantic authority.
- DONE — Compiler preimage is frozen outside Git before any tenant edit:
  `artifacts/video-catalog-semantics-v1/work-items/compiler-preimage-20260828-v1`,
  `files in=24 out=24 distinct=24 gaps=0`, canonical relative content roster
  `sha256:d1932ff8acc4c90319c6ac734ff460ce73c9f3ae20986641687c29f4e06701a4`.
  The two tenant artifact-set identities are recorded inside that private
  build. Post-patch equality must be recomputed from relative paths.
- FIX — The task-created compiler-preimage subtree is now uniformly private:
  `items in=32 out=32 distinct=32 gaps=0`; directories are owner-only `0700`
  and files are owner-only `0600`. The private-boundary bootstrap was rerun
  after the correction and remains `VALID`.
- FACT — A one-unit schema-bound local inference smoke passed with the pinned
  already-installed model and produced one host-owned draft concept without
  persisting source text or model output in public evidence.
- STOP — The local-model full-roster authoring attempt was terminated after a
  bounded smoke because editorial authority belongs to L0 Frontier. No partial
  local-model ontology was published, merged or used in a mapping decision.
- DONE — L0 Frontier personally reviewed the complete frozen source roster and
  produced a terminal private disposition ledger: `units in=148 out=148
  distinct=148 gaps=0`. The validated ontology contains `concepts=64`; its
  private-runner result is `VALID`, `ontology_valid=true`, and exposes no raw
  payload.
- DONE — The L0-reviewed crosswalk is closed at `concepts in=64 out=64
  distinct=64 gaps=0`, with `mapped=39`, `terminal absent=25` and
  `critical_unresolved=0`. Absence is explicit: no concept was forced onto a
  similarly named legacy field.
- DONE — The reviewed constraint ledger contains `10` bounded rules. It keeps
  editorial cardinality separate from grammar and marks current singular-field
  mismatches as `clarify` or `unsupported`, never as silently applicable.
- DONE — The real versioned schema-2 capture was rerun from a clean temporary
  copy of the exact pinned Metis commit, because the shared Metis checkout is
  dirty with another team's work and remained untouched. The sandboxed run
  denied network and tenant writes and closed at `commands in=16 out=16
  distinct=16 gaps=0`, `catalogs=1 fields=113 finite_fields=15 values=363`.
- DONE — The projection-derived census is closed at `nodes in=477 out=477
  distinct=477 gaps=0`: `catalogs=1 fields=113 values=363`; all nodes were
  `unannotated` at the frozen preimage.
- DONE — L0 authored and independently re-reviewed `130` semantic candidates:
  `catalog=1 fields=49 values=80`, target membership `130/130`, aliases `1`
  with explicit user-query evidence, and zero query syntax, model directives,
  unsupported equivalences or target gaps. These remain candidate material
  until the semantic-only patch and compiler/R8 gates close.
- DONE — The exact candidate roster was rendered and applied fail-closed in the
  isolated tenant: `operations in=130 out=130 distinct=130 gaps=0`, touching
  only `catalogs/video.metis` and `catalogs/video.values.metis`. L0 promoted the
  exact reviewed postimage; direct schema-2 comparison found `reviewed=130`,
  `draft=0`, `unannotated=347`, missing/extra/mismatch `0`.
- DECISION — The user delegated the semantic verification of this wave to L0
  Frontier. That scoped authority closes the isolated-branch review; it does
  not authorize merge into tenant `main`, live writes, training or a product
  accuracy claim.
- DONE — The isolated tenant branch is committed at
  `67564ed18b8821c8556067519f5a46742bca32d3` (tree
  `9233f392bab5ee7f67bbd86985aa055c72388411`). It is one commit ahead of its
  original `main` baseline and remains unmerged.
- DONE — Technical invariance is closed on that exact postimage: tenant build
  passed for `10` endpoints on main and branch; compiled artifacts are
  `in=24 out=24 distinct=24 gaps=0` and byte-identical, canonical relative
  roster `sha256:d1932ff8acc4c90319c6ac734ff460ce73c9f3ae20986641687c29f4e06701a4`.
  The reviewed invariance receipt is
  `sha256:a38fa6d8fa4b585cdad0bfad257bc677c6664850fdd3601a89267aee2a11d28f`.
- DONE — From a clean copy of pinned Metis, `npm run typecheck`,
  `node --import tsx test/r8-description-invariant.ts`, and
  `node --import tsx test/r8-semantic-surface.ts` all exited `0`. The probes
  cover parse/link/validate/IR, formatter/semantic surface and AST anti-vacuity;
  compile-clean is not being used as editorial evidence.
- FIX — The first private index-v2 draft omitted Field `type` and `modifiers`.
  L0 rejected that handoff and extended the closed v2 contract before delivery.
  The successor has `fields with type/modifiers in=113 out=113 distinct=113
  gaps=0`; non-Field technical surfaces carrying those keys are `0`.
- DONE — The successor semantic index is deterministic and closed at
  `entries in=477 out=477 distinct=477 gaps=0`, `catalogs=1 fields=113
  values=363`, `concepts=64`, `semantic refs=39`, `terminal absent=25`,
  `constraints=10`. Its revision is
  `sha256:e87bfb04af92bf0541d3d9da467baa8199e6bf0b01c93b563034f3d83c9582a4`;
  its receipt is
  `sha256:048d315c3e352c3d40ae3114783dbdbcf3b5097ad2b39e007cf07a15cb424b66`.
- DONE — Brain's private reviewed context registry is bound to the same index,
  source, crosswalk and constraint revisions: `concepts=64 mapped=39 absent=25
  constraints=10 gaps=0`, context revision
  `sha256:115d8c784cd1ffc46ceeb509118a66ccbaad21338d1e3824b0ec4ab9f2f7b6e3`.
  The public receipt is hash/count-only and carries no semantic payload.
- DONE — The L0-authored complex grounding sentinel is adjudicated against real
  versioned membership clause by clause: `clauses in=6 out=6 distinct=6 gaps=0`,
  `resolved=1 clarify=3 unsupported=2 targets=1 candidates=3 lookups=0`.
  Overall status is correctly `clarify`; it neither mistakes a legacy literal
  for a dedicated property nor invents unavailable metadata or an unclassified
  value domain. Grounding receipt
  `sha256:576f8977cf125552a584c8a6e5a7454b10689c09eb00cfe2b96aaeede2e5db41`.
- FACT — Point 7 is a deterministic offline Brain handoff, not a Model 1
  benchmark result. P13/P14 model execution, frozen scorecard and any weight
  verdict remain separate gates and are not implied by this materialization.
- RISK — The final independent code reviews found pre-release integrity gaps in
  the patch-promotion proof, post-write rollback coverage, Brain clause
  completeness/context authority and the offline capture boundary. The
  isolated tenant commit remains local and Model 1 remains uncommitted while
  L44-L46 repair and regress these findings.
- STOP — The earlier offline-closed label is superseded by the final audit.
  Promotion, push and wave closure require all L44-L46 regressions, a fresh
  private-boundary audit, and a clean full repository gate on the exact staged
  postimage.
- FIX — L44 now recomputes the exact draft postimage from Git preimage +
  candidate patch before review promotion; a self-consistent forged apply
  receipt is not authority. Apply and review promotion include final dirty,
  commit and tree checks inside the rollback transaction. Sensitive values and
  unsupported `list_entry` operations fail closed. The lane closed `43`
  focused regressions; L0 independently repeated the renderer/applier subset
  with `29/29` green plus lint and format.
- FIX — L45 now rejects omitted request material, overlapping or unanchored
  surfaces, arbitrary resolved targets and one valid phrase swallowing other
  clauses. The context build publishes a detached CAS manifest; grounding
  requires context + receipt + manifest and the manifest SHA independently
  pinned by the Brain session. A fully rehashed tampered bundle therefore
  differs from the trusted authority.
- DONE — L0 rebuilt the real private context bundle with its CAS manifest and
  replayed the exact six-clause frontier sentinel through the public CLI:
  `clauses in=6 out=6 distinct=6 gaps=0`, `resolved=1 clarify=3 unsupported=2
  targets=1 candidates=3 lookups=0`. Overall status remains correctly
  `clarify`; receipt
  `sha256:46662ed798006db0a2f7b9803792b3dd72d8ba6db96571ea8aa3db1ee92f1d9b`
  is bound to trusted context manifest
  `sha256:125121d8866c10d50fd3a51be476c6bd331fb55ab9511c9fc5720f12f7813bae`.
- FIX — L46 now runs Git with optional locks/config hooks disabled, rejects
  ignored tenant material, derives an exact tracked tenant input roster and
  exposes no injectable runner/verifier on the production API. The Node binary
  is opened `O_NOFOLLOW`, bounded and verified by descriptor metadata before
  hashing. The macOS child uses `deny default`, no network/write capability,
  bounded system/runtime reads, exact tooling surfaces and exact tenant files;
  `.env`, ignored, raw and external files are denied by an actual sandbox
  probe. L0 independently repeated `51/51` focused tests, lint/format and a real
  pinned Node `v22.20.0` sandbox execution (`probe-ok`).
- DONE — Final private-boundary audit on the staged candidate found
  `files in=25 out=25 distinct=25 gaps=0`, untracked files `0`, tracked private
  artifacts/PDF/manuals/credentials `0`, reserved-source citations `0` and
  personal absolute paths `0`. The real context and grounding bundles remain
  ignored under the private artifact store.
- DONE — The exact code/document payload before this closure-only evidence
  update passed `make check` with exit `0`: foundation `passes=84 errors=0
  files=506`, pilot contracts `VALID`, Ruff and format green, and pytest
  `2157 passed, 2 skipped, 0 failed, 22 warnings` in `2791.69s`. The two skips
  are the repository's existing opt-in gates; no failing test is hidden.
- DECISION — The earlier L44-L46 `RISK`/`STOP` records are historical audit
  findings and are closed by the subsequent `FIX`/`DONE` evidence. Live
  reconciliation and P13/P14 Model 1 execution remain explicit separate gates;
  they do not block delivery of this offline semantic-fuel wave and are not
  being claimed as executed.

## Current status

`VIDEO_SEMANTIC_EQUIVALENCE_READY`

The earlier `VIDEO_DOMAIN_SEMANTICS_PROMOTED` verdict is retained below as a
historical technical-coverage checkpoint. It is superseded for editorial
quality by the decoding audit opened on 28 August 2026.

## Successor completion wave — 28 August 2026

- DECISION — The product owner has superseded the earlier selective R5 stopping
  point for `play-demo.video`: this successor must complete the catalog label,
  all field semantics, all finite value semantics and an explicit domain
  disposition. Tautological filler and invented finite domains remain invalid.
- FACT — The successor wave began from the clean, already promoted
  `play-demo/main@67564ed18b8821c8556067519f5a46742bca32d3`; this is also the
  normal checkout opened by VS Code. The Model 1 evidence baseline is clean
  `main@aca03a3bed49e3165ec5ce74ac710d3c3a792195`.
- FACT — The supplied measured snapshot reports `fields means=49/113`, external
  values `23/297`, `aka=1` and no Catalog label, while its domain paragraph also
  mentions `92/108` undecided nodes. L47-L49 must reconcile both denominators
  from the exact AST before any completion claim.

## Canonical domain-completion evidence — 28 August 2026

- DONE — The exact schema-2 successor census closes the canonical roster at
  `catalogs in=1 out=1 distinct=1 gaps=0`, `fields in=113 out=113 distinct=113
  gaps=0`. All `113/113` fields and the Catalog node are `reviewed`; there are
  no `draft` or `unannotated` field nodes.
- DONE — Every non-scalar field now has an explicit domain contract. The final
  disposition is `enum=23`, `inline=26`, `open=26`, `none=38`; all `38` none
  fields are intentionally scalar-only (`date=20 number=12 boolean=6`) and
  `none_non_scalar=0`.
- DONE — The formerly unresolved domain roster closed `in=35 out=35 distinct=35
  gaps=0`: live sanitized terms produced `external enum=18`, `inline=15` and
  `open=1`; the one live-empty field `current_season` was materialized inline
  as the exact versioned consumer literals `false/true`. No production payload,
  credential or credential value entered logs or Git.
- DONE — The finite-domain denominator is now `fields in=49 out=49 distinct=49
  gaps=0`, `values in=1792 out=1792 distinct-by-field-and-literal=1792 gaps=0`.
  Every finite value is `reviewed`; `draft=0`, `unannotated=0`. The successor
  adds and frontier-reviews `1429` finite values across `34` newly finite
  domains: `1427` terms-census values across `33` domains plus the two
  consumer-backed `current_season` values. Existing finite values remain
  reviewed.
- DONE — Product-critical gaps are materially closed, including `mood=20`,
  `basicplot=80`, `protagonistaSesso=3`, `protagonistaSpecie=8`,
  `protagonistaFiguraRicorrenteGenereTematico=171`,
  `settingambientazione=225` and `paesiorigine=182` reviewed values.
- FIX — Frontier review rejected generic descriptions and unsupported
  normalizations before promotion. The final quality audit closes
  newly added `records in=1429 out=1429 distinct=1429 gaps=0`; the full finite
  denominator is `reviewed=1792/1792`. Order mismatches, grammar hazards, short
  meanings, generic IAB filler, generic setting filler, normalized template
  clusters and cross-value alias collisions are all `0`. Ambiguous/sensitive
  legacy literals remain explicitly fail-closed rather than being silently
  normalized.
- DONE — Official `catalog:sync-values --only-empty --dry-run` is a fixed point:
  `skip-not-empty=75`, fetches/edits `0`. No eligible keyword/text/search field
  remains unresolved.
- DONE — Final pinned-toolchain gates exited `0`: typecheck, catalog-domain,
  catalog-semantic, sync rewrite, sync merge, R8 description invariance and R8
  semantic surface. Full-corpus grammar compatibility traversed `411` documents
  with unexpected errors `0` and sentinel collisions `0`.
- DONE — Final tenant compilation produces `10` endpoints, `5` catalogs and
  `123` runtime fields. Baseline and successor IR trees are byte-identical,
  runtime context is byte-identical, and both artifact sets have SHA-256
  `1ecabb4fdd29852cbace5b5d637b8f1d497f8bb50bf2460c449cb0e851a98a77`.
  The build CLI's non-zero aggregate status is solely the pre-existing declared
  A/B branch being four main commits behind; both baseline and successor report
  the same branch-maintenance condition.
- FACT — A concurrent upstream `play-demo/main` change from `3506dda7` to
  `7d05c34d` touched only `experiments/_state.json`. The catalog candidate was
  subsequently rebased onto that exact remote head before fast-forward
  promotion; no concurrent file was overwritten.
- DONE — The candidate was committed, rebased without conflict onto exact
  `origin/main@7d05c34dcb699e664d0bad5b9e49e469f2b1c351`, fast-forwarded through the
  normal VS Code checkout and pushed as semantic commit
  `c4f278d8e4f4bf065ba8d919d6a13d09079b0f5f` on `play-demo/main`.
- FACT — A subsequent concurrent experiments-state commit advanced remote main
  to `78a29b22e6f21ad3e1871262ce3dbc5c2d4e64a8`. It is a direct descendant of
  the semantic commit and changes only `experiments/_state.json`; the two
  catalog files are byte-identical. The normal VS Code checkout was
  fast-forwarded and is clean with local `main=origin/main=78a29b22`.
- DONE — Post-push schema-2 verification ran against the normal `play-demo`
  checkout opened in VS Code, not the isolated candidate: `fields
  reviewed=113/113`, domains
  `enum=23 inline=26 open=26 none=38`, `none_non_scalar=0`, finite values
  `reviewed=1792/1792`. Critical post-push counts are `mood=20`,
  `protagonistaSesso=3`, `protagonistaSpecie=8`, `basicplot=80`, recurring
  protagonist figures `171` and narrative settings `225`, all reviewed.
- STOP — A missing domain is never converted to `enum` without a complete,
  versioned finite roster, and a genuinely open domain is never materialized as
  a convenience list. Non-keyword scalar types are classified according to the
  grammar's actual representational contract rather than forced into keyword
  syntax.
- STOP — Delegates remain barred from reserved sources, ignored private
  artifacts, credentials, Keychain and live data. L0 Frontier owns all semantic
  prose, ambiguity decisions and final review; delegated lanes are read-only
  censuses and deterministic gates only.

## Successor evidence — 28 August 2026

- DECISION — This section is a historical pre-domain checkpoint. Its 35-field
  `STOP`/`OPEN`, `@3506dda7` promotion and conditional gate verdict are
  superseded by the canonical completion evidence above and lane L0-D.

- DONE — L47 independently reconciled the current AST roster:
  `Catalog in=1 out=1 distinct=1 gaps=0`,
  `Field in=113 out=113 distinct=113 gaps=0`,
  `ValueItem in=363 out=363 distinct=363 gaps=0`. The earlier `108/92`
  paragraph is not the parser roster: the exact preimage had `15` explicit
  domains and `98` `none` fields.
- FIX — L0 added `label "Video"`, authored and reviewed the missing field/value
  semantics, and added `open` only to the `25` text, title, person and identifier
  fields whose domain is genuinely the live index. No delegate authored or
  promoted prose.
- DONE — The postimage semantic recount is exact: Catalog `1/1 reviewed`, Fields
  `113/113 reviewed`, finite ValueItems `363/363 reviewed`, `draft=0`,
  `unannotated=0`. The source now contains `477` `means` nodes, one Catalog
  label and three nodes with evidence-backed aliases.
- DONE — Field domain dispositions are exhaustive even though not all are
  materializable: `in=113 out=113 distinct=113 gaps=0` = `15` already explicit
  finite domains + `25` genuine `open` + `38` intentional type-defined `none`
  (`32` range/date/number nodes and `6` booleans) + `35` blocked keyword
  taxonomies. The retrieval contract explicitly permits intentional `none` for
  range/technical fields; it does not require a false `open` marker.
- STOP — The following `35` keyword taxonomies have no exhaustive canonical
  roster in the authorized versioned sources and therefore cannot yet become
  `enum(N)` or `open`: `genere_mcm_primario`, `video_format`, `video_formats`,
  `mythematics_source`, `audio_language`, `subtitle_language`, `basicplot`,
  `brand_category`, `content_rights`, `content_channels_rights`,
  `current_season`, `esg_enabled`, `generediegetico`, `generepatemico_sub`,
  `generetematico`, `generetematico_sub`, `last_live_channel`, `mood`,
  `paesiorigine`, `tematismigenerediegetico`, `tematismigeneretematico`,
  `tematismimacrogeneripatemici`, `published_flag`, `categorieiab_sub`, `epoca`,
  `epoca_sub`, `generediegetico_sub`,
  `genereintrattenimentoeinformazione_ter`,
  `genereintrattenimentoeinformazione_sub`, `messainscena_sub`,
  `protagonistaFiguraRicorrenteGenereTematico`,
  `protagonistaPerformanceDelPersonaggio`, `protagonistaSesso`,
  `protagonistaSpecie`, `settingambientazione`. Consumer literals and endpoint
  lists are partial filters, not proof of a complete domain. Closure requires a
  sanitized, read-only canonical domain export; credentials or live payloads
  are not admitted into this repository or run.
- OPEN — The admissible unblock artifact is a sanitized per-field census bound
  to tenant/index authority, with exact distinct count, overflow flag, ordered
  canonical literals, null/missing counts and normalization collisions for all
  `35` fields. It must contain no documents, credentials or free-text payloads.
  L0 will then choose inline versus `enum(N)`, author value semantics, rerun the
  same gates and close the remaining domain roster without retraining Model 1.
- DONE — L0 compared the exact preimage and postimage: all `113` field
  name/type/modifier tuples are byte-equivalent, all `363` finite literals and
  their declaration order are identical, and the only domain movements are the
  expected `25` `none -> open` transitions.
- DONE — The clean pinned toolchain passed the semantic invariant, semantic
  validator/formatter, sync rewrite, sync merge, catalog-domain,
  catalog-semantic and TypeScript gates. VSIX `0.23.93`
  (`sha256:3a05231140cf52ccd13f30a72ae781d3712b22918e54b281e0b7ab7bae9b1d29`)
  validated `170` tenant endpoints with `0` errors and is the installed editor
  version.
- DONE — Clean preimage/postimage main builds each produced `10` endpoints,
  `5` catalogs and `123` runtime fields. Their complete output directories are
  byte-identical, including artifact-set identity
  `1ecabb4fdd29852cbace5b5d637b8f1d497f8bb50bf2460c449cb0e851a98a77`.
  The declared A/B branch remains behind current main; this is pre-existing
  branch maintenance and does not invalidate the main build comparison.
- DONE — The candidate diff is restricted to the two authorized catalog files;
  no reserved source, credential, ignored artifact, live payload, manual or
  official citation to reserved material enters the tenant commit.
- DONE — The tenant change was rebased over the concurrent experiments-state
  update, reverified, committed and pushed directly to
  `play-demo/main@3506dda7ea08d6a06c68dc2f5a37a4e18ad24780`; the normal VS Code checkout
  is clean and exactly aligned with `origin/main`.
- RISK — The required Model 1 `make check` was run on this board-only candidate.
  Foundation (`84` passes, `0` errors, `506` files), pilot contracts, Ruff and
  format were green; pytest closed `2156 passed, 2 skipped, 1 failed`. The sole
  failure is the pre-existing W3 adversarial FIFO timing case
  `test_transaction_rejects_preexisting_fifo_without_blocking_or_publication[manifest]`:
  its child exceeded the hard-coded `45s` timeout. The same case passed outside
  the canonical harness in about `35s` but reproduced the timeout inside the
  canonical harness (`1 failed in 45.21s`). Neither changed board file is on
  that runtime/test surface, so this is not attributed to the semantic tenant
  patch; it is nevertheless reported as non-green and not hidden.
- DECISION — The W3 FIFO fail-fast repair is a separate security-boundary wave:
  it requires descriptor-relative early preflight plus race-preserving late
  verification and dedicated adversarial tests. This semantic-catalog wave
  does not opportunistically change that runtime merely to make its board
  commit green. The documentary promotion is therefore conditional and the
  global Model 1 gate remains non-green.

## Canonical domain materialization — 28 August 2026

- DECISION — The product owner authorized closure of the `35` unresolved
  domains. L0 retained semantic/editorial authority and opened three disjoint
  frontier review lanes; delegated versioned-source censuses remain supporting
  evidence, never promotion authority.
- FACT — From clean `play-demo/main@3506dda7ea08d6a06c68dc2f5a37a4e18ad24780`,
  L0 created isolated candidate `codex/video-domain-census` and ran the pinned
  official read-only catalog terms census through a credential-contained
  boundary. The operation exposed only per-field literals/counts: no documents,
  payloads or credential values entered the candidate, board or logs.
- DONE — The live census disposition is exact over the blocked roster:
  `in=35 out=35 distinct=35 gaps=0` = `18` external finite value-sets + `15`
  inline finite domains + `1` genuine `open` domain + `1` field absent from the
  current live snapshot but carrying the exact two boolean-like literals
  `false`/`true` in versioned tenant consumers. That last pair is materialized
  as explicit consumer-backed values, not invented from live data.
- FACT — High-impact recovered denominators include `mood=20`,
  `basicplot=80`, `protagonistaSesso=3`, `protagonistaSpecie=8`,
  `protagonistaFiguraRicorrenteGenereTematico=171` and
  `settingambientazione=225`. `tematismigeneretematico` crossed the tenant
  `enum-max=300` guard and is therefore correctly `open`; no truncated enum was
  written.
- DONE — The post-census field disposition is exhaustive:
  `Field in=113 out=113 distinct=113 gaps=0` = `23 enum + 26 inline + 26 open +
  38 scalar none`. Every remaining `none` is type-defined (`20 date + 12 number
  + 6 boolean`); no keyword, text, identifier or person/title field remains
  without a retrieval disposition.
- DONE — Before value prose was added, clean pinned builds of baseline and
  candidate each produced `10` endpoint IR files, `5` catalogs and `123`
  runtime fields with byte-identical IR/runtime hashes and artifact-set identity
  `1ecabb4fdd29852cbace5b5d637b8f1d497f8bb50bf2460c449cb0e851a98a77`.
  The already-known stale declared A/B branch remains a separate maintenance
  finding in both builds.
- DECISION — This historical pre-review `OPEN` is closed and superseded. The
  final finite denominator is `reviewed=1792/1792`; semantic recount, retrieval,
  sync idempotence, compiler invariance, VSIX, diff/privacy and normal-checkout
  gates closed before semantic commit
  `c4f278d8e4f4bf065ba8d919d6a13d09079b0f5f`, now contained unchanged in
  `play-demo/main@78a29b22e6f21ad3e1871262ce3dbc5c2d4e64a8`.

## Final closure receipt — 28 August 2026

- DONE — Independent post-promotion audit on current clean `play-demo/main`
  closes `Catalog reviewed=1/1`, `Fields reviewed=113/113`, retrieval fields
  `in=75 out=75 distinct=75 gaps=0`, `none_non_scalar=0`, finite fields
  `reviewed=49/49` and finite values `reviewed=1792/1792`; `draft=0`,
  `unannotated=0`, reserved-source/path/credential leaks `0`.
- DONE — Current local `main`, tracking `origin/main` and remote live all resolve
  to `78a29b22e6f21ad3e1871262ce3dbc5c2d4e64a8`. The semantic commit is its direct
  ancestor `c4f278d8e4f4bf065ba8d919d6a13d09079b0f5f`; both catalog blobs are
  unchanged by the intervening experiments-state commit.
- DONE — The required Model 1 repository gate completed with exit `0`:
  foundation `passes=84 errors=0 files=506`, pilot contracts `VALID`, Ruff and
  formatting green, pytest `2157 passed, 2 skipped, 0 failed, 22 warnings` in
  `2809.44s`. This fresh green run supersedes the historical FIFO-timeout risk
  recorded in the pre-domain checkpoint.
- DECISION — Domain semantics remain retrieval-owned tenant data. This wave did
  not train, retune, inject catalog literals into, or otherwise mutate Model 1
  weights, adapter, checkpoints or optimizer state.

## Semantic decoding audit — 28 August 2026

- RISK — The owner review found that all `27/27` values of
  `last_live_channel_code` were marked `reviewed` with repeated prose declaring
  each code opaque, while the sibling `last_live_channel` domain contains the
  human channel names required by natural-language retrieval. A coverage count
  of `reviewed=1792/1792` therefore overstated semantic quality: reviewed syntax
  is not proof of decoded meaning.
- STOP — The editorial gate is reopened. No final semantic-accuracy claim is
  valid until an authoritative `code -> channel name` relation is established,
  the affected values carry discriminative retrieval semantics/aliases, and a
  catalog-wide anti-pattern census has classified analogous code-like or
  boilerplate-reviewed values.
- DECISION — L0 alone owns mapping acceptance and editorial promotion. Delegated
  lanes may perform read-only censuses and design a payload-safe aggregate
  check, but may not infer mappings, inspect credentials or raw documents,
  modify repositories, or promote a result.
- DECISION — Catalog keys and values remain retrieval-owned tenant state. This
  remediation changes catalog semantics only; it does not inject channel codes,
  names or any other tenant value into Model 1 weights.
- FACT — An ephemeral aggregate-only read through the pinned read-only client
  returned `hits=0`, `_source=false`, document IDs/samples/credentials `0` and
  exhaustively reconciled `27` codes, `26` names and `26` observed pairs. Two
  consecutive complete passes were byte-identical (`13216` sanitized output
  bytes each), so no between-pass drift was observed.
- FACT — `24/27` channel codes have at least one observed human label. `20` are
  one-label complete, `EC` and `ER` have one unique observed label plus `8` and
  `1` unlabeled documents, `KF` has the historical labels `TGCom|Tgcom24`, and
  `QY` has `Mediaset Infinity|Mediaset Play`. `FT`, `KN` and `N4` have no
  observed human label (`26`, `8` and `5` unlabeled documents respectively).
- FIX — The isolated decoding candidate replaces the `27/27` opaque boilerplate
  with the observed human mapping and retrieval aliases. The owner-observed
  surface `Italia1` maps to literal `I1`; the spaced `Italia 1` label is also
  retained. `FT`, `KN` and `N4` are deliberately downgraded to `draft`, with no
  invented channel name or alias.
- RISK — The exhaustive anti-pattern audit examined all `1792` finite values.
  Beyond the channel field it found `7` definite undecoded code literals:
  `published_flag={CMS,RDY,WKP}` and
  `audio_language={afg,csk,ing,yug}`; `UCL` and `UCL_SVOD` are expansion/alias
  candidates. These require a versioned/authoritative dictionary, not initials
  or model intuition.
- RISK — Separate P1 retrieval debt is not to be conflated with opaque codes:
  human-readable but template-heavy domains include `genere_mcm`,
  `content_channels`, `content_channels_rights`, `last_live_channel` and
  `paesiorigine`. In particular `paesiorigine` has `42` proven same-meaning
  groups over `89` physical literals; an Italy request must be verified against
  the emitted predicate, because `aka` alone cannot safely imply selection of
  every dirty stored variant.
- DECISION — The reserved tagging guidance was used by L0 only for the
  editorial taxonomies that it actually defines (narrative, thematic,
  protagonist, mood and setting semantics). It is not authority for operational
  source codes. No reserved source, filename, quotation, locator or derived raw
  text is present in the tenant candidate, repository documentation or receipts.
- DONE — The channel relation was established independently of the reserved
  guidance through a payload-free aggregate-only current census plus versioned
  consumer evidence: `codes in=27 out=27 distinct=27 gaps=0`, current mapped
  codes `24`, unresolved `3`. The three unresolved codes remain `draft` and
  carry no invented alias.
- FIX — Seven analogous opaque-code annotations were also corrected instead of
  being left falsely reviewed: `published_flag={CMS,RDY,WKP}` and
  `audio_language={afg,csk,ing,yug}` are now `means draft`. The exact finite
  recount is therefore `values=1792 reviewed=1782 draft=10 unannotated=0`;
  semantic state is reported as review authority, not coverage theater.
- DONE — Independent candidate-diff census closed `changed ValueItem in=34
  out=34 distinct=34 gaps=0`. Field count remains `113`, finite literal roster
  and order remain `1792/1792`, and name/type/modifier/domain surfaces are
  unchanged. The candidate adds `43` distinct aliases with no alias shared by
  two channel codes; `26` intentionally coincide with the sibling human channel
  literals.
- FIX — Brain's exact resolver now applies strict maximal-span selection before
  rank/tie adjudication. A full reviewed surface such as `Italia 1` therefore
  suppresses the contained country surface `Italia`, while disjoint and
  crossing spans remain independent and equal spans still use the existing
  deterministic rank/fail-closed contract. The production-shaped regression
  uses `last_live_channel_code=I1` with aliases `Italia 1|Italia1`.
- DONE — Real candidate grounding through the pinned schema-2 projection is
  green for `Italia1`, `Italia 1`, `Canale5`, `Rete4`, `TopCrime` and
  `pubblicato`; each resolves to an exact snapshot member. The focused Model 1
  regression is `8 passed`, with Ruff and format checks green.
- DONE — The exact candidate parses on pinned Metis and the targeted toolchain
  gates are green: typecheck, R8 description invariant, R8 semantic surface,
  catalog-domain, sync rewrite and sync merge. Direct baseline/candidate
  compilation closed at `documents=29 endpoints=10`; runtime and endpoint IR
  are byte-identical with hashes
  `4b238459546f087a2a7aa365b9f12ab2fca48bc9931b872042da8487cfed5f8a` and
  `340315a0af3683107734b247c2b3ff95b38687cb0edec32cbaa8c8a07cef5513`.
- OPEN — `audio italiano`, `sottotitoli inglesi` and `prodotto in Italia`
  expose a different P1 contract gap: one human concept may need an OR-group of
  several physical literals (`ENG|eng`, `ITA|ita`, or multiple country
  variants). Repeating one `aka` would create a tie, while choosing one literal
  would miss real records. Pinned Metis lists are executable but have no
  list-level `means`/`aka`, and Model 1 does not currently index list groups.
  This requires an explicit tenant-owned semantic-group contract; it must not be
  hidden by an unsafe alias shortcut.
- DONE — The reviewed tenant correction was committed as
  `654beba326bc824bc40f9f618b94eebe29dea2bb` and pushed to canonical
  `play-demo/main`. A concurrent experiments-state commit then advanced remote
  main to `5f7b1d7d4191ced705736eba423983f7b2309f4d`; it contains the semantic commit
  as a direct ancestor. The normal VS Code checkout was fast-forwarded and is
  clean/aligned with that remote head; no concurrent work was overwritten.
- RISK — The required Model 1 `make check` is not globally green on this exact
  code/document candidate: foundation is `84/84`, pilot contracts, Ruff and
  format are green, and pytest is `2156 passed, 2 skipped, 2 failed`. Both
  failures are the pre-existing W3 FIFO fail-fast timing cases
  `test_transaction_rejects_preexisting_fifo_without_blocking_or_publication`
  for `manifest` and `bootstrap`, each exceeding its hard-coded `45s` timeout.
  Isolated replay made `manifest` pass, while `bootstrap` reproduced the same
  timeout alone. These tests do not touch the catalog or resolver surfaces, but
  the global gate remains non-green and is not reported otherwise.
- DECISION — The W3 descriptor-relative fail-fast repair remains a distinct
  security-boundary wave. This semantic correction does not change or weaken
  W3 merely to obtain a green receipt. Its scoped acceptance rests on the
  focused resolver tests, pinned parser/compiler/R8/sync gates, exact technical
  invariance and canonical tenant promotion recorded above.

## Equivalence closure and proposal reconciliation — 28 August 2026

- FACT — The external P0/P1 proposal is an input, not authority. Its
  `1628`-value, `7`-draft and single-`aka` snapshot is superseded by the current
  parser census: `fields=113`, `finite fields=49`, `values=1792`,
  `reviewed=1782`, `draft=10`, `unannotated=0`.
- DECISION — The proposal's `zero draft` stopping rule is rejected. The ten
  unresolved operational codes remain quarantined and cannot ground a natural
  request; removing `draft` without a tenant-owned dictionary would fabricate
  authority.
- DONE — L62 inspected grammar, lists and both Brain resolvers. No existing
  named-list mechanism simultaneously owns natural semantics, exact membership
  and resolver execution. A sidecar would duplicate truth.
- DONE — L63/L65 mechanically enumerated only equivalences already stated by
  reviewed tenant semantics. L0 independently recomputed the roster and
  corrected the delegated arithmetic by one: `concepts in=57 out=57
  distinct=57 gaps=0`, physical members `in=132 out=132 gaps=0`, not `131`.
  Ambiguous near-neighbours remain deliberately separate.
- DECISION — One reviewed `aka` repeated on all and only the ValueItem nodes of
  one catalog+field declares a tenant-owned physical OR group. The group is
  executable only with at least two reviewed members and exact complete
  membership. Draft, omitted, extra and cross-field targets fail closed.
- FIX — Model 1 v1 now returns one `reviewed_aka_group` selection with
  `literal=null`, deterministic `literals=[...]` and `value_mode=any_of`.
  Brain v2 accepts `REVIEWED_AKA_GROUP` only after independently rebuilding the
  exact same-field reviewed alias roster from the pinned index and proving that
  no same-catalog carrier exists on another field; semantic refs cannot
  substitute for or expand it.
- FIX — The `play-demo/main` candidate adds contextual aliases to all 57 proven
  equivalence concepts, including the complete country, subtitle, legacy genre,
  IAB, thematic and setting rosters. It also adds natural aliases to all 29
  reviewed audio-language codes; the four draft audio codes remain without
  aliases.
- DONE — Current parser replay is `fields=113`, `finite_fields=49`,
  `values=1792`, `reviewed=1782`, `draft=10`, `unannotated=0`; alias grouping is
  `shared surfaces=247`, `equivalence concepts=57`, `physical members=132`,
  `unsafe shared surfaces=0`.
- DONE — Real schema-2 projection replay resolves “prodotti in Italia con audio
  in italiano e sottotitoli inglesi” to exactly three selections: country
  `any_of=4`, audio `ita`, subtitles `any_of=2`. Separate real probes resolve
  the reviewed US, setting, primary-genre and thematic groups.
- DONE — L67 verified the compiler surface and lowering: scalar membership is
  `@field in ["A", "B"]`, multi membership is
  `@field has any ["A", "B"]`; both already lower and render as OR semantics.
  `contains any` remains a distinct legacy containment operator.
- OPEN — Model 1 currently stops at grounding/adjudication and has no
  grounding-to-DSL emitter. That seam is required by the future distributable
  Brain/Fast product but is not falsely claimed as part of this catalog audit.
  It needs no grammar change and must compile every emitted constraint against
  the pinned toolchain.
- DONE — L64 closed the current tenant catalog roster at `fields in=167 out=167
  distinct=167 gaps=0`: `video=113`, `video_pg=40`, `users=9`,
  `smart_index=3`, `user_session=2`. The explicit next order is `users` P0,
  `video_pg` and `smart_index` P1, then `user_session` P2. `video_pg` must reuse
  rather than duplicate the `@video` vocabulary.
- OPEN — Runtime demo hardening from the proposal (M6 recapture, cold PostgreSQL
  diagnosis/warm-up and Grafana click-through) is a separate Metis/runtime
  wave. M6's supplied expectation is internally inconsistent between
  `search:play-demo:video` and `search:play-demo:users` and must be ratified
  before execution.
- FACT — The claimed VSIX `0.23.94` is not present in the current Metis
  checkout; the highest verified semantic package is `0.23.93`. No unpublished
  version is made a gate. The four grammar/sync ratifications are already
  represented in the upstream team's active plan; this repository does not
  overwrite that dirty owner surface.

## Frontier closure pass — 28 August 2026

- FIX — The proposal's complete confusable-field roster now has discriminative
  field aliases: `36` fields carry `59` alias surfaces, with duplicate aliases
  within a field `0` and exact collisions between fields `0`. Search-only
  technical fields were deliberately not decorated for coverage theater.
- FIX — L0 removed `29` mechanically generated, grammatically noisy audio
  aliases of the form “audio in lingua <masculine>”. All `29` reviewed audio
  codes retain two natural retrieval surfaces; the four draft codes retain
  none. The final value-alias census is `421` carrier nodes / `1106` surfaces.
- DONE — The exact semantic denominator remains
  `values in=1792 out=1792 distinct=1792 gaps=0`, with `reviewed=1782`,
  `draft=10`, `unannotated=0`. Same-field equivalence remains
  `shared_surfaces=247`, `concepts=57`, `physical_members=132`,
  `unsafe=0`. Eight reviewed alias surfaces occur on values in different
  fields and remain explicit clarification cases, never equivalence groups.
- RISK — L68 found a v1 catalog-scope bypass in the first group implementation:
  OR groups were constructed before filtering the caller-selected catalog.
  It also found that non-string v2 `resolution`/`reason_code` values could leak
  raw `TypeError` exceptions.
- FIX — Both findings are closed. V1 filters groups by `allowed_catalogs`; v2
  validates both enum-shaped inputs before membership checks. L0 additionally
  found and closed a hidden v2 arbitrary-choice path: a same-surface alias on a
  different field of the same catalog now invalidates the proposed group even
  when omitted from the target roster.
- DONE — The focused combined resolver/index suite is `50 passed`, including
  explicit catalog-scope escape, malformed enum, incomplete/draft/extra roster,
  visible cross-field target and hidden cross-field competitor regressions.
  L68 independently replayed each repair and returned PASS.
- DONE — Real schema-2 replay after the final aliases remains closed at
  `catalogs=1 fields=113 finite_fields=49 value_responses=49 values=1792
  gaps=0`, index entries `1906`. “prodotti in Italia con audio in italiano e
  sottotitoli inglesi” resolves to country `any_of=4`, audio `ita`, subtitles
  `any_of=2`; reviewed US and discriminative field-alias probes also resolve.
- DONE — Direct `play-demo` baseline/candidate compilation on the current
  toolchain closes `documents=29 endpoints=10`, parser/validation errors `0/0`;
  runtime and IR are byte-identical. Runtime hash is
  `4b238459546f087a2a7aa365b9f12ab2fca48bc9931b872042da8487cfed5f8a`
  and the canonical endpoint-set digest used in this replay is
  `4c40ed98bb19dccb85fb3c8b4b55bc9c097c08f2a60d33830133fa5bb6a7e8c8`.
- DONE — Current Metis typecheck, R8 description, R8 semantic surface,
  catalog-domain, catalog-semantic, sync rewrite, sync merge and formatter are
  green. A clean archive of pin `0b41a25d...` independently parses the candidate
  at `113/113` reviewed fields and `1792` values (`1782 reviewed`, `10 draft`,
  `0 unannotated`); every gate available at that pin is green. The later
  formatter probe is verified on current Metis, not falsely attributed to the
  older archive where that test file does not exist.
- DECISION — `@video` closure does not close the tenant. The measured queue is
  retained as `users` P0, `video_pg` and `smart_index` P1, `user_session` P2;
  later catalog additions require a new pinned census. Runtime M6/cold-PG/
  Grafana hardening and the future grounding-to-DSL emitter remain distinct
  executable waves.
- DONE — The required Model 1 repository gate completed on the exact integrated
  candidate with exit `0`: foundation `passes=84 errors=0 files=508`, pilot
  contracts `VALID`, Ruff and formatting green, pytest `2175 passed, 2 skipped,
  0 failed, 22 warnings` in `3029.00s`. The two skips are declared opt-in
  authority gates and are not counted as executed. The known W5 readiness
  verdict remains `BLOCKED` for its historical dataset/seal/authority reasons;
  it is not a regression of this semantic wave.

## Promotion receipt — 28 August 2026

- DONE — The canonical tenant patch is committed and pushed as
  `play-demo/main@484768ed486281878c9e1bc61ab469ac6bd5e387`. A concurrent,
  non-overlapping experiment-state commit advanced the remote immediately
  afterwards; it descends from the semantic commit. The local checkout was
  fast-forwarded without rewriting history and is clean and aligned at
  `main@f18819fc5fddd3a92dec34ab9ae928db51b621ce`.
- DONE — L0 repeated the direct compile comparison after the final alias byte:
  baseline and promoted candidate both load `29` documents, produce `10`
  endpoints and report parser/validation errors `0/0`. Runtime bytes are equal
  at `sha256:4b238459546f087a2a7aa365b9f12ab2fca48bc9931b872042da8487cfed5f8a`;
  the combined canonical runtime-plus-endpoint digest is equal at
  `sha256:7fb0d5383f993aecae14ef1ff39f4774c470170df6bf29de5bab9110e3daf899`.
- DONE — Final scoped diff checks, formatter/lint, foundation `84/0/508`,
  focused resolver replay and restricted-source scan are green. Repository
  documentation contains no restricted-source locator or credential material.
- DECISION — `VIDEO_SEMANTIC_EQUIVALENCE_READY` closes this `@video` wave only.
  The catalog queue, application emitter and runtime-demo hardening remain
  explicit subsequent waves and cannot inherit this verdict by implication.
