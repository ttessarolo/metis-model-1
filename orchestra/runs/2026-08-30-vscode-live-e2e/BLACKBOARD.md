# Metis Brain VS Code live E2E blackboard

## Objective

Deliver the first installable VS Code proving slice: an authorized `@metis`
participant opens the already-selected `play-demo` tenant session, uses the
existing local Model 1 MLX runtime plus reviewed schema-2 catalog semantics,
generates a bounded `.metis` proposal, compiles it with the pinned Metis
toolchain, and shows progress plus preview without autonomous tenant writes.

## Scope

- IN — existing local Qwen3.8/adapter runtime wiring, session-bound semantic
  retrieval, Brain orchestration, VSIX build/install artifact, and one real
  VS Code consumer smoke.
- QUEUED — Metis Fast, standalone Mac installer, updater, signing/notarization,
  Windows, remote inference fallback, palimpsest/channel publication, and
  autonomous application.
- STOP — credentials, `.env`, Keychain, raw live/production data, external
  tenant writes, weight mutation, training, and unpinned or silent model
  download. Existing local model artifacts may be read and loaded only through
  their already-qualified manifest/runtime path.

## Preflight

- FACT — Model 1 baseline is clean `main@e1124f9bc1d7654b01a227f66c7e6113505baf7d`.
- FACT — Metis/Visix baseline is clean `main@c9f410a9b9b28e61dd1505b661ebc996e388e6e0`.
- FACT — The isolated Visix worktree
  `/Users/tommasotessarolo/Developer/ares-matioska/metis-brain-visix` is at the
  same commit on `codex/metis-brain-visix`; it is the only writable Metis lane.
- FACT — `play-demo` is clean and aligned at
  `main@44aa8ec170003b3822db71cb9443c8e7db9e3dd0`; the tenant remains read-only
  during Brain and VS Code validation.
- DECISION — The only demo checkout authorized for this wave is the checkout
  already open in VS Code,
  `/Users/tommasotessarolo/metis-tenants/play-demo`. The separate
  `/Users/tommasotessarolo/Developer/play-demo` clone has the same Git commit
  and tree but is not a Brain input and is not modified or relied upon.
- DECISION — L0 frontier owns runtime identity, prompt/retrieval truth,
  compiler-loop integration, real E2E evidence, promotion and final claims.
  Delegates own only bounded census or disjoint mechanical surfaces.

## Acceptance contract

1. Brain loads the already-qualified local Model 1 base/adapter once and
   reports their pinned identities; unavailable or mismatched artifacts fail
   closed without falling back to Ollama or a remote provider.
2. Retrieval is derived exclusively from the immutable session snapshot,
   follows native `semantics from @catalog`, exposes reviewed fields/values,
   quarantines drafts, and asks for catalog clarification only on real
   ambiguity.
3. A real `play-demo` request reaches Model 1, returns a bounded `.metis`
   candidate, and receives a real pinned compiler receipt; repair is bounded
   and compile-clean is not promoted to semantic correctness.
4. A newly packaged VSIX contains the `@metis` participant and Brain client,
   can be installed without source-worktree maneuvers, and one real VS Code
   consumer process completes session -> turn -> candidate -> compile ->
   preview.
5. No Brain path writes the tenant. Applying a proposal remains an explicit
   client preview/confirm/CAS action and is not required for this smoke.
6. Focused adversarial gates, repository-native gates, artifact-content checks,
   hashes, commit/push and post-push clean alignment are recorded before
   closure.

## Status

`STOP_SEMANTIC_DRAFT_REWORK`

## Evidence wire

- FACT — The previous wave pushed the protocol foundation in Model 1, native
  `@metis` Chat Participant in Metis, and first-class `semantics from`; it did
  not wire a production MLX runtime or schema-2 retriever and did not produce a
  real non-fake VS Code turn.
