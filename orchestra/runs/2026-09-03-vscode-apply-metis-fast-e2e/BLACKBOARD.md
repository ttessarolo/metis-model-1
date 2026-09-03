# VS Code Apply and Metis Fast real E2E

Status: **CLOSED — SOFTWARE GREEN; LIVE UI/CONTENT ACCEPTANCE DEFERRED**

## Mandate

Resume the Mac product path after the Git environments/variants delivery. Close
the remaining product boundary in the smallest safe order:

1. verify the installed VS Code Draft -> explicit Apply -> post-apply compile
   contract without granting Brain write authority;
2. update Metis Fast from its legacy shell to the current universal Brain turn
   protocol;
3. exercise a real multi-turn Brain flow with clarification, refinement,
   grounded `.metis`, compilation and preview;
4. identify and implement the bounded client-owned acceptance/runtime seam
   needed to create the demo fast channel;
5. preserve current model, adapter, tenant semantics and local-first security.

## Preflight

- Model 1 repository: `/Users/tommasotessarolo/Developer/metis-model-1`;
- Model 1 baseline: `39560fa31488bc4f090c0acb7ecad5119ec92861`,
  clean `main`, aligned `0/0`;
- Metis repository: `/Users/tommasotessarolo/Developer/ares-matioska/metis`;
- Metis baseline: `bc2ce746c40e147cbacaa3fd662da2e070e80f00`, clean
  `main`, aligned `0/0`; released editor tag `editor-v0.24.0` points to
  `aa583efa1b094fcb95813b51b6ec863984392119`;
- Metis Fast repository: `/Users/tommasotessarolo/Developer/metis-fast`;
- Metis Fast baseline: `ee9e05bc167af3a19268d00a71d076ad908bf03a`,
  clean `main`, aligned `0/0`;
- canonical Brain demo tenant:
  `/Users/tommasotessarolo/metis-tenants/play-demo`, clean `main`, aligned
  `0/0` at `27e4b118ce9b7592b65d22037a7665b3b286b096`;
- installed VSIX observed by process census: `metis.metis-dsl-0.24.0`;
- new source role: Metis `examples/play-prod-v2` remains at the same path but is
  a vendored fixture from `metis-tenant-play-prod` commit
  `8d81d7492dfa45c5fe4d8f1152c9f7e3662b0759`, recorded by
  `.vendored-from.json`, date `2026-09-03`, tooling `0.24.0`;
- existing historical Model 1 source SHAs remain valid; no re-vendor, manifest
  rewrite, dataset regeneration or retraining is required by this role change.

## Authorities and exclusions

- Brain may retrieve, generate and compile against its immutable session
  snapshot; it never writes a tenant.
- Draft, consent, CAS, filesystem mutation, post-apply compile and undo belong
  to the client.
- No write to canonical `play-demo` is authorized during census or automated
  tests. Apply tests use a disposable isolated fixture until the owner
  explicitly starts the installed UI gate.
- No live ARES/OpenSearch, VPN, credentials, `.env`, Keychain, remote fallback,
  model download, training, S3 mutation, Windows work or persistent memory.
- The two current detached experiment worktrees under `metis-tenants` and the
  second historical `/Users/tommasotessarolo/Developer/play-demo` clone are
  outside this wave and remain untouched.
- `npm run tenant:vendor` is not run unless a future explicit source-pin change
  is ratified; if run, baseline, ledger and current-state regeneration must be
  in the same Metis commit.

## Required source documents

- `docs/00-charter-and-decisions.md`;
- `docs/06-delivery-roadmap.md`;
- `docs/19-local-companion-and-vscode-direction.md`;
- `docs/22-metis-brain-session-wave.md`;
- `docs/23-metis-brain-local-runbook.md`;
- `docs/25-catalog-semantic-completion-backlog.md`;
- `docs/26-metis-brain-interactive-session-wave.md`;
- `docs/27-metis-brain-local-latency.md`;
- Metis `STATO-CORRENTE.md` and
  `docs/piano-metis-brain-vscode-chat.md`;
