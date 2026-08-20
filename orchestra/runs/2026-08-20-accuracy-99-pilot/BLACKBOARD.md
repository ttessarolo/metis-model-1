# Accuracy-99 pilot blackboard

## Objective

Advance Model 1 toward a defensible 99% end-to-end correctness target by
sealing measurement semantics before training, completing the W1-W3 entry
gates, executing a bounded W5 pilot only when authorized by evidence, and
reporting every denominator and non-claim.

## Acceptance

- The 99% target names an exact metric, population, denominator, confidence
  rule, family breakdown and critical-failure policy.
- The benchmark and its genealogy are frozen before any training material is
  generated from the same source families.
- Every materialized example has immutable provenance, sensitivity, split and
  applicable executable-oracle results.
- Baseline A/B precedes pilot training; checkpoint selection uses dev only.
- W5 records exact config, seed, dataset/model/runtime hashes, telemetry,
  adapter identity and a B/D comparison.
- No score is called 99% unless its frozen held-out evidence satisfies the
  ratified statistical and semantic contract.
- The frontier coordinator independently reruns gates and recomputes at least
  one claim from every delegated lane.

## Scope and authorization

- Repository: `/Users/tommasotessarolo/Developer/metis-model-1`.
- Baseline: `main@ad7a1169104c22fa8736b7463a93f65ea9f670f8` with the existing,
  user-authorized uncommitted foundation/W1/W4 changes preserved.
- Writable: this repository's contracts, code, tests, boards and reports;
  ignored local paths for datasets, checkpoints, adapters and raw telemetry.
- Explicitly read-only: `/Users/tommasotessarolo/Developer/ares-matioska/metis`.
  No edit, checkout, formatter, generated output or cleanup may run there.
- The four untracked entries observed in the Metis checkout at preflight are
  pre-existing user state and remain untouched.
- External orchestra source is read-only; its wrapper may write only its
  ignored runtime logs and activity workspace.
- Forbidden: credentials, `.env`, keychains, private keys, raw production/live
  ARES payloads, external publishing, commit, push or autonomous Metis writes.
- Training mandate: local QLoRA/model evaluation for this wave is explicitly
  authorized by the user. Model-family substitution is not.

## Fixed identities

- Metis evidence commit: `a2dde2b191f6b78c2003d74875560da782470968`;
  language `0.43`; read-only.
- MLX checkpoint: `mlx-community/Qwen3.8-27B-4bit` at
  `3e6447f082e89cc7f0bc6e5441afd38dfce760ff`.
- Training runtime: CPython `3.12.10`, MLX `0.32.1`, MLX-VLM `0.6.15`, exact
  lock SHA-256 `e5a39821599ac1f4eba46b3f5ae04040bd4973f3518351bd75f48677f6c9a340`.
- Second frontier team: Kimi Code `0.36.1`, model alias `kimi-code/k3`, selected
  explicitly by the user; write, JSONL-stream and session-id capability probes
  passed before dispatch.

## Expected outputs

1. Ratified accuracy-99/evaluation contract and benchmark manifest.
2. W1 slice closure report or explicit fail-closed blockers.
3. W3 deterministic builder, oracle/evaluator harness, dataset and split
   manifests; materialized payloads outside Git.
4. A/B baseline and 30-50-task pre-W5 smoke report.
5. Ratified O-003/O-005/O-006 or exact evidence preventing ratification.
6. W5 pilot adapter, telemetry and B/D report outside Git, with tracked hashes
   and a frontier/Kimi adversarial closure report.

## Verification commands

- `make check`
- task/dataset/oracle/contamination commands added by this wave and exercised
  against both valid and deliberately invalid fixtures;
- exact runtime/model/dataset/config hash checks before training;
- post-run `git diff --check`, artifact-boundary check and Metis checkout status
  recheck.

## Established

- FACT — The previous W4 bounded path is technically qualified, including a
  600-step run and bit-exact dropout-0 full-state resume.
- FACT — W4 does not establish Metis semantic uplift or 99% accuracy.
- FACT — Current benchmark planning allocates 30 distinct sources across six
  families but leaves dependency closure, rights and task-specific oracles
  unsealed.
