# Model 1 delivery blackboard

## Objective

Deliver a locally functioning Model 1 project: executable task-specific
oracles, contamination-safe benchmark/data production, reproducible A/B and
B/D evaluation, bounded QLoRA training and a truthful final promotion verdict.

## Acceptance

- Every gate is executable from a documented command and fails closed.
- Every benchmark or training row has content, oracle, policy and genealogy
  evidence; `in=N out=N distinct=N gaps=0` is reported at each boundary.
- Benchmark v1 is frozen before related training examples are materialized.
- W5 uses only the ratified model/runtime/grid/store identities and dev-only
  checkpoint selection.
- The frozen benchmark is run once against the frozen finalist.
- `TARGET_99_CONFIRMED` is emitted only if the registered 600-task semantic,
  Wilson, critical-veto and independence gates all pass. Any weaker result is
  named exactly.
- `make check`, artifact-boundary checks, real smoke execution and the Metis
  no-write invariant are green at handoff.

## Scope and authorization

- Writable repository: `/Users/tommasotessarolo/Developer/metis-model-1`.
- Baseline: `main@ad7a1169104c22fa8736b7463a93f65ea9f670f8` plus the existing
  user-authorized uncommitted project foundation.
- Writable ignored artifacts: this repository's `artifacts/` tree only.
- Read-only evidence source: `/Users/tommasotessarolo/Developer/ares-matioska/metis`
  at `a2dde2b191f6b78c2003d74875560da782470968`.
- The `18` currently observed untracked Metis paths are user state and must
  remain byte-for-byte untouched.
- Read-only orchestra source: `/Users/tommasotessarolo/Developer/ai-multi-team-orchestra`
  at `fcf2a170c4b923da6e930e674cddaeaa49a35626`; its wrapper may write only
  ignored `runs/` evidence.
- Local training/evaluation is authorized. The user authorized committing and
  pushing the text-only project repository on 2026-08-20. External upload or
  distribution of weights, adapters, checkpoints, optimizer state, datasets or
  other materialized payloads remains forbidden, as do deployment, secret
  access, `.env` reads, live ARES access and model-family substitution.

## Fixed identities

- Model: `mlx-community/Qwen3.8-27B-4bit@3e6447f082e89cc7f0bc6e5441afd38dfce760ff`.
- Runtime: CPython `3.12.10`, MLX `0.32.1`, MLX-VLM `0.6.15`, lock SHA-256
  `e5a39821599ac1f4eba46b3f5ae04040bd4973f3518351bd75f48677f6c9a340`.
- Full-state wrapper SHA-256
  `0fb908e6dc80f9f2d888d7692932f585d81b3ba8dad95f317a5fb099983e2e3a`.
- Second frontier team: Kimi Code `0.36.1`, `kimi-code/k3`, maximum configured
  reasoning, invoked only through the ratified protocol wrapper.

## Execution order

1. Frontier/Kimi delivery census and exact contract partition.
2. Task-specific oracle execution and independently-authored source contract.
3. Benchmark v1 freeze, then W3 train/dev/internal-test materialization.
4. A/B baseline and O-003 ratification.
5. W5 grid, dev-only finalist selection and multi-seed confirmation.
6. B/D internal test, then one frozen A/B/C/D evaluation.
7. Final package, commands, audit and handoff.

## Established

- FACT — The predecessor wave is closed with W5 blocked, `make check` at
  `134 passed`, no tracked payloads and a bit-exact full-state resume.
- FACT — Current storage is `492 GiB` free and ignored artifacts occupy
  `32 GiB`; O-006 preflight thresholds are currently satisfiable.
- FACT — The pinned Metis checkout has the same HEAD and four pre-existing
  untracked entries observed at the predecessor wave close.
- FACT — The current tracked Metis corpus supplies at most two defensible
  ancestry roots; repository-only relabeling cannot satisfy 563 independent
  groups.
- FACT — This wave may author new local public-synthetic sources, but shared
  templates/generators/semantic specs remain shared ancestry and cannot be
  counted as independent merely by changing identifiers.
- FACT — L0's first read-only test census found `7,673` assertion call sites in
  `159` pinned Metis test files and `201` source-literal hits in `37` files.
  These are candidate semantic anchors only: neither assertion count nor file
  count is accepted as an independence denominator without source/target
  genealogy and oracle extraction.
- DONE — L1 closed the exact six-family/30-task oracle inventory:
  `families in=6 out=6 distinct=6 gaps=0; tasks in=30 out=30 distinct=30
  gaps=0`. Structural parse/link/validate/compile, diagnostics, AST/IR, patch
  and migration scaffolds are implementable now; no generic primitive can
  invent task semantics or blind-human labels.
- DONE — L0 independently executed a source outside the Metis checkout through
  the pinned Langium `DocumentBuilder` and `compileEndpoint`. The proof returned
  parser errors `0`, diagnostics `0`, endpoint `play.model1_probe`, IR version
  `0.6`, and wrote only under ignored `artifacts/oracle-poc`.
- DONE — L2 separated delivery truth into two non-interchangeable verdicts.
  Correlated local tasks can support `PRODUCT_EVIDENCE` or
  `OBSERVED_99_ONLY`; `TARGET_99_CONFIRMED` still requires at least 563
  independently rooted groups. Six hundred outputs from one shared
  generator/template/model session cannot become 563 groups by identifier
  changes.
- FACT — The executable route is therefore dual-track: build and train a
  functioning local Model 1 on oracle-accepted non-benchmark sources while the
  population claim remains independently gated. The frozen benchmark verdict
  will report both observed task accuracy and the separate independence gate.
- DONE — K4 completed its three-unit architecture roster through the ratified
  wrapper: `in=3 out=3 distinct=3 gaps=0`. L0 inspected the report, rechecked
  both repository invariants and independently matched the `197/199/201`
  corpus arithmetic. Report SHA-256 is
  `eb202f1abb40a7a3d5fa18189913fd397f26908af1015e1788b8c9917a590d08`;
  Kimi provider sub-lanes were `agent-ey6w5ekr` and `agent-7659sngt`.
- FACT — K4 independently confirms that the implementable harness and the
  target-authoring work are separate, that a shared generator/template/spec
  cannot manufacture 563 groups, and that the functioning-local track can
  advance while the population claim remains explicitly capped.
- FIX — L4 returned a deterministic independence graph, but L0's first review
  rejected the delegated green because non-frozen groups/scores and rootless
  tasks could have inflated promotion. The frontier hardening now requires a
  content root per task, scores and group thresholds only the frozen split,
  exact 600-task/family coverage, complete zero-critical evidence, aggregate
  equality and task-ID-independent group hashes. Focused result is currently
  `19 passed`; independent adversarial audit remains open.
- FACT — L3 returned the first external-source oracle runner with `9 passed`.
  It executes real pinned Langium/compiler code and leaves Metis unchanged;
  frontier runtime/toolchain/path/semantic audit remains open before acceptance.
- FIX — L0 reconciled the final multi-file oracle runner with its fail-closed
  source pin. The reviewed runner SHA-256 is
  `524faa22f6725e660f1d3d36c41d431502a4dcf24adc8109ec04719049a253c4`;
  the focused oracle suite is `12 passed`.
- DONE — The repository handoff gate is green after the pin reconciliation:
  foundation checks `in=21 out=21 distinct=21 gaps=0`, Python tests
  `in=168 out=168 distinct=168 gaps=0`, with lint and format checks green.
- FACT — This green repository gate publishes reproducible project code and
  qualification evidence only. W5 remains blocked and no semantic-accuracy or
  99% result exists yet.
- DONE — K7 second-frontier review returned through the ratified Kimi wrapper
  as `kimi-code/k3`, activity `metis-model1-w1-w3-closure`, label
  `sourceability-adversarial`. Its three-unit roster attacks honest 563-group
  sourceability, the real 30-task W1/A-B path and the W3-to-W5 execution seam;
  `in=3 out=3 distinct=3 gaps=0`. Report SHA-256 is
  `8e7ab7d633d387ddbea195a6fb6c5bb68b059d1228e848feae472ee7fe3ec0f8`;
  provider session is `session_cff527a9-28c7-4839-bbdc-058aa3efb9b1`.
- FACT — K7 independently re-derived `199` tracked Metis files, `197` in the
  tenant, two non-tenant sources, one distinct author and at most two defensible
  ancestry roots. Current material cannot construct 563 groups: the defensible
  deficit is at least `561`, not a quantity cosmetic generation can close.
- FACT — K7 closed its enumerations with `tasks 30/30`, oracle classes `13/13`,
  families `6/6`, build steps `10/10` and missing W3 units `13/13`. Of the 13
  oracle classes, four are implemented, three are evidence-only and six lack
  executors; at least eight allocated sources need a non-endpoint oracle mode.
- OPEN — K7's first-pass project status invariant is intentionally unavailable
  because L8/L9 hardening began after its preflight. K7 caught the concurrent
  red focused test and correctly refused to bless a moving tree. L0 must first
  publish the accepted hardening SHA, then resume the same Kimi session against
  that clean commit. The read-only Metis invariant remained exact.
- FIX — L8 closes the false-promotion paths by unioning shared benchmark roots,
  requiring non-empty content roots, serializing and hashing frozen per-task
  evidence, recomputing family counts, critical failures, Wilson bounds and
  verdicts, and binding every TaskResult to its family, success, leakage group
  and Oracle predicates/hashes. The registered target-contract anchor remains
  fail-closed while unset; a self-declared contract cannot promote.
- FIX — L9 executes each Oracle from an isolated archive of the pinned Metis
  revision with copied and rehashed Node, runner and node_modules. The child
  environment is replaced with a sterile allowlist, and mandatory macOS
  `sandbox-exec` applies a registered global `deny file-write*` policy plus a
  denied-write canary. Existing untracked or ignored Metis bytes are therefore
  outside both the execution snapshot and the write boundary.
- DONE — L10's final frontier replay accepts L8/L9 with `P0=0`, `P1=0` and one
  non-blocking test-coverage advisory. It reproduced the prior aggregate,
  family, rootless, runtime-identity, hostile-environment and no-write attacks;
  the focused integrated suites are `in=81 out=81 distinct=81 gaps=0`. The
  accepted runner SHA-256 is
  `8278504a71c2d609aa441a0e81537c92de28d329453a6a99bba2b43afc0aefe0`.
- DONE — L0 reran the complete integrated repository gate after the accepted
  fixes: foundation `in=21 out=21 distinct=21 gaps=0`, Python tests
  `in=193 out=193 distinct=193 gaps=0`, with Ruff and format checks green.
  `validate-pilot` remained intentionally fail-closed on the five W5 evidence
  blockers rather than converting technical qualification into an accuracy
  claim.
- FACT — K7 resumed the same Kimi K3 provider session against clean commit
  `9418ad1d94ad43f8580d84a3f88fd2da5f792b6c`. It independently confirmed both
  repository invariants, 39 frozen tasks with one shared benchmark root forming
  exactly one group, unset promotion authority failing closed, and isolated
  Oracle execution. Coverage is `in=3 out=3 distinct=3 gaps=0`; report SHA-256
  is `2fb3145d7275b12a07c8900a2265ad6cd798f9c904d1c63fdeeed5a2af35fa9a`.
- FIX — K7 also found that the documented test command depended on ambient
  `PATH`: Node 26 correctly failed the runtime pin, but made a green gate depend
  on operator shell state. L0 added an explicit `METIS_MODEL1_NODE` selection,
  an all-PATH resolver that accepts only the registered version and binary
  digest, a qualified Makefile default with portable override, and mutation
  coverage for wrong-first-PATH and forged explicit binaries. The mutable source
  candidate is never executed: it is hash-only, then copied and rehashed before
  the sandboxed runner reports the version bound by the response verifier.
- DONE — The corrected documented `make check` was run with hostile ambient
  `PATH=/opt/homebrew/bin:/usr/bin:/bin`: foundation
  `in=21 out=21 distinct=21 gaps=0`, Python tests
  `in=198 out=198 distinct=198 gaps=0`, Ruff and format green. No unqualified
  Node fallback is accepted.
- DONE — L10's final hostile resolver/TOCTOU replay returned `P0=0`, `P1=0`.
  Relative and wrong overrides, no exact digest, wrong-first and unreadable
  candidates, duplicates/symlinks and pre-sandbox execution were all exercised;
  only a cross-host Makefile-default advisory remains documented.
- DONE — K7's final clean-SHA replay on
  `9ba7c75631b64bf6c8d67bcd614eec9f4d4ceebc` returned `ACCEPT`, `P0=0`,
  `P1=0`, `P2=1` cross-host-default advisory. Kimi independently ran the
  hostile-PATH documented gate (`198/198`), re-probed 39 shared-root tasks as
  one group, confirmed unset promotion authority and source-Node-never-exec,
  and preserved both repository invariants. Coverage is
  `in=3 out=3 distinct=3 gaps=0`; report SHA-256 is
  `85939a2fa4ad106fd10cbbf74597b143ab43e249c87756b254c926f713279196`.
- FACT — The current executable W5 assessment is contract-valid but blocked on
  five exact items: leakage groups `1/563`, unsealed task-specific oracles,
  synthetic-only W3, O-003 and missing A/B baseline. Real semantic accuracy is
  therefore unmeasured.
- FACT — The local MLX path is technically qualified on Apple M3 Max / 128 GB:
  the pinned Qwen3.8-27B 4-bit checkpoint and full-state adapter replay are
  present outside Git, `486 GiB` is currently free, and ignored artifacts use
  `32 GiB`. The only materialized examples are `17` qualification fixtures;
  they are synthetic runtime probes, not an accepted semantic training corpus.
- FIX — L0 hardened the current full-state wrapper against runtime/model drift,
  non-finite sampler state and LoRA target substitution. The verified model
  topology yields exactly `496/496` distinct ordered target keys; arbitrary,
  non-empty proper-subset and extra-key mutations all fail before adapter
  application. The payload-free adversarial suite is `8/8`.
- DONE — L0 requalified the hardened wrapper on the pinned real checkpoint with
  a fresh step one, fresh-process resume to step two and uninterrupted two-step
  reference. Losses match exactly and adapter config, adapter tensors and full
  state are byte-identical. The ignored report SHA-256 is
  `4d23e0f1f7f27945d0071113fbd0984e84c2cc4ca9f4a9cff70069826c01b27c`;
  semantic continuation-state SHA-256 is
  `4bee697cb4179f82d6623a8ceeca2c1a6366e0fd950f94726fc87f2dc2c40581`.
  This remains technical evidence, not semantic training or accuracy.
- FIX — L13 implemented the registered W3 contract for F-1/F-2/F-3 only:
  exact benchmark/source/adapter authorities, content-derived genealogy,
  atomic output roots, split isolation, full canonical edit/repair messages,
  rights envelopes, exact Oracle evidence and deterministic replay. Four
  successive frontier mutations closed same-class adapter substitution,
  runtime callable injection, forged receipts and malformed nested JSON.
- DONE — L17/L18 independently accepted the final F-1/F-2/F-3 contract with
  `P0=0`, `P1=0`, `P2=0`. Focused coverage is
  `in=112 out=112 distinct=112 gaps=0`; L18 additionally rejected
  `141/141` malformed top-level, benchmark and nested inputs with zero raw
  exceptions or false accepts. L0 independently replayed the two prior
  `TypeError` attacks and the same-filename callable forgery; all fail closed.
- FACT — This acceptance is not a production dataset result. Benchmark,
  source-register, Oracle adapter and Oracle identity authorities remain
  `None`; the current W1 F-1/F-2/F-3 allocation has production receipts
  `in=15 out=0 distinct=0 gaps=15`. Fixture runtime receipts bind policy only
  and explicitly do not prove execution through the isolated Metis runner.
  F-4/F-5/F-6 remain unimplemented.
- DONE — L0's hostile-ambient integration gate completed foundation
  `in=23 out=23 distinct=23 gaps=0`, Python tests
  `in=270 out=270 distinct=270 gaps=0`, with Ruff and format checks green.
  The payload-free W4 suite is separately `8/8`; no model payload was loaded by
  either gate.
- FACT — The read-only Metis invariant after these gates is HEAD
  `a2dde2b191f6b78c2003d74875560da782470968`, tracked diff clean and `18`
  untracked paths. SHA-256 of NUL-delimited porcelain-v1 expanded status is
  `ea7eb74f131f8d8e1fd3f785da7941bce2c21dc239d06ccd17a389e7ed6beb54`.
- DONE — K19 audited clean pushed SHA
  `acb698d204147fb0fcd7bc773c5bfb18f03e6944` through the ratified Kimi K3
  wrapper and returned `ACCEPT`, `P0=0`, `P1=0`, `P2=5`. Units close as
  `in=3 out=3 distinct=3 gaps=0`; distinct executions are `390/390` green:
  W3 `112/112`, W4 payload-free `8/8` and hostile integrated `270/270`.
  Project porcelain remained empty. Metis HEAD remained pinned with the same
  four collapsed untracked entries, equal to the `18` expanded paths recorded
  above. No payload or Metis write occurred.
- FACT — K19 provider session is
  `session_0b443c60-3c8f-495b-909a-4acac8736729`. Master report SHA-256 is
  `047618f753f89be3e382f0258dfaaf6bde74c5808e77ce827101165d023a925d`;
  Kimi activity-board SHA-256 is
  `af47770942984ef336b86b16a11079349969611cc3b227b7f824d3a2d527f4e2`.
- RISK — K19's five accepted P2 advisories remain explicit: W3 identity does
  not yet bind mutable module globals; transient mutate-and-restore state is
  not observable; unset-authority validation raises rather than returning an
  error list; `qualification/probe_model.py` retains diagnostic-only remote
  code trust outside the qualified wrapper; missing-payload/torn-publish W4
  branches are inspection-covered but lack adversarial tests.
- STOP — L20's production-registration preflight found no current false green,
  because all authorities remain unset, but a naive adapter is blocked. Before
  registration the implementation must bind real isolated-runner envelopes,
  independently authorized typed semantic truth, run-fatal trust failures,
  transitive bridge/schema/profile identities, deny-network sandbox evidence
  and a runner mode that does not require exactly one endpoint.
- DONE — The next F-1/F-2/F-3 bridge roster is closed on paper:
  `families in=3 out=3 distinct=3 gaps=0`,
  `tasks in=15 out=15 distinct=15 gaps=0`, and
  `phases in=25 out=25 distinct=25 gaps=0`. Real receipts remain
  `in=15 out=0 distinct=0 gaps=15`; this arithmetic authorizes infrastructure
  work, not source sealing or semantic credit.
