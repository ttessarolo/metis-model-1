# Brain generality and descriptor authority blackboard

Status: **G5 CORE VERIFIED — CLIENT AND ADVANCED PACKS OPEN**

Baseline: Model 1 `a640cc6facd1b6ce7e6e838225c0d6c3e3080050` on clean `main`

Previous evidence: [`../2026-09-04-play-prod-semantic-readiness/BLACKBOARD.md`](../2026-09-04-play-prod-semantic-readiness/BLACKBOARD.md)

## Current delivery receipt — 2026-09-05

- DONE [L0] — Final `make check TEST_WORKERS=2` on the independent frozen
  Metis authority completed with **exit 0**, wall 1509.39s. Exact ledger:
  `in=4444 out=4444 distinct=4444 gaps=0 passed=4442 skipped=2 failed=0
  error=0 xfailed=0 xpassed=0 workers=2`. Groups: 1715 passed; 1705 passed plus
  two explicit opt-in skips; 1022 passed. This supersedes the failed and
  interrupted gate attempts below, without reclassifying those attempts.
- DONE [L0 independent check] — Reopened all four copied private ledgers
  through `read_private_ledger`, recomputed their exact union and outcome
  counts, and asserted equality to the canonical 4444-case roster: gaps=0,
  duplicates=0. All 13 new real compiler/projection cases executed and passed;
  the complete 46-case Flash module also passed in the final serial group.
- FACT [L0] — Source/test/runtime/schema roster remained frozen throughout:
  `1b0070bc954905a21e9f4bfce0ba7fd6e2db8f2baa9f9ab82890455497ff041f`.
  Only documentation/receipt edits follow this gate. The delivery commit is
  the commit containing this receipt; publication and remote alignment must
  be checked independently after push, not inferred from this file.
- FACT [L0] — Persistent ignored artifacts:
  `artifacts/brain-generality/g5-close.Xp2gvs/make-check-final-seal.log`
  SHA256 `df5e0f4094433b04d05ad314b134a8a00a77344f585192687965c90fc894d096`.
  `ledgers-final/collection.json` SHA256
  `fd09ecf2d3c4b4fadc32b6369084886a54e926ab87c59cb0a414d9be344e8d3a`;
  `parallel-0.json` `ba0e166ed79ab4d2d5bc7243db90deb439bc0fca37138b6b2db73593dcb8f116`;
  `parallel-1.json` `cee6e61a5d21e13833017ba5f22020c59b52a8cc6e50110993516ae4b0e7bc71`;
  `serial-quarantine.json` `3dbc0d80068cab24113787d24459d0c54237b665e943ea439853833865aaec08`.
- DONE [L0] — Bounded delivered roster: 7/7 generic operations (add filtered
  block, add root page, change total count, field ordering, named projection,
  same-Draft fallback, similarity from explicit input), source-bound private
  technical roles, emitted response roots, nested original-authority anchors,
  and real-retrieval natural dialogue. Closed domain recipes remain test-only.
  Two renamed synthetic tenants prove portability within this admitted scope.
  This does not certify all Metis constructs or all natural-language prompts.
- FACT [L0] — No real model inference/training, weight change, live data,
  tenant write, Apply, client update or external repository write occurred.
  All delegated lanes and gate processes are finished. No total-suite speedup
  or model accuracy/latency claim is inferred from this software receipt.
- OPEN [delivery queue] — Next integration: the external VSIX must consume
  universal dialogue v2, then pass real HTTP/chat/Draft checks. Follow
  `docs/handover-g5-visix-dialogue-v2.md`; do not modify that read-only repo
  without the relevant mandate. Metis Fast stays after VSIX as requested.
  Advanced packs (`view-all`, external fallback, grouping, arbitrary catalog
  relations) and the new complex-cohort inference qualification remain open.
  The documented long synthetic prompt is an unresolved linguistic case.

Earlier ACTIVE/OPEN/STOP entries below are historical evidence, not live
process state. The current residual scope is the queue immediately above.

## Objective

### Historical integration receipts (G5, after 61a6c47)