- DONE — L90 runtime census `in=3 out=3 distinct=3 gaps=0`: qualified
  Python/MLX runtime, 16.05 GB pinned base checkpoint and 233.58 MB selected
  step-50 adapter are all present locally. The worker loads once, speaks
  bounded JSONL and is neither Ollama nor remote. The missing surface is one
  persistent `BrainModelRuntime` adapter and lifecycle closure.
- FACT — The qualified base is
  `mlx-community/Qwen3.8-27B-4bit@3e6447f082e89cc7f0bc6e5441afd38dfce760ff`;
  the selected adapter payload is
  `sha256:5e65a0b48531ce9e2a9751c201f570f8793da87bd2a2a9446f461dbe0589dcfb`.
- DONE — L91 semantic census `in=6 out=6 distinct=6 gaps=0`: immutable
  session capture, strict schema-2 parser, describe/values projection join,
  semantic index v2, reviewed context registry and host-owned grounding
  adjudicator already exist. `SnapshotRetriever` is only a regex census and
  must be replaced by an adapter bound to the exact session snapshot.
- RISK — A semantic bundle revision is not identical by definition to
  `ContextSnapshot.semantic_source_revision()`. The implementation must bind
  the validated bundle to the snapshot membership explicitly and fail closed
  on drift; it may not substitute one hash for the other.
- DONE — L92 VSIX census `in=3 out=3 distinct=3 gaps=0`: current Metis source
  contains the native participant, controller and session client, but the
  tracked `metis-dsl-0.23.93.vsix` predates them and contains no
  `chatParticipants` contribution. A newly built artifact and content audit
  are mandatory.
- FACT — The current example Brain config authorizes neither the `play-demo`
  tenant nor client `visix` chat capabilities. A bounded, non-secret local
  demo config and matching extension settings are required before the smoke.
- DECISION — Implementation lanes remain disjoint: L90 owns the persistent MLX
  runtime adapter and unit tests; L91 owns the snapshot-bound schema-2
  retriever and tests; L92 owns only the isolated Metis worktree packaging and
  consumer harness. L0 owns config/service wiring, prompt semantics and the
  real live run.
- DONE — L90 runtime implementation `in=3 out=3 distinct=3 gaps=0`: the
  qualified Python worker, pinned base and selected adapter are wired through
  a persistent bounded JSONL runtime. The worker digest is rechecked before
  spawn/recycle; cancellation, deadline, process-group termination, bounded
  close and pre-cap recycling are covered. Ollama and remote fallback are not
  present.
- DONE — L91 retrieval implementation `in=6 out=6 distinct=6 gaps=0`: exact
  immutable snapshot membership and semantic revision are checked, native
  semantic ownership/mirrors are honored, drafts and open domains cannot
  ground, and every material clause must resolve before Model 1 or the
  compiler may run.
- DONE — L92 VSIX implementation `in=3 out=3 distinct=3 gaps=0`: version
  `0.23.94` packages the native `@metis` participant, controller, session
  client and all three Brain settings. The final artifact is 685242 bytes,
  SHA-256
  `4489cd6f8cc183c8f4fe5f1e65b1c22ee01145769f11a27aae7406bf3a6e2d38`,
  with 13 archive entries; its content gate and extracted tenant validation
  pass. The artifact is reproducible/ignored and is not committed as source.
- FACT — VS Code reports `metis.metis-dsl@0.23.94`, Metis serve `0.3.45`, the
  visible `play-demo` checkout on `main`, and zero workspace problems. The
  configured Brain executable, non-secret demo config and `visix` client open
  the local service on numeric loopback.
- DONE — Real fail-closed guard `in=1 out=1 distinct=1 gaps=0`: the request
  containing black-and-white films, awards, Italy, open endings and
  masterplot revenge completed as `unsupported_metadata`; unresolved clauses
  were `vinto premi` and `finale aperto masterplot revenge`. Model 1 remained
  unloaded, the compiler was not invoked, and `tenant_modified=false`.