- Metis Fast `README.md` and current typed client/UI sources;
- Ares/Metis handover
  `blackboard/git-ambienti-varianti-nota-team.md`.

## Exit gates

1. `VENDORED_SOURCE_ROLE_SAFE`: the role change is represented without moving
   the path or invalidating historical manifests.
2. `VSIX_APPLY_CONTRACT_GREEN`: disposable-fixture tests prove explicit consent,
   CAS, exact target, post-apply compile, stale rejection and bounded undo.
3. `FAST_BRAIN_PROTOCOL_CURRENT`: Metis Fast uses turn schema 2 and the
   universal `/answer` route for every advertised typed question.
4. `FAST_REAL_BRAIN_DRAFT_GREEN`: a real local multi-turn flow returns an exact,
   grounded and compiler-clean Draft with `tenant_modified=false`.
5. `FAST_ACCEPTANCE_BOUNDARY_GREEN`: acceptance remains client-owned and cannot
   mutate without a valid proposal/preflight/base/revision tuple and explicit
   operator action.
6. `FAST_DEMO_CHANNEL_E2E_GREEN`: the accepted endpoint feeds the application
   preview and creates the bounded demo channel/palinsesto without moving those
   responsibilities into Brain.
7. Focused suites, package/build gates, authoritative applicable repository
   gates, diff review, clean-tree and remote alignment are green before closure.

## Evidence wire

- FACT — The 2026-09-03 handover was inspected at the live Metis main. The
  vendored sidecar contains exactly schema v1, tenant repository, 40-hex source
  SHA, date and tooling version. The Model 1 path remains unchanged.
- DECISION — The vendored-role change is provenance-only for this wave:
  historical manifests keep their original monorepo source revision and future
  measurements must record both monorepo revision and `.vendored-from.json`
  tenant revision.
- FACT — The canonical Brain config resolves `play-demo` to
  `/Users/tommasotessarolo/metis-tenants/play-demo`; the separate Developer
  clone is stale and is not an authority for this wave.
- RISK — Metis Fast `main` is a legacy schema-1 shell. Its current clarification
  contract represents only `catalog` and resubmits the original turn instead of
  using the universal server-owned answer route.
- RISK — The installed VS Code evidence proves compiled Draft only. Apply,
  post-apply compile and undo remain a distinct gate and no canonical tenant
  mutation is authorized by this preflight.
- OPEN — Complete the three read-only lane censuses and freeze disjoint writable
  surfaces before implementation.
- DONE — Read-only preflight census `in=3 out=3 distinct=3 gaps=0` completed.
  The VSIX Apply implementation already covers preflight, target/base/document
  guards, immediate CAS, workspace edit/save, candidate hash, fresh session,
  post-apply compile and rollback, but lacks an executable unit gate, explicit
  Undo receipt and restored-preimage compilation on rollback. Metis Fast is a
  clean schema-1 proposal shell and cannot parse the current schema-2 terminal
  or SSE envelopes. The runtime/player lane confirmed that real content
  execution, preview, channel state and palinsesto publication do not yet exist.
- DECISION — Implementation is split into two disjoint temporary worktrees:
  Metis/VSIX Apply closure at
  `/Users/tommasotessarolo/Developer/ares-matioska/metis-brain-apply-e2e-20260903`
  and Metis Fast protocol/E2E at
  `/Users/tommasotessarolo/Developer/metis-fast-brain-e2e-20260903`. Both start
  from the exact clean baselines above. They must be integrated to their own
  `main`, verified and removed before the wave closes.
- RISK — A real preview through the PostgreSQL execution mirror cannot claim
  `@video_pg` correctness while the current semantic projection receipt remains
  `UNVERIFIED`. Draft/compile against `@video` is unaffected. The runtime lane
  must either close the v2 projection receipt or explicitly remain an
  `@video`-only non-PG demo; it may not silently bypass this boundary.
- OPEN — L804 is implementing the bounded VSIX Apply/rollback/Undo contract in
  its isolated worktree. L805 is implementing the current universal Brain
  protocol and multi-turn UX in the isolated Metis Fast worktree.