- FACT [L0] — Isolated delivery completed with a valid aggregate ledger but
  three test failures: `in=4444 out=4444 distinct=4444 gaps=0 passed=4439
  skipped=2 failed=3 error=0 xfailed=0 xpassed=0 workers=2`, wall 1547.06s.
  All three failures are the first fake Flash worker warmups in the serial
  quarantine: a 1.0s fixture timeout fired before semantic validation. The
  whole unchanged 46-case module passed on immediate independent rerun.
  Cold interpreter startup/scheduling is compatible with the evidence, not
  measured; both parallel shards had already finished, so their concurrency
  is not the cause established by this receipt. This run is NOT green.
- FIX [L0/L1142] — Only the Flash test fixture's non-timing default changed
  from 1.0s to 10.0s. Production timeout remains 60.0s. Explicit 0.03s timeout,
  30.0s cancellation budgets, cleanup/join limits and every assertion remain
  unchanged. Independent frontier review approved this test-only change;
  complete module rerun: `46 passed in 5.97s`; lint, 472-file format and diff
  checks passed. No model was started by these synthetic subprocess tests.
- FACT [L0] — Final code/test roster is now
  `1b0070bc954905a21e9f4bfce0ba7fd6e2db8f2baa9f9ab82890455497ff041f`.
  The next full `make check TEST_WORKERS=2` uses the same independent frozen
  Metis clone and logs to `/tmp/metis-g5-gates.KgSGIx/make-check-final-seal.log`.
  No previous partial or failed run substitutes for its actual final exit.
- FACT [L0] — The previous isolated run and its four JSON ledgers are saved
  under ignored `artifacts/brain-generality/g5-close.Xp2gvs/`; log SHA256 is
  `2a354d6e36613c62508dc92c427cd74de3b6a648c1e71f3ea44d66d002675e5c`.
  Independently checked all 13 new real compiler/projection outcomes: passed.
  Its two skips are explicit opt-in video toolchain-object and W3 real bridge
  qualifications, not any new descriptor compiler case.
- FIX [L1143/L0] — Lower-cost read-only delivery audit found stale v1 UX
  claims. Runbook/interactive docs now distinguish historical VSIX delivery
  from the required G5 v2 consumer, v1/v2 budgets and current capability scope.
  Core validation before Git delivery is also distinguished from later sealed
  complex-journey qualification. All eight relative document links existed.
- FACT [L0] — Delivery run executed every test successfully: groups
  `1715 passed`, `1705 passed, 2 skipped`, `1022 passed` (4442 passed plus two
  skips). Nevertheless the outer harness returned `test authority validation
  failed`, exit 2, after the serial group; this is NOT a green final gate.
  The log ended at 19:59:36 +0200, four seconds before external Metis committed
  `5e321f48` (doc-only register update, reflog 19:59:40). This timing is
  consistent with its source-worktree-cleanliness guard; the wrapper redacts
  the exact caught exception, so the cause is an inference, not a captured
  exception detail. Model1 code/test roster still matches `28187193...`.
- FIX [L0 environment] — To remove concurrent external-worktree authority,
  created an independent local Git clone (no hardlinks or alternates) under
  ignored `artifacts/brain-generality/g5-close.Xp2gvs/metis-authority`, detached
  at `5e321f4806d11827847366da3acdd565d74361ca`, with matching `origin/main` and
  an independent node_modules copy. No tracked `.env` files, no source repo
  writes, no model/data payloads or pin changes. Static Brain verifier on this
  copy: `in=29 out=29 distinct=29 gaps=0`.
- FACT [L0] — Current final command is `make check TEST_WORKERS=2
  PINNED_METIS_ROOT=/Users/tommasotessarolo/Developer/metis-model-1/artifacts/
  brain-generality/g5-close.Xp2gvs/metis-authority` (path is one line).
  Log: `/tmp/metis-g5-gates.KgSGIx/make-check-isolated-delivery.log`.
  Same frozen code/test digest `2818719307a199eb69d472cf9ebeae9e51c44ad6ebc2be32a073369c9413e2ab`.
- FIX [L0 workflow] — Avoid another expensive late fixture migration: before
  freezing a future wave, run whole affected modules, including server wiring
  when constructor arguments change; run every affected real-pin test by its
  explicit module, not a name substring (`real_pin` omitted a `pinned` case
  here). Only then run full `make check`. This changes gate ordering, not the
  required coverage or the standard for a green final receipt. No total-suite
  speedup is claimed from uncontrolled cross-run timings.