- DONE — Real supported API E2E `in=1 out=1 distinct=1 gaps=0`: the request for
  black-and-white films produced in Italy resolved `play-demo.video`,
  `tipologia=Film`, `genere_mcm=Bianco e nero` and the reviewed Italy value
  variants; local Model 1 generated a candidate and the pinned compiler
  accepted it in one attempt with zero diagnostics. Compiler receipt is
  `sha256:d837a288e202d09c4dda4e958251a13e05af3fa954726c6381bbbe68c8a2c33d`;
  candidate source is
  `sha256:ea70758209b344e99c2bd6ce0036424345d0a88a05c63ff451e33611e87b918c`.
  The receipt explicitly keeps `semantic_correctness=false` and
  `tenant_modified=false`; compile-clean is not promoted to accuracy truth.
- FACT — That live session was bound to context revision
  `sha256:906a1e926d8be2fa3a6da902b98d29b3cf231ad4b9c04e366e3bed1748db865d`,
  semantic revision
  `sha256:81859c0f89389798340026d2d618d40efec8708cd39b825005847eb0a9e9279d`
  and toolchain binding
  `sha256:abe518496a49c4e261c013968f264691226bc8026d268d93791ebf83842dd41c`.
- FIX — The generation contract now requires the smallest compiler-valid
  change and forbids unrequested filters, ordering, ranking or business rules;
  this closes the extra-ordering defect found by L0 in the first API sample.
- FIX — Brain startup now removes a partial bootstrap token and its private run
  directory when token creation, write, sync or permission setup fails; the
  synthetic failure test passes and leaves `in=1 out=0 gaps=0` run dirs.
- FACT — The real VS Code `@metis` request opened the already-selected tenant,
  selected the video catalog, loaded the exact local Model 1 identities and
  reached the real compiler. Health after completion reports
  `model_loaded=true`, `compiler_executions=1`, `in_flight=0` and one active
  session. The Mac locked before L0 could inspect the rendered proposal and
  open its preview diff; no Apply action was taken.
- FACT — Once unlocked, VS Code rendered the proposal in 3m03s with the three
  reviewed mappings and the explicit warning that semantic correctness remains
  editorial. The first `Apri diff` smoke then found a real client defect:
  creation was hard-coded to `properties/play`, which does not exist in the
  demo tenant, so the compiled candidate could not be opened for comparison.
- FIX — The Visix client no longer assumes a production namespace. It derives
  confined existing endpoint areas from the selected tenant and derives their
  logical namespaces from actual endpoint declarations, never from the path.
  It auto-selects the sole `{directory: demo, namespace: demo}` area here,
  asks only when more than one real area exists, and passes both
  `properties/demo/<name>.metis` and the qualified `demo.<name>` endpoint to
  Brain. Symlink/empty/invalid areas are excluded;
  targeted chat tests, typecheck, the package-content gate and packaged
  validation of 170 endpoints all pass. Diff command errors are now surfaced
  to the operator rather than disappearing in the extension-host log.
- RISK — The isolated toolchain deliberately rehashes and copies roughly 199
  MB / 17312 dependency files per operation. This is safe and functionally
  green but makes the first local turn slow; caching or a read-only shared
  authority is queued as a separately reviewed performance wave and must not
  weaken the existing pin, sandbox or before/after drift checks.
- FACT — Independent final audits report P0=0. Runtime, semantic retrieval,
  VSIX contents and static/focused toolchain boundaries are green. The focused
  toolchain audit passed 48 tests; the aggregate focused Model 1 suite passed
  110 tests before the bootstrap-cleanup addition, and the server suite then
  passed 17 tests after it.
- DONE — Authoritative Model 1 gate `in=2259 out=2259 distinct=2259 gaps=0`:
  `make check` completed with 2259 passed, 2 expected skips and zero failures;
  foundation contracts, pilot checks, Ruff and formatting were also green.
- DONE — The second real VS Code smoke reached the corrected target
  `properties/demo/metis_brain_vscode_demo.metis`, opened the virtual proposal,
  kept the physical tenant file absent and left the tenant clean. L0 and the
  operator both inspected the rendered source; no Apply action was taken.