- FIX — L21a closed the first production-bridge STOP without registering an
  adapter. The external runner request now binds explicit execution mode
  `endpoint|source`; source mode validates parser/link/semantic diagnostics and
  emits AST evidence with deliberately null IR, while endpoint mode retains
  exact-one compilation. Sandbox policy v2 denies both `file-write*` and
  `network*`; loopback TCP `connect` and `bind` canaries accept only
  `EPERM/EACCES`, use no DNS/listener/external target, and fail closed under a
  broadened rehashed policy.
- FACT — L21a repinned runner SHA-256
  `484dd9518afe1dcf712bde80e367aa70f175c9dd28a3a214243616c1a298cbe5`
  and sandbox-policy SHA-256
  `deb8f45c9dfc2f336dbfb6f69a13e599a51929864ede8229969fa7f6e03f40aa`.
  The pre-regression real Oracle suite closed `in=23 out=23 distinct=23
  gaps=0`; the newly added mode/network attack slice closed
  `in=5 out=5 distinct=5 gaps=0`. No Metis write or production authority was
  introduced. Resume command:
  `METIS_MODEL1_NODE=/Users/tommasotessarolo/.hermes/node/bin/node uv run pytest -q tests/test_oracles.py`.
- OPEN — L21b remains active: typed run-fatal trust/infrastructure failures,
  transitive adapter identity, independently authorized semantic registry,
  full runner-envelope receipts and the real `3/3` candidate, `5/5` execution
  bridge gate.
- RISK — L21b's first two independent frontier audits both returned `REWORK`
  before authority registration. The strongest payload-free replay replaced
  only the live `run_oracle` global after identity measurement and falsely
  obtained candidates `3/3`, executions `5/5`, rejected `0` and replay errors
  `0` against a nonexistent Metis root. Further P1 findings were incomplete
  exact-request and artifact-byte bindings, schema-valid fixture/production
  downgrade, stale declared content hashes, semantic truth closures `0/3` and
  three self-declared leakage groups for one authoring wave. Authorities
  remained `None`; no false production record was promoted.
- FIX — L21b REWORK remediation now independently hashes the live transitive
  Python globals resolved by the production adapter, rechecks that identity
  before and after evaluation, recomputes family content from canonical
  candidate fields, reconstructs the exact registered Oracle request, and
  binds every receipt to the canonical bytes and SHA-256 of its materialized
  artifact. Oracle evidence declares exact `fixture-policy` or
  `real-runner-envelopes` mode and the run schema rejects mixed/downgraded
  evidence. Verifier failures are trust-fatal; runner launch failures are
  infrastructure-fatal.
- FIX — The three typed truths now require exact IR for F-1, exact before/after
  IR plus the sole changed path for F-2, and exact failure, diagnostic object
  and repaired IR for F-3. Candidate manifest SHA-256 is
  `4ee3e735179194b838ec38b0c11f1f9a166d640fcfece1eee68b6f9b6dd63bc5`;
  semantic-registry SHA-256 is
  `9b9aa14836eb6924e61df0ab1e0a7b7224f9958b78056ae66fd27f59868cc7c3`.
  The common authoring session and generator are now shared roots: candidates
  `3/3`, distinct candidate IDs `3`, honest leakage groups `1`, gaps `0`.
- FACT — Post-remediation payload-free gate is
  `in=108 out=108 distinct=108 gaps=0`; four Draft 2020-12 schemas are valid,
  Ruff and `git diff --check` are green. Blocker regressions cover live
  executor/verifier replacement `2/2`, stale content `1/1`, exact semantic
  near-misses `3/3`, conservative genealogy `1/1`, and standalone receipt-mode
  downgrade `1/1`. The production bridge and registry authorities remain
  unset. Resume command:
  `METIS_MODEL1_NODE=/Users/tommasotessarolo/.hermes/node/bin/node W3_PRODUCTION_CONTRACT=1 uv run pytest -q tests/test_w3_production_adapter.py -k real_bridge`.
- OPEN — L21b remediation is frozen for independent frontier re-audit. Only an
  accepted re-audit permits the two-fresh-process real bridge gate and the
  repository-wide integration gate; neither smoke candidates nor their
  self-authored registry receive production semantic credit before independent
  authority ratification.
- RISK — L21b re-audit 2 returned `REWORK`, `P0=0`, with the remaining semantic
  P1 reproduced `1/1`: a function clone retaining code/module/qualname/defaults
  but resolving a changed `__globals__` namespace kept the former runtime and
  full identity hashes. Runtime review also found that one schema-valid run
  could mix individually valid fixture and production records. Exact request,
  artifact bytes, content, three semantic truths and one-group genealogy were
  independently accepted in this replay.
- FIX — L21b rework 2 now hashes a cycle-safe transitive function graph using
  each function object's actual `__globals__`, following Model 1 dependencies
  through adapter, Oracle bridge, verifier and provenance code. Adapter-side
  and protocol-side measurements must agree, so replacing the measurement
  guard and executor together fails closed. Regressions cover top-level
  executor/verifier replacement `2/2`, same-code/different-globals clone `1/1`
  and guard-plus-executor swap `1/1`.
- FIX — W3 run manifests now declare one top-level receipt mode and require
  every accepted record to match it; standalone schema tests accept isolated
  fixture and real shapes but reject a mixed roster. Artifact verification now
  rejects symlinks before resolution, and authority/identity drift is typed as
  `W3OracleTrustError` while remaining run-fatal.
- FACT — L21b rework-2 payload-free gate is
  `in=110 out=110 distinct=110 gaps=0`; four schemas, Ruff, formatting and
  `git diff --check` are green. Authorities remain `None`; real bridge evidence
  is deliberately not rerun until frontier re-audit 3 accepts this frozen
  snapshot.
- STOP — L21b re-audit 3 returned `REWORK`, `P0=0`, `P1=1`: coordinated
  replacement of executor and both same-interpreter measurement guards can
  still preserve the former identity. Extending the identity graph closed the
  exact same-code/different-`__globals__` replay, but cannot create a trusted
  root inside an interpreter whose executor and verifier are both mutable.
  Runtime review also notes that stdlib module/class attributes belong to the
  same mutable address space. The real bridge gate is therefore STOPped before
  ten executions; no authority or production record is created.
- FACT — All other L21b findings are independently closed: exact request,
  canonical artifact bytes and hash, pre-resolution symlink rejection,
  homogeneous top-level receipt mode, typed trust/infrastructure failures,
  content recomputation, exact semantic near-miss rejection `3/3`, conservative
  one-group genealogy, and source authorities unset `5/5`.
- FIX — L22 architecture is now the smallest honest continuation: a fresh
  one-shot launcher/verifier, separate from the untrusted W3 worker, operating
  on a content-addressed immutable bundle under an ignored artifact root. It
  must receive an externally ratified authority manifest, run with isolated
  flags and an allowlisted environment, recompute input/output/role/artifact/run
  hashes itself, and reject self-authored `matched=true`. Same-process adapter
  globals remain non-authoritative implementation detail; all five source
  authorities remain permanently `None`.
- FACT — L22 dependency census confirms that
  `qualification/.venv/bin/python -I -B -S` resolves neither `metis_model1`
  nor `jsonschema`, `attrs`, `referencing` or `rpds`. The clean qualifier can
  therefore remain stdlib-only, but the real bridge must execute in a separate
  worker with an explicit pinned dependency bundle; absence of that bundle is
  a STOP, never an implicit ambient import.
- OPEN — L22 external qualifier implementation is active on disjoint new
  runtime/schema/test files. Until its independent audit and an independently
  ratified semantic registry exist, permitted claims remain only candidate
  roster `3/3`, one leakage group, internal schema/hash coherence and
  payload-free regression evidence—not production Oracle green or accuracy.
- FACT — L22 first implementation is payload-free `21/21`; L0 independently
  reproduced the combined qualifier/contract slice `45/45`, schema `1/1`,
  Ruff/format and `git diff --check` green. The report correctly restricts its
  claim and lists four STOPs, including no production worker/runner and no
  accuracy claim.
- STOP — Independent runtime re-audit returned `REWORK`: the official CLI did
  not require `-I -S -B`, and an authority-hashed worker wrote an absolute
  sentinel outside its output root while the report still returned
  `qualified`. A descendant also retained an artifact FD and corrupted the
  published bytes after green. The worker therefore needs an outer deny-write
  and deny-network sandbox, a dedicated killed/reaped process group, exact
  launcher/Python/policy pins and immutable publication checks.
- STOP — Independent semantic re-audit returned four false greens: a mismatched
  request/truth endpoint, a forged F-3-invalid endpoint, JSON booleans accepted
  as integer `1`, and a rehashed candidate id accepted by code but rejected by
  the report schema. L22 rework is active; no authority, receipt, production
  execution or promotion was created.
- FACT — L23 dependency census establishes a feasible separate production
  worker bundle on root CPython `3.13.3`: six runtime packages plus five
  version-metadata directories, `144` files and `1,799,002` bytes. The closure
  includes the arm64 CPython-313 `rpds` extension and passes an isolated
  `-I -B -S` import/validation probe only when its bundle path is explicitly
  prepended; it is not compatible with the Python 3.12 MLX environment.
- RISK — L22's first remediation reached focused `33/33`, but L0 and the
  independent reviewers withheld acceptance after five additional exact
  replays: a forked process could detach and retain an artifact descriptor,
  a rehashed semantic filename containing `..` qualified, `true` could stand
  in for the F-2 integer occurrence count, `artifact/bundles` could redirect
  through a pre-existing symlink, and the fixture worker could read outside
  its registered roots. No qualification from those replays was promoted.
- FIX — L22 remediation 2 now permits child execution only through the exact
  pinned Python binary and denies child creation, so the detached-process
  replay exits blocked before publication. The outer profile denies data reads
  from source, artifact, user, volume, temporary and keychain roots while
  allowing only the exact Python, current bundle and per-run process roots; a
  source-file read canary is mandatory. Bundle and qualification namespaces
  reject symlinks before and after creation.
- FIX — Semantic input validation now mirrors the bounded F-1/F-2/F-3 schema:
  safe relative `.metis` filenames, exact top-level and provenance fields,
  strict JSON integers/booleans, exact family contracts and family-specific
  truth fields. The schema uses the same segment-safe filename grammar.
- FACT — L22 remediation-2 focused gate is `in=41 out=41 distinct=41 gaps=0`;
  the combined qualifier/contracts gate is `65/65`. Ruff, formatting, two
  Draft 2020-12 schemas and `git diff --check` are green. L0's stronger
  delayed-descriptor process replay is blocked with exit `2`, empty stderr and
  no qualification tree: `in=1 out=1 distinct=1 gaps=0`.
- OPEN — L22 remediation 2 is frozen for fresh runtime and semantic review.
  Its only permitted claim remains three-candidate infrastructure with explicit
  STOPs for production worker/runner, materialized stdlib closure, W1/data,
  F-4/F-5/F-6 and accuracy. All five production authorities remain unset.
- FACT — L22 runtime review accepted remediation 2 with `P0=0`, `P1=0`,
  `P2=0`, but the independent semantic review correctly returned `REWORK` on
  three consistently rehashed false greens: boolean top-level manifest version,
  F-3 failure-kind/diagnostic-presence drift and schema-invalid Oracle
  diagnostic rows. Runtime acceptance was not promoted to an integrated green.
- FIX — L22 remediation 3 validates exact candidate/registry identities and
  integer schema versions; cross-binds F-3 failure kind, diagnostic channel,
  nonempty evidence and filename; and manually enforces the bundled Oracle
  diagnostic/failure types before accepting hashes. The Oracle schema now uses
  the same safe relative `.metis` filename grammar.
- FACT — L22 remediation-3 qualifier gate is
  `in=46 out=46 distinct=46 gaps=0`; the exact new regressions cover manifest
  booleans `2/2`, F-3 cross-binding `2/2` and malformed Oracle diagnostics
  `1/1`. Ruff, formatting, three schemas and `git diff --check` are green.
- OPEN — Fresh semantic replay of those exact three findings is pending; no
  authority, runner receipt, production record or accuracy credit exists.
- DONE — L22 bounded qualifier infrastructure is accepted after independent
  runtime and semantic reviews, each `P0=0`, `P1=0`, `P2=0`. Semantic replay
  blocked prior false greens `5/5` and IR-name substitutions `4/4`; a clean tmp
  baseline produced canonical stdout `1/1`, schema-valid report `1/1`, canonical
  schema-valid Oracle artifacts `5/5`, candidates `3`, executions `5`, roles
  `5`, gaps `0`.
- FACT — L0 integrated the final L22 snapshot with Oracle, W3 builder, W3
  verifier, production-adapter, contracts, dataset and independence tests:
  `in=225 out=225 distinct=225 gaps=0`, with `224` passed and one deliberate
  opt-in production test skipped. The pinned Metis checkout remained exactly
  HEAD `a2dde2b...`, tree `75473e26...`, expanded-status SHA-256
  `ea7eb74f...beb54`, tracked diff files `0`.
- STOP — L22 acceptance is infrastructure-only. It does not ratify the
  semantic registry, materialize the production dependency bundle, execute the
  real runner, promote W1/W3 data, implement F-4/F-5/F-6 or establish any
  accuracy. Those remain the ordered L23+ continuation.
- FACT — Repository-wide `make check` on the accepted L22 snapshot is green:
  foundation `25/25`, pilot contracts valid, Ruff clean, `83` files formatted,
  pytest `335` passed / `1` deliberate opt-in skip. The readiness validator
  remains honestly `BLOCKED` for W5 on `1/563` groups, unsealed task-specific
  oracles, no real W3 dataset, O-003 and absent A/B baseline. Post-gate Metis
  HEAD/tree/status remain byte-identical with tracked diff files `0`.
- DONE — Kimi K3 independently audited pushed clean SHA
  `96cedd2df4074c31ee9ae70a8475e9a60a537329`: bounded infrastructure verdict
  `ACCEPT`, semantic-registry decision `RATIFIABLE`, `P0=0`, `P1=0`, `P2=5`.
  Its report is external to this repository at
  `runs/metis-model1-finished-delivery/artifacts/k3w3-w3-qualifier-report.md`,
  SHA-256 `a810598d9b62143f6172a4faa58f91879d4ac19f097cc19255a6ce43356fb83a`.
  Coverage: units `in=3 out=3 distinct=3 gaps=0`; clean diff files `21/21`;
  qualifier/contracts `70/70`; semantic rows `3/3`; real ordered executions
  `5/5`; direct IR/diagnostic truth `11/11`.
- FACT — Kimi recomputed candidate manifest
  `sha256:4ee3e735179194b838ec38b0c11f1f9a166d640fcfece1eee68b6f9b6dd63bc5`
  and semantic registry
  `sha256:9b9aa14836eb6924e61df0ab1e0a7b7224f9958b78056ae66fd27f59868cc7c3`,
  then ran the opt-in real bridge gate in an isolated `/tmp` clone. Two fresh
  processes were byte-identical, with roles `author/before/after/mutated/fixed`,
  statuses `ok/ok/ok/invalid/ok`, five distinct receipts/artifacts and `13/13`
  mutation attacks closed. All five artifacts bind exact Metis revision/tree.
  The three rows conservatively remain one shared session/generator leakage
  group; this grants no population or accuracy credit.
- FACT — L23 dependency availability is local and download-free. The CPython
  `3.13.3` arm64 worker closure is `in=144 out=144 distinct=144 gaps=0`,
  `1,799,002` bytes, no symlinks, sorted-roster digest
  `db649bc14ee947ff43a2e5dbd540585123a259bb771a087692b72a4c0d463f42`;
  isolated `-I -B -S` import passes. Native `rpds` SHA-256 is
  `b2e1ac864b42ac726e2d95ffa3c5de5b74df21ff0415949b082e364414a36d86`.
  Node `v22.22.3` and the runner are already present with the registered hashes.
- STOP — Do not wire the accepted L22 fixture worker directly to `run_oracle`.
  The current qualifier caps source-root bundle files at `128`, while the
  external worker closure has `144`; its Seatbelt profile permits only the
  pinned Python executable, while a real run needs the pinned Node/tooling
  capsule; and `run_oracle` still snapshots from the live Git checkout. L23
  therefore requires an external immutable Python bundle, an immutable Metis
  runtime capsule, a low-level run-from-capsule boundary and an authority/report
  v2 bound to the Kimi report hash. All five source authorities remain `None`.
- OPEN — Implement L23 v2 payload-free first, audit and publish a new clean SHA,
  then materialize the already-local dependency bundle and Metis capsule outside
  Git. Only after a second Kimi recheck may two fresh qualified runs (`2/2`
  processes, `10/10` physical invocations, five semantic roles per run) count as
  production bridge evidence. This is still before W1 `15/15`, F-4/F-5/F-6,
  benchmark freeze, training or any measured accuracy.
- FACT — L23 capsule-v2 payload-free implementation wave opened on clean pushed
  baseline `4ec625fcec8a9c41423bc048688d17775e57353c`; exact architecture, writable
  roster, verification and STOP conditions are sealed in
  `orchestra/briefs/2026-08-21-model1-l23-capsule-v2.md`. No payload
  materialization or real runner execution is authorized in this sub-wave.
- RISK — L27's first broad verification command included pre-existing
  `tests/test_oracles.py` cases that call the live read-only Metis checkout. The
  implementer detected the mandate crossing during the second such case,
  terminated only its exact pytest PIDs and retracted the broad `172/172` green
  as admissible L23 evidence. L0 immediately rechecked Metis: HEAD
  `a2dde2b...`, tree `75473e26...`, expanded-status SHA-256
  `ea7eb74f...beb54`, tracked diff files `0`. L23 verification is narrowed to
  seven capsule-only Oracle tests using tmp fixtures plus the non-live suites.
- FACT — The narrowed payload-free checkpoint is `121/121`: seven explicit
  capsule-only Oracle tmp-fixture tests, `90/90` qualifier/worker/bridge tests
  and `24/24` contract tests. This is provisional implementation evidence, not
  a frozen L23 verdict, and the retracted broad `172/172` run remains excluded.
- RISK — L27's first five tmp-only process-policy probes initially returned `2/5`:
  authority-byte binding and inner exact-Node timeout/reap pass; three outer
  Seatbelt probes terminate CPython `3.13.3` at macOS `dyld CacheFinder` before
  any worker or Node code runs. A bounded read-only census is isolating the
  minimum interpreter/system read closure. The fix may allow process creation
  only for the registered Node while keeping exact-executable, denied-network,
  denied-write and outer process-group supervision. No Metis, model payload,
  network or training execution is in scope.