- FACT [L0] — Complete seal run finished, not promoted:
  `in=4444 out=4444 distinct=4444 gaps=0 passed=4441 skipped=2 failed=1
  error=0 xfailed=0 xpassed=0 workers=2`, wall 1564.33s. The sole failure is the
  stale server callback assertion described below; its whole module has since
  passed. No additional failure was hidden by an early stop.
- FACT [L0] — Final delivery run is now executing:
  `/tmp/metis-g5-gates.KgSGIx/make-check-delivery.log`. Frozen code/test roster
  digest: `2818719307a199eb69d472cf9ebeae9e51c44ad6ebc2be32a073369c9413e2ab`.
  Implementation and all delegated lanes are frozen. Only final receipts,
  documentation and Git delivery remain; do not restart implementation while
  this run is active. Its exit and ledger still require independent checking.
- FACT [L0] — The seal run passed both parallel groups (1715 passed; 1705
  passed plus two expected skips), including all 13 descriptor/technical real
  compiler cases. Its serial group exposed one stale server wiring assertion:
  it still required the intentionally removed `exact_value_resolver` provider
  callback. L0 changed only that test to assert absence. Independent complete
  server module rerun: `29 passed in 6.51s`; lint/format/diff checks green.
  `make-check-seal.log` is not a green receipt. Let its serial group finish to
  identify any additional failures, then perform a fresh final complete run.
- FACT [L0] — The next full run found exactly two assertion failures in the
  strengthened original descriptor compiler test: it read AST key `block`
  instead of pinned IR key `ref`. Both actual compilations were `ok`; the new
  engine's emitted-root tests used the correct IR key and passed. L0 verified
  `compileVariant`/`compileContainerMembers`, fixed the assertion to exact
  `uses[].ref == [main]` plus pool/takes checks, and stopped that failed run.
  `make-check-final.log` is therefore also intermediate, never a green receipt.
- FACT [L0] — Seal rerun log: `/tmp/metis-g5-gates.KgSGIx/make-check-seal.log`.
  Frozen source/test/schema/runtime roster digest after the test-only fix:
  `7b1f5c83480f0a9d8343abcef0ec58dadbc4ccbf0cb85c39e53cfc16ce885b14`.
  No production logic was changed for these two assertion failures.
- FACT [L0] — Final frozen rerun collected `4444` distinct tests. Code roster
  digest (`git ls-files --cached --others --exclude-standard src tests runtime
  schemas | sort | xargs shasum -a 256 | shasum -a 256`) is
  `1de85abd24f10506b4115a46b8c97a42e83c5e5ef92edf3acd96b22c31e10909`.
  Final log is `/tmp/metis-g5-gates.KgSGIx/make-check-final.log`; no successful
  complete verdict exists until its final ledger and process exit are checked.
- FACT [L0] — Independently reran the strengthened actual-retrieval dialogue,
  planner and budget suite: `191 passed in 2.38s`. Every Ready requires exact
  resolved grounding; unadmitted labels and extra unknown requirements cannot
  produce a Draft. There is no fixed-retrieval bypass in the revised journey.
- RISK [L1139/L0] — Synthetic initial phrasing containing `collezione` and
  `totali` remains unsupported by direct retrieval; the minimal equivalent
  request resolves. This linguistic/Flash/model qualification case is recorded
  in the client handover, not hidden by artificial descriptor aliases.
- RISK [L1142/L0] — Independent real-retrieval-at-every-turn probe exposed a
  pre-Draft third-message filter loss hidden by a fixed-retrieval journey
  fixture. The initial complete check was interrupted after 361.24s to avoid
  promoting mixed-code evidence; log `/tmp/metis-g5-gates.KgSGIx/make-check.log`
  is an interrupted intermediate run, NOT a final gate or timing baseline.
- FIX [L0] — Cumulative retrieval now re-resolves only the original reviewed
  request across fully covered adjacent server-admitted answers. After a
  Draft, pure answers retain only its private grounding; labels never add
  domain predicates. Quantity-only empty semantic text has no catalog
  evidence, rather than causing an index exception. Additional free text
  still rejects cumulative authority.