- FACT — The rendered create proposal was presented as an empty-file diff even
  though the Brain wire already identifies it as `operation=create`. New files
  require a single-document Draft surface; only `operation=replace` is a real
  before/after diff.
- FACT — The rendered country predicate contained all four reviewed literals
  currently grouped by the shared natural-language aliases for Italy:
  `ITALIA`, `Italia`, `italia`, and `val ITALIA val`. The last literal is not a
  model invention: it is a reviewed reflected value in
  `catalogs/video.values.metis`, so schema-2 and the deterministic retriever
  authorized it.
- STOP — The operator's editorial review rejects serialized storage artifacts
  such as `val ITALIA val` as acceptable natural-language grounding output.
  Compile-clean and complete alias expansion therefore do not close the E2E.
- DECISION — Serialized `val ... val` country literals remain audit-visible but
  are quarantined from grounding as `draft` until an authoritative
  normalization contract can preserve their recall without exposing storage
  encoding in authored `.metis`. The seven matching `paesiorigine` members are
  the exact bounded correction roster; no other catalog values change.
- DECISION — Brain adds a deterministic post-generation grounding adjudicator:
  every finite predicate must match exactly the reviewed selection and its
  field cardinality. Scalar fields lower to `is`/`in`; multi fields lower to
  `has`/`has any`. Omission, duplicate, extra, wrong operator, unauthorized
  field/catalog or unsupported condition surface trigger bounded repair and
  ultimately fail closed before the compiler.
- OPEN — Closure now requires the seven-value quarantine, post-generation
  adjudicator, create-Draft UI, focused/full gates, a rebuilt/reinstalled VSIX,
  one final no-Apply VS Code smoke, commit/push alignment and process cleanup.
- DONE — Tenant correction roster `in=7 out=7 distinct=7 gaps=0`: all
  `paesiorigine` literals serialized as `val ... val` are retained as visible
  `draft` audit data and their natural aliases are removed. Semantic commit
  `bef4071d3dc21198b7f68617e2ec9bef77d037c7` is pushed; current clean tenant
  head `bfd6cbe4c7b06cc00a2493eac34db02887bc997b` changes only experiment state
  and retains semantic blob
  `67c7353aa893499d8bbe3ae1eed8032ddbc80b20`.
- FACT — Current `@video` denominator is 49 finite fields / 1792 values:
  `reviewed=1775 draft=17 unannotated=0`. `paesiorigine` is 182 values with
  `reviewed=175 draft=7`; exact phrase `prodotti in Italia` now resolves only
  `ITALIA`, `Italia`, `italia` and never `val ITALIA val`.
- FIX — Schema-2 already contained exact field `type` and `modifiers`, but the
  intermediate semantic-index v1 intentionally omitted them and the Brain
  context silently emitted `type=null, modifiers=[]`. Retrieval now keeps a
  separately validated projection-bound technical roster, checks its exact
  membership against the index, and propagates cardinality to both model
  context and grounding selections without changing the canonical v1 index.
- FACT — The candidate guard recognizes the complete finite literal surface
  currently authorized by Brain, treats comments as token trivia, permits
  valid inline `if` guards, validates authorized source catalogs, and rejects
  negative/similarity/preset/ids/other ungrounded conditions. Focused guard,
  retrieval, orchestrator, turn and equivalence suites pass `in=83 out=83
  distinct=83 gaps=0`; all Brain suites pass `in=170 out=170 distinct=170
  gaps=0`. Independent final reaudit and the full repository gate remain open.
- DONE — Create-Draft UX is independently GREEN. Metis main contains
  `53008910f7ea0f842900a74be17f5db149cb1a1e` and
  `c1919ad8a3500b84a9f1f692e43a37bcff3f6b53`; VSIX `0.23.95` is installed.
  Create opens `Bozza - <file>.metis` as one virtual document, replace retains
  native diff, and Apply is guarded by existence/hash/version/dirty checks plus
  a per-URI mutex. Deterministic unpacked package digest is
  `sha256:bbf315bd8b7f8f5e5269813e0837f189bf5e04f5ed75c729137e858920ea0e4c`.
