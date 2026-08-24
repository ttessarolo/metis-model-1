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
- FACT — L62 preflight compares two independent read-only reviews of the real
  materialization boundary. Kimi accepts `4ec625f...` as a ratification
  baseline because executing code is separately hash-bound; Qwen reports a
  provenance ambiguity because the required production worker and frozen
  Oracle bytes postdate that tree. Mechanical census accounts the old literal
  at `9/9` locations: four executable/schema pins and five historical briefs;
  qualifier-pin literals are `2/2`. No repository, Metis or artifact write was
  made by either review.
- RISK — L0 resolves the disagreement fail-closed: real materialization is
  NO-GO while `project.revision` can be read as a tree that does not contain the
  source worker actually executed. This does not invalidate the L60
  infrastructure ACCEPT; it blocks only the next source-bundle authority.
- OPEN — L62 is recorded in
  `orchestra/briefs/2026-08-21-model1-l62-source-revision-repin.md`. It defines
  `project.revision` as the source-bundle Git freeze and repins it acyclically
  to full commit `5a5d817bb3df817fbd5d47b7bc4edd4517f8d9b7` while launcher and
  qualifier identity remain independently hash-bound. Exact writable roster is
  seven product/schema/test paths; real bundle/capsule materialization, runner,
  authority registration, data and training remain STOP.
- FACT — Read-only L62 source-closure census derives the minimum worker bundle
  directly from Git object `5a5d817...`: `6/6` regular files, `141,507` bytes,
  no missing/drifted path. L0 independently recomputes all six raw SHA-256 and
  byte sizes exact. The roster is the worker, `metis_model1` package marker and
  Oracle module, Oracle-result schema, frozen candidate manifest and frozen
  semantic registry; every current byte equals the freeze blob. Proposed
  canonical file-array roster SHA-256 is
  `sha256:0d58e69823d5edd46624874a6488526362665a4f08e7354e9f6e6ede596d5b82`.
- FIX — L62 tests-first delta is limited to the seven authorized
  runtime/schema/test paths. Exact former-baseline attacks are RED `7/7`, then
  the four revision pins move to full source checkpoint `5a5d817...`; qualifier
  formatting yields SHA-256
  `7303d59b65af90e3fef2c9e01c53cd4916b724f5b6e155298651db06ab937421`
  and the bridge pin matches exactly. Worker, Oracle, contracts product,
  manifests and all five source authorities are untouched.
- DONE — L0 independently replays the frozen L62 bytes: safe-only collect/run
  `517/517`, historical executable mutation matrix `71/71`, schemas `3/3`,
  authorities `None` `5/5`, compile/Ruff/format/diff-check GREEN. Mandatory
  hermetic `make check` against a temporary Metis clone at exact `a2dde...`
  passes foundation `28/28`, pilot contracts, schemas and pytest
  `777 passed, 1 skipped` in `317.12s`; the clone is removed, the live checkout
  is untouched and final process census is empty. Writes freeze for independent
  audit; real materialization remains STOP.
- RISK — First L62 frontier audit returns REWORK `P0=0/P1=0/P2=1`: the two new
  qualification-report tests changed `project_revision` without recomputing
  `manifest_sha256`, so they could reject for a stale digest even if the
  revision guard regressed. Product behavior is independently correct for
  canonical re-hashed former-baseline reports `2/2`; the gap is test-only.
- FIX — The two report tests now canonical-rehash after substituting `4ec...`.
  Focused `2/2` and safe-only `517/517` are GREEN; runtime/schema bytes and the
  qualifier/bridge hashes are unchanged. The frontier re-audit simulates a
  removed revision guard and confirms both tests would then fail, closing the
  false-green seam. Final verdict is ACCEPT `P0=0/P1=0/P2=0`.
- FACT — Independent Kimi final review returns ACCEPT `P0=0/P1=0/P2=0` after
  recomputing the qualifier hash/pin, four revision pins, ancestry, historical
  references, unchanged semantic pins and exact writer/off-limits roster.
  Qwen's first full-repository client attempt stalls without output and is
  terminated by exact session only; a bounded safe-mode review of the supplied
  final diff returns ACCEPT with no P0/P1 and only already-green style notes.
- DONE — Final post-rework `make check` on a newly created temporary pinned
  Metis clone is GREEN again: foundation `28/28`, pilot contracts/schemas,
  Ruff/format and pytest `777 passed, 1 skipped` in `362.39s`. Temporary clone
  removal, diff-check, runtime hashes and process census are exact. L62 is
  accepted and ready for a payload-free Git checkpoint; this acceptance opens
  no production authority, real runner, data, training or 99% claim.
- DONE — Accepted L62 source-revision semantics, tests, schemas, audit evidence
  and resumable board state are committed as `85069d4`
  (`fix: bind W3 source bundle revision`) and pushed to
  `origin/codex/model1-local-99-foundation`. No payload or authority instance is
  committed. The next wave may now design/materialize external bundles, but
  only after its own explicit brief and with the real runner still fail-closed.
- DONE — L62 status evidence is committed as `2d519d9`
  (`docs: record L62 source revision checkpoint`) and pushed; HEAD and remote
  coincide and the worktree is clean at L63 open.
- FACT — L63 direct preflight corrects a delegated false negative: durable
  CPython `3.13.3` arm64 exists at the resolved uv runtime and repo `.venv`
  points to it; durable Node v22.22.3 exists at `~/.hermes/node/bin/node` with
  exact registered SHA-256 `5d9d3872...f7cd5c`. Reconstructing the six package
  plus five metadata directories from `.venv` yields dependency closure
  `in=144 out=144 distinct=144 gaps=0`, `1,799,002` bytes, no symlinks and
  exact registered digest `db649bc1...3f42`. No bundle or runner was executed.
- OPEN — L63 real external materialization and replay is sealed in
  `orchestra/briefs/2026-08-22-model1-l63-real-capsule-qualification.md`.
  Tracked writes are brief/board/ledger only; payload writes are limited to the
  ignored retained `artifacts/w3-production-v2/l63-source-5a5d817/` root.
  Kimi K3 and Qwen reviews are mandatory both before and after the single bridge
  invocation. Training, W1/W2 population, source-authority registration and
  any accuracy claim remain STOP.
- STOP — L63's first real-runtime canary, still without runner execution or
  materialization, exposes two exact incompatibilities in the frozen capsule
  launcher. Under the actual Node Seatbelt policy and environment, importing
  the registered TSX loader first fails `EPERM` while creating its cache in the
  ambient macOS temp root. Supplying a canary-only `TMPDIR` below process root
  closes that write, then TSX/esbuild fails `spawn EPERM` because the accepted
  policy denies all process creation. Current v2 can therefore not execute the
  real TypeScript runner; no authority or capsule is created and L63 remains
  fail-closed.
- OPEN — L0 is routing the incompatibility to frontier plus Kimi/Qwen before a
  product change. The preferred boundary must preserve no-detach/no-residual
  guarantees; broadening Node fork/exec merely to satisfy TSX is not accepted
  without a new executable trust design. A precompiled, hash-bound runner is a
  candidate, not yet a decision.
- FACT — L63 retained prototype establishes a second concrete option without
  executing the W3 runner. A 48-line stdlib-only ESM loader uses the exact
  Node v22.22.3 `node:module.stripTypeScriptTypes(mode=transform)` API and maps
  registered relative `.js` specifiers to existing `.ts` files. Under the exact
  frozen Node Seatbelt policy it imports `serialize.ts` with rc0/stderr empty,
  then imports the pinned Git `metis-module.ts`, `compile.ts` and `serialize.ts`
  over a mechanically derived Langium closure of `15` packages, `1,790` regular
  files, `7,710,543` bytes and zero symlinks: rc0, stdout
  `METIS_NATIVE_TS_OK`, stderr empty, temp roster empty. Fork remains denied and
  no executable besides Node is introduced.
- RISK — The prototype is feasibility evidence, not authority or semantic
  parity. Adopting it requires a new loader hash/role, truthful replacement of
  every TSX identity, exact runtime-module roster, Node flag/loader pin and a
  five-role TSX-vs-native semantic parity wave before any production replay.
  Kimi currently prefers deterministic precompiled JS; frontier is comparing
  that design against the observed native-loader result and Qwen is still
  reviewing. No L63 materialization proceeds during this decision.
- FACT — L63 frontier closes the executable-design comparison on frozen bytes.
  The pinned runner source closure is `29` TypeScript files, `909,608` bytes and
  `77` import/export edges: all `48` relative edges resolve by exact
  `.js -> .ts`, external imports are only `langium`, `langium/lsp`,
  `vscode-languageserver` and `node:path`, and the only non-erasable construct
  is one parameter property served by `stripTypeScriptTypes(mode=transform)`.
  No enum, namespace, decorator, path alias, runtime JSON asset or unresolved
  relative edge was found.
- DONE — After receiving the real-graph canary, Kimi K3 and Qwen independently
  revise their initial prebundle preference to the same verdict as L0/frontier:
  adopt the 48-line stdlib-only native loader; retain precompiled JS only as a
  fallback if semantic parity fails; reject any production fork/esbuild broker.
  Review convergence is `in=3 out=3 distinct=3 gaps=0` across Kimi, Qwen and the
  internal frontier review.
- STOP — L63 remains closed for materialization for a second independent
  reason: the exact qualified Node is `112,915,776` bytes but the current
  `production-trusted-root` per-file cap is `8 MiB`. Copying the present capsule
  into that retained root necessarily blocks even if execution succeeds. Full
  Metis (`2,309` files) and full node_modules (`17,312` files, `22` symlinks)
  also violate the retained capsule contract; only selective Git and package
  closures may proceed.
- OPEN — L64 is frozen in
  `orchestra/briefs/2026-08-22-model1-l64-native-loader-runtime-root.md`.
  L0 chooses a dedicated retained `production-runtime-root` for the exact Node
  preimage rather than raising the trusted-content cap. The root is captured,
  rehashed, sealed and double-snapshotted once per qualification; the ordinary
  trusted root remains `8 MiB` per file. L64 is tests-first and payload-free;
  L63 resumes only after native-vs-TSX `15/15` parity, safe gates, make-check and
  independent frontier/Kimi/Qwen acceptance.
- FACT — L64 tests-first starts RED `0/10`: the old bytes lack the exact v3
  discriminator, loader identity/file, runtime-root order/caps, final policy and
  v3 schemas while fixture v1 remains the required compatibility surface. The
  writer then stops before product edits when the mechanical census finds one
  missing authority validator path. L0 expands the roster once from 19 to 20
  paths by adding `src/metis_model1/w3_oracles.py`; it constructs and validates
  the production receipt identity and cannot truthfully retain `tsx_path`.
- STOP — The first real native parity invocation blocks before producing any
  result: the frozen 29-file regex closure omitted a multiline commented import
  of `pipes-census.js` from `metis-validator.ts`. Native exits rc2 on the
  missing roster byte. The loader, sealed Node root and sandbox reached the
  module graph correctly; no execution receives credit. L0 retracts the
  29-file/`7dc6...` roster as authority evidence and requires a registered
  TypeScript-AST fixed-point census plus loader-observation equality.
- FACT — This STOP does not regress the product gates already reached: the L64
  focused contract is green, the fd-only Node runtime-root swap/roster attacks
  are `3/3`, safe capsule/FD matrix `40/40`, qualifier `321/321`, bridge
  `123/124` with only the deliberately stale final pin, `w3_oracles 29/29`,
  builder `43/43` and contracts+worker `42/42`. Parity restarts from zero only
  after the closure census is corrected.
- FACT — The registered TypeScript-AST fixed-point census replaces the
  retracted regex roster with `in=32 out=32 distinct=32 gaps=0`: `967,481`
  bytes, maximum file `213,424`, `99` edges, relative resolution `66/66`, four
  exact external specifications and roster SHA-256 `e8e586d0...`. The
  manifest-derived package closure remains a conservative `1,790/1,790` files,
  `7,710,543` bytes, 15 packages and zero symlinks; it is not misrepresented as
  a runtime-observation equality target.
- DONE — Native-versus-reference semantic parity was restarted from zero on the
  corrected closure and passes `in=15 out=15 distinct=15 gaps=0`: all three
  candidates and five ordered roles are normalized byte-for-byte, including
  F-3 mutated diagnostic ranges, lines and characters. Native production uses
  the exact deny-fork Seatbelt policy, captured one-file Node runtime root,
  empty stderr/temp rosters and zero residual PIDs; the TSX reference is
  reference-only and receives no production credit.
- FACT — Loader observation is reported as containment, not false equality.
  Runtime loads `30/32` conservative Metis source files; the two static-only
  files are reached solely through erased `import type` edges. It observes 13
  of 15 conservative package identities, and all `338` observed capsule file
  URLs belong to the exact `1,827`-file, `8,921,621`-byte selective capsule;
  observed outside/ambient files are `0`. Final format, hash/repin, broad gates,
  hermetic `make check` and independent audits remain open before L64 acceptance.
- OPEN — A broad read-only production-adapter run finds exactly two stale tests
  that still require schema v2 or build a schema-v2 receipt without the new v3
  runtime fields (`12` pass, `2` fail, `1` skip). L0 amends the writable roster
  once more by adding only `tests/test_w3_production_adapter.py` as path `21`;
  the tests must move to truthful v3 semantics, while product code must not
  regress to satisfy obsolete expectations.
- DONE — L64 freezes its exact 21-path implementation roster after the complete
  hermetic gate returns exit `0`: foundation `28/28`, retained schemas `6/6`,
  Ruff and format GREEN, and pytest `800 passed, 1 skipped` in `310.42 s`.
  Final raw identities are loader `7d5e59de...f126`, runner
  `772baa27...f5d`, qualifier `045e355b...2f43`, bridge
  `eff3361b...da55`; bridge qualifier pin and loader/runner pins agree exactly.
  Oracle policy `deb8f45c...40aa` and actual Node execution policy
  `4f29bf5e...de51` are deliberately distinct and regression-bound.
- FACT — The final corrected closure and parity receipts remain exact after the
  freeze: source AST roster `32/32` and SHA-256 `e8e586d0...fe918`; package
  roster `1,790/1,790` and `35a56f21...8bbb`; capsule `1,827` files,
  `8,921,621` bytes, zero symlinks and `61ac4f62...4f56`; native/reference
  parity `15/15` with comparison roster `f0520da9...1490`. Loader observations
  are `338/338` contained, outside/ambient `0`, with the conservative/type-only
  `30/32` source and `13/15` package distinction recorded explicitly.
- STOP — L64 is implementation/test green only. Production materialization and
  authority remain forbidden because `V3_PROJECT_SHA` still names the prior
  `5a5d...` source checkpoint and all source authorities remain unset. Frozen
  bytes now require independent frontier, Kimi and Qwen audits, followed by a
  separate acyclic source-bundle repin before L63 can resume.
- STOP — Independent L65 authority audit finds a production seam outside the
  L64 roster: `src/metis_model1/w3_production_adapter.py` still constructs the
  actual real-runner bundle with `schema_version: 2`, while the v3 identity,
  manual validator and run schema require exact `3`. The only actual adapter
  execution test remains explicit opt-in/skip, so `800/1` did not exercise this
  contradiction. L64 is therefore `REWORK` pending completion of all frozen-byte
  audits and a bounded tests-first port; no source repin or L63 resume may start.
- STOP — The same audit finds a second independent L64 proof gap: the qualifier
  retained-cleanup mutation matrix (`18/18`) and bridge child-cleanup matrix
  (`7/7`) still call their validators with stale expected order
  `(process, trusted)`. An unmutated valid v3 cleanup has three roots
  `(process, runtime, trusted)` and is therefore rejected before any parametrized
  mutation matters. All `25/25` named cases can false-green and must be repaired
  with a positive control plus mutation-specific rejection before acceptance.
- STOP — A canonical-rehash authority attack exposes schema/manual divergence:
  replacing the loader hash consistently in `capsule.loader`, its roster row,
  capsule manifest and authority manifest is accepted by the Draft 2020-12
  production-authority schema, while qualifier and bridge correctly reject the
  unregistered loader. The schema uses a generic capsule identity for loader
  and runner instead of the exact frozen pins; L64 therefore needs exact schema
  constants and schema/manual/bridge mutation agreement before acceptance.
- STOP — The authority schema also leaves capsule file `role` as any nonempty
  string. Fully recounted and rehashed authorities containing legacy
  `role: "tsx"` or `role: "node"` are schema-valid `2/2`, although qualifier
  and bridge reject them. The current raw-source assertion merely proves those
  words are absent from schema text; it does not prove fail-closed residual-role
  behavior. This independently violates L64's exact v3 role and schema/manual
  agreement contract.
- STOP — Exact closure/observation/parity evidence is not durable on the frozen
  tree. Searches find `32/30`, `1,790/13`, `1,827/338` and their roster hashes
  only in board/ledger prose, not in a canonical receipt, manifest, retained
  roster or deterministic census tool; the only older retained prototype has a
  different `1,953`-file capsule. Under the repository contract, DONE prose and
  an ephemeral writer handoff cannot establish these denominators. Rework must
  retain independently reproducible exact rosters/comparison receipts without
  committing payload bytes before parity or containment can be accepted.
- STOP — Independent runtime audit finds the v3 launcher identity impossible:
  bridge still pins the old combined policy `cfd09f90...`, while the qualifier
  recomputes and publishes `d4f6cb3c...` from the changed outer+Node templates.
  All other launcher fields match, but one authority cannot satisfy both
  validators (`in=1 matched=0 mismatched=1`). The bridge pin and a direct
  recomputation regression must move together.
- STOP — The same audit reproduces a same-UID transient-byte substitution across
  the new native path. Loader/runner/modules and Node are ultimately reopened or
  executed by pathname; retained fd checks prove inode identity, not byte
  immutability. A `0444/0555` file can be chmod/replaced in place, executed with
  altered bytes, then restored before the post-snapshot. Exact probes accept
  transient module substitution `1/1`, changed-byte same-inode Node `1/1`, and
  identify both qualifier/public pathname-exec surfaces `2/2`. L64 cannot claim
  captured-preimage execution until this boundary is redesigned and attacked.