- FACT [L1142] — Independent no-fixed-retrieval probe: six natural messages
  through defer, page selection, quantity and confirmation reach Ready and
  permit/executor. Appending an additional exclusion returns unsupported,
  zero selections and cumulative rejected. L1139 is replacing fixed retrieval
  in the full natural journey before the final frozen rerun.
- FACT [L0/L1140] — The real compiler gate rejected `page_default` inside a
  named block. Source audit additionally proved that a pool-only endpoint can
  compile without emitting any response. Earlier compile-only receipts are
  insufficient evidence of useful output; neither failure was waived.
- FIX [L0/L1140] — First filtered CREATE now issues pool plus emitted variant
  with an exact use. Add-block also requires explicit response inclusion;
  multiple/conditional/parametric roots fail closed. `add_filtered_page`
  creates a direct root-variant page only; block quantities are total-only.
  New real-pin tests assert normalized-IR emission and preserve the illegal
  nested-page case as an explicit negative.
- FACT [L1139] — Actual natural-answer integration reports 7 operations,
  25 question rounds, 28 decisions and 32 history messages on renamed
  alpha/beta fixtures. Answers traverse adjudicator, claim/store, provider,
  original-authority issuer, permit/executor and renderer. No compiler/HTTP/
  model/VSIX evidence is inferred from this test.
- FIX [L0/L1139] — Generic defer rounds survive pure admitted chat answers,
  not new substantive requirements. Safe labels and complete paged rosters
  are exercised through the real resolver. V2 has 32 bounded question rounds
  and 32 decisions; v1 remains three rounds. History admits 64 short messages
  while retaining its previous total-byte allowance (20 x 65536 bytes).
- RISK [L0/L1138] — Current external VSIX still parses v1 clarification shape
  and sends v1 answers, with a three-round cap. This repository cannot claim
  VSIX G5 interoperability; a read-only-evidenced handover is in
  `docs/handover-g5-visix-dialogue-v2.md`. No external repository was modified.
- FACT [L0] — Independent focused rerun across structural/complex historical
  fixtures, descriptor generality, technical authority, tools and semantic
  retrieval: `266 passed, 2 skipped in 2.34s`. These two skips are real runner
  cases outside the authority harness, not compiler evidence.
- FACT [L1140] — Full-authority synthetic runner lane reports 29/29 passed,
  including two renamed pinned AST projections. L0 inspected runner/loader
  and strict-sidecar diff; final independent harness rerun remains mandatory.
- FIX [L0/L1139] — Product legacy provider options and recipes are removed;
  historical regression chains now live solely in `tests/legacy_*` fixtures.
  New nonremovable nested anchors are checked against original parent hash,
  endpoint-relative path and subtree, with explicit evidence on every leaf.
- FIX [L0/L1138] — All three source/repair ModelRequest paths omit private
  `technical_authority` and `catalog_reference_roster`. New dynamic tests cover
  initial generation, grounding repair and compiler repair.
- RISK [L1139/L0] — Generic dialogue audit identified pre-Draft correction reuse
  and unselectable rosters above 64. L0 added substantive-request round
  invalidation and complete paged choices; targeted regression tests pass in
  the delegated lane. End-to-end provider/engine gate is still open.
- FACT [L1138/L0] — Test-only pipeline optimization reuses a defensive copy of
  one freshly validated Foundation report solely in six downstream cases.
  Fresh end-to-end and contract mutation tests remain. No measured overall
  speedup is claimed before the full gate.
- OPEN [L0] — Generic operation engine, provider/plan/renderer integration,
  renamed synthetic compilation, final frontier review and complete `make
  check` still precede Git closure. No current complex live-demo or model
  qualification is implied by these receipts.

Make tenant generality and descriptor-derived knowledge constitutional and
executable properties of Metis Brain. Brain owns grammar-level structural
capabilities and safety invariants; the immutable active-tenant snapshot owns
catalog, field, value, alias and business-domain knowledge. No product path may
be made green by adding endpoint-, play-prod- or play-demo-specific shortcuts.

## Boundary

- Writable: Model 1 charter/design, Brain structural/semantic authority,
  focused tests, synthetic fixtures, this run board and session ledger.