- FIX — The macOS 26 bootstrap closure is now minimal and reproducible: literal
  root lookup `/` is readable for dyld and the registered stdlib remains on
  `sys.path`, without opening user/external roots. Process creation is allowed
  only through a post-bootstrap guard for the registered capsule Node; shell,
  alternate executable, `start_new_session` and alternate process group are
  rejected. The Node inherits the outer supervised group and inner timeout
  kills its exact PID.
- DONE — Process-policy probes `in=5 out=5 distinct=5 gaps=0`, repeated twice
  (`0.57 s`, `0.70 s`): registered Node starts; `/usr/bin/true` is denied;
  detach is rejected; outer timeout/group cleanup kills the Node; inner timeout
  kills the exact PID; worker/policy drift invalidates authority. Registered
  probe-Node census is `before=0 after=0 pids=none`. The 71-case matrix keeps
  its denominator but now names the process case honestly as
  `fork-registered-child-supervised`.
- FACT — Independent L28 reproduced the bootstrap from a fresh tmp-only profile:
  canonical CPython realpath plus exact binary, `libpython3.13.dylib`, stdlib and
  `file-read-data` on literal `/` returns exit `0`, stdout `1`. Removing `/`
  reproduces exit `134`/SIGABRT; removing the executable, dylib or stdlib also
  fails closed. No explicit `/System`, `/usr`, network, write or `sysctl-read`
  grant is needed, and the `.venv/bin/python` symlink is correctly unsuitable.
- DONE — L27 payload-free implementation is frozen on the exact 13-file brief
  roster. Admissible safe-only pytest is `in=151 out=151 distinct=151 gaps=0`:
  qualifier/production-worker/bridge/contracts `144/144` plus the seven
  explicitly named capsule-only Oracle tmp tests `7/7`. Logical mutation
  coverage is separately `A=11 B=12 C=12 D=12 E=16 F=8`, total
  `in=71 out=71 distinct=71 gaps=0`; it is not inflated into the pytest count.
- FACT — Frozen static gates: ten Python files compile; Ruff check and format
  check pass `10/10`; three Draft 2020-12 schemas meta-validate `3/3`; diff
  check passes; fresh import reports all five production authorities `None`.
  HEAD remains baseline `4ec625f...`; off-limit W3 builder/adapter/runner files
  and Git artifact status are unchanged. The prior broad `172/172` history
  remains explicitly retracted.
- OPEN — Independent frontier reviews L29 (capsule/process containment) and L30
  (authority/schema/replay/claim boundary) are running read-only on the frozen
  diff. No payload materialization, real Metis runner, repository-wide
  `make check`, commit or push occurs before both reviews and L0 replay close.
- RISK — L30 reproduced a tmp-only false green without Metis or runner: the
  standalone replay accepts a caller-supplied qualifier path plus caller-supplied
  matching digest, does not reload/cross-bind the canonical authority, and does
  not independently validate the report launcher/authority relationship. A
  forged qualifier ignored an empty authority, emitted five fake artifacts and
  obtained `replay-qualified` with the advertised `2` processes / `10`
  invocations / `5` identities. This is P1 and blocks L23. The bridge needs an
  independent trust root and exact qualifier/authority/report/artifact binding,
  plus a regression that rejects this full forged flow.
- RISK — L29 independently proved the process guard is not authoritative. The
  bootstrap wraps only `subprocess.Popen`, while Seatbelt permits registered
  child creation; two alternate standard process paths created the exact
  registered Node in a new session/process group. Both children survived the
  outer group cleanup and were then killed by exact PID during the tmp-only
  audit. This violates the brief's no-detach contract and makes the existing
  Popen-only regression insufficient. L31 must close this at policy or
  architecture level and prove no residual PID for both paths.
- RISK — L30 also recomputed the claimed mutation denominator: the names are
  arithmetically `A11+B12+C12+D12+E16+F8=71`, all distinct, but the current test
  only counts strings. It does not dispatch all 71 mutations, so this is an
  exact census, not `71/71` executed coverage. L31 must bind every roster item
  to a real rejection/positive proof and report census separately from executed
  cases.
- FIX — L31 architecture is sealed before writing. The bridge will carry a
  compiled exact qualifier-byte pin, parse canonical duplicate-free authority
  input itself, bind the independently supplied authority digest and Kimi/project
  constants, and cross-check launcher/report/five artifact bytes. The worker
  will no longer create processes: five exact Node invocations move to the
  trusted qualifier, each as its own supervised session/group under a
  deny-fork/deny-network exact-read/write policy; the pure Python worker also
  has no child-creation capability. This removes the unsafe Popen monkeypatch as
  a containment boundary.
- OPEN — L31 must finish with three distinct proofs before re-review: forged
  qualifier blocked before execution; alternate Python and Node child-creation
  routes leave PID census `0 -> 0`; and all 71 named cases are observably
  executed, with `census=71/71` and `executed=71/71` reported separately.
- FACT — A read-only L0 invariant check detected an external Metis HEAD advance
  at `2026-08-21T10:30:02+02:00`: current HEAD/tree are
  `26ce2d56de9778e51668486ee7eddcb5b0985a96` /
  `6c44e3b74b44985133393439a1dc81dd7d316196`. Expanded-status SHA remains
  exactly `ea7eb74f...beb54` and tracked diff remains empty. Reflog attributes
  the transition to a normal commit; the only delta from ratified `a2dde2b...`
  is new `docs/piano-metis-db.md` (`170` lines), and the ratified commit is its
  ancestor. No L23/L27/L29/L30 process wrote or committed in Metis.
- STOP — Do not silently repin Model 1 to current Metis HEAD. Existing Kimi,
  candidate, registry, runner and capsule-v2 contracts remain bound to immutable
  `a2dde2b...`; the later real wave may read that exact Git object into an
  external capsule without checking out or modifying Metis. Adopting
  `26ce2d5...` would require an explicit requalification wave despite its
  docs-only delta.
- FIX — L31 first implementation boundary: `w3_production_worker.py` is now a
  pure verifier/materializer of pre-supervised capsule envelopes and imports no
  runner/process API. `w3_qualifier.py` separates a deny-fork Python policy from
  a deny-fork Node policy, launches each registered Node directly as a supervised
  session/group leader, reconstructs raw result/envelope evidence, then invokes
  the pure worker. Worker focused tests are `12/12`; py_compile is green. No real
  capsule, runner or Metis execution occurred. Bridge pin/authority binding and
  executable 71-case coverage remain in progress.
- FIX — L31 bridge trust root is implemented: canonical duplicate-free authority
  parsing, measured launcher/Python/sandbox/policy identity, compiled exact
  qualifier-byte pin, input-authority/report cross-binding, five-role artifact
  and result/evidence/runtime hash reconstruction, and immutable publication
  tree verification. Focused bridge tests excluding only the deliberately
  deferred final-byte-pin assertion are `13/13`; the full forged qualifier plus
  empty authority flow now blocks before child execution. Final pin is written
  only after qualifier format freeze.
- DONE — Redesigned process boundary probes are
  `in=5 out=5 distinct=5 gaps=0` in `4.6 s`: the pure worker is denied both
  standard fork/spawn APIs; the registered Node runs directly as its own
  supervised session/group; Node child creation for an unregistered executable
  and an exact detached child are both denied; outer timeout kills/reaps the
  exact group with no residual PID. The first run's two failures were only a
  test-harness mismatch because Node reports synchronous typed `EPERM`; the
  assertion was corrected and no product timeout or residual child occurred.
  All probes used tmp-only scripts, not the real runner or Metis.
- RISK — The first genuinely executable 71-case matrix run is `63/71` green in
  `11.8 s`, proving the former string census has been replaced by observable
  calls. Five failures were fixture defects (four JavaScript probe syntax, one
  v1 temporary-parent setup) and are corrected. Three Node runner timeout/cap
  cases expose a real exact-path policy gap: resolving an absolute import/runner
  path requires metadata lookup on path ancestors before the registered capsule
  subpath becomes reachable. Direct `node -e` containment probes remain `5/5`.
  L31 is testing a metadata-only exact-ancestor solution; no broad read grant is
  accepted and the matrix remains red until all 71 cases execute successfully.
- FIX — L0 approved only a bounded metadata resolution closure: fixed policy
  slots for literal ancestors derived from the already resolved capsule root,
  with depth cap, symlink-ancestry checks and authority-bound template bytes.
  It grants no ancestor subpath or file data read. Acceptance requires fake
  runner startup plus sibling/ancestor content denial, directory-list denial,
  depth-overflow rejection and parameter-drift rejection before rerunning 71.
- DONE — Executable mutation matrix now passes
  `in=71 out=71 distinct=71 gaps=0` in `14.5 s`, separately from the identical
  A11/B12/C12/D12/E16/F8 census. The bounded ancestor policy uses 32 fixed
  literal metadata slots with canonical/symlink/depth validation and
  authority-bound template hash. Focused metadata/process cases are `6/6`:
  fake runner starts; sibling content and ancestor listing remain denied; depth
  overflow and parameter drift block; timeout/stdout/stderr cleanup leaves no
  PID. No broad `/private` or `/Users` data/subpath access was added.
- DONE — L31 frozen safe-only gate is
  `in=235 out=235 distinct=235 gaps=0` in `28.4 s`: qualifier `175`, pure
  worker `12`, bridge `17`, contracts `24`, and exactly seven capsule-only
  Oracle tmp tests. Qualifier final SHA-256 is
  `d29ec5f43feb3722fbe5e3ec2a0ebf1cdbfaef5888c1309c8021f96114b39c8e`;
  bridge pin and one-byte drift regression pass. Final Node policy template is
  authority-bound at `e538a80f...18a44`.
- FACT — L31 static freeze: schemas `3/3`; authorities `None` `5/5`; Ruff check
  passes; format check `10/10`; diff check passes; exact writable roster
  `13/13`; no residual probe process. No external bundle/capsule, real runner,
  Metis access, payload, network, credentials, training, commit, push, broad
  Oracle suite or `make check` occurred.
- OPEN — Fresh L32 runtime-lifecycle and L33 authority/data reviewers are now
  inspecting the frozen rework read-only. L23 remains uncommitted and cannot
  advance until both verdicts and L0's independent replay are green.
- RISK — L33 reproduced a new tmp-only P1 TOCTOU. The bridge measures the
  pinned qualifier once, then executes the mutable original path in both fresh
  runs without copying/rechecking the measured preimage. Replacing that file
  after authority load but before `_run_once` executed different bytes
  (`691428f...`) and still returned `replay-qualified` with `2/10/5` counts and
  authority-shaped fake artifacts. L32/L33 promotion is therefore REWORK.
  Fix must execute bytes derived directly from the measured pinned preimage,
  not merely hash the same mutable path again, and include the exact timed-swap
  regression.
- RISK — L32 found a second P1 in the public low-level capsule API. The active
  L31 qualifier path is contained and leaves zero residual PIDs, but
  `run_oracle_from_capsule` still launches Node without Seatbelt/session-group
  containment and timeout kills only the exact PID. It is currently unreachable
  from L31 yet remains the production boundary required by the brief; L34 must
  either harden it to the same deny-fork/group model or remove/declassify it.
- RISK — L32 P2s: the Node policy's `file-read*` literal `/` permits listing the
  exact root directory, so the metadata-only claim is overstated; and external
  input paths with a symlink in a parent are resolved to a canonical target
  rather than rejected. No escape was reproduced, but L34 must first try
  metadata-only root startup (otherwise document and test the minimal exception)
  and reject noncanonical symlink ancestry across all v2 roots.
- FACT — L32 confirms the new effective L31 route itself: pure worker, deny-fork
  Python, five sequential Node session/group leaders, child creation denial,
  timeout/stdout/stderr group reaping, no live-Metis reference and final PID
  census zero. Its read-only/tmp focused replay is `32/32`. L33 independently
  recomputed qualifier/candidate/registry hashes and executed matrix `71/71`;
  no additional authority/schema P0/P1 exists beyond the timed path swap.
- FIX — L34 design is sealed before writing. The bridge will read and pin the
  qualifier preimage once, then feed those exact bounded bytes through an
  anonymous pipe to a minimal Python bootstrap with content-addressed logical
  `__file__`; no child reopens the mutable source path. The public
  run-from-capsule API will gain the same deny-fork/no-network exact-root Node
  session/group supervision and group reaping. All v2 input paths will reject a
  symlink in any parent component. Root metadata-only startup is probed first;
  an exact-root data exception is not accepted without necessity evidence and
  explicit narrowed claim. New regressions stay outside the historical 71.
- FACT — L34 root probe established a platform necessity. Node `v22.22.3` under
  Seatbelt with only `file-read-metadata` literal `/` aborts before JavaScript
  (`returncode=-6`, empty stdout/stderr); adding exact `file-read-data` literal
  `/` starts successfully, and that same capability necessarily permits listing
  only the root directory. L34 may therefore use exact root data+metadata as an
  explicit bootstrap exception, never `file-read*` or a root subpath. Claims and
  tests must state this honestly and prove `/Users`, `/private`, sibling content
  and nonregistered directory listings remain denied.
- FIX — L34 timed-swap replay now executes the measured preimage itself. A
  benign qualifier was read, its pathname replaced with code writing `swapped`,
  and the `-I -S -B -c` bootstrap consumed the original bounded bytes through
  EOF on an anonymous pipe. Exact result: exit `0`, empty stdout/stderr, marker
  `measured`; no mutable executable snapshot or pathname reopen. Compile
  filename is content-addressed `qualifier-v2://sha256/<digest>` and CLI argv is
  reconstructed before main. Four changed runtime files py_compile cleanly.
- FIX — Public capsule execution is now coded with deny-fork/no-network
  Seatbelt, exact paths/ancestor slots, Node session/group leadership,
  kill-group/reap and policy/envelope binding. Focused child/no-residual probes
  remain required before this claim can become DONE.
- DONE — Public capsule lifecycle probes `in=2 out=2 distinct=2 gaps=0` in
  `3.4 s`: a registered Node loop times out with typed failure and both PID and
  PGID are absent after reap; a Node request for a detached child receives
  `EPERM/EACCES`, writes no marker and leaves no child. The exact execution
  policy plus 32 ancestor slots are embedded in the envelope and revalidated
  from recalculated bytes.
- DONE — L34 path/read closure: exact-root data is explicitly modeled only for
  Node bootstrap; sibling content/list, `/Users` listing, `/private` listing and
  `/private/etc/hosts` data are denied. Parent-symlink/canonical-policy tests are
  `18/18`: bridge inputs `6/6`, qualifier inputs `6/6`, worker roots `2/2`,
  public capsule ancestry `1/1`, public process/output `2/2`, policy-slot drift
  `1/1`. Historical executable matrix remains separately `71/71`; a root
  necessity test is the 72nd test outside that denominator.
- RISK — L34 first final pin `3c344c...` is explicitly provisional/retracted.
  The corresponding safe suite was `256/256`, but final Ruff found three
  mechanical issues (two SIM300 and one import-order item). L34 will apply only
  those formatter/lint changes, recompute a new qualifier pin and rerun the
  pin/full safe gate; `3c344c...` must never be cited as final. Schema `3/3`,
  format `10/10`, diff check and process census were otherwise green. The fresh
  authority check is also being repeated against the correct three source
  modules.
- DONE — L34 final qualifier pin is
  `6c442871503369bffc329f136466fa07f1d048c6c33b84d04865bffc947c5a24`;
  the provisional `3c344c...` remains retracted. Pipe-bootstrap identity is
  `c8267391...f4610`, Node policy `d04f00ad...337f2`, and combined launcher
  policy `4e09a6bf...11891`. Timed path replacement executes only the measured
  preimage; public capsule timeout reaps PID+PGID and child creation is denied.
- DONE — L34 final safe-only gate is
  `in=257 out=257 distinct=257 gaps=0` in `29.8 s`: qualifier `184`, pure
  worker `14`, bridge `25`, contracts `24`, and ten exact capsule-only Oracle
  nodeids. Historical mutation matrix separately executes `71/71` in `14.6 s`.
  Parent-symlink, stream-root and exact-root exception regressions are outside
  that denominator.
- FACT — L34 final static gates: schemas `3/3`; Ruff and format `10/10`; diff
  check green; source authorities `None` `5/5` from the correct three modules;
  process census zero; owned roster `13/13`, inherited L0 board/ledger/brief
  `3/3`, unexpected files `0`. No real runner/Metis, bundle/capsule payload,
  network, training, `make check`, whole Oracle, commit or push occurred.
- OPEN — A final fresh dual re-audit must independently replay timed preimage,
  public capsule containment/path boundary and authority/replay/data bindings
  before L0 may accept or commit L23.
- FACT — L0 independently reran the exact L34 safe-only command after freeze:
  qualifier `184`, worker `14`, bridge `25`, contracts `24`, and ten explicit
  capsule-only Oracle nodeids all exited green, `in=257 out=257 distinct=257
  gaps=0`. L0 also remeasured the qualifier as
  `6c442871503369bffc329f136466fa07f1d048c6c33b84d04865bffc947c5a24`.
  This nominal gate does not override adversarial findings.
- RISK — L35 reproduced a new tmp-only P1 in the public capsule boundary.
  If `process_root/invocations` already exists as a symlink to an external
  directory, `run_oracle_from_capsule` creates its invocation workspace through
  that link before strict canonical/symlink validation; the probe ended with a
  typed missing-Node error but `external_workspace_created=True`. L34 is
  therefore REWORK until every creation parent is validated before the first
  write and an exact outside-empty regression passes.
- RISK — L35 reproduced a second tmp-only P1 in bridge supervision.
  `_execute_qualifier_preimage` uses a timeout that terminates only the direct
  Python process. A measured preimage that created a new-session descendant was
  reported blocked at timeout while the descendant remained alive; the auditor
  killed and reaped it explicitly. The bridge must supervise and reap the full
  qualifier process tree/session on timeout, including the real qualifier's
  separately supervised Node/worker descendants.
- STOP — L34 promotion, commit and push remain closed despite `257/257`: the
  independent runtime re-audit has two P1 findings. Authority/data review and
  the remainder of the runtime audit continue read-only while a narrowly owned
  L37 remediation is prepared.