- RISK — Runner bytes are hash-pinned but its canonical capsule location is not:
  identical runner bytes at `alternate/runner.ts` are accepted by qualifier,
  bridge and public verifier `3/3`, while receipts claim
  `/.metis-oracle/runner.ts`. Add exact path pins and canonical-rehash tests.
- STOP — Qwen's independent frozen-byte review exposes a direct v3 replay
  impossibility, now confirmed by L0 source inspection. The qualifier seals and
  snapshots the sole `production-runtime-root` Node file as `0555`, but bridge
  `_snapshot_holder_tree` rejects every regular file not `0444` and also writes
  `0444` into its roster row. Both qualified and blocked child remeasurement
  route all three root kinds through that helper. A genuine v3 runtime root
  therefore fails first on mode and would then fail on roster digest; current
  tests either stub remeasurement or construct the runtime fixture through the
  generic `0444` holder sealer. L64 cannot enable L63 until per-kind physical
  mode/digest remeasurement has an exact positive real-shape regression.
- FACT — Kimi's resumed independent audit returns REWORK and independently
  confirms the stale combined launcher pin, the vacuous `18+7` cleanup
  mutations, the non-durable closure/parity evidence, schema permissiveness for
  loader drift and legacy roles, alternate runner location, and the pathname
  same-UID boundary. Kimi recommends declassifying `ProductionW3Adapter`
  instead of porting another in-process execution route around the external
  qualifier+bridge authority.
- STOP — Frontier architecture review finds no honest in-process fix for an
  active same-UID writer on this macOS boundary: modes, retained inode FDs,
  double snapshots and a same-UID copy remain transiently writable, while an
  executable-fd route is unavailable/failed locally. Strong executed-preimage
  evidence requires a separately authorized OS boundary (for example a
  distinct-UID broker with non-caller-writable ancestry and authenticated
  receipts). The bounded rework must fail-close/declassify production and keep
  L63 stopped; it must not silently rename this into a proven preimage claim.
- OPEN — One tests-first L66 rework must close the complete frozen-audit census
  together: per-kind runtime-root remeasurement, launcher-policy recomputation,
  exact three-root mutation controls, authority schema pins/role enum, canonical
  runner path, legacy adapter declassification, and a deterministic metadata-only
  closure/parity receipt tool. No product patch starts until Qwen's final census
  and the architecture brief are frozen.
- STOP — Qwen's final frozen-byte verdict is REWORK with two functional P0s:
  the `0555` runtime root is impossible to remeasure through bridge's `0444`
  helper, and the stale combined launcher-policy pin makes the v3 authority
  unsatisfiable. Qwen also confirms the adapter-v2 seam, 25 false-green cases,
  authority-schema under-pinning, prose-only denominators and the same-UID
  pathname surface. Positive findings remain fail-closed source authority,
  loader containment, separate runtime-root caps and process hygiene; none
  overrides the blockers.
- FACT — L66 architecture is frozen in
  `orchestra/briefs/2026-08-22-model1-l66-native-proof-rework.md`: exact 21-path
  writer roster, mandatory REDs, per-kind `0555/0444` remeasurement,
  deterministic metadata-only evidence manifest, legacy adapter
  declassification and production fail-closed until a distinct-UID/root broker
  exists. L63, source repin, payload and training remain STOP.
- FACT — L66 writer preflight is complete on exact HEAD `2d519d9`: full
  brief/board/ledger/charter/roadmap read, writable `21/21` and off-limits roster
  checked, inherited L64 diff preserved and diff-check clean. No product/schema
  byte has been touched; the writer is now adding tests-only RED cases. The
  protected-broker absence remains an explicit production pre-FS/pre-process
  STOP, not a deferred hardening item.
- FACT — First L66 tests-only RED is captured before any product/schema write:
  exact combined-launcher recomputation fails `0/1`, bridge literal
  `cfd09...f4d8` versus qualifier-derived `d4f6...9c97`. The first bridge test
  slice stages `10` cases: policy `1`, runtime modes `2`, exact identity
  schema/manual/bridge/public attacks `6`, and pre-FS/process production STOP
  `1`. Remaining RED files are still being constructed; no GREEN credit yet.
- FACT — L66 tests-only staging now spans `6` files and `59` nominal cases,
  still with zero product/schema writes. Exact partial REDs: runtime-root `0/2`
  (bridge helper has no kind), combined policy `0/1`, canonically rehashed
  identity/schema attacks `0/6`, and bridge cleanup controls `0/7`. The first
  qualifier cleanup invocation used host Python 3.11 and stopped on the known
  3.13 requirement; it carries no denominator credit and is being rerun with
  the pinned `.venv` interpreter before the adapter/STOP/evidence batch.
- FACT — L66 exact RED capture is complete on pinned Python 3.13 with product
  and schemas still untouched: runtime modes `0/2`, combined policy `0/1`,
  qualifier+bridge cleanup `0/25`, six canonically rehashed identity/legacy
  role attacks `0/6`, adapter/qualifier/bridge/public pre-boundary STOP `0/5`,
  same-UID nonclaim `0/1`, durable receipt mutations `0/19`, deterministic
  emit/verify `0/1`, metadata/nonclaims `0/1`, and three evidence bindings
  `0/3`. Aggregate `in=64 out=0 distinct=64 gaps=0`; every first failure maps
  to the frozen brief and no new scope/architecture STOP emerged. Product and
  schema implementation may now begin.
- FIX — First L66 product slice is implemented within the authorized roster:
  bridge snapshots retained files with exact per-kind `0555/0444` modes,
  combined launcher pin is `d4f6...`, runner path is canonical in qualifier/
  bridge/public validation, authority capsule roles and loader/runner identities
  are schema-pinned, and production qualifier/bridge/adapter/public entrypoints
  stop before filesystem/process without broker authority while exposing the
  same-UID nonclaim. Four modified Python product files compile cleanly. The
  deterministic receipt tool/schema/manifest and their three report bindings
  remain in progress; no claim is made from compile evidence.
- FACT — The native census tool independently reconstructs from pinned Git
  objects and registered tooling: source `32 files / 967481 bytes / 99 edges /
  66 relative`, runtime fixed point `30/32` with only `preview-plan.ts` and
  `executor/rows.ts` behind type-only edges, and packages `15 / 1790 files /
  7710543 bytes / 0 symlink`. Historical 15-row actual parity hashes and the URL
  trace were not retained; the writer correctly stopped rather than derive
  equality from expected targets.
- FACT — L0 amends L66 narrowly to authorize one bounded reference-only parity
  reconstruction: three fresh rounds × five public-synthetic roles, pinned Git/
  tooling/Node, native deny-fork versus separately labelled TSX comparator,
  actual result/diagnostic hashes and URL trace, temp roots outside Git, zero
  production/authority/dataset/training credit. Every other runner execution
  remains STOP.
- OPEN — The authorized parity run is not yet started (`0/15`), so there is no
  mismatch/stderr/temp/PID evidence to report. The writer is completing the
  temp-only Git-object capsule builder, final-policy native command, separately
  labelled TSX comparator, trace/hash normalization and cleanup preflight first.
  The census JS wraps tracing without changing the frozen loader pin. Execution
  starts only after those controls are inspectable and stops on the first
  mismatch.
- FACT — Receipt harness syntax boundary is clean: new Python evidence tool
  passes `py_compile` and the tracing/census loader passes Node `--check`.
  Parity remains deliberately `0/15`; compile evidence receives no closure or
  parity credit. Inherited off-roster L64 changes remain untouched.
- FACT — L66 no-run dry preflight is GREEN and independently recomputes source
  `32 / 967481 bytes / 99 AST edges`, package closure `15 / 1790 files /
  7710543 bytes`, and tooling pins. Ruff for the new tool/tests is green.
  Parity remains `0/15`; exact receipt schema is the last prerequisite before
  the single authorized capture.
- FACT — New native-evidence schema is Draft 2020-12 meta-valid and the tool is
  schema-aware. It verifies exact denominators/order/hashes, source/package/
  capsule cross-projections, actual result+diagnostic equality, input hashes and
  temp roots outside Git. Python compile, Node check and Ruff remain green.
  Capture is still `0/15` during the final document-only preflight; no runner
  result is inferred from the schema.
- FACT — Final no-run capture preflight is GREEN: pinned Git revision→tree and
  blob OIDs verified, full tooling installation verified, reference comparator
  fixed to `tsx@4.22.4` with explicit child/temp permission, and exact native
  Seatbelt policy parse/exec canary returns stderr `0`. L0 authorizes the one
  already-scoped `3×5` capture now, with immediate STOP on mismatch, native
  stderr/temp, residual PID or outside/ambient trace.
- STOP — The first authorized capture stopped before native preload and before
  any row (`0/15`): an auxiliary tracing wrapper under `run-1-1/native` hit
  Seatbelt `EPERM` while realpath walked an ungranted ancestor. Native stderr was
  nonzero, no receipt was emitted, the capture root is empty and exact process/
  temp census is zero. No parity result is credited and no retry is authorized
  with that design.
- FIX — L0 freezes the narrower trace design: the actual native loader writes
  observation URLs only to an explicitly inherited reference-only FD; the
  production environment proves that FD/variable absent. No auxiliary loader
  pathname and no broad metadata/data policy widening are allowed. A focused
  trace-FD canary plus zero production trace precedes the single retry.
- FACT — The inherited-FD trace necessarily changes the native-loader bytes.
  L0 therefore amends the exact L66 writable roster from `21` to `22` by adding
  only `schemas/w3-run.schema.json` for the loader-hash cascade. Leaving its v3
  const stale or silently calling the schema legacy would recreate the schema/
  manual divergence; `oracle-result` and every other off-limits path remain
  frozen.
- FACT — Inherited-trace rework has its own tests-first RED `0/2` before the
  loader edit. Both cases fail on the absent explicit trace-FD environment
  contract; the canary does not spawn Node, so parity remains `0/15` and no
  additional runner execution is consumed. Scope `22/22` is acknowledged with
  only the w3-run loader pin newly writable.
- FIX — Inherited trace-FD rework is GREEN `2/2`: the actual native loader emits
  exactly the contained canary URL, stdout is `42`, stderr/temp are zero and
  exact PID/PGID census is zero. Census JS is parser-only; production oracles
  and qualifier omit both trace env and `pass_fds`. Loader/qualifier hashes and
  bridge/schema pins are cascaded across the exact 22-path scope; bridge pin,
  meta-schema, compile, lint and static `32/32` plus package `15/1790` gates are
  green. L0 authorizes the one `3×5` retry now.
- STOP — The trace-FD retry commits no row (`0/15`) and no receipt. Native
  F1-author completed with stderr/temp/PID/PGID zero and contained trace, but the
  harness incorrectly rejected the separately authorized TSX comparator temp
  files as a production invariant. Temporary roots were fully removed and outer
  capture root is empty. No parity credit and no immediate retry.
- FIX — Receipt semantics now separate native and reference-comparator temp:
  native stays exactly empty; TSX temp must be bounded, symlink-free, fully
  enumerated/hashed, explicitly labelled reference-only, then deleted with an
  independent zero-residual check. One final retry may occur only after a
  dedicated tests-first RED→GREEN for this roster/cleanup; any later execution
  STOP closes L66 parity as blocked.
- FACT — Comparator-temp rework has its own pre-edit RED `0/2`; both cases fail
  on the absent bounded snapshot API and the symlink attack cannot be processed.
  No Node, runner or capture was launched. Tool edits may begin, but the final
  parity retry remains unauthorized until both cases and cleanup proof are
  GREEN.
- FACT — Comparator-temp exact focused denominator is now `0/3`: snapshot,
  cleanup and semantic API were absent. The separately authorized TSX canary
  confirms expected nonempty temp with stderr/PGID zero. The implementation now
  has recursive metadata-only rows, symlink/special rejection, caps
  `64 dirs / 4096 files / 64 MiB`, per-file and roster hashes, race resnapshot,
  deletion and residual-zero verification; schema distinguishes native temp
  zero from reference-only comparator child/temp. Semantic verifier/focused
  GREEN remains pending and no parity retry has started.
- FIX — Comparator-temp contract is closed: RED `0/3` becomes focused GREEN
  `6/6`, covering contained native trace/stderr0/temp0/PGID0, zero production
  trace, bounded hashed temp roster and cleanup, symlink rejection, actual TSX
  reference child/temp with residual0, and qualifier pin. Receipt schema is
  Draft 2020-12 valid and records rows/counts/bytes/file+roster hashes plus
  deleted counts/residual0; native and comparator nonclaims are exact. Tool/JS
  compile, Ruff and static closure remain green. L0 authorizes the final `3×5`
  attempt; any further execution STOP closes parity blocked with no fourth run.
- STOP — Final authorized capture completes all `15` semantic/diagnostic
  comparisons in process, with native `337` URLs each, stderr/temp/PID/PGID0,
  TSX temp `30 files / 844603 bytes` inside caps and cleanup/process residual0.
  Publication then fails closed because the registered historical observation
  denominator is `338`, not `337`. No manifest exists, capture/temp roots are
  empty and console-only equality receives zero durable credit. No fourth
  attempt is permitted.
- FIX — L66 now emits only a deterministic blocked evidence manifest: full
  recomputable static source/package/capsule metadata and pins, parity
  `status=blocked`, `available=false`, expected rows `15`, durable rows `0`, and
  stable observation-denominator-drift reason. It must not persist console-only
  hashes or relabel 337 as observed evidence. Two blocked emits and independent
  static verify remain required. L66 maximum outcome is `PARTIAL / STOP`; L63
  remains stopped.
- FIX — Blocked receipt implementation is now structurally exact: capture API
  is permanently closed; parity is `blocked/available=false`, expected `15`,
  durable `0`, reason `observation-denominator-drift`, credit `none`. The builder
  recomputes full `32` source, `1790` package and `1827` capsule metadata rows
  plus pins, and excludes all console hashes/URL rosters. Schema is blocked-only
  and future tests are static/synthetic so no Node/TSX/canary can run. Manifest
  emission and independent verification are still pending.
- STOP — First two static blocked-receipt emits fail before writing because the
  package builder emits grouped package/rglob order while the verifier requires
  global byte-path order. Output directories remain empty and no runner,
  capture or TSX process occurs. This is a deterministic metadata ordering bug,
  not a parity attempt; the writer is sorting all `1790` rows globally before
  retrying the two static emits.
- DONE — Blocked evidence receipt is durable and independently reproducible:
  two fresh static emits are byte-identical (`735078` bytes, file SHA-256
  `1efbde...65510`) and both pass `--verify`; internal manifest hash is
  `7bad7d...7b052`. It retains source `32/967481/99/66`, packages
  `15/1790/7710543` and capsule `1827/8922291`, while parity is exactly
  `BLOCKED`, available false, expected 15, durable 0, credit none and durable
  URLs 0. No console-only 337 roster/hash is present. Canonical metadata-only
  copy is `manifests/w3-native-loader-evidence.json`; report/schema bindings and
  broad static gates remain.
- FIX — Exact evidence binding is now closed across schema and runtime: the
  three production schemas bind the manifest `3/3`; qualifier/bridge compile;
  schema/manual qualified+blocked/key-agreement/pin focused batch is `10/10`,
  and authority/manual mutation batch is `19/19`, with no process execution.
  Final qualifier SHA is currently
  `b3c4a02c196c4c6b5cf547c208ee05ca970fd76040c827f9d5fbe18bfd21ca45`
  and bridge pin matches. Static receipt reverification and broad gates remain;
  wave outcome remains `PARTIAL / STOP`.
- DONE — Post-binding static receipt gate is GREEN: canonical blocked manifest
  passes independent `--verify`, contracts are `29/29`, and native-evidence
  tests are `28/28`. These tests use only the static emitter and explicitly
  synthetic fixtures; capture API remains closed and no runner/TSX/canary is
  executed. Broader compile/lint/owned-suite gates follow.
- FIX — Broad adapter/oracle static batch found seven stale tests that still
  expected legacy identity/runner-v2 work after the new broker STOP. They now
  assert the authorized invariant: registry, content/runtime measurement and
  executor remain untouched before broker authority. Rerun of w3-oracles plus
  production-adapter, excluding the opt-in real bridge, is `46/46` GREEN with
  no runner execution. This closes test-contract drift, not a product-runtime
  result.
- DONE — L66 broad static gates are GREEN: foundation validation `29/29` with
  evidence schema included, pilot contract checks GREEN with W5 correctly
  BLOCKED, lint/format-check over `97` files, adapter/w3-oracles `46/46`, focused
  runtime/schema/STOP `15/15`, receipt `28/28`, contracts `29/29`, canonical
  manifest verify and `git diff --check`. `make check` is deliberately NOT run
  because its runner/Node/TSX cases are forbidden after the final parity STOP;
  it receives no implicit credit. Static closure is durable, parity remains
  durable `0/15`, and L66 outcome remains `PARTIAL / STOP`.
- FACT — L0 independently rechecks the frozen static surface instead of relying
  on the writer handoff: exact collected roster is `90` (`contracts 29`, public
  oracle STOP 1, bridge L66 10, native evidence 28, adapter STOP 2, qualifier
  cleanup/STOP/nonclaim 20) and runs `90/90` GREEN on Python 3.13. Canonical
  manifest `--verify` independently exits 0; file SHA is
  `1efbde3a197a958c853af37f2b9236aa93ed78ede196d728cf1582437a665510`;
  qualifier raw SHA matches writer `b3c4a02c...1ca45`; off-limits runner and
  worker hashes remain exact L64 values `772baa27...ef5d` and
  `1fc139fe...13e`. Post-run owned-process census is zero (only the census
  shell/rg itself). This is static/pre-boundary evidence, not parity credit.
- STOP — Frozen-audit inspection invalidates the stronger “process-free static
  verify” wording above. `runtime/w3_native_evidence.py --emit/--verify` calls
  `_build_blocked_document -> _ast_census -> _run`, which launches the pinned
  Node binary to run `native_evidence_census.mjs`. It does not run the Metis
  runner, TSX comparator or parity canary, but it contradicts the L66 contract
  and tests claiming that future blocked-receipt verification cannot run Node.
  The prior `--verify` green remains evidence of deterministic recomputation,
  not evidence of a Node-free/static-only gate. L0 has opened a bounded
  tests-first rework; parity stays closed and no fourth attempt is authorized.