- Read-only: repository history and vendored public/pinned tenant examples.
- Excluded: `.env`, keychain, credentials, live ARES/OpenSearch, VPN, raw
  production payloads, writes to Metis or tenant repositories, Apply, model
  execution, training, weight/adapter changes and external publication.
- Model routing: L0 owns architecture, semantic authority and promotion.
  Delegated lanes are read-only audits unless this board later assigns a
  disjoint writable surface explicitly.

## Constitutional gate

The wave is not green unless all hold:

1. The charter states that Brain code knows Metis constructs while tenant
   descriptors provide domain knowledge.
2. Product runtime code does not require a known tenant, catalog, field,
   literal, endpoint, fallback target or Italian phrase to authorize a generic
   structural capability.
3. Catalog/field/value selections are bound to reviewed Schema 2 descriptors
   (`label`, `means`, `aka`, domain/value-set and `semantics from`) from the
   immutable session snapshot.
4. Model-visible selections are opaque typed refs; Model 1 never gains path,
   raw endpoint, hidden template, compiler IR or unreviewed-value authority.
5. Two isomorphic synthetic tenants with disjoint catalog/field/value names
   produce equivalent canonical structure without a Python code change.
6. Renaming/removing/downgrading a descriptor invalidates the relevant
   authority and fails closed under the snapshot revision.
7. Existing qualified behavior remains regression-green; a tenant-specific
   qualification profile may stay specific, but cannot register runtime
   product authority.

## Plan

- G0: ratify the principle in the charter and delivery roadmap.
- G1: complete a product-runtime hardcoding census; separate legitimate
  benchmark pins, generic construct policy and forbidden domain assumptions.
- G2: specify a revision-bound descriptor authority contract and a generic
  capability registry boundary.
- G3: implement the smallest vertical slice that replaces one existing
  play-prod semantic roster with descriptor-selected typed refs while
  preserving the current Draft/compile contract.
- G4: prove anti-tailoring with two renamed synthetic tenants plus negative
  descriptor-state/revision/tamper tests.
- G5: migrate remaining closed recipes and only then add multiblock, pools,
  smart pages, search, injection, root rails, bounded fan-out and new
  similarity families as universal capability packs.
- G6: run focused, Brain-wide and repository gates; frontier-audit, commit,
  push and verify clean aligned `main`.

## Historical G5 extraction plan

Read-only dependency audit by L1136, accepted by L0 before this implementation.
Extraction is now complete; capability scope and remaining work are recorded
in the current delivery receipt above. The first-tranche gate was historical.

1. Preserve the six canonical legacy specs and historical 40-prompt classifier
   outside `src/metis_model1`, under test support. Preserve their historical
   hashes; do not reseal old qualification plans as evidence for the new default.
2. Extract closed domain constants, the four legacy intent builders,
   recognizers and `reviewed_semantic_index` from
   `brain_create_structural_authority_v2.py`. Preserve generic AST helpers,
   reviewed descriptor authority and the neutral intent/evidence types.
3. Remove `legacy_closed_recipes`, its branch and legacy-only question builders
   from `brain_create_authority_provider_impl_v2.py`. Remove the provider's
   legacy-only `exact_value_resolver` injection and its argument at server
   construction; retain the retriever's general exact-value lookup capability.
4. Rebuild the structural registry, reconstruction branches and import-time
   implementation manifest as descriptor-only. Test direct issuer rejection
   of former family IDs. Moving constants alone would not close this gate.
5. Migrate old positive product-issuer tests into historical fixture tests.
   Add import/package-boundary negatives: product must not import fixtures or
   offer a callback that re-registers closed recipes. Keep endpoint schema,
   combinators, renderer, plan, permit and executor behavior unchanged.
6. Run descriptor/provider, inventory, builder/combinator, plan/executor and
   transferred legacy tests, then `make check TEST_WORKERS=2`, including both
   real renamed-tenant compiler cases. Inspect changed inventory identity;
   old performance/complex-journey evidence remains explicitly historical.

Only after extraction expand general authority: explicit ordering/pagination,
then blocks/parameters, then similarity/grouping/fallback with attested roles.
Extraction closes package isolation only; complex capability coverage and
complex demo qualification remain separate OPEN gates.

## Wire

