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