- FACT — L67 captures the exact tests-first RED without executing Node: the
  new blocked emit/verify guard permits only Git object-reader commands and
  intercepts the attempted command
  `/Users/tommasotessarolo/.hermes/node/bin/node .../native_evidence_census.mjs`
  before spawn. Exact selector is `0/1`; two additional pure-parser multiline
  import cases are `0/2` on the absent API. A no-write prototype already
  reproduces the registered source fixed point `32 files / 99 edges / 66`
  relative resolutions with zero row mismatch, so the bounded process-free
  rework is implementable without runner/TSX/canary or parity execution.
- FACT — Kimi K3 independently returns `REWORK` on the pre-L67 frozen bytes:
  it confirms the Node-in-verify blocker, requests mutation-specific rejection
  assertions for the `18+7` cleanup cases, a durable same-UID substitution
  canary instead of constants-only prose, and correction of the historical
  receipt mutation count from `19` to `20`. It also notes a deferred policy
  fixture mismatch in inherited L64 off-limits tests; production remains
  unreachable behind the broker STOP and L67 does not silently expand scope.
- FIX — L67 removes Node from blocked receipt emission and verification. A
  bounded pure-Python TypeScript import census reads only pinned Git objects,
  accepts the registered leading-static-import profile (including multiline
  inline comments), resolves the fixed point and retains exact denominators
  `32/99/66`. The guarded emit/verify test permits Git object-reader commands
  only and is GREEN without spawning Node/TSX/runner/canary. Cleanup mutation
  assertions now bind every case to its actual rejection reason and correct
  three misleading case names; a tmp-only three-role same-UID replacement
  canary proves held bytes differ from pathname bytes while preserving the
  explicit nonclaim. Combined focused roster is `31/31` GREEN.
- DONE — On formatted generator bytes, two fresh process-free blocked emits are
  byte-identical at `735078` bytes; new file SHA-256 is
  `a8f2464b189faf3740c5a0af39d7e018b76190b540c2115147b61babe58e5556`,
  generator SHA-256 is
  `bdcc216697f6ac9a19a8945dc62458b90262dc485a5eb9fee889b7057a5e43b2`,
  and internal manifest hash is
  `sha256:05b7435eb199c51d835a9619ebde2c72c9952774043ebfe2a055bb298506c2b2`.
  Both fresh outputs verify; canonical evidence suite is `31/31` GREEN. The
  manifest remains BLOCKED/false/expected15/durable0/credit-none and contains
  no console parity rows.
- FACT — Historical L66 bookkeeping is corrected without rewriting the prior
  RED event: the durable-evidence mutation parameter roster contains `20`, not
  `19`, distinct attacks. Its current evidence-file suite collects/runs
  `31/31`, including all `20/20` attacks plus deterministic emit/verify,
  nonclaims and static/synthetic boundary checks.
- DONE — L67 frozen safe-only gate collects and runs `103/103`: evidence `31`,
  contracts `29`, qualifier `23`, bridge `17`, public STOP `1`, adapter STOP
  `2`. No Node/TSX/runner/canary is spawned; Git subprocesses are used only as
  the explicit pinned-object reader and are asserted as the sole commands in
  emit/verify. Py-compile/Ruff/format are `6/6`, Draft 2020-12 schemas are
  `5/5` with manifest errors `0`, `git diff --check` is GREEN and final owned
  process census is zero. Frozen hashes: qualifier
  `e5fb9642d0c5367b923e31d3ee9a5c0e9ff4175df986b32630b039f4ccac1672`
  with bridge pin exact; bridge
  `5b8aa1a5d173d1f346553a77eff0caaf0086fcee7b9d875ef393d7bee9c8dfe6`.
  Fresh internal/Kimi/Qwen read-only audit is still required; parity remains
  durable `0/15` and outcome cannot exceed `PARTIAL / STOP`.

- DONE — L67 final synchronized re-freeze supersedes the historical hashes in
  the preceding L67 rows without rewriting them. The obsolete two-argument
  `_ast_census(metis_root, node_path)` call in unreachable legacy assembly is
  removed; every current census call uses the pure-Python one-argument API.
  Two process-free fresh emits are byte-identical and the canonical receipt
  verifies with file SHA-256
  `c2b852d923fb06ece6ebaacd5b706597095f9c10cb2504150f1d17009e39bb9a`,
  generator SHA-256
  `35da08596227b87b33246f98f1073d040f66f2debd4c8afc2b109637fa19a715`
  and internal manifest
  `sha256:a84ec4511009102f1c2cc23604a4147606e34030809537d1528fd49032f331f6`.
  Qualifier SHA-256 is
  `248549cf7dceab4a878daa3fae58bc7f39237c9fbea72344849c8c86d5ec4e26`
  with exact bridge pin; bridge SHA-256 is
  `b7faa38eee48e250e5a6a07cfad7c68cbba5d60db6667a186e18e907f5552ee0`.
  Receipt binding is exact `5/5` across qualifier, bridge and three schemas.
  The final safe-only gate reruns `103/103`; CLI verify, py-compile/Ruff/format
  `6/6`, schemas `5/5`, diff-check and owned-process census are GREEN. An
  independent frontier re-audit runs `34/34` and returns
  `ACCEPT STATIC-PARTIAL`, `P0=0 P1=0 P2=0`. Parity remains truthfully
  `blocked/available=false/expected=15/durable=0/credit=none`; no Node, TSX,
  runner, canary, `make check`, production promotion or L63 credit is claimed.
- DONE — Independent review convergence on the synchronized freeze: the
  frontier auditor returns `ACCEPT STATIC-PARTIAL` with `P0=0 P1=0 P2=0` after
  `34/34`; Kimi K3 independently rehashes and traces the full requested static
  surface and returns `ACCEPT STATIC-PARTIAL`, with no P0/P1 and only
  non-blocking hygiene notes. The historical-board note in that report is
  resolved by the append-only synchronized entry above. Qwen 3.8 Max is
  registered in `.orchestra/teams.json` and was used alongside Kimi; its final
  consistency adjudication returns `ACCEPT STATIC-PARTIAL`, `P0=0 P1=0`, and
  classifies only the already-declared durable parity `0/15` as P2/promotion
  debt. Qwen had no shell tool in its review runtime, so its result is explicitly
  a semantic consistency adjudication of the independently collected evidence,
  not a third file-hash audit. Final owned process census is zero.

- FACT — The user ratified O-010 as a lightweight-first maintenance policy.
  Five disjoint clean surfaces now encode `NO_RETRAIN -> DELTA_QLORA ->
  FULL_SUCCESSOR`: every Metis revision is pinned and impact-measured; retrieval
  plus the previous adapter is tried first; compatible residual drift receives
  only bounded delta QLoRA with oracle-clean data, stable replay and dev-only
  selection; prior benchmark, dataset and adapter identities remain immutable.
  Evidence: `docs/02-dataset-and-provenance.md`,
  `docs/03-evaluation-and-gates.md`, `docs/06-delivery-roadmap.md`,
  `docs/10-open-decisions.md`, `manifests/decision-register.json`.
- FACT — L68 preflight preserves exact HEAD
  `2d519d90be9eae0c562a10becbe2bc7e9ac4bbb0` plus the complete inherited dirty
  L66/L67 state; no product/runtime/schema/test byte was touched by the policy
  update. The local Orchestra bible was read. Network lesson sync was not run
  because this project's external-upload STOP takes precedence.
- FACT — Internal Orchestra reconnaissance closes `in=3 out=3 distinct=3
  gaps=0`: Luna recomputed scope/status and wrapper interfaces; Terra derived the
  minimal O-010 policy surfaces; Daybreak Blue independently threat-modeled the
  protected broker. L0 independently rechecked HEAD/status, the five-file diff,
  JSON parsing and `git diff --check` before external dispatch.
- FACT — Orchestra band preflight reports Qwen `22,661,610` measured weekly
  tokens across `16` runs and Kimi `0` measured by the current log source;
  neither team has a declared provider limit, so no quota percentage is
  invented. Both project pins remain verified in `.orchestra/teams.json`.
- OPEN — L68 is frozen in
  `orchestra/briefs/2026-08-23-model1-l68-protected-execution-broker.md` as a
  payload-free protected-broker architecture/tests wave. Phase A cannot create
  an OS user, load `launchd`, run Node/Metis, register authority, materialize
  payloads or train. Kimi and Qwen perform disjoint read-only master reviews on
  the shared activity blackboard before any Phase A product writer opens.
- FACT — L68 external Orchestra reviews are running concurrently through the
  repository-pinned wrapper and shared activity `model1-l68-fast-closure`:
  Kimi session `72558` owns governance/maintenance/fast-path/nonclaim review;
  Qwen session `60975` owns broker trust-boundary/protocol/lifecycle review.
  The internal `delivery_census_lead` frontier lane concurrently delegates and
  rechecks bounded W1/W2 mechanical censuses. All three lanes are read-only;
  product writes remain unopened until the two master reviews converge.
- DONE — Internal delivery census closes `in=2 out=2 distinct=2 gaps=0`.
  The frontier lead independently recomputed the Luna results: allocation is
  `30/30` distinct tasks across six families, closure is `30/30` with
  `201/201` sources but remains `computed_not_sealed` and one correlated
  leakage group, and all `201/201` assets remain local-only with
  `legal_review=not_performed`. W3 supports only F-1/F-2/F-3; F-4/F-5/F-6
  remain unimplemented. Fastest honest order is L68 Phase A plus human rights
  review, separately authorized Phase B, protected oracle receipts and W1 seal,
  then the F-4/F-5/F-6 semantic wave and real W3 data. No promotion claim.
- DONE — Kimi K3 master review closes `in=4 out=4 distinct=4 gaps=0`
  read-only at external activity artifact
  `artifacts/kimi-l68-maintenance-review-report.md`. It finds no O-010 STOP,
  confirms the lightweight ladder and nonclaims, and warns that the dead legacy
  adapter body must be replaced by receipt consumption rather than re-enabled.
  L0 independently recomputed `30` tasks, six families times five, `201`
  assets/sources, one leakage group, `legal_review=not_performed`, benchmark
  total `600` and minimum `563` independent groups. Kimi resume id is
  `session_27f2c29c-f04b-4370-a43f-73c9b65b5f96`.
- STOP — The original L68 one-UID target is internally inconsistent: if the
  broker and Node share one dedicated UID, DAC makes a broker-owned signing key
  reachable to the child and Seatbelt becomes the only barrier, contradicting
  the explicit key-unreachable stop rule. The defensible minimum is a non-root
  broker UID holding key/ledger, a distinct non-root runner UID, and a minimal
  root launcher/supervisor that accepts only the broker peer, selects only
  root-owned configured releases, irreversibly drops groups/GID/UID before Node,
  owns no signing API/key and returns on the original bound connection. L68
  product writing remains stopped until Qwen completes and L0 amends the brief,
  roster and exact denominator.
- DONE — Qwen 3.8 Max closes the external broker review read-only at
  in=4 out=4 distinct=4 gaps=0: 38 raw findings deduplicate to 33 distinct
  findings (P0=8 P1=18 P2=7), with no already-executed STOP. L0 independently
  rechecked the one-UID/key contradiction, the single consumer hit in the old
  brief, the two-fresh-process loop and the schema constants 2/10/5. Evidence:
  artifacts/qwen-l68-final-report.md in shared activity
  model1-l68-fast-closure; Qwen session 60975.
- FIX — The one-UID P0 and the other seven design P0s are absorbed in the
  re-frozen L68 brief. The corrected boundary uses _metisbroker, a distinct
  _metisrunner and a minimal root launcher with no signing/semantic API; every
  executable byte is installed in root-owned immutable ancestry, caller digests
  are claims only, the receipt signs all fields with full rosters, ledger
  durability precedes side effects/delivery and consumers pin sequence plus
  chain head. The writer roster is now exact 17 paths and the retired 48/48
  proposal is replaced by 73/73 including 10 launcher-contract cases. Phase A
  product writing is now open; Phase B remains separately privileged and
  unauthorized.
- DONE — Mechanical native-toolchain census closes in=6 out=6 distinct=6
  gaps=0: no existing C/C++/Rust build surface, Apple clang 21.0.0 is locally
  available, and Phase A may use syntax-only C validation while every compiled
  launcher binary remains outside Git and without authority.
- FACT — Corrected L68 pre-writer gate is green: decision-register JSON parses,
  `git diff --check` exits zero, `make validate` reports `29` passes and
  `0` errors across `155` files, and contract tests pass `29/29`. This is
  static/policy evidence only and does not change parity or production credit.
- FACT — Phase A writers are active concurrently with disjoint ownership on
  shared activity `model1-l68-phase-a`: Qwen session `63191` owns protocol,
  three schemas and exact `12` protocol tests; Kimi session `47821` owns the
  declarative installer, two plist templates, normative security spec and exact
  `6` installer tests. Neither lane may touch current production surfaces,
  execute Node/Metis, create identities/services/keys or perform privileged work.
- DONE — L0 launcher-source slice closes `10/10` Phase A contract cases:
  fixed bounded binary frame, exact peer UID/GID, no JSON/semantic/signing/path/
  argv/env/ancillary-FD surface, fixed installed paths, irreversible
  groups->GID->UID drop order, non-stdio FD closure, Phase-B fail-closed
  placeholder and clang syntax. Apple clang with
  `-Wall -Wextra -Wpedantic -Werror -fsyntax-only` is clean; focused pytest is
  `10 passed`, Ruff/format/diff-check green. No binary was produced and no
  launcher, child, Node or privileged operation ran.
- FIX — L68 ledger ordering is now exact: a durable global
  `attempt_sequence` is reserved before any side effect; the contiguous
  `receipt_sequence` and previous receipt head are assigned only after cleanup
  proof and atomic publication under the same single-writer lease. Crash recovery
  tombstones the attempt without allocating a receipt index, so consumers see no
  gap; a durable receipt is replayed byte-for-byte and never re-signed.
- FIX — Independent L0/Kimi-slice recheck keeps the installer declarative but
  removes principal substitution: Phase A plans now accept exactly
  `_metisbroker` and `_metisrunner`, not arbitrary distinct non-root names.
  Expanded per-leaf Node/loader/worker ancestry remains a Phase B acceptance
  obligation and cannot receive authority from the directory-level plan.
- DONE — Qwen protocol writer closes roster `5/5` and focused denominator
  `12/12`; L0 independently reruns pytest, three Draft 2020-12 schema checks,
  compile, Ruff/format and diff-check. Shared-board corrections are present in
  final bytes: separate attempt/receipt sequences, previous receipt head and
  authority-bound launcher hash. L0's adversarial follow-up also rejects dot
  roster segments and impossible `receipt_sequence > attempt_sequence`; both
  project and standalone Ruff gates are green.
- RISK — First independent Daybreak post-writer audit returns REWORK despite
  nominal protocol/lifecycle/client `61/61`: it reproduces caller-policy
  self-authorization, role/path substitution, ledger-leaf replacement with an
  orphaned consume, cross-attempt terminal-receipt wrapping, bool-as-int drift,
  a six-leaf completeness cap and consumer high-water reset after state-file
  deletion. Nominal green is explicitly not accepted as closure.
- FIX — L0 plus the lifecycle/client lanes close the original exploit family
  structurally: policy is authority-installed, role/path/digest bindings are
  exact, recovery cross-binds every attempt/receipt claim, bool integers are
  strict, ledger inode identity is checked through the locked transaction and a
  detected replacement poisons the broker instance. Lifecycle remains exactly
  `43/43`; protocol plus lifecycle is `55/55`.
- FIX — The second Daybreak P1 set is absorbed rather than waived: secure core
  defaults require a root-owned non-writable parent and pre-created broker-owned
  `0600` leaf; the explicit unprotected test mode has zero authority. The
  installed roster is now an extensible complete sorted superset of the six
  required role leaves, and release ancestry is domain-derived from release id
  plus the full roster. Consumer anti-rollback CAS-anchor implementation is in
  progress; Phase A remains REWORK until that lane and the repeated audit close.
- DONE — Daybreak independently replays the hardened storage and full-roster
  contracts and returns A=ACCEPT, B=ACCEPT for Phase-A design. Secure default
  rejects an euid-owned parent and a missing leaf before executor; replacement
  yields `LEDGER_REPLACED`, same-instance retry yields `LEDGER_POISONED`, calls
  stay exactly one. Extensible rosters validate above six rows, stale/add/omit/
  mutate/reorder/role-swap cases reject, and exact full pre/post is required.
  Focused lifecycle remains `43/43`; real-world roster completeness is correctly
  retained as Phase-B census evidence, not inferred from structure.
- DONE — Consumer lane closes C structurally with an initialize-once canonical
  anchor and `load_required` plus monotonic compare-and-swap before success.
  Missing/deleted state, second initialization, stale CAS, instance/revision/
  head rollback, bool integers and a barrier-forced two-consumer race are
  covered inside the exact client `6/6`; public E2E remains exactly `2/2`.
  Only `UnprotectedTestAnchorStore` exists in Phase A and its documentation and
  signed receipt nonclaims grant zero authority.
- FACT — L0 independently collects the exact Phase-A denominator
  `12+43+6+2+10=73` and reruns `73/73`. Three broker schemas validate `3/3`,
  contract tests pass `29/29`, foundation reports `29` passes/`0` errors,
  Python compile, Ruff, format, clang syntax for both compile-time branches and
  `git diff --check` are green. Final Daybreak anchor/exploit replay remains the
  only Phase-A acceptance gate still running.

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

- DONE — Final Daybreak C/exploit replay accepts L68 Phase A only as
  `BROKER_DESIGN_ACCEPTED_PAYLOAD_FREE`: P0=0, P1=0, P2=0; exact focused
  denominator `12+43+6+2+10=73/73`, original-exploit spot checks `7/7`, and
  reviewer roster `in=17 out=17 distinct=17 gaps=0`. Schema, Python, Ruff,
  format, clang and diff gates are green. No production, privilege, Node/Metis,
  model/data or training credit follows.
- RISK — `UnprotectedTestAnchorStore` remains intentionally process-local and
  zero-authority: a fresh object can accept a manually restored old test file.
  Signed synthetic nonclaims and hard-denied production verification prevent
  Phase-A authority; a protected initialize-once CAS/anti-rollback store is an
  explicit Phase-B acceptance obligation.