- RISK — L36 reproduced a third tmp-only P1 at the authority/data boundary.
  The v2 qualifier and pure worker compare declared role counts to integer `1`
  without first requiring exact `int`, so canonical JSON
  `expected.roles.author=true` passes because Python treats `True == 1`.
  The standalone bridge rejects it, but qualifier and worker are not
  independently fail-closed. L37 must add strict integer checks in both loaders
  plus canonical rehashed bool regressions; editing the qualifier requires a
  new measured pin and full bridge/static replay.
- RISK — L36 also reproduced a capsule execution TOCTOU P1. The qualifier
  verifies the immutable capsule before and after the five executions, but each
  execution reopens Node/tsx/runner by mutable pathname. In a canonical fake
  capsule, replacing only the `0444` runner after pre-verification executed the
  replacement (`marker=swapped`); restoring the original bytes before the
  post-check made both capsule verifications pass. L37 must execute immutable
  measured preimages/content-addressed copies under the process root, bind those
  exact executed bytes to the envelope, and add the timed runner-swap replay.
- FACT — L35 final verdict is `REWORK`, `P0=0 P1=2 P2=0`. Its remaining
  positive runtime slice is `30/30`: measured qualifier preimage, current pins,
  external parent-symlink rejection, deny-fork/network, exact-root exception,
  public timeout/reap and no-live-checkout all pass. A common inherited process
  group is not sufficient: under the current Seatbelt profile a tmp child
  successfully called `setsid()`. L37 therefore uses an explicit bridge-owned
  registration/ACK barrier before child exec and reaps every registered child
  group plus the qualifier on timeout.
- FIX — L37 is dispatched to the same frontier implementation lane on the
  frozen 13-file ownership surface. Its combined acceptance set is: secure
  `dir_fd`/`O_NOFOLLOW` workspace creation with outside-empty proof; bridge-owned
  child registration/ACK and zero-residual timeout cleanup; strict integer role
  counts in qualifier and worker; and immutable measured/content-addressed
  capsule execution bytes with timed runner-swap rejection. No real
  Metis/runner, network, payload, training, board write, commit or push is
  authorized in that lane.
- FIX — L37 first checkpoint closes the secure-creation and strict-count
  slices. Public `process_root/invocations/name` is now created through a held
  root directory fd with `mkdirat/openat`, `O_DIRECTORY|O_NOFOLLOW|O_EXCL`;
  stdout/stderr are created and read through the held invocation fd. The exact
  preexisting-symlink replay is blocked and the external roster remains empty.
  Qualifier and worker now require exact integer candidates/executions/roles;
  canonically rehashed bool variants are blocked. After correcting a shared
  test-fixture dict contamination, the bounded first gate is `5/5` and touched
  files compile cleanly. Child registration and immutable capsule snapshot
  slices remain in progress; this is not promotion evidence yet.
- RISK — L0's adjacent public-boundary read found the same class after runner
  completion: `output.parent.mkdir(parents=True)`, temporary write and replace
  still use mutable pathnames after the earlier symlink check. L37 must either
  require and hold an already verified output-parent directory fd or create the
  full output path through no-follow dir-fd operations, then publish with an
  anchored rename; an output-parent swap/symlink replay must leave the external
  target empty. The invocation-only repair is not sufficient.
- DONE — L37 secure publication slice now closes both creation surfaces.
  `invocations` requires exact mode `0700`; invocation and full output ancestry
  are created/traversed with held directory fds plus
  `O_DIRECTORY|O_NOFOLLOW`, and output publication uses an exclusive temporary
  file plus no-clobber anchored link/unlink/fsync rather than path-based
  `os.replace`. Exact symlink-outside-empty, namespace `0777/0555` and timed
  output-parent rename+symlink regressions are `in=5 out=5 distinct=5 gaps=0`.
  Child registration and immutable capsule preimages remain open.
- DONE — L37 bridge supervision first gate is
  `in=4 out=4 distinct=4 gaps=0`. A bridge-owned socketpair carries a nonce;
  each qualifier child becomes its own session/group leader in pre-exec,
  atomically registers role and `pid=pgid=sid`, and cannot exec before ACK.
  EOF/SIGPIPE before ACK exits `125`. The bridge validates the live identity
  and exact six-role roster, budgets `6 * child_timeout + 15 s`, kills every
  registered group on timeout, permits qualifier unwind/reap, then proves all
  groups absent. Tests cover measured preimage, two separate child groups with
  zero residual PID/PGID, exact role/budget wiring, and EOF-before-ACK. Final
  pin remains intentionally open until immutable capsule work and formatting.
- DONE — L37 qualifier-side execution-preimage slice is green. Source,
  dependency and capsule bytes are captured once from their verified external
  rosters, materialized content-addressed under a private `trusted_root`
  disjoint from writable `process_root`, sealed to directory `0555` and exact
  file `0444/0555`, and fully reverified before and after use. A live timed
  external runner swap+restore still executed `original`; the runner's snapshot
  write attempt returned `EPERM/EACCES`, and post-roster bytes were identical.
  The pure worker likewise cannot open source/dependency manifests for write.
  Public `run_oracle_from_capsule` parity is being completed with an immutable
  capsule and disjoint writable sibling; no final D promotion yet.
- RISK — L0's public-parity read found one remaining path race in the in-flight
  code: the held invocation fd exists, but capsule snapshot materialization
  still creates its target/parents/files through the yielded pathname. Renaming
  that invocation and replacing it with an external symlink could redirect
  writes before Node launch. Public D cannot close until the entire capsule
  tree is materialized relative to the held invocation fd and a timed
  invocation-rename/symlink probe leaves the external target empty.
- DONE — L37 public execution-preimage parity is now
  `in=2 out=2 distinct=2 gaps=0`, with the capsule materialized entirely by
  `mkdirat/openat/write-at` from the held invocation fd. The opened capsule fd
  supplies recursive pre/post roster reads, and capsule/write root `dev+ino`
  identities are checked at entry, immediately before Popen and after reap.
  A real Node/Seatbelt runner swap executes captured `original`, denies snapshot
  writes and preserves exact post-roster; a timed invocation rename+external
  symlink during write-at is blocked with outside roster empty. The expanded
  capsule-only public/verifier slice is `16/16`.
- RISK — Platform boundary stated without overclaim: sandbox-exec/Node still
  require a pathname for Node/loader/runner; macOS/Python offers no fexecve here.
  L37 holds and rechecks the private fd-root but does not claim atomic loader
  fexec. Final auditors must rank this against the explicit trusted-parent-host
  boundary rather than silently calling it byte-atomic execution.
- DONE — L37 integration checkpoint after final format is green. Final qualifier
  candidate pin is
  `8f71b47e5e6b113d57d5196f271f147173e0019cdb92d120aa42562fd9c085a1`,
  bootstrap `62982b45...c046a`, Node policy `79ee98a6...c81f6`, combined
  launcher policy `cfd09f90...5f4d8`. The exact safe-only roster is
  `in=273 out=273 distinct=273 gaps=0` in about `39 s`, including sixteen
  explicit capsule-only Oracle cases and never the whole Oracle file. The
  historical executable matrix separately remains `71/71` in `17.36 s` with
  A11/B12/C12/D12/E16/F8 exact. Schemas `3/3`, Ruff, format `10/10` and diff
  check are green. L0 and fresh independent auditors must still replay this
  final-byte snapshot; delegated green alone does not promote it.
- DONE — L0 independently replayed the frozen L37 bytes. Exact collection is
  qualifier `187`, worker `15`, bridge `31`, contracts `24`, explicit Oracle
  `16`, totaling `in=273 out=273 distinct=273 gaps=0`; the full selected run
  exits `0`. L0 separately reran the executable matrix `71/71`. It recomputed
  qualifier, bootstrap, Node policy and combined launcher hashes directly from
  bytes, `4/4` exact, and independently obtained schemas `3/3`, authorities
  `None` `5/5`, Ruff green, format `10/10`, diff check green. Current dirty
  roster is exactly the authorized `16/16` paths: owned implementation `13/13`
  plus L0 board/ledger/brief `3/3`, unexpected `0`.
- FACT — Frozen-byte re-audits L39/L40 are dispatched to the same two frontier
  reviewers that found the four prior P1s. L39 owns runtime creation/process
  containment and must replay fd-anchored symlink races plus registered-child
  timeout cleanup. L40 owns authority/data/executed-byte binding and must replay
  strict bool rejection plus qualifier/public external runner swaps. Both must
  explicitly rank the disclosed pathname-not-fexec boundary under the trusted
  parent-host assumption. They are read-only/tmp-only and cannot infer ACCEPT
  from L0's `273/273`.
- RISK — L0 independently reproduced a new bridge external-root P1 on the
  frozen L37 bytes. After the first strict check of a missing `artifact_root`,
  the probe renamed its parent and replaced it with a symlink to an external
  directory. `artifact.mkdir(parents=True)` then created
  `outside/artifacts`; only the second strict check blocked. Exact evidence:
  `swapped=True`, `outside_artifact_created=True`. This is the same
  check-then-create class and prevents L37 ACCEPT despite all nominal gates.
  L39 must census the analogous qualifier artifact/run creates; remediation
  must anchor missing external-root creation to held no-follow parent fds and
  prove every external target remains empty.
- FACT — The analogous qualifier census is now reproduced independently for
  both v2 external roots. A timed parent rename plus symlink after the first
  strict check caused `outside/artifacts` to be created before the qualifier
  blocked on its second artifact-root check; the same attack caused
  `outside/runs` to be created before the second run-root check blocked. The
  affected external-root roster is therefore bridge artifact, qualifier
  artifact and qualifier run: `in=3 out=3 distinct=3 gaps=0`. This remains one
  check-then-create P1 class, not three inflated findings.
- FACT — L40's frozen authority/data re-audit returns `P0=0`, `P1=1`, `P2=1`.
  The only P1 is the already counted three-path external-root class; no further
  authority, strict-type, report, artifact or replay blocker was found. Exact
  bool probes `2/2`, qualifier/public external-runner swaps `2/2`, bridge plus
  pure-worker `46/46`, fd timed swaps `2/2` and the genuinely executed matrix
  `71/71` are green. All current pins were independently recomputed exact and
  the five production source authorities remain `None`. P2 is the honestly
  disclosed pathname-not-fexec boundary: retained root fds and immediate
  dev/inode plus roster checks provide no observed bypass under the trusted
  parent-host assumption, but this must never be described as atomic fexec.
- RISK — L39 has now reproduced a second external-path P1 in the shared
  `_publish_qualification` surface. Swapping the artifact-root parent just
  before the qualifications namespace `mkdir` redirected both namespace
  creation and the output-tree rename into the external target; exact probe
  evidence is `swapped=True`, `outside_published=True`,
  `outside_payload=True`, and the function returned green. Because the helper
  is shared by fixture v1 and production v2, L41 must make publication
  fd-relative to the already opened artifact root and must cover both callers;
  a root-creation-only patch is insufficient.
- RISK — L39's final lifecycle census also proves the temporary-tree cleanup
  must be part of the same root-anchoring rework. `mkdtemp(dir=run)` remains
  pathname-racy after the second check, and a later parent swap made the
  path-based `_remove_tree(process_root/trusted_root)` delete the attacker's
  outside tree while preserving the displaced original: exact evidence
  `outside_tree_deleted=True`, `displaced_original_preserved=True`. Final L39
  verdict is `P0=0 P1=2 P2=1`: P1 lifecycle (create/use/cleanup) plus distinct
  P1 shared publication; P2 is the already disclosed trusted-parent
  pathname-not-fexec boundary. Its positive runtime recheck is `21/21` with
  final process residual count `0`.
- FIX — L41 design is sealed before implementation. Qualifier and bridge each
  receive an independent retained-directory-handle boundary: canonical
  existing parent fd, missing leaf created with `mkdirat`, leaf opened with
  `O_DIRECTORY|O_NOFOLLOW`, exact `0700`, and retained dev/inode/mode. Random
  holder/process/trusted/bundle/publication namespaces are created only below
  those handles. Shared v1/v2 publication will stage, snapshot, seal and
  `renameat` within the retained qualifications fd. Cleanup recursively
  unlinks/rmdirs relative to retained fds and never follows a reconstructed
  pathname. Path arguments survive only where macOS sandbox/Node require them,
  with held-inode checks and the existing explicit non-fexec limitation.
- FIX — L41's qualifier primitives are now implemented: retained root/child
  handles with exact `0700` identity, fd-recursive cleanup, fd-relative
  snapshot/write/seal, and a rewritten shared publisher that copies and seals
  only through process/artifact descriptors without pathname rename or reopen.
  v1/v2 caller wiring is still in progress, so no compile/focused green is yet
  claimed from this intermediate state.
- FACT — First honest L41 runtime checkpoint is green: qualifier compile passes
  and the exact v1 positive slice covering no source-authority registration plus
  two fresh launcher subprocesses/publications is `in=2 out=2 distinct=2
  gaps=0`. This establishes v1 caller wiring only; v2, bridge and timed parent
  swaps remain open and are not inferred from it.
- FACT — L41 bridge fd holder/run wiring now compiles and its mocked positive
  plus drift slice is `6/6` green. The complete qualifier safe file initially
  exposed only two intentional contract drifts—legacy precreated artifact mode
  `0755` versus new exact `0700`, plus error wording—and their focused rerun is
  `2/2` green after fixture correction. No fd/path child incompatibility is
  observed. Real fake-capsule v2 and five timed-root/publication regressions
  remain required before any new pin.
- DONE — The exact L41 timed parent-swap roster is now
  `in=5 out=5 distinct=5 gaps=0`: bridge missing artifact root `1`, qualifier
  v2 missing artifact/run roots `2`, and shared fd publisher v1/v2 `2`.
  Every attack renames the validated parent and installs a symlink immediately
  before create or publication; every call blocks, every external target is
  exactly empty, and the bridge root attack launches no qualifier child. The
  publisher cases also exercise fd-rooted cleanup after the swap. Broad safe
  suites and real fake-capsule v2 compatibility remain open before repinning.
- DONE — The L39 cleanup attack is closed by a separate, non-inflated
  regression `in=1 out=1 distinct=1 gaps=0`. After swapping the run parent to
  an outside tree containing same-name process/trusted directories, fd-rooted
  cleanup removed both displaced owned originals, preserved both outside
  sentinels byte-for-byte, and returned success. No path-based process/trusted
  cleanup remains in the v2 lifecycle.
- FACT — Real tmp-only fake-capsule compatibility is `2/2` green after the fd
  conversion: registered fake Node execution and captured-preimage execution
  during external runner swap/restore both succeed, with no fd/path child
  incompatibility. The first broad qualifier pass had one stdout-cap timing
  message mismatch; its immediate isolated rerun is green and left no residual
  PID, so it remains a flake pending the clean broad rerun rather than accepted
  evidence. Mechanical lifecycle census now finds zero `mkdtemp`, path rename
  or path rmtree uses in qualifier/bridge.
- FACT — The complete pre-final-mode qualifier file is now clean:
  `in=192 out=192 distinct=192 gaps=0`, exit `0`, about `34.4 s`, failures
  `0`; this supersedes the earlier stdout-cap flake. Four subsequently added
  exact-`0700` root-mode regressions are separately `4/4` green, making the
  final qualifier denominator `196` pending one broad replay. Formatter is
  frozen and the new candidate qualifier pin is
  `31ff5fea12f74afcfe7529b7478241ef4a5f692fd86b781ebe4add63895a2f1f`;
  it is not yet accepted until the final-byte gate and independent audit.
- DONE — L41 final-byte safe-only gate is
  `in=285 out=285 distinct=285 gaps=0`: qualifier `196`, bridge `34`, pure
  worker `15`, contracts `24`, and sixteen explicitly selected capsule-only
  Oracle cases. Run exits `0` in about `34.9 s`, with no raw exception,
  surviving timeout, whole Oracle file, real Metis or real runner. The
  separately executed historical matrix remains `71/71` in `15.97 s` with
  exact A11/B12/C12/D12/E16/F8 roster. Final pin/root/publish/cleanup/mode
  focused set is `14/14` green. Static gates, L0 replay and fresh frontier
  audits still prevent promotion.
- DONE — L41 is byte-frozen for L0 and independent review. Final hashes are
  qualifier `31ff5fea12f74afcfe7529b7478241ef4a5f692fd86b781ebe4add63895a2f1f`,
  bootstrap `62982b45...c046a`, Node policy `79ee98a6...c81f6`, combined
  launcher policy `cfd09f90...5f4d8`; qualifier raw hash equals the bridge pin.
  Draft 2020 schemas `3/3`, Ruff, format `10/10`, diff check, authorities None
  `5/5`, owned roster `13/13`, board/ledger/brief `3/3`, off-limits `0`, and
  process census `0` are green. Mechanical lifecycle census finds zero path
  `mkdtemp`, rmtree/remove-tree, rename, or artifact/run mkdir uses. L41 exact
  focused accounting is timed roots/publish `5/5`, swapped-run cleanup `1/1`,
  exact modes `6/6`, combined critical set `14/14`, and real tmp-only
  fake-capsule/captured-preimage `2/2`. No further L41 writes are authorized
  until L0 and fresh reviewers return.
- RISK — L0 rejected the L41 freeze before reviewer dispatch. Mechanical
  `rg` found one residual pathname create at `_run_capsule_node_v2`:
  `invocation.mkdir(parents=True)`. A direct tmp-only timed parent swap then
  produced exact evidence `swapped=True`,
  `outside_invocation_created=True` before an intentional stop. The same
  function opens/stats/reads Node stdout/stderr by pathname. This violates the
  sealed all-child-fd lifecycle despite `285/285`; the reported zero path-mkdir
  census was therefore false. L41b must pass the retained process-root handle,
  create node-invocations and each execution with mkdirat/openat, and handle
  stdout/stderr only via invocation descriptors. Node/sandbox path arguments
  remain the separately disclosed P2 boundary.
- RISK — L0's avoidable-parent-I/O census also found v1/v2 worker artifact
  verification reopening `process_root.path/output`, and bridge `_run_once`
  reconstructing and traversing `artifact_root/qualifications/...` by path even
  though retained process/run-artifact handles already exist. L41b must pass
  and consume output/publication descriptors for all parent-owned create,
  open, stat, read, write and delete operations. Only pathname arguments that
  macOS sandbox/Node fundamentally require remain under the explicit P2
  trusted-parent boundary.
- FIX — L41b Node invocation lifecycle is now descriptor-based end to end:
  retained namespace/execution directories with mkdirat and exact `0700`,
  stdout/stderr openat `O_EXCL|O_NOFOLLOW`, live caps via fstat, final reads via
  `_read_regular_at`, and cleanup through the retained parent fd. Compile plus
  fake runner, captured-preimage and stdout-cap focused paths are `3/3` green.
  v1/v2 output-verifier descriptors and bridge publication descriptors remain
  in progress; no new pin is claimed.