- FACT — `kimi provider list` reports default model `kimi-code/k3`; project
  capability verification passed write, streaming and session-id probes.
- FACT — Orchestra lessons are current at `fcf2a170c4b923da6e930e674cddaeaa49a35626`.
- FACT — L1, L2 and K1 completed disjoint read-only inventories and adversarial
  review; L0 retains all semantic, training and promotion gates.
- DONE — L1 verified the exact W1 source roster; L0 independently recomputed
  `in=30 out=30 task_ids=30 paths=30 blob_oids=30 matches=30 gaps=0` at the
  pinned Metis commit with read-only `git ls-tree`.
- FACT — Structural parse/link/validate/compile libraries exist, but the 30
  allocations do not yet have task-specific minimality, repair, migration-pair,
  wire/golden, structural-explanation or human-oracle harnesses.
- FACT — L2 found no existing W3 dataset builder or A/B/C/D evaluator; L0
  independently confirmed the CLI currently exposes only foundation validation.
- RISK — The grammar header still says `v0.42` while authoritative
  `tooling/src/language/version.ts` declares `0.43`; Metis stays read-only and
  the evidence conflict must be classified before sealing language-bound tasks.
- DONE — K1 returned through the protocol wrapper in 558 seconds. L0 accepted
  its arithmetic, source-identity and oracle-gap findings with two corrections
  recorded in `KIMI-ACCURACY99-AUDIT.md`; the source report hash is
  `c5463bc0a75c6c568960c4c2dd7d410c03acf66346df542bcb7e18f7ad0c04bb`.
- FACT — Kimi's concurrency STOP is resolved: the newly observed accuracy plan
  was an authorized concurrent L0 write. Kimi did not write it.
- FACT — The exact Metis status has four pre-existing untracked entries, not
  the three claimed in Kimi's closing prose; before and after states match.
- DONE — Accuracy scorer implements exact denominators, two-sided Wilson 95%,
  immutable task observations and critical vetoes. The pre-candidate target is
  now 600 tasks, at most one failure and at least 563 distinct leakage groups.
  L0 independently recomputed 600/600, 599/600, 598/600 and the 563 minimum.
- RISK — Planned per-family counts of 80–110 cannot establish per-family 99%
  confidence; the target is global with family breakdowns and no cross-tenant
  extrapolation.
- DONE — L0 executed the pinned structural path without writing to Metis:
  Langium corpus validation reported `files=197 errors=0 warnings=123`, language
  `0.43`, and every positive/negative polarity check green.
- DONE — L0 built the tenant twice from an isolated `git archive` outside the
  Metis checkout. Both runs produced byte-identical output: 170 endpoints,
  artifact-set identity `776676472b8066a143f755b69c9ed123e2ec6d0d3e02b814ce5ed21fc05c5f4c`.
  Exact boundary and hashes are in `W1-STRUCTURAL-PATH.md`.
- FACT — The normal `build:tenant` CLI is not used for the read-only lane:
  frontier inspection found an all-branches path that mutates Git worktrees and
  a source-snapshot path beside the supplied tenant. Isolated archive execution
  is the accepted route.
- RISK — Structural green does not discharge task semantics. The 30-task smoke
  roster remains unsealed until every family-specific oracle is executable and
  polarity-tested.
- DONE — L7 closure recomputation is accepted after rework:
  `tasks in=30 out=30 distinct=30; sources in=201 out=201 distinct_paths=201`
  `distinct_oids=201 gaps=0`; every planned source OID matches the pinned Git
  object and the tracked manifest recomputes byte-for-byte.
- FACT — All 30 tasks share one content-derived whole-tenant leakage group,
  `sha256:2efe88f1ec36ca151c15a728db8623de4e8a34628ad3aaf60c76ae10ea170c47`.
  Task-local source signatures are not split identities.
- STOP — The current slice provides `1`, not `563`, distinct leakage groups.
  It can support a correlated structural smoke only; it cannot support the
  registered 99% population-confidence claim or a train/frozen split drawn from
  the same whole-tenant ancestry.