- FACT — Read-only closure census reproduces tasks `30/30` across six families,
  sources/assets `201/201` and `gaps=0`, but the slice is
  `computed_not_sealed`, every asset is internal/local-only with legal review
  not performed, task-specific oracles are unexecuted, and the corpus has only
  one correlated leakage group versus the minimum 563 population-claim groups.
- OPEN — Immediate unprivileged work is the W1/W2 evidence package: exact
  30-task blocker map, 201-asset rights dossier, typed/oracle specifications and
  F-4/F-5/F-6 evidence plan. Phase B OS installation, real W3 data/model work
  and training each require their own explicit authorization.
- FACT — L69 opens only the safe local evidence-package wave. Three internal
  frontier-led read-only lanes own the 30-task blocker census, 201-asset
  rights/provenance dossier and F-4/F-5/F-6 typed-oracle gap. Kimi K3 and Qwen
  3.8 Max run concurrently as external masters on shared activity
  `model1-l69-evidence-package`, each required to delegate, validate and report
  arithmetic before L0 opens any tracked writer roster.
- DONE — Internal read-only census converges on tasks `30/30`, assets
  `201/201`, raw dependency categories `10`, executed task evidence `0/30`,
  F-4/F-5/F-6 `0/15` tasks and `0/75` oracle cells. L0 rejects the first
  F-4/F-5/F-6 report's ambiguous gaps arithmetic and accepts only the corrected
  task/cell denominators; future protected role receipts are a target
  `25=10+10+5`, not current evidence.
- DONE — Kimi K3 frontier master delegates three units and validates blocker,
  rights and gate inventories at `30/30`, `201/201` and `45/45`, then returns
  `ACCEPT_PACKAGE_DESIGN`. Its dominant P0s remain external evidence debt:
  protected receipts `0/30`, leakage group `1<563`, and legal review `0/201`.
- FIX — Two disjoint lower-cost writers create immutable-input sidecars rather
  than rewriting the stale allocation plan. L0 rejects nominal first greens:
  W1 originally assigned runtime tags by row index, and W2 did not compare every
  identity field. Corrected W1 derives exact per-task dependencies; corrected W2
  binds both asset-register canonical hash and file-byte SHA-256. L0 reruns
  focused `17/17`, schema `2/2`, compile, Ruff, format and diff gates green.
- FACT — W1 blocker sidecar is exact `30/30`, raw dependency histogram `10/10`,
  assets `201/201`, one correlated group, every task blocked and every evidence
  reference empty. W2 rights dossier is exact `201/201`, reviewed/approved/
  excluded `0/0/0`, pending `201`, with no license, rightsholder or evidence
  invented. Neither sidecar grants a seal.
- OPEN — Frontier-led seal-package lane is generating the four remaining
  fail-closed manifests: zero-execution oracle roster, honest one-group leakage
  assignment, six-family held-out map and an obligatorily unsealed benchmark
  seal. Qwen F-4/F-5/F-6 external review remains active.
- RISK — Qwen 3.8 Max inspected and delegated the F-4/F-5/F-6 surface, posting
  grounded facts for the `15` blob identities and the current typed-oracle gap,
  but its provider quota exhausted before either delegated artifact or a final
  verdict landed. No Qwen acceptance credit is claimed; the partial journal and
  session log remain durable in shared activity `model1-l69-evidence-package`.
- FIX — L0 rejects the first seal handoff until all closure/asset distinct
  denominators are recomputed, blocker and rights validators are transitively
  enforced, Accuracy-99 is pinned to `600/563/O-003`, and the ambiguous group
  counter is renamed. The hardened seal suite then passes `14/14`; leakage and
  seal hashes are `05918e...5743` and `139694...28cf`.
- DONE — L69 local evidence package is accepted only as **UNSEALED**. Six
  schema/manifest pairs are bound into foundation and replayed semantically;
  L0 reruns focused `61/61`, foundation `36` passes/`0` errors, Ruff, format,
  compile and diff gates green. Current truth remains tasks `30/30`, assets
  `201/201`, oracle cells `0/160`, F-4/F-5/F-6 cells `0/75`, legal review
  `0/201`, leakage `1<563`, future protected-role target `0/25`, and
  `seal_eligible=false`. No Node, privilege, model payload, training or
  promotion credit follows.
- OPEN — The immediate critical-path gate is separately authorized L68 Phase B
  for protected OS principals, launcher, signing key and consumer CAS anchor,
  followed by public-synthetic `3/3` candidates and `5/5` executions. Data/legal
  review and any later training remain separate authorizations.
- STOP — Read-only Phase-B preflight proves privileged execution is premature:
  the host is clean/compatible, but the repository is not installable. The C
  launcher still returns `ENOTSUP` and has no accept loop; the broker is
  synthetic-only with no daemon/real signer; the client denies Ed25519 and has
  only an unprotected test anchor; the installer is plan-only; no host-evidence
  harness exists. Explicit privilege alone cannot cure missing product code.
- FACT — Host preflight observes service identities `0/4`, planned install tree
  `0/13`, ledger/key `0/2`, launchd services `0/2`, sockets `0/2`; SIP,
  Gatekeeper, clang 21, SDK and sandbox-exec are available. Evidence preflight
  freezes Phase-B targets at host predicates `0/28` (14 positive+negative),
  fresh runs `0/2`, candidates per run `0/3`, roles per run `0/5` and physical
  executions `0/10`. No sudo, binary build, Node/Metis or host mutation ran.
- OPEN — L70 must first implement an unprivileged tests-first Phase-B package:
  distinct protected-public-synthetic evidence mode, real launcher/daemon,
  Ed25519 sign+verify, protected anchor CAS, operational installer/rollback and
  normalized host-evidence report. Privileged authorization will be requested
  only after those bytes and adversarial gates are accepted.
- DONE — L70 frontier architect delegates one lower-cost dependency census,
  validates Phase A `12+10+43+6+2=73/73`, and freezes a five-principal/
  three-service boundary. `_metisanchor` owns only an append-only verified
  receipt head; it cannot read the private key, broker ledger, payloads or run
  Node. `protected-public-synthetic` is distinct from both synthetic and
  production and carries exact no-production/no-semantic/W5 nonclaims.
- FACT — Local uv cache contains a compatible `cryptography` wheel, so L70 may
  pin and resolve it strictly offline. Any network fallback is a STOP. The new
  local acceptance denominator is `12 crypto + 10 framing + 10 broker + 8
  anchor + 10 installer/evidence = 50/50`, kept separate from Phase A `73/73`.
- OPEN — L70.1 protocol/crypto frontier writer owns only protocol, Ed25519,
  authority/receipt schemas, dependency lock and exact crypto tests. Native,
  broker and anchor writers remain closed until the serial crypto seam passes.
- DONE — L70.1 crypto is accepted after independent L0 replay: the lower-cost
  KAT/schema census closes `in=7 out=7 distinct=7 gaps=0`; Phase-A protocol
  `12/12` plus new Ed25519/KAT/mutation/key/mode cases `12/12` give
  `in=24 out=24 distinct=24 gaps=0`. `cryptography==47.0.0` resolves, syncs and
  imports strictly offline from the cached macOS wheel bound in `uv.lock`;
  authority/receipt schemas are `2/2`, and Ruff, format, compile and diff gates
  are green. Production verification remains explicitly unavailable and no
  real key, host, privilege, Node/Metis or Phase-B evidence credit exists.
- OPEN — L70.2 begins with disjoint frontier-led teams. Native owns only the C
  launcher, fixed-target FD-3 shim, launcher plist and its new operational
  `10/10`; broker performs a delegated read-only service/transport census
  before its isolated writer mandate. Anchor remains closed until its own
  delegated prewrite can run without displacing an active validation team.
- DONE — L70.2 three-team delivery is locally replayed by L0: native closes
  operational `10/10` plus prior static `10/10`; broker closes service `10/10`
  plus protocol `12/12`, crypto `12/12` and public E2E `2/2`; anchor closes
  exact `8/8` plus client/E2E compatibility `8/8`. Both launcher branches and
  all three shim variants compile with `-Werror`; focused lint, format, plist,
  schema, compile and diff gates are green. These are simulated local contracts,
  not installed-service or Phase-B host evidence.
- RISK — L0 adversarial integration review rejects a premature L70.2 seal:
  anchor FD 3 does not yet validate exact AF_UNIX/stream/path or peer UID/GID;
  the anchor plist lacks socket owner/group and its service logs share a state
  path whose ownership is not yet reconciled. The legacy lifecycle denominator
  remains honestly `42/43` because its planner still names the pre-shim broker
  program. All are mandatory L70.3 integration debts.
- STOP — Independent replay confirms a runnable-contract P0 across the nominally
  disjoint native/broker lanes. The launcher fixes `node --import loader
  runner.ts` and forwards the protected-broker request bytes, while the actual
  runner requires the experimental-loader argv contract, roughly twenty fixed
  identity flags and an oracle-request stdin shape. The real child would exit
  before Metis execution. L70.3 writer scope must therefore include a fixed,
  authority-bound payload adapter and launcher/runner argv compatibility plus
  an execution-free real-contract test; planner/evidence work alone cannot earn
  `PHASE_B_INSTALLABLE_UNEXECUTED`.
- STOP — The same cross-lane replay finds two further false-evidence paths.
  First, receipts bind distinct `worker` and `runner` roles although the current
  native path executes only Node/loader/runner and service tests inject an
  unobserved worker digest; L70.3 freezes `worker` as the measured broker-side
  payload/result/publication adapter. Second, temp cleanup reopens a
  runner-writable `runs/active` pathname after execution, allowing rename/swap
  to forge `TEMP_ZERO`; the parent must be root-owned and the launcher must hold
  and reverify the exact pre-fork leaf dirfd/inode.
- RISK — Protected-anchor availability is not restart-safe yet. A response lost
  after durable ADVANCE is returned as idempotent by the service but rejected by
  the stale client cache, and a fresh genesis cache cannot recover an advanced
  head. The ADVANCE-only boundary stays frozen: L70.3 must verify and replay the
  complete retained public signed-receipt journal locally, prove its derived
  head through exact idempotent ADVANCE, and fail closed on truncation, rollback,
  mutation, gap or fork.
- FACT — An anchor delegate ran the repository-wide `make check` outside the L70
  mandate. Its `894 passed, 103 failed, 1 skipped` result receives zero gate
  credit and does not authorize Node, production, installation or host claims;
  L0 will not repeat that command while the active STOP remains.
- OPEN — L70.3 frontier integration begins read-only with a delegated bounded
  installer/evidence census. Writing stays closed until L0 accepts the exact
  ten-case roster, disjoint ownership, dry-run/apply digest guard, transactional
  journal/rollback, frozen bundle/runtime binding and separate future-host
  denominators `28/2/3/5/10`.
- OPEN — L70.3 correction wave is now split into disjoint frontier-owned native,
  anchor and integration surfaces. Native repairs real runner argv, native ID
  binding and dirfd temp census; anchor repairs listener/peer and retry/recovery;
  integration owns the broker worker, installer/executor, bundle and evidence
  harness after consuming the two published interfaces. Final bundle hashing is
  serial and cannot precede both upstream L0 replays.
- DONE — L70.3 protected-anchor correction is independently accepted:
  `in=5 out=5 distinct=5 gaps=0`, focused anchor/client/public-E2E `16/16`,
  and adversarial lost-response plus fresh-restart/journal replay `8/8`. The
  service now binds the exact FD-3 Unix-stream path and caller `501/20`, the
  launchd socket declares `501/20/0600`, and restart recovery derives and proves
  the signed public-journal head while rejecting empty, torn, rollback, gap,
  fork and mutation cases. This is local execution-free evidence only: host,
  install, service and production credit remain `0`.
- STOP — L0 and the independent native audit found three further install-time
  false greens before freeze. The launcher passed a parameterized Seatbelt
  profile through `-f` without parameter bindings; the two socket shims
  directly executed ambient/non-importable Python source; and the generic
  installer backend could mark every step complete with an empty command map.
  L70.3 now requires a concrete hash-verified policy, two distinct shim
  artifacts invoking the pinned Python/site-packages closure, and a complete
  fixed command/postcondition roster before authority registration.
- FACT — The stable installed release pathname is frozen independently of all
  content hashes as
  `/Library/Application Support/MetisModel1/releases/w3-public-synthetic-v1`.
  Bundle, release-ancestry, semantic-policy and concrete-policy digests remain
  distinct identities and never name that directory. The runs parent is
  root:wheel `0711`; only its `active` leaf is runner-owned `0700`.
- STOP — Host identity replay observed UID `501` as account
  `tommasotessarolo`, primary GID `20` (`staff`), not the planner's fictional
  OS account `caller`. The logical caller role must be separated from or bound
  to the observed account name; no installable verdict may depend on an
  impossible name/UID precondition.
- RISK — Native adversarial replay found a root-side PID/PGID reuse window:
  the launcher reaped its group leader and then killed/censused the released
  numeric PGID, which could target an unrelated newly reused process group.
  The leader identity must remain retained until a bounded Darwin group census
  proves only the terminal leader remains; reaping is the last operation and
  no subsequent numeric-PGID action is allowed.
- STOP — The first pinned-site-packages layout exposed a wrong installed import
  calculation in `w3_broker_client.py`: `parents[2]` resolves above
  `site-packages`, so the anchor module could not load the sibling `runtime`
  protocol under `python -I -B -m`. The client now needs a fixed package import
  plus client/anchor/E2E replay before the two service entrypoints are runnable.
- STOP — L70 integration found that a frozen pre-install bundle cannot honestly
  contain `authority.release_identity.ancestry_root_sha256`: the protocol binds
  that digest to the measured installed-code roster, including target `dev` and
  `ino`, which do not exist before installation. Treating a source or staging
  hash as runtime ancestry would be false evidence.
- FIX — L0 ratifies two non-interchangeable identities. The frozen bundle and
  install plan bind `release_content_roster_sha256`, computed over the canonical
  expected installed projection without `dev`/`ino`. Only after installation
  may the fixed backend measure the complete installed roster, verify its
  content projection, derive `release_ancestry_hash`, construct the authority,
  and register it as the final step. Runtime ancestry receives no not-run or
  pre-install credit.
- STOP — L0 replay of the first installed-import correction failed during
  collection: console-script pytest exposes the editable `/src` package but
  not the repository-root `runtime` namespace, so unconditional
  `from runtime import w3_broker_protocol` raises `ModuleNotFoundError` before
  the 6+8+2 client/anchor/E2E roster runs. The accepted cure is a fixed installed
  import plus an explicitly source-tree-only fallback that can never walk above
  an installed `site-packages`; both layouts require direct tests.
- DONE — L70.3 native correction is independently accepted on frozen bytes:
  launcher source `a992adb3dfaff865dd741e69a85835a6f25dc12da7bf320821cd24ccd8197cf7`
  (`69509` bytes), shared shim source
  `be43112ea26b46499a69051664fc23bba98801b576b6266ae0728876e7487c5c`
  (`5363` bytes), and exact-ten test
  `398c1e8e05734adc9753404fdf4bfb188b55bae327001641cf36bdb78c1a2e27`
  (`50615` bytes). Writer stress is `60/60`; L0 and adversarial replay are
  exact `20/20`, launcher clang A/B `2/2`, two shim variants `2/2`, with
  `P0=0 P1=0 P2=0`.
- FIX — The accepted cleanup retains the leader with `waitid(..., WNOWAIT)`,
  uses bounded byte-validated `proc_listpids(PROC_PGRP_ONLY, ...)` census,
  signals only while identity is retained, and reaps last with no subsequent
  numeric PID/PGID operation. A non-established group takes a PID-only retained
  path. The harness covers singleton, extra-member termination, `ECHILD`,
  misaligned/full/zero census and post-reap reuse attempts. Native host credit
  remains `0` until the separately authorized privileged wave.
- STOP — L70 evidence adversarial replay constructed a wholly invented
  `complete` host document that the first validator accepted. Predicate and
  census hashes had no loaded path/size/kind preimages, receipts were neither
  parsed nor signature/chain/cross-binding checked, and the same census hashes
  could be reused across all ten claimed executions. The initial `not-run`
  document also combined zero observations with `gaps=0`. Complete host credit
  now requires loaded canonical evidence artifacts and independently recomputed
  receipt, authority, run, role, execution and census bindings; not-run cannot
  claim zero gaps.
- STOP — The first frozen-bundle validator compared the declared Python and
  Node source-census digest to a pin without recomputing that pin from the
  census entries. Arbitrary stdlib or node-module entries could therefore keep
  the published file/byte denominators and self-consistent outer rosters while
  retaining an unrelated pinned scalar. The exact external roster preimage or
  its canonical entries must be loaded and recomputed; counts and representative
  artifact roles alone do not ground the runtime closure.
- STOP — The first concrete backend still could not start the installed stack:
  the anchor's mandatory installed config had no bundle role or writer, the
  three plist log parents were not materialized with exact metadata, and the
  authority roster collapsed the full executable/import closure to seven
  selected leaves. The cure must build one postinstall authority candidate from
  the complete measured closure, derive both service configs from that same
  candidate, and keep services inactive/fail-closed until one authority-last
  activation marker is published.
- STOP — Macro-step journaling left an authority-last crash window. The backend
  could create and fsync the active authority, then crash before `step-complete`
  recorded its ownership receipt; recovery would correctly refuse destructive
  withdrawal of the now-ambiguous leaf, leaving authority active after a failed
  transaction. Irreversible micro-effects require durable ownership records;
  authority must be prepared inactive and activation-intent journaled before an
  exact final CAS/rename that recovery can identify and withdraw.
- STOP — The current concrete executor cannot bootstrap a fresh host: the
  transition journal opens an already-existing parent and leaf before entering
  the plan, while `precreate-install-journal` is itself a later plan operation.
  L70.3 needs an explicit no-clobber, inode-bound journal bootstrap whose first
  durable transaction record precedes every other host effect.
- STOP — The concrete backend still permits destructive preimage drift before
  ownership exists: `/usr/bin/install -d` can remodel an existing directory and
  `/usr/bin/install source target` can overwrite an existing leaf. The whole
  managed target set must pass a root-to-leaf no-follow conflict preflight, and
  fresh leaves must use exclusive/no-replace creation with exact postchecks.