- FIX — L41b has completed the parent-side conversion in code: v1/v2 worker
  output verifiers now consume retained output handles and perform traversal,
  reads, normalization replace and snapshots fd-relative; bridge `_run_once`
  receives retained artifact/run handles and opens the qualifications digest,
  report and artifacts entirely via descriptors, with no `rglob` or path read.
  Compile/focused and timed invocation/stream/publication attacks are still
  pending, so this is implementation evidence only.
- DONE — First L41b timed fd-I/O attacks are
  `in=4 out=4 distinct=4 gaps=0`. Qualifier Node invocation-create parent swap
  and stdout-read parent swap are `2/2`: both block; the first leaves outside
  empty and the second preserves the outside sentinel/roster. Bridge retained
  publication snapshot positive plus timed artifact-parent swap are `2/2`; the
  attack blocks with outside empty. v1/v2 callers now open retained output
  handles. Broad runs remain closed until the lifecycle path census finishes.
- FACT — L41b qualifier broad rerun is `in=198 out=198 distinct=198 gaps=0`
  in about `31.6 s`. Its first pass exposed one diagnostic-only mismatch for an
  artifact symlink; anchored no-follow metadata classification restored the
  explicit rejection and the full rerun is green. Bridge is `34/35`, with the
  sole failure the deliberately stale qualifier pin; all functional bridge
  tests pass. The expanded lifecycle census now finds no parent-owned pathname
  create/open/read/stat/delete in process, trusted, output, invocation,
  publication or bundle verification. Remaining path uses are nine explicit
  child/sandbox/canary arguments or returned child paths under P2, plus external
  immutable-input reads/root identity assertions. v1 bundle and v2 trusted
  preimage post-verification are also fd snapshots. Final format/repin and
  frozen-byte replay remain open.
- DONE — A delegated read-only lifecycle census independently returns zero
  residual parent-owned pathname operations across root/child creation,
  recursive cleanup, fd stat/read/write/replace/seal, v1 bundle, v2 trusted
  preimage, worker streams, Node invocation, both output verifiers,
  qualification publication and bridge replay/publication. It enumerates nine
  remaining pathname surfaces exactly, all limited to child/sandbox/canary
  commands, cwd/environment/arguments or returned child paths under the
  explicit P2 boundary. External immutable-input reads and root identity guards
  are separately classified. Census made no edits.
- DONE — L41b final formatted-byte runtime gate is
  `in=288 out=288 distinct=288 gaps=0`: qualifier `198`, bridge `35`, worker
  `15`, contracts `24`, explicit capsule-only Oracle `16`. The separate
  executable mutation matrix remains `71/71`; final pin plus three P1 timed
  regressions are `4/4`. Frozen qualifier candidate pin is
  `17e608896053eef984494c7c258ee25f433aae558cb4251406b68956c20362af`.
  Static, authority, ownership and process censuses are still running, and L0
  plus fresh frontier reviewers must replay before promotion.
- DONE — L41b is frozen for audit. Draft 2020 schemas `3/3`, Ruff/format
  `10/10`, diff check, authorities None `5/5`, owned roster `13/13`, HEAD exact
  baseline and final process census `0` are green. Final hashes are qualifier
  `17e60889...62af`, bootstrap `62982b45...c046a`, Node policy
  `79ee98a6...c81f6`, combined launcher policy `cfd09f90...5f4d8`. The
  implementation made no Metis/runner/network/payload/training/make-check/Git
  action. L0 replay and two fresh independent frontier reviews remain mandatory
  before the commit/push STOP can be lifted.
- DONE — L0 independently replayed the L41b frozen bytes: exact collection is
  qualifier `198`, bridge `35`, worker `15`, contracts `24`, explicit Oracle
  `16`, totaling `in=288 out=288 distinct=288 gaps=0`, exit `0`. L0 separately
  reran the executable matrix `71/71` and the qualifier-pin plus invocation,
  stream and bridge-publication attacks `4/4`. It independently recomputed all
  four hashes exact, validated schemas `3/3`, authorities None `5/5`, Ruff,
  format `10/10`, diff check, authorized dirty roster and zero owned residual
  processes. Fresh frontier audits remain mandatory.
- FACT — The real Metis checkout advanced externally during this payload-free
  work to HEAD `f5b54b8d5700f90139c0fc4df58f2a55de713fc9`, tree
  `7683d744533970fe44f9bb9c470f211eead99007`; the two commits since the prior
  observation modify only `docs/piano-metis-db.md`. Tracked diff remains empty.
  The untracked roster remains 18 paths but its name/status hash is now
  `5ecade9b10288b12370463ae4bd748c77dfbf220084d89a2fc3125bab7099cd6`,
  so the previous ambient-status hash is stale. L0 made no Metis write and does
  not repin authority: formal qualification remains the immutable
  `a2dde2b1...` / `75473e26...` capsule until an explicit integration wave.
- RISK — Fresh runtime auditor L42 independently reproduced a new P1 in the
  shared publisher after L0 gate replay. `_publish_qualification` writes and
  seals the retained final digest child by fd, but does not reassert the target
  or qualifications namespace pathname identity before clearing
  `owned_entry`/returning success. A timed probe renamed the final target before
  the first write and installed an outside symlink at the canonical name. The
  function returned green; the displaced original held the complete immutable
  publication, while the canonical target remained the attacker symlink. The
  outside sentinel/roster stayed exact, so this is not an outside-write repeat;
  it is a distinct false-green canonical-publication substitution. Commit/push
  remain STOP while L42 completes adjacent census and one bounded rework is
  defined.
- RISK — L42 reproduced the same canonical-child identity class independently
  in the bridge consumer. `_run_once` opens retained qualifications/publication
  handles and snapshots exact fd bytes, but reasserts only artifact/run roots.
  After publication fd open, the probe renamed the publication, restored the
  displaced fd inode to immutable mode and installed an outside symlink at the
  canonical name. `_run_once` returned green with five artifacts while the
  canonical publication remained the symlink; outside sentinel/roster were
  unchanged. The affected roster is now producer plus bridge consumer `2/2`.
  Bundle and trusted-preimage targets already reassert canonical target
  identity and are not in this P1 class. Namespace/target assertions and
  displaced-child cleanup remain to be bounded before rework.
- RISK — L42 also reproduced a distinct green-finalization P1 in bridge replay
  cleanup. A timed probe swapped the random retained replay holder immediately
  before `_remove_owned_directory`; cleanup safely preserved the outside
  sentinel but returned `False`. `run_replay_gate` ignored that result and
  emitted `status=replay-qualified`, leaving both a canonical symlink and an
  empty displaced holder under the artifact root. Qualifier v1/v2 finalizers
  contain the same ignored cleanup-result shape and are under direct replay.
  L44 must make owned cleanup completion a required green invariant, while
  preserving the no-outside-delete behavior.
- RISK — The ignored-cleanup false-green roster is now reproduced across all
  three public lifecycles: bridge replay, qualifier v1 and qualifier v2
  `in=3 out=3 distinct=3 gaps=0`. Each timed child rename+symlink makes
  `_remove_owned_directory` return `False`; each public API still returns a
  qualified result and leaves a canonical symlink plus displaced empty owned
  directory, while outside sentinels remain exact. Publisher error cleanup has
  the same inability to remove a renamed target, but its primary error remains
  blocked; that residual is not inflated into a fourth false-green case. L44
  must require cleanup success for every owned public lifecycle and test the
  blocked publisher residual separately.
- FACT — L42 final verdict on frozen L41b is `REWORK`, `P0=0`, `P1=2`
  classes, `P2=2` classes. P1 classes are canonical producer/consumer child
  substitution and ignored cleanup failure across three public lifecycles.
  P2 covers blocked publisher-error residual cleanup and the nine explicit
  trusted-parent/non-fexec child/sandbox path surfaces. Its bounded existing
  positive slice is `13/13`, which does not cover the newly reproduced attacks.
- FACT — L43 authority/data/replay verdict is `REWORK`, `P0=0`, `P1=0`,
  `P2=3`; it found no authority or replay false green. P2s are wrong v1 blocked
  discriminator for malformed explicit v2 CLI, bool-as-int acceptance in
  authenticated worker denominator fields before safe normalization, and raw
  `TypeError` from non-string capsule-envelope identities. Matrix is genuinely
  executed `71/71`; focused authority/report/bridge/worker/Oracle slice is
  `108/108`; all pins and five None authorities recompute exact.
- FIX — L44 is the final bounded rework: producer/consumer canonical child
  assertions; mandatory cleanup success with inode-aware same-parent hygiene;
  exact v2 blocked discrimination; strict worker count types; typed public
  capsule-envelope identity failures. Existing nine child/sandbox path surfaces
  remain explicit P2 and cannot be relabeled fexec. No commit/push or integration
  action is authorized until frozen-byte L0 plus fresh audits accept L44.
- FACT — L44 retains frontier ownership for implementation and semantic
  judgment; a lower-cost Luna sublane is limited to read-only mechanical
  mapping of affected call sites. It cannot write, promote or widen scope. This
  preserves the project routing contract while the attack regressions precede
  any broad gate.
- FIX — L44 compiles with no architecture blocker. Producer assertions now
  cover existing, raced and new target branches; bridge retains namespace and
  publication handles through validation and reasserts both after snapshot and
  immediately before return. Both cleanup helpers scan only the retained parent
  fd by dev/inode, remove a renamed owned inode without following or deleting
  its replacement, and return false whenever the canonical name was replaced.
  v1, v2 and bridge green returns require cleanup success, with v2 attempting
  both roots. The three P2 code changes also compile; attack regressions are not
  yet green and no promotion is inferred.
- DONE — L44 producer canonical-identity attacks are
  `in=4 out=4 distinct=4 gaps=0`: new target swap with renamed owned inode
  removed, namespace swap, existing-target branch, and forced raced branch.
  Every case blocks on canonical identity and preserves the outside
  sentinel/roster exactly. The macOS fixture had to chmod the same-owner sealed
  target before rename and restore `0555` on the displaced inode; this changes
  only attack setup, not product behavior. Bridge consumer and cleanup public
  paths remain open.
- DONE — L44 closes both P1 class denominators. Canonical identity is
  `in=5 out=5 distinct=5 gaps=0` (publisher `4` plus bridge consumer `1`).
  Mandatory public cleanup is `in=3 out=3 distinct=3 gaps=0`: v1 blocks on a
  false cleanup result; v2 attempts both process and trusted cleanup before
  blocking; bridge removes holder bytes but a false canonical confirmation
  blocks and leaves its artifact root empty. No raw exception or timeout was
  observed. P2 focused regressions and broad replay remain open.
- DONE — All L44 focused attacks are
  `in=15 out=15 distinct=15 gaps=0`. P2 breakdown: safe CLI discriminator
  `2/2` (explicit v2 type error and duplicate/missing mode emit canonical
  `_blocked_v2`); consistently rehashed worker bool claims `2/2` (counts and
  roles rejected by strict `_exact_count_map`); public Oracle non-string
  identities `3/3` (`execution_id`, `run_nonce`, capsule hash raise typed
  `OracleError`). Together with canonical identity `5/5` and mandatory cleanup
  `3/3`, no raw exception or timeout remains in this attack set. Broad
  frozen-byte replay and repin remain open.
- FACT — L44 prepin qualifier+bridge functional roster is `244/244`; after
  final repin the complete safe-only roster is
  `in=303 out=303 distinct=303 gaps=0`: qualifier `208`, bridge `37`, worker
  `15`, contracts `24`, explicit Oracle `19`. The first separate matrix replay
  was `70/71`; only D/stdout-cap crossed its old two-second fixture startup
  deadline and produced a typed timeout, with no raw exception or residual.
  The test now uses synchronous fd write and a ten-second cap-fixture startup
  budget without changing production policy/caps; isolated stdout/stderr cap
  cases are `2/2` green. Exact matrix rerun remains required before freeze.
- DONE — L44 executable matrix rerun is
  `in=71 out=71 distinct=71 gaps=0`; the isolated timeout proof writes its PID
  and is killed/reaped, while stdout/stderr cap proofs are exact. Final
  qualifier bytes are frozen and bridge-pinned at
  `37d60f75f6b4bbf8dcc1dd205ef0ac65d5099d3f7466d601b4b4fca5a4d02065`.
  Only test timing/source changed after this pin. Final static checks and one
  last `303` replay remain open.
- DONE — L44 is frozen for independent audit. Final safe-only runtime gate is
  `in=303 out=303 distinct=303 gaps=0`: qualifier `208`, bridge `37`, worker
  `15`, contracts `24`, nineteen explicit capsule-only Oracle cases. Matrix is
  separately `71/71`; focused L44 attacks `15/15`. Schemas `3/3`, Ruff/format
  `10/10`, diff check, authorities None `5/5`, four content hashes, bridge
  cross-bindings `3/3`, ownership `16/16`, and process census `0` are green.
  Final qualifier pin is
  `37d60f75f6b4bbf8dcc1dd205ef0ac65d5099d3f7466d601b4b4fca5a4d02065`;
  bootstrap and policy hashes remain unchanged. No Metis/runner/network/payload,
  training, make-check, commit or push occurred. L0 replay and fresh audits are
  still mandatory.
- STOP — Commit, push and Kimi clean-SHA replay remain closed on this new P1.
  The already frozen audits continue to bound the full affected roster before a
  single L41 rework is opened; no partial root fix is promoted.
- FACT — L0 independently replayed the L44 byte freeze: safe-only gate
  `in=303 out=303 distinct=303 gaps=0`, executable mutation matrix
  `in=71 out=71 distinct=71 gaps=0`, and the exact L44 attack roster
  `in=15 out=15 distinct=15 gaps=0`, all with exit `0`. Collection closes as
  qualifier `208`, bridge `37`, worker `15`, contracts `24`, explicit Oracle
  `19`; no whole Oracle file, real runner or Metis checkout was executed.
- FACT — Qwen is now a project orchestra team beside Kimi. The tracked
  `.orchestra/teams.json` pins Qwen Code `0.21.12` to the live-observed
  `qwen3.8-max` and Kimi
  Code `0.36.1` to `kimi-code/k3`. Live capability probes are `4/4` for each
  team (temporary write, stream JSONL, session id, pinned model). Pre-wave
  lesson sync is current; usage limits remain undeclared, so no quota
  percentage is invented. The first explicit `qwen3.7-plus` task returned
  HTTP `401` before project work; the successful probe init envelope identified
  `qwen3.8-max`, so L0 corrected the pin and relaunched instead of trusting the
  stale model assumption.
- RISK — Fresh L45 runtime audit reproduced a new cleanup race in all three
  public finalizers: after the owned-inode `stat` but before `rmdir`, replacing
  the canonical name with a new empty directory makes cleanup return green
  while the owned inode survives under a displaced name. Qualifier v1,
  qualifier v2 and bridge replay are false-green `3/3`; current cleanup tests
  only forced a direct false return and did not exercise this window.
- STOP — L44 is therefore not promotable despite `303/303`, `71/71` and
  `15/15`. Commit, push, production authority ratification and training remain
  closed until the stat-to-rmdir race is fixed, independently replayed and the
  full frozen gates are green again.
- RISK — L46 independently found that Python argparse abbreviations remain
  enabled: production spellings such as `--mo`/`--m` are accepted by argparse
  but missed by the pre-classifier, so malformed production-v2 commands can
  emit a fixture-v1 blocked envelope. Exact `allow_abbrev=False` hardening and
  regressions are required; classification P1/P2 awaits the completed L46
  verdict.
- RISK — L46 also reproduced a manual-validator/schema divergence for v2
  authority paths: the qualifier accepts normalized-but-noncanonical strings
  such as `runtime//w3_production_worker.py` after consistent rehash, while the
  authority schema and bridge reject them. No replay false-green was obtained,
  but qualifier and schema truth must agree before promotion. L46 ranks both
  authority findings P2 and returns `P0=0 P1=0 P2=2` for its slice.
- RISK — L45 found an adjacent fail-closed resource leak in the public capsule
  boundary: stdout is opened before stderr, and a typed stderr-open failure
  leaves stdout plus its partial file open. Tmp-only probe is
  `calls=5 typed-blocked=5 fd-delta=+5 partial-stdout=5`. This is P2, not a
  false-green, but it joins the bounded rework.
- DONE — Fresh internal audit denominator before rework: L45 runtime verdict
  `P0=0 P1=1 P2=1` with `42/42` surgical positives plus cleanup attack
  `in=3 expected-blocked=3 actual-blocked=0 false-green=3`; L46 authority
  verdict `P0=0 P1=0 P2=2`, total `in=130 out=130 distinct=130 gaps=0` and
  matrix `71/71`. Both lanes made zero repository writes and kept the thirteen
  implementation files byte-identical.
- FIX — L47 cleanup design is sealed before writes. Because this host exposes no
  portable compare-and-rmdir/fd-unlink primitive for directories, cleanup will
  rename fd-relative to a random quarantine name, verify the quarantine
  `(dev,ino)`, remove only that name, rescan the retained parent with a bounded
  sticky churn/ambiguity flag, and preserve any canonical replacement. Green
  requires canonical identity initially exact, zero churn, owned inode absent
  and canonical name absent; persistent same-UID churn may leave residue but
  must return false and block all public finalizers. Runtime call-site census is
  `in=14 out=14 distinct=14 gaps=0` (qualifier 13, bridge 1).
- STOP — First L47 write is deliberately barred until the active Qwen and Kimi
  read-only audits finish. Both consume the shared working tree; changing bytes
  under their commands would invalidate their snapshot evidence. The design and
  census are complete, so implementation resumes immediately after both
  cross-team reports without reopening architecture.
- RISK — Kimi K3 found a fifth, matrix-missing strict-type divergence:
  canonically rehashed `ratification.independent=1` is accepted by both the
  qualifier and bridge v2 loaders because Python treats `1 == True`, while the
  schema requires boolean `true` and the v1 loader already uses `is True`.
  Controls string `"true"` and integer `0` block; no semantic downgrade was
  demonstrated, so current rank is P2. Both loaders and the consistent-rehash
  regressions join L47; the historical 71 matrix only mutates this field to
  `false` and must not be credited for the integer case.