- FACT [L0] — User mandates continuation to conclusion. Preflight baseline is
  clean `main` at `61a6c472baeecad1148b0d3714e4ecb915d3f81a`, carrying the
  previous 4256-case complete gate. G5 starts with package extraction, then
  descriptor-derived structural capability work and an explicit residual-gap
  audit. Existing data/model/other-repository exclusions remain in force.
- OPEN [L0] — Current ownership: L1138 bounded mechanical structural-module
  extraction; L1139 frontier migration of historical tests and negative
  product-authority gates; L1140 read-only capability/descriptor contract audit;
  L0 provider/server deregistration, architecture, integration and closure.
- FACT [L1140/L0] — Current pinned AST/RuntimeCtx already exposes catalog id,
  similarity profiles and return projections; the missing path is a Brain
  projection, not new grammar. AST root `Model` is not a separately annotatable
  domain `@model` in this pin; do not invent such an authority.
- DECISION [L0] — Add an allowlisted, catalog-qualified technical sidecar to
  the Model1-owned semantic runner, without changing upstream Schema2 or the
  external Metis pin. Never serialize whole RuntimeCtx/settings/services.
  Bind original technical proof independently of candidate fragments and keep
  technical declarations distinct from reviewed editorial descriptors.
- OPEN [L0] — L1140 implementation scope is now only
  `runtime/metis_brain/runner.mts`, `src/metis_model1/brain_tools.py`,
  `src/metis_model1/brain_semantic_retrieval.py`, new
  `src/metis_model1/brain_technical_authority.py` and its focused tests.
  First sidecar roster: catalog identity, named similarity field/binding
  profiles and named returns, catalog-qualified; no endpoint bodies/IR or
  connection settings. L0 owns capability/dialogue consumers separately.

- DECISION [L0] — This is a generality correction, not another play-prod
  accuracy patch. Qualification corpora remain tenant-pinned evidence; product
  authority may not be derived from their expected endpoints or blueprints.
- FACT [L0] — Preflight is clean/aligned at `a640cc6`; the previous v4 run is
  `9/9` exact admitted Drafts but only `1/10` complete T4 journeys. The gap is
  predominantly closed structural authority, not model output quality.
- FACT [L0] — Existing Schema 2 retrieval already carries reviewed catalog,
  field and value `means`/`aka` projections under exact context, semantic and
  toolchain revisions. The current structural module nevertheless defines
  play-domain field names, literals, family keywords and `intrat_recent` in
  Python; this duplicates/bypasses tenant descriptors.
- DONE [L1126] — Product census: core lifecycle/issuer/builder are generic;
  the active closed-recipe layer embeds six play-domain fields, seven values,
  one similarity profile, pool topology and a fixed fallback. P0=0, P1=closed
  recipe/recognizer, P2=presentation and synthetic validation only.
- DONE [L1127] — Schema2 is authoritative for reviewed catalog/field/value
  identity, type, domain, `label`/`means`/`aka` and `semantics from`; it cannot
  by itself prove implicit identity, similarity, join, recency, grouping or
  routing roles. Minimal safe slice is finite reviewed predicates plus exact
  count; implicit roles remain ASK/STOP.
- DONE [L1128] — Builder, CreateDeltaPlan and permit chain are tenant-neutral.
  The narrow seam is structural authority before issuance. A fixed tenant
  binding would preserve case15 but would not satisfy D-017, so it is rejected
  as the product solution.
- DECISION [L0] — Ratify D-017. Implement the first descriptor-native vertical
  slice as a single-catalog filtered collection over finite reviewed
  selections and an exact count. Structural shape is confirmed through a
  server-bound choice; it is never inferred from a tenant phrase. Similarity,
  implicit deduplication, seed lookup, joins, pool topology and routing remain
  fail-closed until their roles have first-class authority.
- FIX [L0] — Ratified D-017 in the charter/roadmap and added the normative
  generality specification. The in-progress vertical slice accepts only one
  reviewed Schema2 catalog plus reviewed finite keyword selections, preserves
  exact context/semantic/toolchain revisions, creates a generic filtered block
  with an explicit total count and keeps concrete domain identities out of the
  model-facing authority projection.