- RISK — The old execution-projection manifest and hash `adde34…` are historical
  evidence for tenant `6d6ce2c…`, not a current receipt. First-class
  `semantics from` now materializes inline execution values and the generic v1
  join rejects that surface. Current execution projection remains
  `UNVERIFIED` until an explicit v2 policy/join/receipt is implemented; the v1
  manifest is deliberately left unchanged.
- DECISION — Interactive Brain clarification is the next product wave, not a
  model improvisation. Questions are server-owned, typed, revision-bound and
  asked only for concrete ambiguity. Required cases include catalog and
  semantic choice; tenant defaults cover low-risk result count/response shape,
  while material fallback/topology choices may ask. Budget: at most three
  blocking questions, no repeats, assumptions visible in the Draft, refine
  always available. Existing catalog clarification is the seed; pending
  clarification identity must be server-bound before generalization.
- DONE — Independent final candidate-guard reaudit is GREEN with P0=0, P1=0
  and P2=0. The focused candidate/retrieval/orchestrator/turn/equivalence
  roster passes `in=95 out=95 distinct=95 gaps=0`; the complete Brain roster
  passes `in=180 out=180 distinct=180 gaps=0`.
- FIX — Transaction output types are now checked before the expensive Phase-B
  bundle build. A pre-existing FIFO, symlink, directory or hard-linked leaf at
  either manifest or bootstrap destination fails closed without reading it or
  entering materialization; the authoritative post-build identity/content/mode
  checks remain in place for race safety. The focused FIFO roster passes
  `in=5 out=5 distinct=5 gaps=0`; independent audit is GREEN with P0=0, P1=0
  and P2=0.
- DONE — Superseding authoritative Model 1 gate
  `in=2319 out=2319 distinct=2319 gaps=0`: a clean `make check` run completed
  with 2319 passed, 2 expected skips, zero failures; foundation contracts,
  pilot checks, Ruff and formatting were green. This supersedes the earlier
  2259-test evidence after the added guards and regressions.
- FACT — Final no-Apply VS Code smoke is running against installed Metis VSIX
  0.23.95 and the clean `play-demo` main tenant. The requested physical target
  remains absent and the tenant remains clean. The Mac locked while the new
  request was completing, so rendered `Apri bozza` content is not yet observed
  and no UI closure is claimed. VPN remained down; no credentials or live data
  were accessed.
- FACT — The first v0.23.95 retry was invalid as a product smoke because the
  automation duplicated the chat participant (`@metis @metis ...`). It still
  exposed a separate deterministic defect: explicit `@play-demo.video` was
  recognized for catalog selection, then the grounding scrubber removed the
  short suffix `@video` first and left `play-demo` as a false unresolved
  semantic clause.
- FIX — Grounding now masks fully-qualified catalog surfaces before short-name
  suffixes, including both `@play-demo.video` and textual catalog forms. The
  qualified regression remains `resolved`, with zero unresolved clauses and
  the expected reviewed selection. Independent audit is GREEN with P0=0,
  P1=0 and P2=0; the focused Brain roster now passes
  `in=96 out=96 distinct=96 gaps=0`.
- DONE — Final authoritative gate after the qualified-catalog fix:
  `in=2320 out=2320 distinct=2320 gaps=0`, 2 expected skips, zero failures in
  3027.41 seconds. Foundation validation passed 85 checks over 536 files;
  pilot contracts, Ruff and formatting were green. This supersedes the
  preceding 2319-test gate.
- FACT — The corrected no-Apply request used exactly one `@metis` participant,
  explicit `@play-demo.video` and target `demo.metis_brain_vscode_demo`. It
  advanced past retrieval into local Model 1 generation; the worker returned
  idle. The physical target remains absent and the tenant remains clean. The
  Mac locked again before the rendered outcome could be inspected, therefore
  `Apri bozza` and the final source text remain honestly unobserved and the UI
  STOP is not lifted. VPN remained down throughout.