- DONE — W2 classified the exact closure roster without reading payloads:
  `assets in=201 out=201 distinct_paths=201 distinct_oids=201 gaps=0`;
  register SHA-256
  `652929ad06a86ba26385293487b47279302b600f9b1048cf5ddb071b6e3eed08`.
  Every record is internal, local training/evaluation only, distribution
  prohibited pending O-009, and explicitly not a legal review.
- DONE — W3 synthetic contract core is accepted after frontier rework. Dataset
  materialization rejects non-accepted/negative rows, requires exact per-family
  oracle registries and one final assistant target, and enforces deterministic
  manifest/split identities. It is pipeline evidence, not a real Metis dataset.
- DONE — The offline A/B/C/D evaluator is accepted after frontier rework and
  additional L0 hardening: exact four-variant rosters, task-specific prompt
  hashes, global comparable sampling/runtime identities, complete stage oracle
  evidence, unfiltered denominators, failure categories, critical vetoes and
  paired `B-A`, `C-A`, `D-B`, `D-C` sign tests. A complete report is not a
  promotion verdict.
- DONE — L0 expanded W4 on a public-synthetic sequence fixture. Rendered
  `raw=7414 prefix=20 completion=7394`; the real training batch was exactly
  `1024` tokens with `1004` retained completion tokens.
- DONE — Sequence-1024 rank-8 step 1 and resume step 2 passed with finite losses
  `0.0608372837` and `0.0536097251`, peak Metal `94.43498243` and
  `95.037375128 GB`; checkpoint manifests and all payload hashes matched.
- DONE — Sequence-1024 rank-16/alpha-32 step 1 passed with finite loss
  `0.0608372837`, peak Metal `94.81756623 GB` and a `1,869,318,364`-byte
  checkpoint. These are technical feasibility results, not Metis accuracy.
- DONE — O-005 is ratified before candidate results: four rank/LR screening
  configurations, seed 17, one finalist repeated on seeds 17/29/43, at most 700
  optimizer steps, 18 hours and 32 GiB published checkpoints; dev-only
  selection and a 110 GB Metal STOP.
- DONE — O-006 is ratified from live storage evidence: local-only
  `artifacts/w5/<run-id>`, 40 GiB per-run cap, 100 GiB free-space preflight,
  60 GiB reserve, full identity/hash publication, fsync/atomic rename and no
  automatic deletion of published artifacts.
- DONE — K2 Kimi K3 returned in 1,015 seconds after independently rechecking
  Wilson arithmetic, `30/30` tasks, `201/201` source/assets, every checkpoint
  payload and the three gates. Its report SHA-256 is
  `23d11be2cd3cd41beb135c4b381ec11f49841f146472d6103f2483b70a25003e`.
- RISK — K2 found that the original standalone `validate-pilot` accepted a
  self-consistently poisoned closure/assets pair. L0 rejected a clean closure,
  added content-derived leakage identity plus exact regeneration from pinned
  Metis Git objects, and made a missing source checkout fail closed.
- DONE — Three disjoint Luna remediation lanes closed K2's evaluator/sign-test,
  dataset lineage/writer, asset and standalone-policy test gaps. Stop-rule and
  non-claim arrays are exact schema constants; open W5 decisions are derived
  from the decision register instead of hardcoded report data.
- DONE — K3 re-executed both closure poisoning attacks, the missing-checkout
  path, lineage/split attacks and unsafe policy mutations. The first report was
  CLEAN for its enumerated scope (538 seconds; SHA-256
  `3756f117bfa44be4ea74ca8613ad30953ec2bb7db09418581fc243b6966a2a10`).
- RISK — Frontier review then found a same-split/different-leakage-group parent
  example could inflate group counts. L0 fixed the genealogy invariant; K3
  resumed its session, corrected its earlier overbroad P2-2 statement and
  returned CLEAN in 183 seconds. Follow-up report SHA-256:
  `863807b0d87f7bad97a224571739dd3e972bb2e1a1c1ccef2d25adb6d7e14be7`.
- DONE — The final dataset rule is: an example named as a provenance parent
  shares both split and leakage group with every child, independent of row
  order. Same-group multilevel lineage remains valid; non-example assets retain
  the one-split rule.