- FIX [L0] — Product construction of `PinnedCreateV2AuthorityProvider` remains
  on the descriptor-native default. The pre-existing closed recipe roster is
  now behind explicit `legacy_closed_recipes=True`; only the legacy regression
  helper enables it. It is not yet removed from the product package, so G5
  remains open and the constitutional gate is not promoted.
- DONE [L1132] — `docs/31-metis-brain-typed-create-authority.md` now carries
  D-017, the descriptor-only authority boundary, opaque refs, typed ASK/STOP
  behavior and the first-slice/migration limits; `git diff --check` green.
- FACT [L0] — Last completed focused gate at the pause checkpoint:
  `uv run ruff check` on the three changed CREATE modules plus the touched
  legacy test is green; the three focused pytest files are `66 passed`.
  `git diff --check` is green. No full `make check`, model run, tenant read,
  compiler E2E, commit or push has been performed in this wave.
- OPEN [L0] — Resume in this exact order: (1) finish the two-renamed-tenant
  metamorphic/negative test file; (2) finish the provider ASK→Ready and
  model-projection privacy test; (3) complete frontier security audit of the
  new binding and reconstruction code; (4) decide whether legacy recipes must
  move physically out of the product package in this wave; (5) rerun focused,
  Brain-wide and `make check`; (6) inspect diff, update this board, commit,
  push and prove clean aligned `main`.
- STOP [L0] — User requested an application-update pause. All live delegated
  lanes were interrupted after their last completed write. No partial new test
  file exists; the working tree intentionally preserves the uncommitted wave.
  Resume baseline remains `a640cc6facd1b6ce7e6e838225c0d6c3e3080050`.
- FACT [L0] — User resumed the wave after the application update. Git HEAD
  remains `a640cc6`; every checkpoint file is present and no partial test file
  was found. The user pause is lifted; execution resumes at G4 and the
  independent authority audit.
- FIX [L0] — Adversarial review found candidate-derived semantic/count
  authority and stale structural-choice reuse. Validation now requires the
  separately held original reviewed index and exact count; semantic leaf
  origins/identities must match. Confirmation binds filters, count, inventory
  and covered dialogue history. New requirements trigger a superseding ASK.
- FIX [L0] — `any_of` is mandatory for multivalue alternatives; duplicate
  field selections and duplicate value evidence fail closed. Count replacement
  uses the latest bound decision. Choosing an unsupported complex structure
  returns an explicit unsupported result instead of repeating the question.
- FIX [L0] — Catalog short-name uniqueness is checked against the complete
  compiler-derived Schema2 catalog roster, including unreviewed catalogs. The
  roster enters the semantic proof. The product slice uses no source-regex
  reconstruction of the catalog namespace.
- DONE [L1134/L0] — Synthetic metamorphic/retrieval tests:
  `in=17 out=17 distinct=17 gaps=0`. Renamed meanings/aliases resolve through
  real Schema2 retrieval; a draft catalog with the same short name prevents
  emission; descriptor, count and evidence tampering fail closed.
- DONE [L1135/L0] — Provider/dialogue tests:
  `in=14 out=14 distinct=14 gaps=0`. Includes opaque model payloads, exact
  count replacement, stale confirmation, unsupported structure and catalog
  collision. L0 independently reran both new test files together: 31 passed.
- FACT [L1137] — Two synthetic tenants traversed intent → issuer → plan →
  one-shot permit/executor → render → real pinned compiler successfully.
  L0 subsequently annotated the synthetic source descriptors and strengthened
  missing-environment failure handling; final rerun is part of `make check`.
- FACT [L1136] — Independent frontier re-audit reproduced rejection of the
  original literal, origin and count forgery cases and stale-history reuse.
  No residual P0/P1 confirmed in the bounded generic slice. G5 remains OPEN;
  this does not attest full generic structural coverage or complex demo readiness.
- FACT [L0] — `make validate validate-pilot lint format-check` completed
  successfully; full `make check TEST_WORKERS=2` is running. Historical
  promotion-readiness blockers printed by validate-pilot remain separate from
  the repository's contract-validity result.
