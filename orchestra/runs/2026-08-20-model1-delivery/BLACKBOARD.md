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
- The four pre-existing untracked Metis entries are user state and must remain
  byte-for-byte untouched.
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
  `af6053b88571dcd421943ef5dae1f7b8205b44e995d9c31a27f36e0bc525eae4`.
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

## Open

- OPEN — Close the independent adversarial audits for the oracle runner and
  content-derived independence graph; integrate only after P0/P1 are zero.
- OPEN — Benchmark v1, real W3 dataset, A/B baseline, O-003 and W5.
- OPEN — Final semantic accuracy and promotion verdict.

## Stop rules

- STOP — Any Metis checkout write, secret/live-data access, external upload,
  materialized payload entering Git or model-family change ends the lane.
- STOP — A generated benchmark cannot certify its own targets without an
  independently validated semantic oracle.
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