- FACT — The current canonical tenant at `27e4b118` declares
  `video_pg semantics from @video`; a direct current schema-2 census exposes 40
  projected fields, 18 finite domains and 57 inline literals. The remaining
  qualification gap is in the Model 1 projection receipt: v1 rejects every
  execution-side materialized finite domain instead of proving exact ordered
  compatibility.
- OPEN — L806 is building a non-destructive v2 projection receipt that accepts
  materialized finite domains only after exact kind, size, nature, literal
  order and value-semantics comparison with the canonical source. It may not
  mutate either tenant or rewrite the historical v1 evidence.
- DONE — L805 universal Brain protocol implementation
  `in=5 out=5 distinct=5 gaps=0`: Metis Fast now sends schema-2 turns, answers
  every typed clarification kind through the server-owned `/answer` route,
  preserves proposal-based refinement, consumes the current SSE roster and
  deterministically reopens an expired/stale session. Independent coordinator
  replay: `pnpm test` = 7/7, `pnpm typecheck` = PASS, `pnpm build` = PASS. The
  client remains preflight-only and has not written a tenant.
- OPEN — L807 is extending that read-only shell into a trusted local Fast
  gateway. The browser must not receive upstream Brain credentials or any host
  filesystem authority; accepted proposals are materialized and executed only
  in a volatile per-session tenant snapshot until a later, separately
  authorized canonical persistence wave.
- DECISION — The normative ownership, BFF credential virtualization,
  acceptance tuple, volatile snapshot, runtime, preview, channel state machine
  and separate deterministic/live claims are frozen in
  `docs/29-metis-fast-trusted-runtime.md`. Browser-supplied source or paths are
  never acceptance authority.
- FACT — A warm Brain process is currently present and listens on loopback, but
  the configuration loaded by that process grants only client `visix`.
  The tracked non-secret fixture now grants an equivalent, separately named
  `metis-fast` client; the running process must be deliberately restarted only
  when the real Fast HTTP gate begins. No bootstrap file or token was read.
- DONE — L804 VSIX Apply closure `in=6 out=6 distinct=6 gaps=0` independently
  replayed by L0: create/replace Apply, immediate CAS, post-apply compile,
  compile-failure rollback, restored-preimage compile and explicit Undo all run
  through the actual `MetisChatApply` class under the VS Code adapter fixture.
  Undo is session-sized (20-minute TTL, FIFO cap 8) and CAS-protected. Gates:
  `npm run test:brain-chat`, `npm run typecheck`, `node esbuild.mjs` and
  `git diff --check` all PASS. This is automated extension evidence; installed
  VS Code Apply remains a separate live gate.
- RISK — The first full Metis `npm test` replay used ambient Node `v26.5.0`
  and reached the lossless-renderer adversarial suite before failing exactly
  three depth-limit assertions: Node 26 completed a 150-level parse that Node
  `v22.22.3` rejects as `PARSER_LIMIT`. The focused suite is GREEN under the
  qualified Node `v22.22.3`, but `package.json` currently advertises
  `node >=18`; therefore the ambient failure is not being waived. L808 is
  making the safety limit deterministic across both runtimes before the full
  gate is replayed.
- DONE — L806 projection-v2 closure `in=18 out=18 distinct=18 gaps=0`: the
  execution catalog `play-demo.video_pg` exposes 40 fields, 18 finite domains
  and 521 ordered values; exact kind, size, nature, literals and ValueItem
  semantic provenance are proved against canonical `play-demo.video`. Current
  receipt `sha256:15f4bfad611fc6bfba4fc5d0a698076d0fa510bf55af08f29873a753c45dc05e`;
  `finite_to_none_fields=[]`; focused projection/contracts, Ruff, schema
  validation and current qualified Node `v22.22.3` replay are GREEN. Historical
  v1 evidence remains immutable.