- STOP — Python and Node source censuses are recomputed but are not yet the same
  byte-for-byte closure installed from `STAGED_INSTALL_TREE`; a genuine census
  can accompany a mutated staged module. Every external-census row must map to
  its exact staged-install and installed row, and the allowed closure must reject
  extra paths even beneath the broad Python and release roots.
- STOP — The exported recovery seam can return `already-complete` from the
  journal alone. Only the fixed production entrypoint may emit host-attesting
  status, after reconstructing the exact backend from the fixed frozen bundle
  and remeasuring the active authority and complete installed postconditions.
- DONE — L70 anchor activation is independently accepted on frozen bytes:
  service `667c3e52856b446690c4c3231352e900e7821df8886bb1194b72884e991a9775`,
  exact-eight test `7c3a79f956e27815cf758312a8809f150c0416c4b1f912b091fa9c16875b2641`,
  and schema `8306667176ccec6ca089a7aa782f5e74b403fc5bf1818f4f21481c62891f61b7`.
  Writer and L0 replay are anchor `8/8`, combined client/anchor/E2E `16/16`,
  config fields `13/13 distinct=13 gaps=0`, with Ruff, format, compile and
  Draft 2020-12 schema checks green. Missing, swapped, forged or registry-
  unbound active authority fails before service construction; host credit is `0`.
- STOP — `verify-no-extra-missing-or-symlink` currently verifies only declared
  target rows, not the live directory contents. An undeclared `sitecustomize.py`
  or `.pth` in a reused Python tree remains invisible and can execute because
  isolated Python still imports `site`; every managed live closure therefore
  needs an exact-set census that rejects extra, missing and symlink entries.
- FIX — L0 keeps future updates compatible with O-010: project-module digests
  belong to the frozen complete source/install roster, whose exact
  `bundle_sha256` is supplied as explicit CLI consent, included in the plan and
  recomputed from staging and live bytes. They are not duplicated as installer
  source constants. Hard constants remain limited to toolchain/runtime and
  dependency provenance; a legitimate new project bundle necessarily produces
  a new digest and new operator consent, while same-plan substitution must fail.
- STOP — The full authority roster correction exposed a runnable cross-lane
  mismatch: the installer now emits more than the seven named role/policy rows,
  but the installed broker's default `InstalledRosterProbe` still maps only
  those seven. Its exact-set guard therefore raises `ROSTER_PATH_MAP_MISMATCH`
  before the first real job. The root-owned broker config needs the complete
  deterministic logical-to-absolute map and a non-role pre/post replay test.
- STOP — Operation-level journal events have been introduced, but recovery on
  the current cut still reconstructs only macro step starts/completions. A crash
  after an identity, file, service or authority effect therefore cannot adopt
  the exact postimage or roll it back. Recovery must consume operation intents
  and receipts for each mutating class; authority activation additionally needs
  exact CAS-intent reconciliation.
- STOP — The post-install verifier currently validates only metadata for the
  broker ledger and public receipt journal. Byte corruption or truncation with
  unchanged ownership and mode can therefore preserve an `already-complete`
  result while the next broker/public replay fails. Final attestation must parse
  and cross-bind the ledger, receipt chain and anchor heads without repairing
  them; stat-clean evidence is not semantic evidence.
- STOP — Rollback itself is still one macro effect between `rollback-start` and
  `rollback-complete`. A crash after unlink, bootout, archive, key move, rmdir or
  identity deletion causes the next recovery to repeat a non-idempotent action
  and can permanently end in `recovery-failed`. Rollback needs durable
  operation-level intent/receipt/reconciliation or exact-state idempotency, with
  crash-boundary tests for every mutating class.
- STOP — No root-trusted Phase-B entrypoint exists yet. Invoking
  `w3_broker_executor.py` through `sudo`, `python -m` or its `/usr/bin/env`
  shebang executes repository-controlled Python imports before any plan, bundle,
  interpreter or import-closure check. The privileged wave therefore needs a
  minimal fixed native bootstrap and a two-stage root-owned/no-replace
  installation boundary that verifies the consented bootstrap and staged
  closure before an isolated fixed-argv CPython exec; repository poison,
  `PATH`, `PYTHONPATH` and CWD must be non-authoritative.
- STOP — A clean rollback is not currently retryable. Preflight demands absent
  ledger, public journal, anchor log, public-key registry, anchor config and
  authority candidate, while rollback deliberately retains the journals and
  leaves several prepared files in place. Transaction two therefore fails even
  without a crash. Retry must adopt only exact empty/genesis retained journals
  and receipt-bind archive/version/cleanup of prepared registry, config and
  candidate state; a fresh-retry replay is mandatory.
- FIX — L0 chooses the minimal honest evidence boundary for the unprivileged
  wave: the repository manifest stays `not-run`, and the fixed production
  loader must categorically reject `complete` host evidence until a separately
  authorized Phase-B wave supplies the obligation-specific 28-probe collector
  and verifier. A fully grounded local fixture may exercise artifact, crypto,
  roster and cleanup validation only through an explicitly unprotected,
  non-attesting API; generic `passed=true` rows earn no host credit.
- DONE — The fail-closed host-evidence package is accepted for the unprivileged
  wave on frozen bytes: runtime
  `493dfb400eeb418a3934b0c44b4d1da6fe7a33c6f8687c1a99b3aa039b97e026`,
  schema `3f61b4e3ce31886b9b022949095bd508668b9c3b8ac0af7fcc1199a5aa81910a`,
  manifest `2dc33068548241c622061fb3bfe376fdd8249d61238bc9a3be996409d3480cf1`
  and exact-eight test
  `9d7f5e4adeeff55207cd9ba657c056838fa3a9b0d5c694a675fca464be0f7769`.
  Writer and L0 replay are `8/8`, collect `8/8`, skip `0`, schema/manifest
  `1/1`, with Ruff, format, compile and diff checks green. L0 independently
  recounts source status `not-run`, artifacts/predicates/runs `0/0/0`, all five
  observed counters zero and `gaps=null`. Production `complete` is stable-denied;
  the 139-artifact complete fixture is explicitly non-attesting, so host credit
  remains `0`. Independent adversarial replay preserves all four hashes and
  returns `P0=0 P1=0 P2=0`, with `in=4 out=4 distinct=4 gaps=0`.
- FIX — Live macOS inspection confirms `/var -> private/var`; a component-wise
  `O_NOFOLLOW` bootstrap cannot truthfully claim symlink-free ancestry through
  `/var`. L0 therefore freezes the physical trust paths under
  `/private/var/db/MetisModel1` for bootstrap, descriptor, staging and install
  journal, with the untrusted source at
  `/private/var/tmp/MetisModel1-w3-phase-b-source`. No alias exception is
  permitted. The already frozen `/var/run` socket pathname is a separate
  sockaddr contract and is not traversed by this staging resolver.
- OPEN — The later privileged host gate still has one bounded P1: a SIGKILL
  between publication-temp creation and link/unlink can leave the deterministic
  broker-owned `.<attempt>-<request>.json.tmp`. Broker restart tombstones the
  pending attempt but does not yet reconcile this publication substate. This
  does not clobber a final output and does not block the pristine
  installable-unexecuted package because production `complete` is hard-denied;
  it does block the future
  `ledger-chain-cleanup-publication-crash-replay` host predicate. The host wave
  must reconcile the one ledger-bound temp under the single-writer lock and
  fail closed on unknown temps before any attestation.
- STOP — The first complete native Stage-0 cut creates the fixed closed-bundle
  target with `O_EXCL` and deliberately retains it on copy failure, but has no
  digest-bound partial ownership/recovery state and no accept-existing exact
  path. A SIGKILL during the pre-journal copy therefore makes every retry fail,
  while even a fully successful first invocation prevents a second invocation
  from reaching the Python install journal's `already-complete` replay. L70
  cannot seal the bootstrap until a native crash-boundary harness proves safe
  partial recovery, exact-complete remeasurement and double invocation without
  accepting unknown files, symlinks or mismatched descriptor state.
- STOP — `PHASE_B_INSTALLABLE_UNEXECUTED` also requires provenance for the
  native Stage-0 bytes, not a handwritten binary digest. The current manifest
  contract names bootstrap source and binary size/hash but has no exact compiler
  identity, SDK/deployment target, flags or build recipe, and no production
  bootstrap byte has been materialized even temporarily. After the retry-safe C
  source freezes, L0 must build it outside Git under a closed recipe at least
  twice, prove byte-for-byte reproducibility, and cross-bind the measured binary
  hash into the descriptor and frozen bundle. Syntax-clean source alone cannot
  close the installable gate.
- OPEN — The current Stage-0 main verifies only effective UID/GID zero before
  the fixed Python exec. Real/saved IDs, supplementary groups and inherited
  signal mask/dispositions are not normalized. Because the bootstrap is not
  setuid this is not a non-root escalation, but inherited `SIGCHLD` or blocked
  signals can alter subprocess wait/failure semantics and undeclared groups
  violate the sterile-entry claim. Treat as P1 hardening until the frozen
  source either resets and rechecks this process state with an inherited-state
  harness or proves the state non-authoritative end to end.
- STOP — Current rollback leaf handling still contains two pathname swap
  windows. `_quarantine_seed` checks an ownership receipt and later reopens the
  path for metadata mutation without re-binding its inode; the archive helper
  validates/reads, closes, then unlinks by pathname. An exact-content replacement
  can therefore be quarantined or deleted instead of the journal-owned preimage.
  The installer gate remains unaccepted until both operations retain parent and
  leaf descriptors, compare receipt/dev/ino and postnamed identity immediately
  before mutation, use `unlinkat` on the held parent, fsync, and replay the swap
  exploit in the exact-ten suite.
- STOP — Launchd recovery currently treats any present target label as an
  installer-owned completed bootstrap. The operation intent binds only a label
  and `absent` precondition; a foreign bootstrap between the check and command
  can make apply fail `PREEXISTS`, after which recovery adopts that job and
  rollback may boot it out. Presence plus a measured plist pathname is not an
  ownership receipt for the loaded job. Each service intent/reconciliation must
  bind the exact plist/job semantics and a transaction-correlated root-owned
  claim (or fail ambiguous without bootout), recheck absence immediately before
  bootstrap, and replay the preloaded-label race before installer credit.
- DONE — The native Stage-0 source is frozen and independently accepted at
  SHA-256
  `66e686da506dfb67c6652c7cbd5952095d9867a0230d99542f96a2cebe0f7a31`,
  size `79144`. L0 and the adversarial auditor independently replay the
  `22314`-byte harness
  `1ac1d30abd004b895be3a2588e9d80d8d2bb2d9d397f3bf31a891e0c30f77c57`:
  standard `9/9` twice plus ASan/UBSan `9/9`, with
  `in=9 out=9 distinct=9 gaps=0`. The frozen C rejects and leaves untouched
  stale/unknown candidate siblings, recovers only the digest-owned locked
  candidate, publishes with exclusive rename, remeasures an existing fixed
  target, survives the declared crash boundaries and double invocation, and
  normalizes the tested inherited process state. Independent frozen-scope
  verdict is `P0=0 P1=0 P2=0`; no binary was executed as Stage-0 and no host,
  install or production credit follows.
- OPEN — Clearing `environ` at C `main` cannot authenticate the dynamic loader
  activity that precedes `main` for a custom Mach-O. The frozen install contract
  must therefore require a trusted administrative invocation whose environment
  is scrubbed before Stage-0 is execed (for example the exact protected
  `sudo -> /usr/bin/env -i -> Stage-0` chain), while the C cleanup remains
  defense in depth. This is an explicit host-boundary/nonclaim, not a C cure;
  the manifest, brief and docs must bind it before bundle acceptance.
- FIX — L0 performs the authorized bounded production-form build twice outside
  Git and does not execute or install either Mach-O. The frozen source builds
  byte-identically under the declared Apple clang/SDK/flags/environment recipe:
  both outputs are arm64, size `54232`, contain no `LC_UUID`, compare equal and
  hash
  `ddd09fcffc5e8a38ab0f140fce640e66b9020b2654e398a2268a77fd787a8447`.
  Compiler, linker, SDK settings, resolved libSystem interface, CommonDigest
  header and C-source hashes are unchanged before/after. This closes byte
  reproducibility only; bundle/plan/descriptor cross-binding and independent
  audit remain required, and the binaries earn no runtime or host credit.
- STOP — The current release-specific provenance validator pins the toolchain
  recipe but accepts arbitrary replacement Stage-0 source and binary sizes and
  hashes when an attacker makes the two build hashes self-consistent and
  recomputes `bundle_sha256`. An independent in-memory replay is accepted with
  fake size `999`. The frozen schema and Python validator must pin the accepted
  C source `66e686da…/79144` and Mach-O `ddd09fcf…/54232` (or one equivalent
  immutable release-provenance digest) and reject the rehashed replacement
  before manifest credit.
- STOP — Launchd package identity is still underconstrained. The current reader
  checks label, nonempty generic `ProgramArguments` and a package marker but
  does not enforce each role's fixed executable, identity, socket ownership and
  mode, logs, lifecycle policy or exact key set. Because artifact digests can be
  recomputed, a re-frozen `/bin/sh` or wrong-socket plist can match its own
  receipt. A single exact per-role semantic validator must run on staged bytes
  before effects and on installed bytes before bootstrap/reconciliation, with
  mutation replay; the own-success/crash recovery case remains part of the
  same P0 gate.
- STOP — The frozen bundle's raw dependency-wheel preimage denominator is
  `in=3 out=0 distinct=0 gaps=3`. Existing offline uv/pip caches retain all
  three pinned filenames/hashes and expanded archive trees, but not the raw
  `.whl` bytes: cryptography 47.0.0 (`160ad728…`), cffi 2.0.0
  (`45d5e886…`) and pycparser 3.0 (`b7274141…`). Declared lock sizes and cache
  metadata are not same-FD measurements and expanded directories cannot prove
  raw wheel hashes. L0 refuses a `materialized=false` claim reduction and the
  active brief forbids network access, so no frozen manifest/descriptor may be
  synthesized. A later explicit exact-three public fetch mandate must retrieve,
  same-FD hash and close these preimages; no model/data payload is involved.
- STOP — The resolved admin runbook currently authenticates only descriptor
  header hashes, not the descriptor `FILE` roster against the frozen manifest.
  An independent in-memory exploit supplies correct manifest/plan header hashes
  but arbitrary fixed Python/executor FILE hashes and still obtains
  `status=frozen`; Stage-0 would execute those root-selected bytes before the
  Python executor can validate the bundle. Descriptor generation and validation
  must use one exact projection of every manifest `source_roster` row plus only
  canonical raw manifest/plan metadata, with derived modes, exact count/bytes
  and explicit Python/executor cross-binding. Omission, extra, hash and mode
  mutations must fail before any runbook can be frozen.
- STOP — The first integration freeze closes bootstrap/recovery identity but
  final and `already-complete` service verification regresses to substring-only
  `state = running` plus `pid =`. A foreign job can replace an exactly loaded
  label with different path/program/argv/package marker and still pass final
  postconditions. All three services must be accepted from one structurally
  parsed `launchctl print` that simultaneously matches the exact installed
  semantic identity, package discriminator, `running` state and positive PID;
  both initial-final and already-complete replacement replays are mandatory.
- OPEN — The same frozen integration cut passes semantic tests but not the
  repository lint/format gate: `ruff check .` reports `573` issues across six
  new W3 files (`562` line-length plus bounded import/modernization/simplify
  findings). L0 requires a mechanical targeted format/lint cure followed by
  complete hash/test/audit replay; no lint-green claim is granted to the current
  bytes.
- FIX — Freeze `L70.4-INTEGRATION` removes `KeepAlive` from all `3/3` exact
  launchd plists, preserving real socket-demand registration with
  `RunAtLoad=false`. Registration is identity-only and may be waiting without a
  PID before authority. After the authority CAS, exactly three journaled
  `/bin/launchctl kickstart system/<label>` operations run without `-k`, recheck
  the exact job identity and require bounded `running` plus positive-PID health.
  Foreign identity, command failure, timeout, live and non-live crash recovery,
  rollback and fresh retry are replayed by the frozen exact-ten suite.
- FIX — The pinned CPython 3.13.3 subprocess proved that Darwin/CPython adds
  `LC_CTYPE=C.UTF-8` and `__CF_USER_TEXT_ENCODING` after Stage-0's PATH-only
  `execve`. The executor now accepts only that exact key set, binds the first of
  three bounded hex CF fields to the effective UID, removes both runtime-added
  keys and reasserts PATH-only before effects. Extra keys, wrong locale/UID and
  malformed or oversized fields fail closed. The UID-501 proof is local only;
  effective-root values remain a target-host probe with credit `0`.
- FACT — Automatic launchd recovery is scoped to the fixed Stage-0/executor
  sharing the inode-bound install-journal flock. A second independent root or
  package manager mutating the same system-domain labels is outside the threat
  and automatic-rollback claim; the administrator must exclude it or STOP
  before privilege. This explicit nonclaim closes the earlier causal-ownership
  overstatement without pretending that semantic equality proves causality.
- DONE — L0 and two independent frontier auditors accept the frozen L70.4
  code/contracts at installer
  `a6727e405eaecf5c1f6e412011692e7551f2ed2a7a27c7d88682f3f1c256c6a1`
  and executor
  `039c77acd8f87a155df72e61acc176f787ad47a28f270f229a37d4c883e3fca6`:
  adversarial verdict `P0=0 P1=0 P2=0`, integration claims
  `in=10 out=10 distinct=10 gaps=0`, Local50 `50/50`, PhaseA `73/73`, evidence
  `8/8`, schemas `13/13`, plist `3/3`, clang `6/6`, Python compile `65/65`, Ruff,
  format and diff gates green. Native Stage-0 remains byte-identical at
  `66e686da…/79144`; standard and Darwin-correct ASan/UBSan harnesses each replay
  `in=9 out=9 distinct=9 gaps=0`. No privilege, service, Node/Metis, network,
  production, model or training credit follows.
- STOP — The overall installable bundle remains honestly blocked. Required raw
  wheels are `in=3 out=0 distinct=0 gaps=3`, and production
  manifest/plan/descriptor/admin-runbook are `in=4 out=0 distinct=0 gaps=4` and
  intentionally absent. A later explicit network mandate may acquire only the
  three public pinned wheel preimages, remeasure them and materialize those four
  artifacts. The separately known host-wave atomic-publication temp risk remains
  `P1=1` before host promotion; production-complete and install credit stay `0`.