- DONE — A read-only pinned-commit source census found all tracked `.metis`
  files `in=199 out=199 distinct_paths=199 distinct_oids=199 gaps=0`, but only
  three syntactic roots and at most two defensible ancestry roots. Even the
  invalid file-level upper bound `199` is below `563`; the current tracked
  corpus cannot supply the population claim without new or external sources.
- FACT — The integrated local gate is green with foundation errors `0`, pilot
  contracts valid, Ruff/format clean and `134 passed`. `validate-pilot` exits
  `0`; `assess-w5` exits `1` with five derived blockers and cannot authorize W5.
- DONE — The W4 full-state wrapper was hardened after strict frontier review:
  exact model weights/config/revision and live runtime pins (including NumPy)
  are bound, remote code is disabled, payload manifests are hashed/atomic,
  sampler/RNG/optimizer state is fail-closed and non-finite trees are rejected.
  Final wrapper SHA-256:
  `af6053b88571dcd421943ef5dae1f7b8205b44e995d9c31a27f36e0bc525eae4`;
  the independent final audit returned `CLEAN` with no P0/P1.
- DONE — L0 re-executed the current uninterrupted-vs-stop/resume comparator.
  At global step `4`, final loss `5.221731185913086`, canonical
  model/optimizer state (`700,776,754` bytes), adapter, adapter config and
  semantic continuation state matched bit-for-bit. The regenerated report has
  the same SHA-256 as the recorded final report:
  `504508b63f941fca27c4d98b9c1a69b5265527a582e26619daa8ea9f57a96f25`.
- DONE — Final closure recheck: `make check` exits `0` with `134 passed`,
  `validate-pilot --json` exits `0`, `assess-w5 --json` exits the required `1`,
  `git diff --check` is clean, `tracked_payloads=0`, and the read-only Metis
  checkout remains at `a2dde2b191f6b78c2003d74875560da782470968` with exactly
  its four pre-existing untracked entries.

## Open

- OPEN — Ratify the exact 99% statistical/semantic contract before observing a
  candidate score; the proposal and executable arithmetic now exist, Kimi's
  review is accepted, and W1 benchmark evidence remains outstanding.
- OPEN — W1 dependency closure and operational local-use classification are
  complete; seal remains blocked by one shared ancestry group, unresolved
  runtime dependencies and missing task-specific semantic oracles.
- OPEN — Implement the missing task-specific oracle harnesses; existing generic
  compiler/IR entrypoints alone cannot seal semantic tasks.
- OPEN — W3 code and synthetic mutation fixtures exist; produce real,
  independently grouped and oracle-accepted dev/internal/frozen inputs.
- OPEN — Source at least 563 genuinely independent leakage groups or ratify a
  cluster-aware target that withholds the population claim; cosmetic task
  multiplication inside this tenant does not close the gap. The complete
  tracked Metis corpus has only 199 files and at most two defensible roots, so
  this requires newly authored or independently sourced material.
- OPEN — Measure A/B and the pre-W5 smoke denominator.
- OPEN — Ratify O-003 after frozen denominators and baseline variance; O-005
  and O-006 are complete and do not bypass this blocker.
- OPEN — Run W5 and establish whether D improves B semantically.

## Stop rules

- STOP — Any write attempt in the Metis repository ends the lane.
- STOP — Leakage, ambiguous oracle, unreconstructible identity or a materialized
  dataset entering Git invalidates the associated score/run.
- STOP — A compile-only gain cannot satisfy semantic accuracy.
- STOP — Frozen benchmark results cannot select hyperparameters.
- STOP — NaN/Inf, OOM, abnormal memory growth or save/reload/resume failure
  blocks scaling.
- STOP — Missing evidence is reported as open; no invented number is accepted.

## Ruled out

- Treating 99% training-set accuracy or falling loss as product accuracy.
- Editing or generating files inside the Metis checkout.
- Random file splits, cosmetic duplicates or shared provenance ancestors.
- External upload/distribution and model-family substitution.

## Outcome

COMPLETE WITH W5 BLOCKED — every currently executable foundation, technical
training, hardening and adversarial-audit step in this wave is closed. W5 was
not started: O-003, independent oracle-sealed data, task-specific semantic
oracles and A/B baseline remain evidence prerequisites, not implementation
work that can be manufactured from the current corpus.