- DONE — L808 deterministic parser boundary is closed at total structural
  nesting 64, excluding strings, escapes and comments. The exact 64/65 edge,
  three repeat cycles and all five lossless suites are GREEN under both Node
  `v22.22.3` and `v26.5.0`; the full Metis `npm test` replay under Node
  `v26.5.0` subsequently completed exit 0 through
  `LOSSLESS_COMPILE_PROOF: VERDE`. The earlier runtime-dependent failure is
  superseded, not waived.
- FACT — L0 independently found and closed a create-rollback/create-Undo
  session-context defect after L804's first handoff: every successful rollback
  now refreshes Brain context even when the restored preimage is absence;
  focused Apply and type gates are GREEN.
- RISK — L807's first claimed real runtime adapter parsed generic `hits` forms,
  while the pinned `metis-serve` wire is ordered `blocks[].items`; such an
  adapter would deterministically reject a real preview. L807 is reopened to
  implement and test the exact canonical wire, pin the server-side Brain client
  identity and bound non-streaming upstream waits. No live gate may be claimed
  before these findings close.
- DONE — L807 trusted Fast runtime `in=11 out=11 distinct=11 gaps=0` is closed:
  the BFF owns Brain credentials and an exact launcher target policy; verifies
  the public context manifest before a private Git snapshot; enforces proposal,
  preflight, context, semantic-source and CAS bindings; invokes authoritative
  Brain compile before the pinned tenant build and `metis-serve`; parses only
  canonical ordered `blocks[].items`; bounds bodies, upstream waits, processes,
  sessions, turns and materializations; and cleans up on close, TTL and partial
  failure. Initial and refinement intent is derived from the server-owned
  create/existing target mode. Independent adversarial verdict: P0=0, P1=0,
  P2=0. Canonical Fast gates: 43/43 tests, typecheck, build and diff check PASS.
- DONE — `FAST_DEMO_CHANNEL_E2E_GREEN` is closed at the deterministic software
  boundary: proposal -> private snapshot -> manifest verification -> Brain
  compile adapter -> pinned tenant build -> canonical preview wire -> explicit
  consent -> ordered volatile channel, including negative and cleanup paths.
  This does not claim a live content preview while the VPN is intentionally off.
- DONE — Metis editor `0.24.1` was promoted from commit
  `3fde0820c04244b011a2f7a9604c425891424b34` to clean aligned `main` and pushed
  with remote tag `editor-v0.24.1`. Full `npm test` completed through
  `LOSSLESS_COMPILE_PROOF: VERDE`; package, all three release-asset checksums,
  parity state and parity check are GREEN. VSIX `metis.metis-dsl@0.24.1` is
  installed in the local VS Code profile.
- DONE — Metis Fast commit
  `cd84126d83be4a21841f7cf692232deb5d455c8b` is on clean aligned `main` and
  pushed. Both temporary implementation worktrees and their merged local
  branches were removed after ancestry and clean-tree verification.
- DONE — The Model 1 authoritative full gate completed exit 0 with
  `2939 passed, 2 skipped, 0 failed`. No tenant, model, adapter or training
  artifact was changed by this wave.
- OPEN — L811 is exercising the complex existing-endpoint and refinement path
  through the real local Fast BFF and real Model 1 runtime. Live
  materialization/content preview remains deliberately deferred because the VPN
  and content authorities are off.
- FACT — The first L811 startup failed closed before bind with
  `TOOLCHAIN_UNAVAILABLE`: active Brain pin v1 identified Metis `0.23.97`, while
  canonical Metis and its installed dependencies are now the promoted
  `3fde0820` / `0.24.1`. No token was read, no tenant changed and no candidate
  was generated; this failure is not counted as an E2E result.
- DECISION — Do not combine a legacy v1 compiler checkout with VSIX/Fast
  `0.24.1`. L812 creates a new immutable v2 pin for the promoted Metis commit;
  v1 manifest, schema and historical evidence remain byte-identical as rollback
  authority. The current pin must prove its exact Git objects, Node,
  `node_modules`, package/lock, 29 evidence entries and 9 sandboxed archive
  probes before L811 restarts.