- FACT — The user now explicitly authorizes network access only for the three
  public wheel preimages already fixed by `uv.lock`: cryptography 47.0.0
  universal2 `160ad728…/7912214`, cffi 2.0.0 CPython313 arm64
  `45d5e886…/181043`, and pycparser 3.0 any `b7274141…/48172`. The mandate does
  not include an index, alternate artifacts, models, datasets, privilege,
  services, training, upload, commit or push.
- FACT — L71 preserves branch `codex/model1-local-99-foundation`, baseline
  `2d519d90be9eae0c562a10becbe2bc7e9ac4bbb0` and the inherited dirty worktree.
  One frontier writer exclusively owns the fixed wheel root and four new
  production artifact leaves; L0 retains boards/brief and a read-only frontier
  team concurrently recomputes the exact dependency path to the first W5
  training run.
- DONE — The exact-three public preimage lane is frozen at
  `in=3 out=3 distinct=3 gaps=0`: cryptography `160ad728…/7912214`, cffi
  `45d5e886…/181043`, pycparser `b7274141…/48172`. Writer, independent frontier
  auditor and L0 each remeasured the exact files; ZIP integrity is `3/3`, no
  temporary/extra wheel remains and focused installation `10/10`, schema
  `1/1`, lint/format/diff gates are green. This closes raw wheel preimages only.
- FIX — Stage-0's descriptor requires non-install source rows at `0444`, while
  the three fetched wheels were `0600`. L0 finalized exactly those three inodes
  to `0444`; inodes `254579415/254579512/254579622`, all sizes and all exact
  SHA-256 values are unchanged pre/post. Future materialization must require
  these modes and may not repair them implicitly.
- STOP — Production artifacts remain `in=4 out=0 distinct=0 gaps=4`. The
  installer exposes validation/planning/descriptor/runbook functions but no
  canonical production source-tree/manifest materializer; the only builder is
  the monkeypatched `_fixture_bundle()` test fixture. L0 refuses handcrafted
  manifests or installable credit.
- RISK — The registered CPython census is self-contradictory: pinned
  `2059/50433457/46fe9f95…` includes 251 `.pyc`/`__pycache__` rows while
  `validate_bundle_manifest()` rejects those paths. L0 independently recomputes
  the normalized no-symlink/no-startup-bytecode closure as
  `1808/44064036/b632ae57…`, excluding 251 bytecode files and eight symlinks.
  Constants, schema and a real builder must change together before any bundle
  can validate.
- RISK — The canonical capsule role denominator is
  `git-archive=32, tooling=1793, loader=1, runner=1`, but installer and schema
  omit `git-archive`. L0 reproduces this contradiction against the registered
  `1827/8922291/d72a8a4…` receipt; L71.1 may add only the missing exact role and
  must retain rejection of every foreign role.
- RISK — The frozen administrator document binds only the Stage-0 target under
  `/private/var/db`; its two reproducible source binaries live in random
  user-owned build roots absent from the runbook. The strict Stage-0 source
  scanner would reject an unlisted binary added to the bundle root, so current
  bytes are not yet a durable operator-installable preimage.
- FACT — Live `assess-w5` remains contract-valid but exits `1` with five blocker
  classes: groups `1/563`, W1/oracles unsealed, W3 synthetic-only, O-003 open
  and A/B absent. W4/grid/store are closed and the eventual W5 compute is capped
  at 700 optimizer steps / 18 hours; the strict data/evidence path, not GPU
  time, dominates the schedule.
- FIX — L71.1 opens one frontier materializer writer on four exclusive tracked
  files and fixed ignored source-root children. Exact CPython/Node/Metis Git
  object/Stage-0/wheel inputs are read-only; no privilege, services, keys,
  Node/Metis execution, model/data payload, training, commit or push is granted.
- FIX — L0 ratifies the separate durable Stage-0 source leaf
  `/private/var/tmp/MetisModel1-w3-phase-b-bootstrap/w3-installer-bootstrap`,
  mode `0555`, atomic no-clobber and publishable only after the two builds match
  `ddd09fcf…/54232`. Bundle/template/runbook must bind source and privileged
  target separately and require trusted copy plus target remeasurement; no file
  is added to the bundle root exact set and no privileged action is authorized.
- DONE — First L71.1 materializer slice is independently live-replayed by L0:
  CPython closes `1808/1808`, normalized executables `49`; exact wheel install
  file rows are cryptography `117`, cffi `30`, pycparser `13`; capsule closes
  `1827/1827`, `8922291` bytes, `d72a8a4…` with roles
  tooling/git-archive/loader/runner `1793/32/1/1`. Focused tests `8/8` and Ruff
  are green. This is input construction credit only; artifact20/four outputs
  remain open until the high-level transactional builder validates.
- FIX — The independent adversarial lane reproduced two wheel path-tree
  escapes before publication: a regular file accepted as an ancestor of
  another member (`a` plus `a/b.py`) and case-folded parent aliases
  (`Foo/a.py` plus `foo/b.py`). The materializer now rejects both, rejects raw
  NUL-truncated ZIP names and applies the same component/type collision policy
  across all wheel install partitions. L0 reruns the expanded focused suite at
  `25/25`; high-level build, formatting and four-output publication remain
  open and receive no artifact credit yet.
- STOP — The user-requested Qwen rejoin was attempted through local Qwen Code
  `0.21.12` as a bounded read-only L71 reviewer. The provider returned
  `429 insufficient_quota` before any review, with reset reported for
  `2026-08-28 13:28 UTC`; Qwen receives zero evidence credit. Kimi remains
  quota-exhausted, so the live wave continues only with the three internal
  frontier lanes and L0 replay.
- FIX — Adversarial registry replay found three false-installable paths before
  composer integration: duplicate families collapsed by a dictionary, role
  denominator drift inherited from a private helper, and helper-generated
  request/runtime identities foreign to the frozen capsule. The builder now
  pins and self-hashes both three-candidate manifests, cross-binds their
  semantic specs, owns an exact local five-role roster and reconstructs every
  request plus all 15 runtime identity fields from fixed pins. The independent
  reviewer replays those cures green; no real-run or W5 credit follows.
- FIX — Native release construction is now source- and toolchain-bound rather
  than merely repeatable: exact C bytes are copied no-clobber to held temporary
  snapshots, compiler/linker/SDK inputs are remeasured, and both builds enforce
  arm64, no LC_UUID, exact libSystem and no `/Users/` bytes without executing
  outputs. L0 independently rebuilds launcher
  `53976/bab27833…`, broker shim `34272/97fa87cc…` and anchor shim
  `34272/ff4f3af8…`; each pair is byte-identical and both shims are distinct.
- RISK — A no-clobber helper initially followed a symlinked parent, created an
  out-of-scope leaf and only failed after the write. Component-wise held
  `O_NOFOLLOW` directory descriptors and same-inode cleanup are now landed and
  focused tests are expanding; composer-level transactional publication and
  crash/adoption behavior remain open until the four outputs exist.
- STOP — The first clean-room composer validates, but adversarial parent-swap
  replay proves it re-resolves the staging pathname for each leaf: after the
  owned root is renamed away, a foreign replacement at the same name receives
  the next write before the final inode mismatch is noticed. Publication is
  stopped until one held root directory descriptor owns every relative
  `openat/O_NOFOLLOW` write and the mutation proves zero foreign leaf. The
  current successful clean-room denominator is not yet publishable credit.
- FIX — L71.1 replaces pathname publication with held-directory writers and an
  immutable inode ledger. Parent-root, intermediate-component, descriptor-leak,
  effect-before-ledger, post-rename-fsync, exact-copy child replacement,
  pre-existing FIFO and incomplete-rollback attacks now fail closed. Canonical
  Stage-0 and four tracked leaves are first written and fsynced in the private
  workspace, then moved by atomic no-replace rename; a crash can expose only a
  complete adoptable target. Synchronous cleanup now reports
  `rollback incomplete` rather than hiding any owned residue or durability
  failure, and it never removes a foreign replacement.
- DONE — Frozen materializer cut
  `579b432162904320eb01315208ee8815d5c600241ce543ed59b3cfde4835ab72`
  closes focused installation/materialization tests `in=67 out=67 distinct=67
  gaps=0`; Ruff, format, compile, Draft-2020-12 schema and `git diff --check`
  are green. Independent adversarial verdict is `P0=0 P1=0 P2=0`. The explicit
  precondition is exclusive-writer ownership; no defense is claimed against an
  omniscient same-UID/root actor mutating inside an already bound random `0700`
  workspace.
- DONE — L0 publishes the authorized production preimages transactionally and
  then replays the same transaction as exact adoption. The fixed source tree is
  `in=7477 out=7477 distinct=7477 gaps=0`, `372424009` bytes, with partitions
  artifacts/install/source-census/metadata/wheels `20/3817/3635/2/3`; Stage-0
  is `54232/ddd09fcf...`. The four tracked outputs are
  bundle/plan/descriptor/admin `4903172/16838/2137703/2217` bytes. First receipt
  reports created `4+4+1`; second reports adopted `4+4+1`, all nine published
  inodes remain identical, staging residue is zero, bundle digest is
  `9bacb346...` and release-content roster digest is `68239ac5...`. This closes
  only `PHASE_B_INSTALLABLE_UNEXECUTED`: no privilege, service, key, Node/Metis
  execution, dataset, model training or promotion occurred.
- FACT — A fresh `assess-w5 --json` remains contract-valid but blocked by the
  same five classes: leakage groups `1/563`, W1/oracles not sealed, W3
  synthetic-only, O-003 open and A/B absent. The checkpoint is already local
  and W5 compute remains capped at 700 optimizer steps / 18 hours; evidence and
  data readiness, not accelerator time, dominate the schedule.
- OPEN — To expose useful learning before the strict Accuracy-99 population is
  ready, L0 recommends a separately authorized `W5a_RESEARCH_ONLY` lane:
  protected public-synthetic execution, F-1/F-2/F-3 authoring and materializing
  at least 3000 oracle-clean provenance-bound examples, a frozen 30-task A/B
  smoke baseline, then the existing local bounded MLX grid. Its adapter and
  evidence are isolated, non-promotable and categorically `NON_99`; no upload or
  production claim follows. This can shorten time-to-first-useful-adapter but
  does not close or weaken any of the five strict W5 blockers. Privilege,
  Node/Metis execution, dataset materialization and MLX training need an
  explicit new mandate before this lane starts.
- FACT — The user rejects the weeks-long W5a framing and directs L0 to close a
  product-first plan with internal Orchestra only. Three independent read-only
  lanes close `in=3 out=3 distinct=3 gaps=0`: product diagnosis, legacy-gate
  compatibility and dataset/threshold arithmetic. No Kimi or Qwen result is
  used in this wave.
- FIX — O-011 supersedes the historical `>=3000` W5a recommendation for first
  value. W5-XS now runs B12 first, permits `NO_TRAIN`, then conditionally runs
  B24 before any data; only B below `22/24` plus at least three correctable B12
  semantic failures can open the fixed `64 train + 16 dev = 80` dataset. One
  rank-8 configuration, 100 steps, four hours, 8 GiB, 110 GB Metal, zero rework
  and five working days are hard cumulative caps.
- FIX — `manifests/w5-xs-plan.json` plus its strict schema form a tracked,
  machine-readable O-011 contract. `assess-experiment` returns
  `EXPERIMENT_PLAN_READY` only after that contract, its canonical-doc hash, W4
  pin metadata, O-006 publication invariants and repository payload/secret
  boundary validate. It always reports execution-authorized=false and
  physical-checkpoint-verified=false; it does not call Metis or inspect weights.
- FACT — The historical `validate-pilot`/`assess-w5` wire is restored exactly:
  schema v1, lowercase JSON status, legacy text and the same five blockers in
  the same order. Focused plan/contract/pipeline/qualification/seal tests close
  `in=68 out=68 distinct=68 gaps=0`; foundation `36/0`, pilot contracts, Ruff,
  format and diff checks are green.
- RISK — The mandatory broad `make check` was executed and is not green in the
  inherited concurrent W3/Metis state: `983 passed, 102 failed, 1 skipped`.
  Failures are concentrated in Oracle/bridge/qualifier surfaces outside the
  W5-XS writable roster, including live Metis HEAD `f5b54b8d...` versus pinned
  `a2dde2b...` and protected-broker-state expectations. Metis HEAD, tracked diff
  state and status digest are identical before/after the run; no broad-green
  claim is made.
- OPEN — Plan closure is not execution authority. The sole next product action
  is one explicit W5-XS local-only mandate; before it, no Node/Metis inference,
  roster generation, dataset materialization or QLoRA is authorized.
- DONE — Post-cure Orchestra review closes `in=3 out=3 distinct=3 gaps=0` with
  product, gate and dataset lanes all `VERIFICATO`; L0 reruns the canonical gate
  and independently recomputes `3+9=12`, `4+4+4=12`, `8+8+8=24`,
  `48+16=64`, `64+16=80` and `12*4=48`. W5-XS is plan-closed at
  `EXPERIMENT_PLAN_READY`; the old W5a recommendation is superseded and the
  Accuracy-99 promotion gate remains deliberately blocked.
- FACT — The user authorizes immediate W5-XS execution and directs L0 to bring
  Metis Model 1 home. L0 binds that mandate to the ratified local-only bounds:
  checkpoint inference and unprivileged public-synthetic Node/Metis only,
  generated writes under `artifacts/w5-xs`, at most 80 examples and at most one
  rank-8/100-step QLoRA under 4h/110 GB Metal/8 GiB. Network/download,
  privilege/services, live ARES/tenant/credentials, upload, promotion, commit
  and push remain forbidden.
- FACT — Fresh execution preflight rehashes the physical Qwen3.8 checkpoint:
  config plus three weight shards close `in=3 out=3 distinct=3 gaps=0`, exact
  revision `3e6447f0...` and `16054541349` weight bytes. Report:
  `artifacts/w5-xs/2026-08-24-delivery/preflight/checkpoint-verification.json`.
  Runtime pins, Node/runner/loader, tooling package/lock/node_modules and disk
  headroom also match; no network or model download occurred.
- FIX — L0 materializes an offline local clone under the authorized artifact
  root at pinned Metis `a2dde2b1.../75473e26...` and copies the already-local
  199 MB tooling dependency tree. `validate_pinned_metis` independently returns
  the exact revision/tree/package/lock/node_modules identities. The live Metis
  checkout remains untouched at its concurrent newer HEAD.
- OPEN — XS0 now has only the thin one-load runner and exact frozen B12 roster
  left before model output. No B12 output, dataset row or training step exists
  at this point.
- FIX — XS0 thin execution is artifact-local and fail-closed: one persistent
  Qwen load with remote code disabled and process-level network denial; frozen
  temperature 0/seed 17/thinking off/max 512; exact prompt hashes; raw output,
  tokens, latency and Metal telemetry per attempt; direct unprivileged pinned
  compiler envelopes; first-shot plus at most two diagnostic repair cycles; AST,
  IR and F-2 byte-minimality scoring. It never calls the protected production
  broker and exposes no hidden truth to the model.
- DONE — B12 roster/oracle freeze closes `in=12 out=12 distinct=12 gaps=0`,
  families `4/4/4`, origins `3+9`, parent/template groups `12`, honest leakage
  components `2`. All 20 pre-output roles (F-1 target 4, F-2 before/after 8,
  F-3 mutated/fixed 8) execute on the pinned compiler; all golden roles compile,
  every F-2 IR delta is exact and every F-3 mutation produces real diagnostics.
  Seal `80cd5e75...` binds roster `c162588b...`, checkpoint report `47ff40c2...`
  and model_outputs_observed=false. Two rejected pre-freeze drafts are retained
  as evidence; they received zero model output and zero scoring credit.
- OPEN — XS1 baseline B12 inference is now the sole active action. Dataset and
  training remain closed unless the frozen gate returns failure mining.
- FACT — XS1 executes Qwen3.8 adapter-off on the sealed B12 in `267.92s` with
  network sandbox-denied, peak Metal `21.215 GB`, max RSS `16.111 GiB`, no
  residual process, no identity/write drift and only `51.30 MB` of run output.
  First-shot equals post-repair because all twelve first outputs compile; no
  compiler repair is consumed.
- DONE — B12 evidence closes `in=12 out=12 distinct=12 gaps=0`, semantic
  `10/12`: F-1 `2/4`, F-2 `4/4`, F-3 `4/4`. Report `c45c0948...`, manifest
  `ccabfed2.../39 files`, telemetry `f66cede3...`; L0 independently recomputes
  every file hash and both canonical seals. Critical failures and accepted
  invented identifiers are zero.
- RISK — F-1 author tasks `w5xs-f1-author-003/004` have exact expected IR but
  add unrequested `meta template "POSTER"`, so AST differs and both are
  correctly rejected as one recurring semantic/unrelated-change class across
  two distinct parent/template groups. The observed cause is consistent with
  the compact context describing POSTER syntax too broadly; that is diagnosis,
  not permission to rewrite the already observed B12 or claim `NO_TRAIN`.
- OPEN — B12 is below `11/12`; O-011 therefore requires a separately frozen B24
  before any dataset. A green `22/24` B24 still closes `NO_TRAIN`; dataset and
  QLoRA remain unauthorized by result until that gate is known.
- STOP — L0 revokes the B12-v1 gate transition before B24: compact retrieval v1
  stated broadly that endpoint metadata uses `meta template "POSTER"`, while the
  hidden truth for the only two failed author tasks forbade that member. Qwen
  followed visible context; both outputs have exact expected IR and differ only
  by the instructed MetaDecl. Therefore `10/12` is harness-contradiction
  evidence, not model failure, and receives zero `FAILURE_MINING_REQUIRED`
  credit. The immutable run and its hashes remain retained for diagnosis.
- FIX — B12-v2 changes only roster id and one general context sentence:
  metadata is optional, added only when explicitly requested, and unrequested
  members are forbidden. A canonical projection excluding roster/context is
  byte-identical between v1 and v2; all twelve tasks, sources, hidden truths,
  families, lineage and sampling remain unchanged. Roster-v2 hash is
  `1459d1fa...`; it must receive a new pre-output oracle/prompt seal before rerun.