- RISK — Kimi's independently validated sub-auditor found a sixth bounded P2:
  the pure production worker binds role-to-family and counts but not
  role-to-expected-status, so a standalone `mutated` row with expected `ok`
  plus a self-consistent ok envelope returns `status=completed`. The unchanged
  full chain remains fail-closed because the pinned qualifier derives its own
  role contract and rejects those exact bytes. L47 must add a worker-local exact
  expected-status contract and regression; this is hardening, not a chain-level
  false-green.
- DONE — Kimi K3 L47 final verdict is `REWORK`, `P0=0 P1=0 P2=2`. It
  independently replayed L44 hardenings `7/7`, executable matrix `71/71` plus
  census `1/1`, all four content pins, authorities None `5/5`, and re-ran its
  sub-auditor's `8/8` probe before accepting it. Slice units
  `in=5 out=5 distinct=5 gaps=0`; master plus validated sub-auditor attacks
  `in=12 out=12 distinct=12 gaps=0`; no project write or Metis/runner action.
- DONE — Qwen `qwen3.8-max` L47 final verdict is `REWORK`,
  `P0=0 P1=2 P2=3`. Tmp-only syscall-boundary injection independently
  reproduced cleanup helper false greens `2/2`, all three public v1/v2/bridge
  false-green paths `3/3`, the adjacent recursive child-clear race `1/1`, and
  honest controls `3/3`; full probe accounting is
  `in=9 out=9 distinct=9 gaps=0`. The adjacent race can delete a non-owned
  subtree while returning green and preserving the displaced owned child.
  Call-site census is `in=14 out=14 distinct=14 gaps=0`; no repository write.
  Evidence: `ai-multi-team-orchestra/runs/model1-l47-qwen-kimi/artifacts/l47-cleanup-race-report.md`.
- FACT — Cross-team identifiers are durable: Qwen project session
  `e6404f28-55df-4f89-b694-3f6c4ab33853`, log
  `runs/logs/20260821-154934-qwen-qwen-cleanup-audit-v2.jsonl`; Kimi project
  session `session_9fe2a9d5-0711-46c0-918c-7cf1d1e69256`, log
  `runs/logs/20260821-154617-kimi-kimi-authority-audit.jsonl`. Both are under
  `/Users/tommasotessarolo/Developer/ai-multi-team-orchestra`.
- FIX — The L47 snapshot barrier is lifted only after both external reports.
  The frontier implementer now owns the eight bounded runtime/test paths and
  must close seven aggregated items before broad gates: cleanup root race,
  recursive child-clear race, Oracle stderr-open FD leak, argparse abbreviation,
  lexical path canonicality, exact boolean ratification, and worker-local
  role-to-expected-status binding. Qwen/Kimi boards, `.orchestra/teams.json`,
  all other source files and Metis remain off-limits.
- FACT — L47 tests-first baseline is red `14/14` before product changes.
  Exact classes: CLI abbreviations `2/2`, `independent=1` `2/2`, lexical paths
  `2/2`, public cleanup-root races `3/3`, recursive child swaps `2/2`, internal
  success cleanup `1/1`, worker status relabel `1/1`, and Oracle stderr-open FD
  leak `1/1` (first iteration already `fd-delta=+1`). No architecture STOP;
  only the four assigned test files changed at this checkpoint.
- FIX — L47 product patch moves the exact focused roster from RED `14/14` to
  GREEN `14/14`; compile is `8/8`. The first post-patch recursive-swap probe
  correctly returned false but still quarantined the root after child churn;
  root removal is now skipped whenever recursive clear is ambiguous. A single
  transient Node timeout reran isolated and in the full focused batch green.
  Bridge is `39/39`, worker `16/16`; full qualifier replay remains in progress.
  Formatted frozen qualifier candidate is
  `sha256:3c61238ca581f39ed2749fb09d73da9b2c6f9af810b8966b462676d3b3f6218b`
  and the bridge pin matches.
- DONE — L0 independently replayed the L47 attack roster plus the two adjacent
  Oracle lexical aliases: `16/16`, exit 0. The underlying mandated denominator
  remains `14/14`; the two extra parameter cases are reported separately and
  not used to inflate it. L0 independently recomputed qualifier bytes as
  `sha256:3c61238ca581f39ed2749fb09d73da9b2c6f9af810b8966b462676d3b3f6218b`
  and read the exact same compiled bridge pin.
- FACT — L0 safe-only integrated gate is nominally `316/316`, exit 0:
  qualifier `215`, bridge `39`, worker `16`, contracts `24`, explicitly
  enumerated capsule-only Oracle cases `22`. No whole `tests/test_oracles.py`,
  real runner or Metis execution occurred. This green is regression evidence
  only and does not promote because L48 subsequently broke the cleanup proof.
- STOP — L48 persistent quarantine churn defeats the new helper postconditions.
  Both helper implementations returned true `2/2` while the retained owned
  inode survived as a `*.churn-*` entry and an injected non-owned replacement
  was deleted. The same attack reached all public surfaces `3/3`: v1
  `qualified`, v2 `qualified`, bridge `replay-qualified`, each with owned
  residue. Existing focused cleanup tests remain green `7/7` but do not model
  quarantine-name churn. Current formatted pin is therefore REWORK, not a
  shippable trust root.
- RISK — L48 also broke the Oracle stderr-open error cleanup by swapping the
  newly created stdout name before failure. Path and dir-fd branches typed-block
  and close FDs `2/2`, but both delete the non-owned canonical replacement and
  leave the owned partial displaced. Honest controls remain `10/10` with zero
  leak. This joins the blocking cleanup architecture decision.
- DONE — L48 final verdict is `REWORK / STOP`, `P0=0 P1=2 classes P2=0`.
  Additional attacks are `in=12 out=12 distinct=12 gaps=0`: helpers `2/2`,
  public false greens `3/3`, stronger canonical-replacement public paths `3/3`,
  recursive quarantine-file deletion `2/2`, and Oracle replacement deletion
  `2/2`. The complete `_remove_owned_directory` call-site census is
  `in=14 out=14 distinct=14 gaps=0`; `5/14` are success-sensitive.
- FIX — L49 rejects another bounded-rescan repair and preserves the active
  same-UID threat model. Qualification/replay will never automatically unlink
  or rmdir a mutable owned name. It will close/reap resources, seal and measure
  owned roots, retain them as bounded artifacts, emit exact
  `cleanup_deferred` evidence and defer deletion to a separately ratified
  quiescent/exclusive GC wave. Brief:
  `orchestra/briefs/2026-08-21-model1-l49-retained-owned-roots.md`.
- STOP — L47 writes remain frozen while Qwen `qwen3.8-max` and Kimi K3 perform
  disjoint read-only architecture reviews of the L49 brief and current code.
  L0 alone will adjudicate their reports, finalize schema/replay normalization
  and reopen one frontier writer. The nominal `316/316` and qualifier pin
  `3c61238c...f6218b` remain non-promotable.
- RISK — The L49 Kimi lifecycle review did not complete: wrapper log
  `20260821-173142-kimi-kimi-lifecycle-trust.jsonl` stops after mapping the
  qualifier and beginning the bridge; stderr records provider `403` usage-limit
  exhaustion for the current billing cycle. Exit `0` is therefore not accepted
  as a review verdict. No Kimi quota percentage is inferred.
- FACT — The L49 Qwen `qwen3.8-max` review remains active in provider session
  `32ee2933-f08c-427b-9549-cf59c1bf9aa9`. It has independently established
  that retained v2 process/trusted content is deterministic and only the
  top-level locator/inode varies; its final schema/replay verdict is still
  pending. L0 has not reopened any writer.
- RISK — Qwen's deposited provisional architecture journal accepts the
  retain/seal/measure direction but ranks seven brief gaps P1 before writing:
  blocked-report evidence propagation, blocked bridge-holder measurement,
  bounded snapshot caps, strict types, duplicate rejection, exact per-surface
  kind rosters, and an explicit Oracle cleanup channel decision. It also
  requires two physical run bindings plus a bridge-recomputed normalized
  projection with a closed five-field exclusion set. Census validation and the
  final Qwen verdict remain pending; no product writer has reopened.
- DONE — Qwen L49 data/schema/replay review closed with `REWORK`,
  `P0=0 P1=9 P2=10`; architecture direction accepted. Three delegated census
  units closed `in=3 out=3 distinct=3 gaps=0`, and the Oracle classification
  closed `in=40 out=40 live=22 capsule_only=18 distinct=40 gaps=0`, yielding
  an exact current-tree safe roster of `27` expanded node IDs. Full report:
  `/Users/tommasotessarolo/Developer/ai-multi-team-orchestra/runs/model1-l49-retained-roots/artifacts/qwen-l49-architecture-review-report.md`.
- FACT — L0 independently rechecked the missing-roster claim and current test
  function census. The historical capsule-only count `22` is stale and has no
  durable enumeration; L49 will persist the Qwen-derived `27`-case current-tree
  roster before running any integrated gate.
- FIX — L0 ratified the complete L49 contract amendment. It adds exact sealed
  and unmeasurable descriptor unions, exception-carried blocked evidence,
  per-kind measurement caps, hardlink/non-regular rejection, two physical run
  bindings plus one bridge-recomputed substitution projection, blocked holder
  evidence, Oracle-envelope stability, and the corrected in-scope automatic
  deletion roster `in=29 out=29 distinct=29 gaps=0` with six live non-capsule
  sites explicitly excluded.
- DONE — The current-tree safe Oracle roster is now durable at
  `orchestra/briefs/2026-08-21-model1-l49-capsule-only-oracle-nodeids.txt`:
  `in=27 out=27 distinct=27 gaps=0`; every base test function exists and
  `git diff --check` is green. Historical count `22` is superseded.
- FACT — L49 sole frontier writer resumed tests-first on the exact ten ratified
  runtime/schema/contract/test files. Worker, production-authority schema,
  manifests, boards/briefs/team registry, W3 authorities, artifacts, Git and
  Metis remain off limits. No second writer or external-team run is active.
- FACT — L49 tests-first baseline is honestly RED before product/schema edits.
  Exact command
  `tests/test_contracts.py::test_w3_report_schemas_require_deferred_cleanup_on_all_six_variants`
  fails `1/1` because not all six qualifier/replay variants require `cleanup`.
  Writable roster is confirmed `10/10`; no architecture STOP was found.
- FIX — L49 writer pulse: only `runtime/w3_qualifier.py` has received product
  edits so far. The quarantine/delete engine is replaced by retained directory
  descriptors, exact `0444/0555` sealing, two descriptor-rooted snapshots,
  bounded measurement and canonical `root_id`; callsite/report integration and
  both schemas remain in progress. The contract gate intentionally remains RED
  and no L49 GREEN is claimed yet; no architecture STOP is open.
- FACT — First L49 executable slice is independently replayed by L0:
  `.venv/bin/python -m py_compile runtime/w3_qualifier.py` exits zero and the
  exact qualifier census `rg 'os\.(unlink|rmdir)|_remove_owned_directory'`
  returns zero matches. The bridge helper slice is still being integrated and
  the six-variant schema contract intentionally remains RED; this is not a wave
  acceptance verdict.
- FACT — L0 also independently replayed the bridge helper/callsite slice:
  `.venv/bin/python -m py_compile runtime/w3_bridge_gate.py` exits zero and the
  identical deletion census returns zero matches. Replay-v2/normalized
  projection code is compile-clean; schema, fixtures and runtime semantics are
  not yet accepted and remain the next gate.
- DONE — The first L49 contract moved honestly RED to GREEN. L0 independently
  parsed both report schemas `2/2` and reran
  `test_w3_report_schemas_require_deferred_cleanup_on_all_six_variants`: `1/1`
  passes, so `cleanup` is required across all six qualifier/replay variants.
  Manual validators, runtime fixtures and Oracle retention remain open.
- DONE — L0 independently replayed the two exact capsule-Oracle retention test
  functions: `4/4` pytest cases pass. Honest stderr-open controls close all FDs
  while retaining owned stdout partials (`10/10` calls, FD delta zero); both
  path/dir-fd replacement attacks preserve the canonical replacement bytes and
  the displaced owned partial (`2/2`). Capsule-scope deletion expressions are
  gone; the remaining two `.unlink()` calls are in the explicitly excluded
  live-checkout snapshot/output paths.
- FACT — First qualifier broad runtime reached `214/215`; its sole RED was the
  historical matrix case `F-replay-v1-replay-nonce-scope`, where the bridge
  fixture still lacked its required `cleanup`. After fixture integration, L0
  reran that exact node ID and observed GREEN `1/1`. The full suite and frozen
  historical `71/71` denominator still require fresh reruns.
- DONE — The frozen historical executable matrix is independently replayed by
  L0 after L49 integration: `71/71` passes, with its original
  `A11/B12/C12/D12/E16/F8` denominator kept separate from all new retention
  mutations. The bridge now also reserializes canonical child report bytes and
  independently revalidates each physical qualification after `_run_once`;
  focused replay tests remain pending.
- FACT — Writer's current qualifier broad gate is GREEN `215/215` and L0
  independently confirms the collect denominator `215`; it includes the
  separately replayed historical `71/71`. Bridge broad is `35/36`; the only
  deliberate RED is `test_bridge_pin_matches_final_qualifier_bytes`, held stale
  until final format/byte-freeze. No premature repin is accepted.
- RISK — Lower-cost read-only mutation census confirms the current broad greens
  do not yet close L49. Principal executable gaps are stale-report manual
  rejection; snapshot-first/content-rewrite isolation; device and holder caps;
  split/merged and copied physical descriptors; all five allowed projection
  substitutions plus forbidden kind/normalized-roster/semantic/runtime
  substitutions; child-blocked and killed-child/no-report propagation;
  publication-partial retention; and full six-variant schema/manual/bridge key
  agreement. Semantic mutation tests must recompute dependent `root_id` and
  report hashes so a generic stale-hash rejection cannot masquerade as coverage.
- DONE — L0 independently replayed the first new L49 behavioral slices outside
  the historical matrix: qualifier retention/duplicate/publication cases
  `29/29` and bridge projection/copied-descriptor/child-cleanup/blocked/holder
  cases `28/28`. The initial AF_UNIX path-length RED was test-only and is fixed
  with a relative bind. Stale-report, split/merged and full validator agreement
  remain explicitly open.
- DONE — The three remaining mutation classes are independently replayed by L0
  GREEN `6/6`: a consistently rehashed stale report without cleanup; split and
  merged retained rosters; schema/manual/bridge key agreement across all six
  variants; and child locator/physical-roster remeasurement. The bridge now
  opens and remeasures child roots by FD instead of trusting descriptor claims.
  No L49 mutation gap remains from the mechanical census; final broad,
  format/repin and independent frontier audit are still required.
- FACT — Pre-format broad gates are GREEN: qualifier `245/245`, bridge
  `70/70` with only the deliberately stale final-pin test deselected, and
  contract agreement `2/2`. L0 independently confirms collect denominators
  qualifier `245`, bridge `71`, contracts `25`, plus clean `git diff --check`.
  These are not frozen-byte evidence; format, qualifier hash, bridge repin and
  full replay remain mandatory.
- FIX — The durable capsule-only Oracle roster is reclassified after L49 test
  edits: stale `...removes_partial_files` is replaced by
  `...retains_partial_files` and the new replacement-race function is added.
  Current truth is `19` tmp/pure functions, `28/28` distinct quoted selectors,
  collecting `30` pytest items; the tracked roster and active L49 brief now
  carry those exact values. Earlier `18/27` evidence is superseded.
- FACT — On the current formatted bytes, L0 recomputes qualifier SHA-256
  `70d3fbb7bdd400032d580b72be51982cf1ad4f0279c99491e7cd05e20114e6d8`,
  confirms it equals the bridge pin, and reruns the exact pin test GREEN `1/1`.
  L0 also executes the durable quoted Oracle roster GREEN `30/30`. This becomes
  final evidence only if the writer freezes the qualifier without further edits.
- STOP — The `70d3fbb7...14e6d8` pin and L0 integrated run are retracted: before
  freeze the writer reproduced a receipt-continuity P1 where an intent recorded
  before mkdir/open but lacking a duplicated FD could disappear as
  `cleanup=[]`. L0 interrupted its own now-invalid integrated pytest session;
  no residual from that session remains. The bounded fix is focused GREEN
  `4/4`: collision-without-owned-root is removed from the registry, while
  descriptor-capture failures become `unmeasurable`. A new format/hash/repin
  and complete frozen-byte replay are mandatory.
- STOP — L0 process census found one real orphan fake-capsule Node from the
  writer's `pytest-413` historical-matrix execution: exact PID/PGID `82896`,
  PPID `1`, still alive after pytest ended. L0 terminated only that exact group
  and confirmed the PID absent. Any prior zero-residual claim is invalid;
  supervision root cause plus fresh matrix/process census are mandatory before
  L49 acceptance.
- FIX — Root cause is confirmed in `_execute_capsule_node_streams_v2`: a
  `KeyboardInterrupt`/other `BaseException` bypassed its narrow exception arms,
  and the old `finally` closed FDs without unconditionally reaping the Node
  group. The supervisor now performs idempotent group reap from `finally`.
  L0 independently executes the new injected-KeyboardInterrupt regression
  GREEN `1/1` and confirms the exact post-test fake-node/qualifier/bridge process
  census is empty. Full matrix and broad frozen-byte replay remain required.
- DONE — L0 independently replays the final safe-only gate on frozen qualifier
  bytes: collect/run `390/390` = qualifier `247`, bridge `72`, unchanged worker
  `16`, contracts `25`, and the durable Oracle selectors `30`; no whole Oracle,
  real runner, Metis, network or training. Raw qualifier SHA-256 equals bridge
  pin `ecd4b56d95adc96f6ef4f221bb3bd0622bb1e54a30e021df0dfb6acbe16ddbbb`.
  Immediate post-gate process census is empty. L0 then reruns the historical
  executable matrix separately GREEN `71/71`, with another empty census.
  Independent frontier audit remains pending, so L49 is not yet accepted.
- DONE — L0 static replay on the same frozen bytes is GREEN: product compile
  `4/4`; Draft 2020-12 schema meta-validation `3/3`; Ruff check PASS and format
  `8/8`; five production source authorities are exact AST `None` `5/5`; and
  `git diff --check` is clean. These facts do not promote or register any W3
  production authority.
- DONE — L0 independently reconstructs the new L49 attack denominator from
  executable, disjoint selections: qualifier `30`, bridge retention `29`, final
  stale/split-merge/key-agreement/remeasure `6`, Oracle partial retention `4`,
  and interrupt/schema `2`; `in=71 out=71 distinct=71 gaps=0`. All five slices
  execute GREEN `30/30 + 29/29 + 6/6 + 4/4 + 2/2`, followed by an empty exact
  process census. This denominator remains separate from the historical matrix.