- DONE — L812 pin promotion `in=29 out=29 distinct=29 gaps=0`, archive probes
  `in=9 out=9 distinct=9 gaps=0`: current immutable pin
  `metis-brain-toolchain/2026-09-04-v2` binds Metis `3fde0820`, tree
  `432bd3b`, tooling `0.24.1`, qualified Node `v22.22.3`, the installed
  dependency tree and every changed high-value lossless object. Probe receipt
  `sha256:c668accdcd66ceb68100aa0e8b15689786bef29a7b5361d36acdc0d7ff355337`.
  Historical v1 manifest and schema passed byte-identity guards.
- DONE — L811 real complex multi-turn Draft `in=2 out=2 distinct=2 gaps=0`
  crossed the HTTP Fast BFF and the real warm Brain/Model 1 runtime. Initial
  instruction modified `demo.a_b_test` to 24 films with reviewed
  `@tipologia = "Film"`, `@mood has "Romantico"`, female and human protagonist,
  descending publication date and `response.expanded`; Brain first asked the
  legitimate semantic-choice question distinguishing `@sottotipologia =
  "FILM"` from general `@tipologia = "Film"`. The operator answer was sent via
  the universal `/answer` route. The proposal completed in `39.250 s` using
  `generation_strategy=model` and compiled first-pass.
- DONE — Proposal-based refinement `porta 12 risultati` completed in `33.847 s`
  using `generation_strategy=model`; it changed only the requested count to
  `take 12` while retaining all four grounded filters, order and return shape.
  Both terminals report compile `ok`, `semantic_grounded=true` and
  `tenant_modified=false`. The canonical tenant remained clean at
  `27e4b118`; target bytes remained
  `sha256:d0d5080803fbaa480302de2865422012cc5349ff8251988cbaabcf6d9dd2921c`.
  The Fast session and gateway were closed; Brain, Model 1 and Flash remain
  startup-warm on loopback for the installed VS Code client.
- FACT — The live content/materialization gate was not attempted: VPN and data
  authorities are intentionally off. This is a named deferred acceptance gate,
  not a failed or simulated result, and it does not weaken the now-green real
  Draft/refinement path.
- FACT — The Metis `examples/play-prod-v2` role change is non-breaking for
  Model 1: the path is unchanged, `.vendored-from.json` records tenant revision
  `8d81d749`, and an independent read-only census resolved all 201/201 pinned
  source paths with `distinct=201 gaps=0`. Historical monorepo object IDs and
  the tenant-vendor provenance SHA name different authorities by design; no
  `tenant:vendor` run or manifest rewrite is required.
- FIX — The post-release full gate exposed that one test-harness root could no
  longer simultaneously supply active Brain dependencies `0.24.1` and the
  immutable historical oracle dependency hash `1cea5f2f...`. The harness now
  takes the current canonical Metis Git/object authority plus an independently
  hashed historical `node_modules` capsule; the isolated checkout still binds
  Git alternates to the canonical object store. Both authorities fail closed
  at their original hashes. The real harness probe crossed 29/29 Brain
  evidence, 9/9 sandbox probes, the historical oracle validators and a focused
  pytest target with exit 0.
- FIX — The first full replay after the split reached `2942 passed, 2 skipped`
  and isolated two W3 evidence tests whose helper calls still relied on the
  generator's historical absolute default instead of the harness-provided
  authority. The tests now pass that authority explicitly; production evidence
  code and its immutable receipt remain byte-unchanged. Both failures replayed
  GREEN directly and through the real dual-authority harness.
- DONE — Final Model 1 gate `in=2946 out=2946 distinct=2946 gaps=0`: `make
  check` completed exit 0 with foundation `87/87`, pilot contracts valid, Ruff
  and format GREEN, `2944 passed`, `2 skipped`, `0 failed` in `30m30s`.
  Independent dual-authority audit is `P0=0 P1=0 P2=0`; L813 is closed.
- DONE — Wave software closure: all seven exit gates are GREEN at their stated
  deterministic/local boundary. Installed VS Code operator-click Apply and
  VPN-backed live content/materialization remain explicitly named acceptance
  gates for later execution; neither is silently claimed by this closure.