- OPEN — Dataset, B24 and training stay closed while the corrected B12-v2 is
  frozen and executed. A green v2 returns directly to `NO_TRAIN`.
- DONE — Corrected B12-v2 is newly frozen before any v2 output at seal
  `5b2c59f9...`, binding roster `1459d1fa...` and the unchanged checkpoint.
  Pre-output roles again close `20/20`; a canonical comparison proves all 12
  task ids/families/groups, hidden-source hashes and complete oracle truth are
  byte-identical to v1. Only the twelve visible prompt hashes change through
  context v2. Model_outputs_observed remains false.
- OPEN — One and only one corrected B12 execution is authorized now. Another
  prompt/gold contradiction stops technically; it does not permit iterative
  prompt tuning.
- DONE — The sole corrected B12-v2 run closes `in=12 out=12 distinct=12 gaps=0`
  on adapter-off Qwen3.8: conservative gate score `11/12` (F-1 `3/4`, F-2
  `4/4`, F-3 `4/4`), all first-shot, critical failures `0`, accepted invented
  identifiers `0`, recurring failure categories `0`. Report seal
  `d218de25...`, manifest `2b69aa80.../39 files`; project and pinned Metis
  identities are invariant. The only retained miss, `w5xs-f1-author-003`, has
  exact IR and differs only by equivalent inline versus block syntax, so no
  post-hoc score is claimed.
- DONE — Independent Orchestra review closes two bounded audits plus L0 replay:
  manifest `39/39`, frozen+run Oracle envelopes `32/32`, reconstructed final
  requests `12/12`, scores replayed `12/12`, prompt/truth leak `0`, and semantic
  source audit `12/12`. Final verification seal is `061eff91...`; deterministic
  verifier file SHA-256 is `96743670...`. Runtime closes in `278.99s`, peak
  Metal `21.26 GB`, artifact bytes `895695406`, residual processes `0`.
- STOP — O-011 returns `MODEL1_USABLE_LOCAL_NO_TRAIN`. B24, dataset
  materialization and QLoRA are closed by success, not deferred work: examples
  created `0`, adapters created `0`, training steps `0`. The delivered claim is
  local-only, nonpromotable and non99; no network/download, privilege, live
  ARES data, upload, promotion, commit or push occurred.
- RISK — Final mandatory broad `make check` repeats the inherited concurrent
  baseline exactly: `983 passed, 102 failed, 1 skipped`. Failures remain in W3
  protected-broker/qualification contracts and the external live Metis checkout
  mismatch (`f5b54b8d...` versus pinned `a2dde2b...`), outside W5-XS. Foundation,
  pilot contracts, lint and format are green; no broad-green claim is made.
- DONE — W5-XS delivery is closed at `MODEL1_LOCAL_DELIVERED`. The canonical
  handoff is `artifacts/w5-xs/2026-08-24-delivery/DELIVERY.md`, backed by
  `final-verification.json`, the immutable B12-v4 report/manifest and telemetry.
- FACT — The user opens a new accuracy-planning wave and identifies
  `/Users/tommasotessarolo/Developer/metis-tenant-play-prod` as an explicitly
  read-only source. No write, checkout, generated file, runtime call, secret,
  raw payload or live ARES access is permitted there or in any repository
  outside `metis-model-1`; dataset derivation and MLX training remain separate
  gates rather than being inferred from read authority.
- DONE — Read-only tenant census closes `in=197 out=197 distinct=197 gaps=0` at
  clean HEAD `456f11c6...`, tree `1d9ff5a2...`: 170 distinct endpoints, 144
  variants, 556 takes, 15,243 lines and 590,637 Metis bytes. The roster includes
  23 HOLD/NON_PROMOTE/incomplete endpoints and 10 test or AB-test endpoints that
  require explicit classification; no runtime or payload was read.
- FACT — Tenant tree `1d9ff5a2...` is byte-identical to
  `examples/play-prod-v2` at both pinned Metis `a2dde2b1...` and the current
  external Metis HEAD. Language remains 0.43, so this corpus introduces no
  compiler/version migration into Model 1 and can be referenced through the
  already pinned immutable subtree.
- RISK — The 170 endpoints are one whole-program/subtree ancestry, not 170
  independent leakage groups. They provide strong construct coverage but only
  one tenant lineage and cannot support a population or Accuracy-99 claim.
  Tenant-specific identifiers and mutable operational facts must stay in
  retrieval/evaluation, not be memorized in adapter weights.
- OPEN — The bounded accuracy path is D18 diagnostic (`3` per F-1...F-6),
  synthetic/genericized `64 train + 16 dev`, and a pre-output frozen T30 (`5`
  per family) held out from selection. D18 may guide only failure categories;
  train/dev/T30 share no parent/template/identifier material. Training opens
  only for at least three correctable semantic failures across two roots, and
  the rank-8 adapter is retained only for `+3` net T30 successes, closure of at
  least half the baseline failures, zero regression and zero veto.
- STOP — Before any tenant-derived artifact or F-1...F-6 training is
  materialized, local-only rights/sensitivity must be explicitly bound and the
  currently unexecuted F-4 review, F-5 migration and F-6 AST/IR explanation
  oracles must become executable and sealed. Read-only census is not dataset or
  training authority.

- FACT — External Metis (`ares-matioska`) is designing a catalog
  value-representation change. Field value-domains move OUT of the inline
  `values [ ... ]` form and are addressed per-field. The catalog file keeps the
  SKELETON (field name, type, similarity profiles) plus a domain marker carrying
  kind and size: a bounded set becomes `keyword enum(N)` with values stored in
  an external per-catalog value-set the toolchain slices per-field; a
  high-cardinality field becomes `keyword open` (the domain is the live index,
  not a materialized list); tiny stable enums below a tenant-parametric
  threshold stay inline. Threshold values are tenant settings, not hardcoded.
- FACT — The change is a retrieval-contract and grammar-surface change, NOT a
  weights change. It aligns with this board's standing invariant that
  tenant-specific values stay in retrieval, not adapter weights: catalog
  value-domains already belong to retrieval. The delivered adapter (B12-v4)
  memorizes no catalog values and is not invalidated by this change.
- DECISION — Absorb via the ratified grammar-change policy: update grammar pin,
  retrieval indices and semantic oracle to the new surface; try the existing
  adapter on the maintenance benchmark; choose NO_RETRAIN if gates stay green;
  open only a bounded QLoRA delta if a compatible failure is demonstrated.
  Retrieval authority for value-domains remains the toolchain over the checkout
  (deterministic, offline, credential-free); the serve/secret path is only for
  live open-domain runtime lookups, which authoring rarely needs.
- OPEN — Accuracy-wave family/construct selection must plan the "catalog
  value-domain" construct on the NEW surface (`enum(N)` / `open` marker plus a
  per-field external value-set), not on the deprecated inline form. Do not
  harden inline `values [ ... ]` as canonical in dataset, oracle or T30. The
  exact surface tokens (`enum(N)` vs `values(N)`, `open`) and the parametric
  threshold names are pending ratification in `ares-matioska` and will be pinned
  there first; Model 1 pins follow that SHA. No Model 1 artifact or training is
  gated by this note — it is a planning input for the next grammar pin.
- FACT — L73-C census at Model 1 HEAD `d6cf4066...` finds no catalog-domain
  lexical surface in any tracked dataset, oracle, task or T30 contract outside
  this incoming board note. Existing `inline` hits are predicate-literal origin
  metadata, not catalog field-domain declarations. Historical benchmark/W1
  sidecars at Metis `a2dde2b1...` therefore remain immutable rather than being
  rewritten as if they were future grammar truth.
- FIX — `manifests/accuracy-uplift-plan.json`, its strict schema and canonical
  `docs/16-accuracy-wave-catalog-domain-maintenance.md` now bind the active
  D18/64+16/T30 path. The catalog-domain construct reserves at least one F-1
  and one F-6 slot in both D18 and T30, but carries no lexical token field:
  upstream pin is null, provisional lexemes are non-authoritative, tenant
  thresholds are settings-only, and catalog task/oracle materialization is
  false until pin + retrieval + semantic-oracle refresh.
- DONE — Accuracy-sidecar verification closes O-010, document hash, split
  arithmetic, leakage policy, pre-output T30 seal, pending-pin prohibitions and
  NO_RETRAIN-first/delta-only policy. Schema mutations reject injected token
  fields and a non-null pending pin; semantic mutations reject hash, arithmetic,
  decision and training-authority laundering. `validate-foundation` returns
  `passes=40 errors=0` with the new contract and schemas registered.
- FIX — The grammar-independent automatic F-6 lane is now executable in
  `src/metis_model1/f6_structural.py`. A sealed pre-output truth can be created
  only from `verify_oracle_envelope`; each required claim resolves through an
  exact JSON Pointer against the verified AST and/or IR and must equal the
  sealed value. Candidate task/signatures/claim roster/value drift fail closed;
  truth and result receive canonical SHA-256 bindings.
- DONE — L0 live-replays one original public-synthetic, non-catalog endpoint
  against pinned Metis `a2dde2b1.../75473e26...` and the pinned Node runtime.
  The generated F-6 truth `9841aae2...` and result `a10eb16b...` return
  AST=`pass`, IR=`pass`, semantic=`pass`, human=`not_run`; benchmark eligibility
  remains `false` by construction. The temporary probe was moved to Trash after
  verification, and the pinned checkout stayed clean.
- OPEN — Exact catalog-domain task truth still waits for the ratified upstream
  SHA, without stopping non-catalog work. F-6 still needs an independent blind
  human-review receipt before any complete F-6 credit. F-4 still needs real
  wire+golden authority and F-5 a cross-version migration-pair authority. No
  model output, dataset materialization, QLoRA, promotion, external-repository
  write, commit or push is claimed by L73.

- FACT — UPSTREAM PIN LANDED (2026-08-24, written by the ares-matioska session).
  The catalog value-domain surface is RATIFIED and pinned at Metis commit
  `1f7eaae9` (`ttessarolo/metis` main, pushed; spec:
  `docs/design/catalog-values/spec.md`, ledger entry §9.172). Exact lexical
  surface: field markers `enum(N)` and `open` (tiny stable enums stay inline as
  `values [ ... ]`); parametric thresholds are tenant settings
  `settings/catalog { inline-max, enum-max }` with system defaults `12` / `300`
  (compile-scope: they never enter the runtime-ctx). External storage is one
  value-set per catalog, `catalogs/<cat>.values.metis`, declared as
  `values <qualified-catalog> { <field> reflected [ "…" ] | <field> editorial [ "…" ] }`
  — nature is PER-FIELD: `reflected` blocks are regenerated by
  `catalog:sync-values`, `editorial` blocks are editorially owned and never
  touched by sync; "Materialize" flips `reflected` → `editorial`. Resolution is
  by name (catalog+field, path-inert): no syntactic cross-reference from the
  field to the value-set. Implementation (grammar, resolver, sync target,
  tree-view, play-demo migration with artifact-identity gate, and an offline
  retrieval CLI `catalog:describe` / `catalog:values` for Model 1) follows in
  the same ares-matioska cycle; implementation SHAs will be appended here when
  sealed. Grammar pin for Model 1 = `1f7eaae9`.

- FACT — L0 independently verifies the upstream surface pin at full revision
  `1f7eaae9d803edc90f51ff492ea443f18570015e`, tree
  `346ddce27270287c8a3781bced77bf75c5318c11`, and exact specification SHA-256
  `34f26adb53809f1c0aed8e515564d3ed81e75f8023d125eb77ae51f8ab066678`.
  The pinned commit changes documentation only. The external Metis worktree now
  contains concurrent tracked WP-A edits, but those uncommitted bytes are not an
  implementation pin and Model 1 neither reads them as truth nor writes there.
- FIX — The accuracy sidecar transitions from a null lexical pin to
  `surface_pinned_implementation_pending`. It records the exact revision, tree,
  language `0.43`, specification hash, `enum(N)` / `open`, compile-scope tenant
  settings `inline-max` / `enum-max`, and per-catalog per-field value-set
  authority. Retrieval/oracle refresh, catalog materialization, evaluation and
  training remain false until one committed executable grammar/resolver/sync/
  retrieval/oracle pin is independently verified.
- FIX — The automatic F-6 truth boundary now rebuilds the exact Oracle request,
  verifies source path, source Git blob OID and source bytes, and passes that
  rebuilt request into `verify_oracle_envelope`. The live pinned reprobe binds
  request `4940da68...`, envelope `f6dc587f...`, truth `5f533c61...` and result
  `7806aac6...`; AST/IR/semantic pass while human remains `not_run` and complete
  F-6 credit remains false.
- FIX — Adversarial review reproduced standalone self-hashed F-6 credit, trusted
  self-declared policy/truth and caller-owned nonce weaknesses in the first
  human seam. The cured contract makes every final record
  `f6_credit_denied/eligible=false`; even a valid signed `pass` is rejected until
  a protected review authority with enrolled reviewer identity and atomic replay
  state exists. This is a fail-closed interface, not evidence of a human review.
- DONE — The F-5 public-synthetic runner seam executes one bounded live migration
  against pinned Metis `a2dde2b1.../75473e26...`: migrated source equals its
  independently sealed golden at `48394b4e...`, the report is `b9aba93c...`,
  process exit is zero, compile/parity are `1/1` and `1 ok / 0 diverge`, and no
  diagnostic or NON_PROMOTE finding appears. The current result contract names
  this only `local_runner_observation`, sets `promotion_eligible=false`, and
  records `protected_execution_receipt_missing`; it cannot close an F-5 task.
- RISK — Independent F-5 review proves that an earlier self-hashed green result
  could be forged and that mutable toolchain/input paths retain TOCTOU and path
  race exposure. L0 removes the promotion interpretation and also requires the
  golden to declare exactly its path-bound endpoint. The observed one-pair seam
  is useful implementation evidence, but the protected receipt and the five
  held-out F-5 migration pairs remain open; no F-5 roster, dataset or promotion
  credit is claimed.
- DONE — Post-cure independent F-5 replay closes the bounded local seam at
  `15/15`: golden endpoint mismatch stops before execution, every extra or
  symlink output entry blocks, a green record without its workspace is rejected,
  workspace validation recomputes exact migrated/report/roster hashes, and
  promotion forgery is impossible. No P0/P1 remains for the deliberately narrow
  `local_runner_observation` claim; protected authority and family closure remain
  explicitly outside that claim.
- DONE — L0 then executes the cured F-5 seam again, rather than relying on the
  pre-cure run: fixture `30b756e1...`, result `794d01a9...`, migrated/golden
  `48394b4e...`, report `b2e9ca75...`, exact typed roster `e2909ad2...`, exit zero,
  compile/parity `1/1` and `1/0`, diagnostics/NON_PROMOTE false, and
  `promotion_eligible=false`. The pinned Metis clone remains exactly
  `a2dde2b1.../75473e26...` with clean tracked status after execution.
- DONE — F-4 direct-path census closes `in=5 out=5 distinct=5 gaps=0` and L0
  independently recomputes the evidence denominator: all `25/25` task-oracle
  cells are `not_run` with null evidence; task-specific pre-output review truth
  and golden answers are `0/5`. The pinned parity ledger has wire entry plus
  bound promotion evidence for `4/5`; `play.multiple_block_dem_film_free` is the
  exact exception (`wireEntryPresent=false`, `PENDING_LIVE_PARITY`, next action
  `GROUND_LEGACY_WIRE`).
- DECISION — Do not add another F-4 wrapper that can only return a local,
  credit-ineligible observation. The minimum API/schema design is recorded by
  the Orchestra audit, but the next useful F-4 work is direct: ratify the five
  task prompts/findings/patches/golden IR before model output, obtain independent
  wire+golden authority, and ground the missing wire. Compile-clean or the four
  historical wire entries do not substitute for this authority.
- DONE — Required post-cure `make check` executes fully. Foundation is `46/0`,
  Ruff is green, format checks `148` files, and pytest returns `1031 passed, 102
  failed, 1 skipped`. No F-5/F-6/accuracy-sidecar test fails. The `102` failures
  stay in inherited Oracle/W3 bridge/qualifier surfaces: the live external Metis
  checkout is at docs pin `1f7eaae9...` while the historical Oracle requires
  `a2dde2b1...`, and protected-broker/production authorities remain unset. The
  broad gate is honestly RED; this wave does not claim or attempt to cure those
  separate authorities.
- FACT — The user explicitly authorizes commit and push of the accumulated Model
  1 work on `codex/model1-local-99-foundation`. Fresh fetch confirms local HEAD
  and `origin/codex/model1-local-99-foundation` both equal `d6cf4066...` before
  publication; no force, rewrite, merge or external-repository write is needed.
- DONE — L74 Luna pre-commit audit closes `in=142 out=142 distinct=142 gaps=0`,
  `11,780,289` bytes: tracked modifications `40`, untracked non-ignored sources/
  manifests/tests `102`, regular text `142/142`, mode `0644` `142/142`, symlinks,
  binaries, executable modes, credentials, private keys, model/checkpoint/dataset
  payloads and caches all `0`. The exact roster coheres with sessions L63-L73;
  ignored local artifacts remain outside Git.
- RISK — GitHub repository `ttessarolo/metis-model-1` is public. Thirty candidate
  files carry intentional local host/user identity or path contracts for the
  protected broker; this is not secret material and the same category already
  exists in 22 HEAD files, but it remains public machine-specific provenance.
  L0 accepts the audited complete roster rather than breaking sealed hashes with
  an unplanned redaction.
- DONE — The audited 142-file delivery checkpoint is committed as
  `14295a069c5dc341948427b13bbd64ecae36dfab` (`feat: checkpoint Model 1
  delivery and accuracy gates`) and pushed non-force to
  `origin/codex/model1-local-99-foundation`. A fresh `git ls-remote` returns the
  same full SHA and the local worktree is aligned with the remote branch.
- FACT — L74 completion census separates the already delivered local milestone
  from the optional production program. `MODEL1_USABLE_LOCAL_NO_TRAIN` remains
  `11/12`, critical/invented/recurring failures `0/0/0`, with dataset, adapter
  and training steps all `0` by the ratified NO_TRAIN outcome. Therefore there
  is currently no fine-tuned payload to back up. Catalog-domain maintenance
  still needs one executable upstream pin followed by retrieval/oracle refresh,
  D18 `0/18`, T30 `0/30` and the existing-adapter baseline; retraining remains
  conditional on the ratified semantic-failure trigger.