- RISK [L0/L1137] — First full gate is RED, not completed: both new compiler
  cases reached the real pin verifier and failed because the disposable Brain
  Git authority lacked `refs/remotes/origin/main`. The completed shard reported
  `1605 passed, 2 failed, 2 skipped`; L0 interrupted the remaining shard after
  `1239 passed` to avoid finishing an already-invalid run. Harness cleanup
  completed with exit 2. These partial counts are not a full-suite verdict.
- OPEN [L0] — L1137 now owns the bounded harness correction in
  `src/metis_model1/test_harness.py` and `tests/test_test_harness.py`: preserve
  the already verified remote-ref commit in the disposable Brain authority,
  include it in drift checks, and leave the production verifier unchanged.
  Rerun focused real compiler checks and the complete gate after this fix.
- FIX [L1137/L0] — The disposable Brain test authority now preserves the
  verified receipt's exact `refs/remotes/origin/main` target and checks its
  ancestry/identity before and after execution. Oracle isolation stays
  unseeded. No source ref, production verifier or runtime pin was changed.
- FACT [L1137] — Harness/ledger focused suite: 43 passed; lint, format and
  diff checks green. Added invalid/missing/non-ancestor/ref-drift/deletion
  cases and direct source-ref preservation assertions. L1136 static audit
  GREEN with no P0/P1; L0 independent rerun and real compiler run in progress.
- DONE [L0] — Independently reran harness/ledger suite: 43 passed. Corrected
  full-authority harness then executed both synthetic real-compiler cases:
  `in=2 out=2 distinct=2 gaps=0`, exit 0. Root confirmed source annotations,
  exact count and `eq`/`in` predicates. Compiler log (local, not Git):
  `/tmp/metis-brain-generality-gates.R08PLb/compiler.log`.
- FACT [L0] — Final `make check TEST_WORKERS=2` restarted on the frozen code;
  log: `/tmp/metis-brain-generality-gates.R08PLb/make-check.log`. L1136 is
  preparing a read-only, dependency-ordered G5 handoff during the gate; no
  further production changes are authorized until this tranche is sealed.
- FACT [L1137/L0] — Read-only performance follow-up: `validate_pilot` calls
  full `validate_foundation` on every invocation (`pipeline.py`); eight direct
  pilot/CLI invocations appear in `test_pipeline.py`. Foundation also performs
  repeated tracked/unignored file boundary scans (`contracts.py`,
  `validate_repository_file_contents`). L0 verified these call sites; no live
  profiling was performed, so this is a redundancy finding, not measured
  attribution of the whole slow-shard duration.
- OPEN [L0] — Test-only optimization candidate, separate from frozen code:
  keep fresh end-to-end foundation/pilot and mutation gates; only narrowly
  targeted downstream fixture-mutation tests may consume a defensive copy of
  one prevalidated foundation fixture. Prove equivalent negative outcomes and
  benchmark the change before accepting it. Never cache production boundary
  scans across calls or weaken pin/freshness/TOCTOU guards.
- DONE [L0] — Final `make check TEST_WORKERS=2` completed with exit 0.
  Exact ledger: `in=4256 out=4256 distinct=4256 gaps=0 passed=4254 skipped=2
  failed=0 error=0 xfailed=0 xpassed=0 workers=2`. Shards reported
  `1611 passed, 2 skipped`, `1621 passed`, and `1022 passed`. All new real
  compiler tests executed; no missing-authority skip was accepted.
- FACT [L0] — Persistent ignored gate artifacts are in
  `artifacts/brain-generality/2026-09-05/`. SHA256:
  `compiler.log` = `97dedfa836d8baebff4e1d34338ce7dfa915d78569b4c206e5b55ba65113a396`;
  `make-check.log` = `95e2c79cdd8b4d1b72639fac07a19123bc3a7583a0c0e04886252f4232e4f7a2`.
  L0 checked both are ignored by Git. No weights, training, live data, tenant
  writes, Apply or other repository changes were involved.
- DONE [L0] — First-tranche integration gate is verified: reviewed descriptor
  selections, exact count, bound confirmation, renamed-tenant parity,
  adversarial rejection, isolated real compilation and full regression ledger.
  G5 extraction/capability migration remains OPEN. Historical complex-journey
  scores are not product-readiness evidence for the new default. Final Git
  delivery is the commit containing this receipt; publication/alignment must
  be checked independently, not inferred from this entry.