- STOP — Independent L50 frontier audit reproduced the same BaseException
  orphan class one layer higher in `runtime/w3_bridge_gate.py`:
  `_execute_qualifier_preimage` closes controls/streams in `finally` but does
  not unconditionally kill/reap a still-live qualifier. An injected
  `KeyboardInterrupt` left exact `/bin/sleep 30` PID/PGID `95985` alive; the
  auditor terminated only that exact group and confirmed it absent. Frozen L49
  is `REWORK`; all green gates remain regression evidence only. A bounded L51
  bridge-supervision writer is resumed tests-first; commit/push/training remain
  closed.
- STOP — L50 widened the same P1 to qualifier worker supervision: an injected
  `KeyboardInterrupt` in `_run_worker` left exact child PID/PGID `96582` alive
  until the auditor killed that group; `_run_worker_v2` has the same static
  finally-only-FD gap. L51 now covers every supervised `Popen` site with a
  gap-free callsite census and BaseException PID/PGID regressions, not merely
  bridge and Node.
- STOP — L50 also falsified full schema/manual agreement with a consistently
  rehashed production-v2 report: `production-process-root.counts.files=513`
  plus recomputed `root_id` and top-level manifest yields zero Draft 2020-12
  schema errors but manual validation blocks the cap. The shared schema used
  trusted-root maxima and did not bind qualified state/kind/logical/anchor/order.
  L51 expands tests-first to exact per-kind descriptor caps and exact qualified
  root rosters in both qualification and replay schemas; key-set-only agreement
  is no longer accepted.
- STOP — L0's full supervised-process census adds the capsule Oracle boundary:
  `src/metis_model1/oracles.py::_run_capsule_command` also closed only stream FDs
  in `finally` and could orphan its group on `BaseException`. The bounded L51
  denominator is now exact `5/5` Popen sites: qualifier worker v1, worker v2 and
  Node; bridge qualifier; Oracle capsule. Each requires an injected-interrupt
  PID/PGID absence proof; no partial four-site fix can close the wave.
- FACT — L50 dynamically confirms the Oracle capsule gap: injected
  `KeyboardInterrupt` leaves exact PID/PGID `98994` alive until the auditor
  kills only that group and confirms absence. Frozen lifecycle truth is P1 at
  `4/5` supervised sites; three are dynamically reproduced (worker v1, bridge,
  Oracle), worker v2 is the identical static branch, and only Node had the
  unconditional reap fix.
- DONE — L50 final independent verdict on frozen `ecd4...ddbbb` is `REWORK`,
  `P0=0 P1=3 P2=1`. In addition to Popen reap and schema/manual caps, the
  qualifier's `normalized_roster_sha256` hid deeper `stdout.json` byte changes
  via override, while the bridge accepted a synthetic caller-supplied holder
  digest rather than hashing retained rows. A separate continuity probe showed
  true pre-creation failures reported as `creation_observed=true` despite zero
  children. L51 is ratified to normalize owned stdout physically before seal,
  derive both qualifier/holder normalized rosters only from retained bytes, and
  distinguish pre-creation from post-mkdir capture failures. Positive L50 facts:
  Oracle roster `30/30`, automatic deletion qualifier/bridge/capsule `0`, hash
  pins exact, final audit process census empty.
- FACT — L51 tests-first begins with only three test files touched and zero
  product/schema edits. Exact first RED
  `test_fixture_worker_keyboard_interrupt_unconditionally_reaps_process_group`
  is `0/1`: injected `KeyboardInterrupt` leaves spawned `/bin/sleep 30` with
  `poll() is None`; the test itself kills/reaps only that exact group. Additional
  RED selectors cover worker v2, bridge qualifier plus registered child, Oracle
  path/dir-fd variants, and schema process-root boundary `512/513`. No
  architecture STOP is open.
- DONE — L0 independently replays the L51 lifecycle slice GREEN `6/6`: worker
  v1, worker v2, capsule Node, bridge qualifier plus registered child, and
  Oracle capsule path/dir-fd. All `5/5` supervised `Popen` sites now perform
  unconditional BaseException group kill/reap; bridge orders child groups
  before qualifier and rechecks late registrations, and cleanup failure is not
  suppressed. Exact post-run process census is empty. Schema over-cap,
  normalized-roster truth and registry continuity remain open.
- FACT — L51 contract rework is active on the remaining three classes. Current
  static diff derives qualifier and replay-holder normalized roster hashes from
  the retained snapshot bytes and introduces an explicit post-`mkdir` creation
  callback. L0 found one incomplete publication caller that registered an
  intent but did not invoke the callback before descriptor observation; the
  writer has been directed to add the exact pre-create/post-mkdir publication
  regressions before any broad run, format, hash or repin. No accuracy,
  benchmark or training gate is credited by this in-progress state.
- DONE — L0 independently replays the normalized-roster and registry-continuity
  slice GREEN `9/9`. Qualifier stdout is physically canonicalized through the
  retained inode before sealing; path replacement blocks while preserving the
  replacement; physical and normalized roster hashes are equal and byte
  sensitive. Qualifier random roots/publication and bridge holder roots now
  distinguish pre-creation failures (`retained_roots=[]`) from post-`mkdir`
  descriptor failures (`creation_observed=true`, unmeasurable). Bridge holder
  hashes are snapshot-derived, not caller-supplied. Exact schema cap/variant
  agreement remains the only open L51 product class before broad freeze.
- DONE — L0 independently replays exact schema/manual agreement GREEN `19/19`.
  Qualification variants bind worker `512/512/128 MiB`, production process
  `512/512/128 MiB`, trusted `4096/4096/1 GiB` and publication partial
  `128/128/32 MiB`; replay additionally binds holder
  `16384/16384/3 GiB`. Qualified v1/v2/replay reports require exact retained
  root kind, logical root, anchor and order via tuple schemas, and the contract
  validator checks refs, `prefixItems`, `items=false` and numeric caps. The
  original consistently rehashed process-root boundary is accepted at `512`
  and rejected by both schema and manual validator at `513`. Adjacent blocked
  observed-run conditions are still being checked before freeze.
- FACT — L51 pre-audit frozen checkpoint is GREEN on all admissible non-live
  suites: qualifier `263/263`, bridge `84/84`, contracts `25/25`, durable L49
  Oracle roster `30/30` plus the new Oracle KeyboardInterrupt path/dir-fd cases
  `2/2`, and the historical executable mutation matrix separately `71/71`.
  Exact post-qualifier and post-matrix process censuses contain zero retained
  fake-Node/W3/sleep process. These are writer evidence pending L0 static
  recomputation, exact pin capture and independent frontier re-audit; they are
  not a promotion, benchmark, training or accuracy result.
- DONE — L51 writer freezes final qualifier bytes at
  `sha256:d7511960152e0607e415725230424060b126ab63b9834e2716a7b8b1b3ece2fe`;
  the bridge pin matches exactly. L0 updates the durable Oracle roster for the
  new parametrized KeyboardInterrupt lifecycle proof: current classification
  is `42/42` functions (`22` live forbidden, `20` tmp/pure), `29/29` distinct
  quoted selectors collecting `32` pytest items. Historical `28` selector /
  `30` item facts are superseded for future gates. Independent frontier audit
  remains mandatory before ACCEPT.
- DONE — L0 independently collects and executes the final `d751...e2fe`
  admissible safe-only gate GREEN `420/420`: qualifier `263`, bridge `84`, pure
  worker `16`, contracts `25`, and exactly the durable Oracle selection `32`.
  The historical executable mutation matrix is rerun separately GREEN `71/71`
  (`A11+B12+C12+D12+E16+F8`, not merged into `420`). Exact post-gate and
  post-matrix process censuses are empty. Static L0 gates are also green:
  py_compile `8/8`, Draft 2020-12 schema meta-validation `3/3`, Ruff check,
  Ruff format `8/8`, `git diff --check`, five production source authorities
  `None`, and actual qualifier hash equal to bridge pin. L52 adversarial audit
  remains the sole infrastructure acceptance blocker.
- STOP — L52 adversarial audit finds a new blocked-report contract P1 despite
  the green gates. Consistently rehashed blocked v1 with publication-only,
  blocked v2 with trusted-only, and top-level blocked replay with process-only
  are schema-valid while their exact manual validators reject them; a blocked
  observed child with trusted-only cleanup is accepted by both the replay
  schema and bridge parser. The generic cleanup refs must be replaced with
  exact prefix rosters for each blocked surface, and the child parser must
  enforce the production-v2 prefix progression. L53 is opened tests-first on
  these four divergences; `d751...e2fe` and `420/420` remain regression evidence
  only, not ACCEPT.
- STOP — L52 also proves child retained-root remeasurement used the replay
  holder's `256 MiB` per-file ceiling instead of the child class ceiling. A
  sealed production-process root containing one `8,388,609`-byte file, with
  coherently recomputed counts and digests, passed both bridge cleanup
  validation and fd-root remeasurement even though the qualifier cap is
  `8,388,608`. L53 now parameterizes remeasurement by the exact process/trusted
  caps and adds `8 MiB` boundary versus `+1` probes. This is a second P1 on
  frozen `d751`, not a training or model-quality failure.
- STOP — An adjacent L52 conditional-schema probe shows a single blocked replay
  observation with `run_index=2` and null no-report evidence is schema-valid
  while the manual bridge validator correctly requires 1-based positional
  order. L53 therefore also replaces the generic observed-run array with a
  bounded two-position tuple (`1`, then `2`, `items=false`) and adds empty,
  one-row, two-row, skipped-index and reversed-order agreement cases.
- STOP — L52 forces the bridge's first finalizer child-group snapshot empty and
  the second snapshot populated after child ACK/exec plus `KeyboardInterrupt`.
  The qualifier group is gone but the late child group can still be present on
  return; cleanup may also leak raw `PermissionError` from `killpg`. The current
  one-shot kill/absence assertion does not grace-poll or reap late groups. L53
  now closes the control channel, terminates/reaps qualifier, joins the receiver
  to completion, takes the authoritative final roster, repeatedly kills/polls
  every registered group to bounded absence, and emits only typed cleanup
  failure. A deterministic first-snapshot-miss regression is required.
- STOP — L52 also forges a schema-valid blocked child cleanup descriptor that
  claims an empty sealed process root while the fd-root directory actually
  contains an 11-byte `rogue` file. The nonzero child path only performed
  generic cleanup validation and accepted the forged descriptor into
  `error.child_cleanup`; fd-root remeasurement ran only on success. L53 must
  remeasure every sealed blocked child root against the correct run/artifact
  anchor and per-kind caps before recording it; publication partial roots are
  included, while unmeasurable rows remain exact-prefix evidence backed only by
  the coarse holder receipt. Forged cleanup must not enter `observed_runs`.
- DONE — L52 final independent verdict on frozen `d751...e2fe` is `REWORK`,
  `P0=0 P1=4 P2=1`. The four P1 classes are: blocked schema/manual prefix and
  observed-order divergence (`5/5` attacks); absent physical remeasurement of
  sealed blocked child roots; child qualified remeasurement using a `256 MiB`
  holder per-file cap instead of the `8 MiB` child cap; and a timing-dependent
  late-child finalizer that can return with a group present or leak raw
  `PermissionError`. Existing positive evidence remains exact: ordinary Popen
  `6/6`, registry `6/6`, normalization `3/3`, projection substitutions `12/12`,
  qualified schema/manual `20/20`, replay cases `6/6`, durable Oracle `32/32`,
  and zero scoped automatic deletions/process residue. L53 owns only these
  bounded repairs; no earlier green is promoted across them.
- FACT — L53 completes tests-first RED coverage before product edits. Exact
  outcomes: blocked-prefix schema `0/1`; per-file boundary `1/2` with process
  `8 MiB+1` not raising; observed-order `3/4` with singleton index `2` schema
  accepted; forbidden blocked child prefix `0/1` accepted and attached;
  forged sealed child remeasurement `0/1` accepted; late-first-snapshot
  lifecycle `0/1` leaked raw `PermissionError` and left PGID `27356`. The test
  terminated only that exact group and post-census is empty. Product work then
  began on the exact L53 roster; no architecture STOP or training action.
- FIX — L53 closes the first P1 class: blocked v1, blocked v2, blocked child and
  blocked replay holder now use exact sealed-or-unmeasurable prefix tuple
  schemas and matching manual validators; `_run_once` is wired to the exact
  child-prefix validator. Product pycompile `3/3`, schema meta-validation `2/2`
  and the four former blocked-prefix attacks `4/4` are GREEN. Per-file cap,
  observed order, blocked physical remeasurement and late-child lifecycle remain
  in the same bounded rework.
- DONE — L0 independently replays the complete L53 focused roster GREEN
  `25/25`, distinct with no gaps: blocked attacks `4`, process/trusted per-file
  boundaries `4`, sealed/unmeasurable prefixes plus observed order and contract
  checks `12`, forbidden-prefix and forged process/publication child
  remeasurement `3`, and normal/late-first child lifecycle `2`. The bridge now
  chooses fd-root anchors and file caps by child kind; it closes the control
  channel, joins registration, uses the final roster and boundedly kills/polls
  groups to absence with typed `OSError`. Exact post-test process census is
  empty. Adjacent diff/callsite review, format, repin, broad and frontier re-audit
  remain before acceptance.
- FACT — L53 formats and repins a new provisional freeze at
  `sha256:4bb0dedc805ad7e000bf0ce84fadf50a490cc325781f633adbefc61c732c43b6`,
  with qualifier `269/269`, bridge `101/101` and contracts `25/25` GREEN. L0
  rejects a stale handoff count of `30` Oracle items: the durable roster is
  `29` selectors collecting `32` items, and pure worker `16` must also be
  included. Matrix, corrected Oracle roster, worker, static gates and process
  census are pending before this hash is accepted as a final writer freeze.
- DONE — L53 writer freeze is complete on
  `sha256:4bb0dedc805ad7e000bf0ce84fadf50a490cc325781f633adbefc61c732c43b6`;
  L0 independently recomputes the same raw qualifier hash and exact bridge pin.
  Writer evidence is safe-only `443/443` (`269` qualifier, `101` bridge, `16`
  worker, `25` contracts, durable Oracle `32`), historical executable matrix
  `71/71`, focused L53 `25/25`, schemas `3/3`, authorities unset `5/5`, and
  zero scoped residual processes. This closes only the bounded writer lane;
  it does not ratify infrastructure or authorize a model-accuracy claim.
- FACT — L54 starts two independent read-only checks on the frozen `4bb0`
  bytes: a frontier adversarial replay of every L52 attack plus adjacent
  schema/runtime/lifecycle seams, and a lower-cost mechanical replay of the
  exact `443` safe-only denominator, `71` executable mutations, hashes, static
  gates and process census. No real Metis, runner, network, training, commit or
  push is authorized while either check is open.
- DONE — The L54 lower-cost mechanical lane and L0 independently replay the
  frozen `4bb0` safe-only gate GREEN `443/443`; the mechanical lane also
  replays the historical executable matrix `71/71`, schemas `3/3`, compile
  `8/8`, authorities unset `5/5`, exact hash/pin and zero process residue.
  This is mechanical evidence only and cannot override the frontier verdict.
- RISK — L54 frontier audit closes every prior L52 attack so far (`5/5`
  blocked-prefix/order, blocked child descriptor, per-file cap `4/4`, and
  late-first lifecycle `2/2`) but reproduces a new P1 descriptor leak in
  `_open_blocked_child_retained_root`: `KeyboardInterrupt` during target open
  bypasses an `except Exception` cleanup and leaves `/dev/fd` delta `+1`.
  Audit continues read-only for adjacent BaseException ownership seams; `4bb0`
  is REWORK unless the final census disproves or a bounded later wave fixes it.
- DONE — A separate low-cost dynamic census executes all six acquisition seams
  guarded by `except Exception`: `in=6 out=6 distinct=6 gaps=0`. Five leak on
  `KeyboardInterrupt` and together expose seven transient descriptors: bridge
  secure root `+2`, bridge random registry root `+1`, bridge blocked publication
  namespace `+1`, qualifier secure root `+2`, qualifier random registry root
  `+1`. Qualifier preimage materialization is the sole safe control because its
  `finally` closes both handles. Probe cleanup closes every exact leaked FD and
  leaves no residual. L54 therefore has a bounded five-regression rework class;
  the frontier audit still owns the final adjacent-finding census.
- STOP — L54 final frontier verdict on frozen `4bb0` is `REWORK`, `P0=0`,
  `P1=1` systematic lifecycle class and `P2=1` missing regression class.
  Dynamic interruption of ten distinct acquisition/ownership transitions leaks
  thirteen descriptors total: five bridge sites (secure root `+2`, random root
  `+1`, registry dup `+1`, blocked publication `+1`, sequential run roots `+1`)
  and five qualifier sites (secure root `+2`, random root `+1`, registry dup
  `+1`, publication roots `+1`, sequential v2 roots `+2`). The materialized
  preimage control remains `fd_delta=0`. All exact probe FDs were closed and
  final process census is empty. Prior L52 attacks are independently CLOSED:
  blocked/order `5/5`, forged blocked remeasurement, per-file cap `4/4`, and
  normal/late lifecycle `4/4`. L55 owns only two runtime files and two focused
  test files for BaseException-safe acquisition/transfer plus a ten-site FD
  census; no wider architecture, training or promotion action is authorized.
- FACT — L55 starts tests-first with only the two authorized test files touched.
  The exact parameterized acquisition suite is RED before product changes:
  first bridge `secure-root` case fails `0/1` with leaked FD set `{12,13}`
  (`+2`), matching the L54 independent finding; test cleanup closes the exact
  captures. The suite also stages all remaining bridge/qualifier transitions,
  the ordinary second-open failure and the materialized-preimage `delta=0`
  control. No architecture blocker is present.
- FIX — L55 applies the bounded two-runtime repair and compiles both files.
  Exact parameterized FD ownership gate is now GREEN `12/12`: six bridge
  attacks, five qualifier attacks and the safe materialized-preimage control,
  including the ordinary bridge second-open `BridgeGateBlocked` path. Registry
  duplicate ownership is explicit and recoverable: the local duplicate is
  closed on every `BaseException`, entry state is reset with base-dict writes,
  and `OSError` remains typed. Full safe suites, format, repin, static gates and
  independent audit remain open; no promotion is implied.