- FACT — If a rank-8 QLoRA adapter is eventually produced, its current plan
  estimates approximately `233,581,693` bytes; a full resumable adapter plus
  optimizer state is approximately `935,483,304` bytes. The reusable package is
  adapter, tokenizer/runtime configuration, evaluation receipts, immutable
  manifest and SHA-256 checksums, plus optional resumable state. Base Qwen
  weights are not duplicated: their model ID, revision and hash are recorded and
  the payload is fetched again from its authoritative source.
- DECISION — The off-site contract uses the S3 protocol. The practical default
  provider is Backblaze B2 S3-compatible storage, with version history and
  Object Lock; AWS S3 is the conservative substitute when an existing AWS
  account, IAM boundary or organization policy makes it operationally simpler.
  No bucket, credential, cloud resource or upload is created in this wave. The
  future immutable prefix is
  `metis-model1/<candidate-or-run-id>/` containing `manifest.json`,
  `checksums.sha256`, `adapter/`, `tokenizer-config/`, `eval-receipts/`,
  `runtime-lock/` and optional `optional-state/`.
- OPEN — Provision the selected B2/AWS account and private bucket, choose region
  and retention duration, enable versioning/Object Lock, create least-privilege
  credentials outside Git, and perform upload plus clean-room restore/hash
  verification only when a real adapter or resumable checkpoint exists and a
  dedicated external-upload mandate is active.
- FACT — Read-only artifact inventory at HEAD `ccb47ab5...` confirms the pinned
  MLX base checkpoint under `artifacts/w4/2026-08-20-qualification/checkpoint`:
  three weight shards, `16,054,541,349` bytes, verified tree
  `d8f18539...` and config `14b65a0e...`. W4 also contains 24 adapter files and
  14 state files used only for public-synthetic technical qualification; the
  canonical step-4 adapter is `233,581,693` bytes / `049d7a3c...`, and its
  resumable state is `700,776,754` bytes / `bfcc42bd...`. They are not a Metis
  Model 1 candidate and receive no backup/promotion credit.
- FACT — The IAM Identity Center session authenticates as user `metis` through
  role `MetisModel1BackupWriter` in the expected AWS account. The operational
  profile is the generated role/account profile, client/bucket region is
  `eu-west-1`, and scoped listing of `s3://metis-model-1/metis-model1/` succeeds.
  Global `ListAllMyBuckets` and unscoped `HeadBucket` remain denied, while
  `GetBucketLocation` succeeds; this is the intended least-privilege boundary.
- DONE — L0 writes and rereads exactly one zero-byte access canary at
  `metis-model1/access-check/codex-sso-2026-08-24`. `PutObject` and
  `HeadObject` succeed, the returned object is versioned and reports
  `ServerSideEncryption=AES256`, `ContentLength=0` and the exact purpose/client
  metadata. No credential or `.env` was read, copied or stored.
- STOP — W5-XS contains `0` adapter/checkpoint payloads and the registered
  production adapter remains unset: dataset `0`, adapter `0`, training steps
  `0` are the ratified `NO_TRAIN` success, not missing backup bytes. Therefore
  no base model, W4 qualification adapter or synthetic resumable state is
  uploaded as if it were Model 1. The private AWS target is operationally ready
  for the first real candidate package; Object Lock remains disabled by the
  user's explicit choice.
- RISK — Mandatory post-L75 `make check` is fully replayed: foundation `46/0`,
  Ruff and formatting are green, while pytest remains exactly `1031 passed, 102
  failed, 1 skipped`. The failures are the already-open external-Metis revision
  mismatch and absent protected W3/Oracle authorities; no board, backup-contract
  or S3-access regression is present, and no broad-green claim is made.
- FACT — L76's three-lane read-only census independently separates the new
  catalog surface from an executable maintenance pin. Metis commits `1e5e1bee`,
  `68d680f2`, `b4f5e676` and local WP-D `5a2afe50` cover grammar/resolution,
  value-set synchronization, editor/LSP and corpus migration, but `origin/main`
  remains at the specification-only `1f7eaae9`; the local checkout is dirty and
  therefore cannot be promoted by Model 1.
- STOP — The first `catalog:describe` / `catalog:values` implementation and its
  test are present only as untracked upstream working bytes. L0 copied those
  bytes over a `git archive 5a2afe50` snapshot, leaving the external checkout
  read-only: TypeScript typecheck passed, but the retrieval test reported three
  subfield-nesting failures and then raised `TypeError`. The scratch copy and
  incidental npm error log were moved to Trash. No implementation pin,
  retrieval refresh, catalog oracle or model output is accepted from this WIP.
- RISK — L76's adversarial audit reproduced a counter-only false seal: setting
  T30 `materialized=30`, `sealed_pre_output` and matching boolean gates returned
  no contract error despite zero roster and nonexistent evidence. It also proved
  that self-declared upstream evidence paths could previously make a fabricated
  implementation pin appear complete.
- FIX — L77 first hardening changes the no-adapter branch from `NO_RETRAIN` to
  `NO_INITIAL_TRAIN`, preregisters D18 `17/18` plus zero veto/recurring failure
  triage, keeps the three-failure/two-root micro-QLoRA trigger on D18 only, and
  makes T30 a one-shot observed-local confirmation (`29/30`, family `4/5`) with
  no training feedback. A T30 counter/flag pair no longer seals without roster
  and pre-output evidence, and evaluation cannot open before pin, retrieval and
  oracle refresh. Focused plan tests are `11/11`; capability-bound roster and
  decision writers remain under adversarial review before acceptance.
- FACT — The concurrent upstream writer subsequently corrected the uncommitted
  retrieval subfield projection. L0 repeated the same archive-overlay replay
  from fresh bytes: TypeScript typecheck and all `catalog-domain.ts` assertions
  A1-A25, B1-B3, C1-C11, D1-D3, E1 and F1-F9 are green. This supersedes only the
  prior WIP test result; the files, retrieval contract and package-script edit
  remain uncommitted and `origin/main` remains `1f7eaae9`, so the implementation
  pin is still OPEN. The second temporary copy was moved to Trash.

- FACT — UPSTREAM IMPLEMENTATION SEALED (2026-08-24, written by the ares-matioska
  session, follow-up to the pin note above). The §9.172 surface is now fully
  implemented and pushed at Metis main `5e112f91` (full test suite green,
  ledger entry §9.173; grammar pin for Model 1 remains `1f7eaae9` — the surface
  did not change during implementation). Retrieval API for progressive
  discovery is live and contract-documented in
  `docs/design/catalog-values/retrieval-api.md`: `npm run catalog:describe --
  --tenant <dir>` (skeleton: fields with domain kind none|inline|list|enum|open,
  sizes, natures, effective thresholds) and `npm run catalog:values --
  --tenant <dir> --catalog <c> --field <f>` (per-field domain slice) — offline
  on the checkout, no secrets, stable JSON `schema: 1`. Live tenants migrated
  and pushed: play-demo `e2bd044` (5 fields → enum(N), e.g. genere_mcm
  enum(214) reflected), play-prod `31dc23d` (2 fields migrated + opt-in
  `values []` on genere_mcm/content_channels awaiting a live sync run).

- FACT — L0 independently pins the published catalog implementation at Metis
  commit `5e112f9148f40e7e792052e896c5a9efe8eaf0a2`, tree
  `41c7a2b6890fa42d8123bd93f6560d0b9bfae8af`; a detached `ls-remote` before and
  after execution observes the same commit on `refs/heads/main`. The mutable
  external worktree is excluded: all evidence and executable source comes from
  the exact Git commit/tree/blob/archive identities.
- FIX — The executable catalog pin verifier binds the fixed system Git and Node
  binaries, raw schema/manifest preimages, the exact `18/18` evidence roster,
  copied dependency identity and `5/5` bounded catalog/typecheck probes. Remote
  Git discovery runs from root-owned `/private/var/empty`; write, host-home read
  and loopback-network canaries are denied by the probe sandbox. Fresh replay is
  `18/18 distinct=18 gaps=0`, `5/5`, remote=true, manifest
  `f971eafb...`.
- DONE — Independent adversarial replay returns P0=0/P1=0 for the emitted
  `verified_local_cooperative` claim. The report explicitly excludes resistance
  to a hostile concurrent same-UID process and general untrusted-code sandboxing;
  it grants no retrieval refresh, semantic truth, model, training, accuracy or
  promotion authority.
- DONE — L77 closes counter-only and self-declared authority paths. The exact
  D18/T30 draft contract, genealogy/leakage checks and decision schema cannot
  mint `VerifiedMaintenanceRoster`, a pre-output seal, `NO_INITIAL_TRAIN`,
  `MICRO_QLORA_ELIGIBLE` or a T30 result until protected Git/oracle/chronology
  issuers exist. Focused roster `18/18`, decision `12/12` and plan `21/21` are
  green; current materialized and authoritative counts remain zero.
- DONE — L78 implements a pure schema-1 `catalog:describe` / `catalog:values`
  response adapter. It validates deterministic structure, pin/query/input/output
  hashes, nested fields and domain semantics while redacting all value payloads;
  focused tests are `20/20`. Its receipt is deliberately
  `validated_response_non_authoritative`, with execution and retrieval-refresh
  flags false.
- FACT — The maintenance benchmark design roster is arithmetically complete at
  `in=48 out=48 distinct_task_ids=48 gaps=0`: D18 has 3 per F-1..F-6, T30 has
  5 per family, and catalog-domain reservations are exactly four (F-1 and F-6
  in each split). Existing B12 tasks are observed and share only two lineage
  components, so they receive zero new-root credit. New independent roots and
  complete protected oracle authority are currently `0/48`; no synthetic rename
  is laundered into a dataset.
- OPEN — Critical path now: execute retrieval only on newly authored
  public-synthetic tenants at the pinned commit, bind payload-redacted execution
  receipts, refresh affected semantic oracles, author independent D18/T30 roots,
  then publish the Git pre-output seal. Model output remains forbidden until
  that complete seal; S3 remains ready but receives no base/W4 payload because a
  real Model 1 adapter/checkpoint still does not exist.
- RISK — Mandatory post-hardening `make check` is complete, not sampled:
  foundation `52/0`, Ruff and formatting are green; pytest is `1100 passed, 102
  failed, 1 skipped` in `474.69s`. The exact last-failed roster is confined to
  historical/protected surfaces: `tests/test_oracles.py` 31,
  `tests/test_w3_bridge_gate.py` 25 and `tests/test_w3_qualifier.py` 46. The
  focused catalog pin/retrieval/roster/decision/plan suite is `78/78`; no new
  maintenance file appears in the broad failures and no broad-green claim is
  made.
- DONE — Text-only maintenance checkpoint
  `e1fa11bb944c430b82a5d11a5f822d214256e49e` is committed and pushed
  non-force to `codex/model1-local-99-foundation`; post-push `ls-remote` equals
  local HEAD exactly. The unrelated concurrent `fx` note block remains only as
  an unstaged worktree change and was not incorporated into this checkpoint.
- FACT — `origin/main` advanced after the catalog pin to `fb286f0f`, while
  `5e112f91` remains its verified ancestor. The former exact-tip check was
  therefore operationally brittle: the pin verifier now requires the live ref
  to contain the exact pinned revision and rejects a non-descendant or a ref
  change during verification. The archived revision/tree/evidence roster stay
  exactly `5e112f91`/`41c7a2b6`/`18`; no upstream file was changed.
- DONE — Model 1 public-synthetic catalog refresh executes the exact archived
  CLI under deny-write/deny-network with `in=8 out=8 distinct=8 gaps=0` across
  describe, inline, list, editorial enum, reflected nested enum, unsynchronized
  enum, open and none. The fixed fixture and tracked execution receipt contain
  no catalog values; receipt `6d007c93...` binds the exact response/output
  hashes and redacted summaries. Tenant payloads contribute zero examples.
- DONE — Frontier adversarial replay first reproduced four re-sign/TOCTOU P1s,
  then verifies their cures at P0=0/P1=0: exact query/golden/upstream binding,
  raw schema pin, fixture copy plus pre/post hashes, and explicit
  `no_external_execution_attestation`. Focused integrated replay is `84/84`.
- DECISION — Retrieval and affected semantic-oracle refresh gates are now true
  only for `public_synthetic_archive_snapshot_only`; catalog D18/T30 prompt,
  oracle and materialization work is open. Model outputs, tenant values and
  training remain forbidden until the complete 48-task Git pre-output seal and
  later D18 decision.
- OPEN — The critical path has moved to actual D18/T30 construction and its
  pushed-Git pre-output verifier. Existing W1/B12 material does not receive
  fresh-root credit merely by relabeling; the parallel census must identify
  reusable authority or the minimum genuinely new task/oracle set.

- FACT — L0 reran the repository-wide `make check` after integrating the
  public-synthetic retrieval checkpoint: foundation `54/54`, focused
  retrieval/adversarial `84/84`, lint and format are green; full pytest is
  `1106 passed, 102 failed, 1 skipped`. The 102 failures remain confined to
  the three pre-existing protected/live-dependent groups (`oracles=31`,
  `w3_bridge_gate=25`, `w3_qualifier=46`); no catalog-refresh test regressed.
  This is scoped checkpoint evidence, not a production-qualification claim.
- DECISION — L0 rejects the 48-new-task D18/T30 roster as the critical path for
  this bounded catalog grammar maintenance change. The broad six-family
  accuracy wave is postponed, remains materialized at zero and cannot observe
  model output. The active path is a separate public-synthetic eight-case,
  non-statistical and non-promotional probe; `8/8` plus zero vetoes may support
  `NO_RETRAIN`, while any failure is diagnostic and never authorizes training.
- FACT — The probe specification closes `in=8 out=8 distinct_case_ids=8
  distinct_roots=8 distinct_templates=8 gaps=0`, with author/edit/repair
  `5/2/1` and one honest public-synthetic lineage. Exact pinned
  `catalog:describe` replay accepts all eight expected sources; only the
  dedicated retrieval-boundary case receives `Curated`, and no target source
  is present in a prompt. Model outputs remain zero.
- FIX — The pre-output runner binds exact published `HEAD`, Git blob OIDs and
  worktree bytes for the complete local import/fixture closure; raw/self receipt
  identities; the fixed three Qwen3.8 shards plus every auxiliary checkpoint
  file; worker, Python and checkpoint-report identities; prompt/truth/retrieval
  recomputation; a sterile environment; deny-network execution; bounded worker
  I/O; post-load/per-generation checkpoint metadata; canonical case/root gate
  arithmetic; and atomic ignored output. Training authority is always false.
- DONE — Three independent read-only audits plus L0 replay close current probe
  specification and runner at P0=0/P1=0. Focused results are probe `18/18`,
  plan/contracts `54/54`, retrieval/pin `33/33`; foundation, Ruff, formatting,
  compile and diff checks are green. No freeze, inference, adapter, dataset or
  training payload has been produced by this checkpoint.
- RISK — Current live AWS evidence supersedes the earlier canary claim for the
  newly configured SSO profile: STS assumes the expected account/role, but a
  zero-byte `s3:PutObject` canary is denied because the permission set has no
  identity-based `s3:PutObject` grant. No object was created. S3 backup remains
  independent of, and nonblocking for, the local model probe.
- OPEN — Exact next sequence: commit and push this spec/runner checkpoint;
  generate the no-output freeze against that exact remote preimage; independently
  verify and commit/push the seal; then run the adapter-off Qwen3.8 probe once.
  `NO_RETRAIN` is available only at `8/8` with all veto counters zero.
- RISK — Required repository-wide `make check` is complete: foundation has
  `56` passes and zero errors, pilot/lint/format are green, and full pytest is
  `1126 passed, 102 failed, 1 skipped` in `449.62s`. The unchanged 102 failures
  remain exactly confined to historical protected/live-dependent groups
  (`tests/test_oracles.py=31`, `tests/test_w3_bridge_gate.py=25`,
  `tests/test_w3_qualifier.py=46`); probe/retrieval/plan tests do not regress.
  No repository-wide green or production-qualification claim is made.
- STOP — First no-output freeze attempt fails closed before writing a seal or
  starting the worker because the checkpoint contains Hugging Face download
  metadata under `.cache/`, while the initial roster admitted direct files only.
- FIX — The checkpoint contract now hashes the exact three shards plus all 12
  direct auxiliary model files, declares only `.cache` as excluded nonpayload,
  and hashes a worker sandbox policy that denies network, every checkpoint
  write and every `.cache` read. Independent replay returns P0=0/P1=0; probe
  tests are `19/19`, checkpoint identity is `3+12`, and no model output exists.
- DONE — The pre-output freeze is generated from exact published preimage
  `cb146990d51b3681ae44e2edefe5fcdc909da882`, tree `b3da6115...`; canonical
  seal `95d19cf8...`, raw file `df837230...`, bound inputs `27/27`, tasks
  `8/8`, checkpoint `3+12`, gaps zero, model outputs false and training false.
  Two independent audits plus L0 recomputation return P0=0/P1=0.
- DECISION — The separate probe gate advances to `sealed_pre_output`; only its
  bounded evaluation is allowed. Global D18/T30 evaluation and training gates
  remain false. Focused sealed-state tests are `73/73` and foundation is
  `57` passes with zero errors; inference still waits for this seal commit to
  be published byte-for-byte.
- STOP — The first run attempt exits before model load: resolving
  `qualification/.venv/bin/python` to its global target discards the virtualenv,
  and the worker raises `ModuleNotFoundError: mlx_vlm`. The retained artifact is
  one 457-byte stderr log; tasks, generations, report and model outputs are zero.
  This is a technical runner failure, not a model score.
- FIX — The prior seal is revoked. The runtime identity now preserves and binds
  the virtualenv launcher symlink, target binary/stat, `sys.prefix`, Python
  `3.12.10`, MLX `0.32.1` and MLX-VLM `0.6.15`; the sandbox command uses the
  launcher path. Focused spec-state tests are `74/74`, foundation `56/0`, and a
  replacement freeze is required before any retry.