- DONE — L55 freezes final runtime bytes with qualifier/pin
  `sha256:f6eb7a83a42a276b35d0739692f30c8653c11d243100fe5ca6b3e72661e756a3`
  and bridge `sha256:b33abee3fb76d2dc5231b803c4cb03bedfa95080f4912bfd658ff4af4ff4b08a`.
  Writer evidence: qualifier `275/275`, bridge `107/107`, historical matrix
  `71/71`, focused acquisition/control `12/12`, compile/Ruff/format `4/4`,
  diff-check GREEN and zero supervised process residue. Writes are frozen; L56
  independently replays every one of the ten prior unsafe sites, registry state
  semantics, adjacent ownership and prior L52/L53 semantic attacks before any
  infrastructure acceptance.
- DONE — L0 independently replays the frozen `f6eb` safe-only suite GREEN
  `455/455` (`275` qualifier, `107` bridge, `16` worker, `25` contracts,
  durable Oracle `32`) and historical executable matrix `71/71`; hash/pin and
  bridge hash match, diff-check is GREEN and process census is empty. L56 also
  closes all prior L54 acquisition attacks: eleven invocations across ten sites
  have `fd_delta=0`, registry rollback yields created-but-unobserved
  `unmeasurable` receipts, and the materialize control remains `delta=0`.
- RISK — L56 adjacent review nevertheless reproduces the same P1 lifecycle
  class below those callsites: `_write_regular_relative` and
  `_open_relative_parent_descriptor` each leak the newly opened child FD (`+1`)
  when injected `KeyboardInterrupt` occurs in `os.fstat(child)` before ownership
  transfer. Both exact probe FDs were closed and frozen hashes remain unchanged.
  L56 now performs an exhaustive AST/control-flow census of every descriptor
  acquisition and dynamically probes all candidates before any further writer
  wave; isolated two-line repair is explicitly insufficient.
- FACT — The independent mechanical census closes its complete static roster:
  primitive acquisitions `in=49 out=49 distinct=49 gaps=0` (`36` qualifier,
  `13` bridge), with `36` protected/owned and `13` structural pre-finally
  windows; helper-return callsites `in=43 out=43 distinct=43 gaps=0`, with `25`
  sequential ownership windows. Besides the two confirmed `fstat` leaks, the
  highest-priority dynamic candidates are bridge socketpair/two temporary-file
  acquisition, qualifier process/output root sequences, descriptor traversal
  handoffs and representative `open`-before-`try` boundaries. Frontier L56 is
  dynamically adjudicating this full candidate class; no writer resumes from a
  partial two-site list.
- FACT — L56 frontier census has statically accounted `119/119` acquisition or
  helper callsites (`67` qualifier, `24` bridge, `28` Oracle). Dynamic coverage
  is `25/38` on the narrower structural window roster (all `13` primitive
  windows plus `12/25` sequential helper windows); `13` helper probes remain.
  Independent ownership-transfer line tracing adds eight unsafe anchored-handle
  handoffs outside that mechanical `38`, and Oracle has three confirmed direct
  sites. Current unsafe window count is `36`, still being consolidated by
  distinct function and threat type (downstream-call interruption versus
  asynchronous line-boundary transfer). No writer resumes until dynamic
  structural coverage is complete and the Oracle `28` are adjudicated.
- STOP — L56 final verdict on frozen `f6eb` is `REWORK`, `P0=0 P1=1 P2=1`.
  The exhaustive descriptor census is `in=119 out=119 distinct=119 gaps=0`
  (`67` qualifier, `24` bridge, `28` Oracle): `54` unsafe acquisition/transfer
  windows across `35` functions and `65` covered callsites. Unsafe split is
  qualifier `32/21 functions`, bridge `13/8`, Oracle `9/6`. Findings include
  real downstream-call failures and retained-traceback asynchronous line-event
  ownership gaps; GC/destructor closure is not accepted as explicit ownership.
  All probe FDs were closed, final hashes remained exact and process census is
  empty. Positive evidence remains: prior L54 `11/11 delta=0`, exact registry
  rollback, controls `delta=0`, and L53 semantic `25/25`. L57 is restricted to
  qualifier, bridge, Oracle and their three focused test files; it must replace
  weak `/dev/fd` snapshots with robust `fstat` census and execute the complete
  54-window roster before a new freeze. No schema, board-owned runtime design,
  training, Git or Metis action is authorized.
- FACT — L57 touches only the three authorized test files before product work.
  Robust FD census now records `fstat` identity (`dev`, `ino`, mode and rdev),
  retains the injected traceback and discards the transient scan FD. Executable
  denominators are fixed at qualifier `32/21 functions`, bridge `13/8`, Oracle
  `9/6`, total `54` windows across `35` functions. First exact RED is
  `_snapshot_qualification_descriptor` ownership transfer `0/1`, leaving exact
  FD `13` (`+1`) while the traceback is retained; test cleanup closes it.
  Product bytes remain untouched and no architecture blocker exists.
- FACT — L57 completes and executes the writer-owned tests-first denominator:
  qualifier `32/32` RED across `21` functions and bridge `13/13` RED across `8`
  functions, each with retained traceback and exact FD residue. A source-needle
  ambiguity in the bridge test harness was corrected before counting; its 13
  comprise three real setup failures and ten line-transfer cases. Thus
  `45/54` windows and `29/35` functions are executable RED; the disjoint Oracle
  test lane owns the remaining `9/6`. Product repair began only after all 45
  writer-owned cases were RED, starting with qualifier primitive/mid-level
  ownership. No combined GREEN or freeze is claimed yet.
- DONE — The disjoint Oracle tests-only lane adds exactly `9` parameterized
  windows across `6` functions and executes them RED `9/9`; first failure is
  capsule-directory dup with exact extra FD `{12}`. It also replaces three
  adjacent weak FD counters with robust `fstat` identity snapshots; Ruff,
  format and diff-check pass. Combined L57 pre-fix evidence is now complete:
  `in=54 out=54 distinct windows=54 functions=35 gaps=0`, all `54/54` RED before
  their corresponding runtime repair. The parent writer owns product changes
  and subsequent GREEN only.
- FIX — L57's first product slice is executable GREEN `21/21` on the complete
  qualifier low-level ownership roster. One CPython line-event probe showed
  that an exception on a nested `try:` line is outside the expected exception
  table coverage; the bundle materializer therefore removes that
  post-acquisition nested boundary and retains one already-active outer
  finalizer. No signal masking, destructor or GC closure is used. Qualifier
  high-level `11`, bridge `13` and Oracle `9` remain open before combined GREEN.
- DONE — The complete qualifier L57 ownership denominator is GREEN `32/32`
  (`21` low-level plus `11` high-level). Worker/process/output, v2 worker,
  capsule namespace, v1 root/output/bundle and v2 dual-root scopes now keep an
  explicit owner active through transfer. The retained registry duplicate is
  measured into blocked cleanup and then closed in the direct worker probe,
  preserving receipt semantics; primary process/output handles close on every
  `BaseException`. Bridge `13` and Oracle `9` remain before combined `54/54`.
- DONE — Bridge L57 exhaustive ownership roster is GREEN `13/13` and runtime
  compiles. Coverage includes secure-root/child/random handoffs, sequential
  socketpair-to-lock and both tempfile acquisitions, retained-root
  remeasurement, blocked publication namespace and returned handle, `_run_once`
  namespace/publication, and replay artifact acquisition. Combined qualifier
  plus bridge is `45/45`; Oracle `9` remains before the full `54/54` gate.
- FACT — L57 lower-cost read-only mechanical census independently maps the
  current qualifier `32/32` to `21` functions and bridge `13/13` to `8`
  functions, with unique case IDs and `gaps=0`. Static inspection confirms an
  explicit `BaseException` owner remains active from acquisition through each
  handoff/return in the 45 repaired windows. This does not replace the pending
  Oracle `9/9`, full safe-only replay, repin or frontier audit.
- DONE — Oracle closes its exact L57 selector `9/9` after one test-harness
  correction that limits the injected `fstat` failure to the product call and
  no longer corrupts the test's own FD census. The complete formerly unsafe
  roster is now executable GREEN: qualifier `32`, bridge `13`, Oracle `9`,
  `in=54 out=54 distinct windows=54 functions=35 gaps=0`. Full safe-only replay,
  format/repin and an independent frozen-snapshot audit remain mandatory.
- FACT — A second lower-cost read-only census independently confirms Oracle's
  `9` unique parameterized cases across `6` functions and finds no ownership
  gap: directory/preimage/materialization/output-parent/public-capsule/live
  Oracle transfers all retain an explicit `BaseException`-safe owner. After
  format, qualifier and bridge share the frozen `51e4...` pin; final-byte
  qualifier `307/307`, bridge `120/120`, and focused `54/54` are GREEN while
  worker/contracts/durable-Oracle/matrix and frontier audit remain pending.
- DONE — L57 writer freeze is exact. Final hashes are qualifier
  `51e4b28a86e5bb947e26d2a4fe6dc6aecae1aafe8008795a3a2d0a211fcf11f3`,
  bridge `dcc98af0c07670c13250e63666774e7ddcdf00a8461278e69b1e15113b232a96`
  and Oracle `3e903eb8b1ec06e331ad2d74225beee9c9c1aba116f557a338645b17b6fdc9bb`;
  bridge pin equals qualifier bytes. Final gates are qualifier `307/307`, bridge
  `120/120`, worker `16/16`, contracts `25/25`, old Oracle `32/32`, new Oracle
  FD `9/9`, matrix `71/71`, compile/Ruff/format `6/6`, with zero supervised
  process residue. L0 then appends the new parameterized Oracle selector to the
  durable roster and independently obtains `30` selectors -> `41/41`, making
  the safe-only aggregate `509/509` on unchanged product bytes. The snapshot is
  frozen; independent L58 frontier audit is the remaining acceptance gate.
- FACT — L0 independently reruns the full safe-only command on frozen bytes:
  qualifier, bridge, worker, contracts plus only the `30` durable Oracle
  selectors complete `509/509`, exit `0`. The separately named executable
  mutation matrix completes `71/71`; raw file hashes match all three L57
  declarations and bridge's compiled qualifier pin; `py_compile`, Ruff check,
  Ruff format-check and `git diff --check` are GREEN. Five promotion authorities
  remain source `None` and the targeted supervised-process census is empty.
- FACT — Independent L58 frontier preflight recomputes all three frozen hashes
  exactly, collects qualifier `32` + bridge `13` + Oracle `9`, and replays the
  retained-traceback/fstat attacks GREEN `54/54`. It independently rebuilds the
  complete acquisition/helper denominator as qualifier `67`, bridge `24`,
  Oracle `28`, total `119/119`; bridge+contracts regression is `145/145`, pin is
  unchanged and process census is empty. Adjacent-owner static review remains
  in progress, so no ACCEPT is recorded yet.
- STOP — L58 finds a new adjacent Oracle P1 outside the focused `9`: in
  `src/metis_model1/oracles.py:_capsule_preimage_roster_at`, the child directory
  FD returned by `_open_capsule_preimage_directory_at` is acquired before the
  following `try` becomes active. A retained-traceback `KeyboardInterrupt` at
  current line `546` leaves the exact child FD `5` (`+1` by fstat identity).
  The read-only probe closes only that FD, hashes remain unchanged and no
  process survives. Frozen `51e4...` is therefore `REWORK/P1`; L58 continues the
  full `119` adjacency census before one bounded tests-first repair wave.
- FACT — L58 completes the structural adjacency census: qualifier `67/67`
  safe, bridge `24/24` safe, Oracle `27/28` safe, aggregate `118/119` with the
  single confirmed gap above. No `__del__`, `weakref.finalize`, `gc.collect` or
  `atexit` ownership reliance is present. Final dynamic/semantic closure remains
  before freezing the exact one-window L59 repair roster.
- STOP — L58 final verdict is `REWORK`, `P0=0 P1=1 P2=1`. Frozen hashes and pin
  stayed exact; the former unsafe roster is independently GREEN `54/54` twice,
  bridge+contracts is `145/145`, and final process census is empty. The complete
  denominator is `in=119 out=119 distinct=119`: qualifier `67/67`, bridge
  `24/24`, Oracle `27/28`, total safe `118` and gaps `1`. First=last repro is
  `oracles.py:545-549`: child FD acquisition precedes its owner scope; retained
  traceback at line `546` adds exact FD `5`, which the auditor closes. L59 opens
  only `oracles.py` and `test_oracles.py` for one tests-first repair; qualifier,
  bridge and their pin remain frozen.
- FACT — L59 tests-first reproduces the sole gap before product edits. The exact
  Oracle selector returns `9` pass / `1` fail; new case
  `capsule-roster-child-return` retains FD `13` whose fstat identity matches
  `root/child` across helper return -> following `try:`. Test cleanup closes only
  that FD. Qualifier/bridge hashes remain `51e4...`/`dcc98...`; Oracle product is
  still untouched at RED capture.
- DONE — L59 closes the one-window Oracle repair. The new case goes RED with
  exact FD `13`, then GREEN after moving `child_fd=-1` and the owner
  `try/finally` before acquisition. Oracle focused roster is `10/10`; the same
  durable `30` selectors now collect and pass `42/42`. Frozen hashes are Oracle
  `256752c85af082b637e41fa7be29883a7b82a5dd91d85db97ac9e3c2876ceeaf`
  and Oracle tests
  `199c21a671d492d7f6c151027723dd77a523801de37d175371d1a76f691686fa`;
  qualifier/bridge/pin stay exact `51e4...`/`dcc98...`. L0 independently reruns
  the complete safe-only gate GREEN `510/510`, rechecks hashes, pin, compile,
  Ruff/format and diff-check. Independent L60 audit remains before ACCEPT.
- DONE — L60 independent frontier verdict is `ACCEPT`, `P0=0 P1=0 P2=0`.
  Frozen hashes recompute exact `3/3`; the ownership roster collects and passes
  qualifier `32` + bridge `13` + Oracle `10` = `55/55` across `36` functions.
  The former Oracle gap is independently reprobed with the real child identity,
  retained traceback and `fd_delta=0`. The rebuilt broad denominator is
  qualifier `67/67`, bridge `24/24`, Oracle `28/28`, total `119/119 gaps=0`.
  Bridge+contracts remain `145/145`, pin equality is exact, no implicit
  GC/destructor ownership exists and final process census is empty. The L23-L60
  capsule/bridge qualification infrastructure is accepted; this does not
  register production authorities, create W3 data, train a model or establish
  the requested 99% population result.
- STOP — The mandatory repository-wide `make check` is executed before the
  requested commit/push. Foundation `28/28`, pilot contract validation, Ruff and
  format pass; pytest ends `749 passed, 1 skipped, 21 failed`. All 21 fail at
  the same precondition: `tests/test_oracles.py` hardcodes the mutable live
  Metis checkout, whose HEAD is now
  `f5b54b8d5700f90139c0fc4df58f2a55de713fc9`, while Model 1 correctly pins
  `a2dde2b191f6b78c2003d74875560da782470968`. No Oracle payload executes and
  the product fail-closes on revision mismatch. L0 will not reset, rename or
  alter the user's Metis checkout and will not push a red gate; the test harness
  must accept an explicit pinned test checkout/capsule without weakening the
  production revision check.
- FIX — L61 makes only the test harness root explicit: `Makefile` forwards
  `PINNED_METIS_ROOT` as `METIS_MODEL1_METIS_ROOT`, and `test_oracles.py`
  canonicalizes that path. Production revision validation is unchanged. The
  initial pinned-copy run reduced `21` revision-mismatch failures to two macOS
  `/tmp` -> `/private/tmp` expectation aliases; `.resolve()` closes those `2/2`.
- DONE — L0 creates a temporary local shared clone at the exact pinned Metis
  commit, copies only the already-pinned tooling dependencies, and runs the
  mandatory repository-wide gate without touching the live checkout. Final
  `make check` is GREEN: foundation `28/28`, pilot contracts valid with W5
  blockers honestly reported, Ruff/format GREEN, pytest `770 passed, 1 skipped`
  in `319.47s`. Live Metis remains at `f5b54b8...`; the temporary clone is not a
  product artifact and will be removed before commit. Commit/push may now
  proceed for the accepted infrastructure milestone; no model weights or data
  payload enter Git.
- DONE — Accepted capsule/bridge infrastructure, retained-root evidence,
  hermetic pinned-root test harness and Qwen team registration are committed as
  `5a5d817` (`feat: harden W3 qualification bridge`) and pushed to
  `origin/codex/model1-local-99-foundation`. The commit contains `22` explicit
  source/schema/test/board/brief files, no weights, dataset, checkpoint or
  artifact payload. The branch is now a resumable GitHub checkpoint; production
  W3 authorities, real receipts, W1/W2 population, W5 training and the 99%
  result remain open.

## Open

- OPEN — Register a production W3 adapter plus independently reviewed typed
  semantic specifications and obtain real isolated-runner receipts for the
  `15/15` allocated F-1/F-2/F-3 smoke tasks.
- OPEN — First qualify the production bridge on three self-contained
  public-synthetic candidates: `3/3` candidates and `5/5` ordered executions
  (`target`, `before`, `after`, `mutated`, `fixed`), with byte-identical replay,
  denied network/write canaries and exact pre/post Metis invariants. This gate
  does not close the allocated `15/15`.
- OPEN — Implement and audit F-4/F-5/F-6 without weakening the accepted
  F-1/F-2/F-3 trust boundary.
- OPEN — Benchmark v1, at least 563 genuinely independent groups, real W3
  dataset, A/B baseline, O-003 and W5.
- OPEN — Final semantic accuracy and promotion verdict.

## Stop rules

- STOP — Any Metis checkout write, secret/live-data access, external upload,
  materialized payload entering Git or model-family change ends the lane.
- STOP — A generated benchmark cannot certify its own targets without an
  independently validated semantic oracle.
- STOP — A policy-only receipt, compiler-clean output or adapter-authored
  `matched=true` can never serve as production execution or semantic evidence.
- STOP — Cosmetic variation, common template ancestry or shared semantic
  specification cannot inflate leakage-group counts.
- STOP — Training does not start before benchmark freeze, accepted W3 data,
  baseline A/B and O-003.
- STOP — NaN/Inf, OOM, peak Metal above `110 GB`, hash/resume failure or an
  unverified checkpoint blocks promotion.

## Ruled out

- Calling parser/compile accuracy semantic accuracy.
- Training on frozen benchmark targets or using frozen results for selection.
- Claiming the 99% population target from correlated synthetic variants.
- Editing or generating inside the Metis checkout.

## Outcome

IN PROGRESS — delivery wave opened; no promotion verdict yet.
