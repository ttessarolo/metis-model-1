# Accuracy-99 pilot lane ledger

| Lane | Owner | Model | Enumerated task / roster | Exclusive scope | Verification | Status | Session |
|---|---|---|---|---|---|---|---|
| L0 | Root coordinator | Frontier / maximum | Architecture, 99% metric, semantic/leakage gates, integration, training authorization and final verdict | Current repo integration plus single-writer ML runtime | Diff, independent recomputation, oracle/eval/training gates, `make check` | complete; W5 blocked by evidence gates | `/root` |
| L1 | Internal delegate | `gpt-5.6-luna` / high | Exact read-only Metis toolchain/oracle entrypoint inventory for the 30 allocated paths | Metis checkout read-only; report only | Commands, denominators, no-write status | accepted | `/root/w1_oracle_entrypoints` |
| L2 | Internal delegate | `gpt-5.6-luna` / high | Existing Model 1 W3/evaluator contract and implementation-gap inventory | Current repo read-only; report only | Explicit file roster and red tests needed | accepted | `/root/w3_gap_inventory` |
| K1 | Kimi master | `kimi-code/k3` / configured maximum | Adversarial 99% benchmark, oracle and leakage design review | Both repos read-only; orchestra runtime report only | Re-derived claims, arithmetic coverage, STOPs | accepted with two L0 corrections | wrapper `20260820-183033`; session `session_43a913e8-6af5-493b-98a3-9b54429eeda8` |
| K2 | Kimi master | `kimi-code/k3` / configured maximum | Final integrated contract, mutation, technical-evidence and W5-readiness audit | Both repos read-only; orchestra runtime report only | Full gates, adversarial bypasses, independent arithmetic and status invariants | accepted for findings; remediation required | wrapper `20260820-193131`; session `session_2a3ab80a-a975-4f1c-a443-1b1e69c5a4f2` |
| K3 | Kimi master | `kimi-code/k3` / configured maximum | Adversarial remediation audit plus resumed parent-group follow-up | Both repos read-only; orchestra runtime report only | Re-executed attacks, gates, before/after states and explicit correction | accepted after resumed correction | wrapper `20260820-195610` + `20260820-200634`; session `session_8a19981a-5033-42df-a200-e51b59422b3a` |
| L3 | Internal delegate | `gpt-5.6-luna` / high | Post-implementation mechanical test/artifact audit | Read-only merged tree | Mutations, tracked-payload census, exact counts | superseded by K2/K3 and L11-L14 | n/a |
| L4 | Internal delegate | `gpt-5.6-luna` / high | Wilson scorer and binary evaluation gate implementation | `src/metis_model1/evaluation.py`; `tests/test_evaluation.py` only | Targeted pytest and Ruff | accepted after hardening | `/root/accuracy_math_impl` |
| L5 | Internal delegate | `gpt-5.6-luna` / high | Deterministic W3 provenance/dataset core on synthetic fixtures | Seven exclusive dataset/schema/test files | Determinism, contamination mutations, pytest, Ruff | accepted after two reworks | `/root/w3_dataset_core` |
| L6 | Internal delegate | `gpt-5.6-luna` / high | Offline paired A/B/C/D evaluator core | Four exclusive evaluator/schema/test files | Pair-identity mutations, denominator tests, pytest, Ruff | accepted after rework and L0 hardening | `/root/abcd_evaluator_core` |
| L7 | Internal delegate | `gpt-5.6-luna` / high | Conservative dependency closure for the exact 30-task slice | Metis read-only; five Model1 closure files on follow-up | 30 tasks, 201 inputs, one shared leakage group, poisoned-OID mutations | accepted after rework | `/root/w1_dependency_closure` |
| L8 | Internal delegate | `gpt-5.6-luna` / high | Exact 201-asset operational local-use classification | Asset module/schema/manifest/tests only; no source payload reads | 201/201, classification/hash mutations, schema validation | accepted after L0 schema hardening | `/root/w2_asset_classification` |
| L9 | Internal delegate | `gpt-5.6-luna` / high | Public-synthetic sequence-1024 fixture and real batch probe | Generator/test only; artifacts ignored; no training | raw/prefix/completion/batch/mask counts, identity and path mutations | accepted; L0 executed training probes | `/root/seq1024_fixture_probe` |
| L10 | Internal delegate | `gpt-5.6-luna` / high | Integrated read-only pilot validation and W5-readiness CLI | Pipeline/CLI/Makefile/tests only | Exact synthetic regeneration, blockers and exit semantics | accepted after K2 rework | `/root/pilot_cli_integration` |
| L11 | Internal delegate | `gpt-5.6-luna` / high | Evaluator, critical-veto, coherence and exact sign-test coverage | Evaluator test files only | 64 focused tests, Ruff/format, frontier rerun | accepted | `/root/evaluator_coverage_close` |
| L12 | Internal delegate | `gpt-5.6-luna` / high | Dataset lineage, split identity, oracle polarity and writer defenses | Dataset source/test only | 16 focused tests, adversarial parent cases, frontier rework | accepted after parent-group rework | `/root/dataset_lineage_close` |
| L13 | Internal delegate | `gpt-5.6-luna` / high | Standalone grid/store schemas and asset closure branches | Contracts/assets tests and contract validator only | 33 focused tests, unsafe mutations, Ruff/format | accepted | `/root/contracts_assets_close` |
| L14 | Internal delegate | `gpt-5.6-luna` / high | Pinned-commit `.metis` sourceability census | Metis Git objects read-only; report only | 199/199 paths/OIDs, candidate-root upper bound, status invariant | accepted | `/root/independence_source_census` |

## Transition log

| Seq | Lane | Transition | Evidence |
|---:|---|---|---|
| 1 | L0 | `PLANNED -> IN_PROGRESS` | User explicitly authorized local training and Kimi K3 second-team orchestration |
| 2 | L0 | `PREFLIGHT -> COMPLETE` | Repo/model/runtime/boundaries/output/gates recorded on active board |
| 3 | K1 | `PLANNED -> PREFLIGHT` | Kimi CLI `0.36.1`; alias `kimi-code/k3`; capability probe pending |
| 4 | K1 | `PREFLIGHT -> VERIFIED` | `verify-team.sh kimi`: write, JSONL stream and session-id probes passed |
| 5 | L1 | `PLANNED -> DISPATCHED` | Bounded 30-task source/OID and oracle-entrypoint census |
| 6 | L2 | `PLANNED -> DISPATCHED` | Bounded current-file and W3/evaluator gap inventory |
| 7 | K1 | `VERIFIED -> DISPATCHED` | Protocol wrapper, activity `metis-model1-accuracy99-pilot`, 7200 s budget |
| 8 | L4 | `PLANNED -> DISPATCHED` | Exact scorer contract; two-file disjoint ownership |
| 9 | L1 | `DISPATCHED -> RETURNED -> FRONTIER_CHECK -> ACCEPTED` | Root recomputed 30/30 task/path/OID matches; missing task-oracle harnesses retained as blockers |
| 10 | L2 | `DISPATCHED -> RETURNED -> FRONTIER_CHECK -> ACCEPTED` | Root confirmed CLI-only foundation surface and accepted dependency-ordered W3/evaluator roster |
| 11 | L4 | `DISPATCHED -> RETURNED -> FRONTIER_CHECK -> REWORK` | Initial 13 tests green; root found mutability and non-finite/target-shape fail-closed gaps |
| 12 | L5 | `PLANNED -> DISPATCHED` | W3 core limited to synthetic fixtures and disjoint files |
| 13 | L6 | `PLANNED -> DISPATCHED` | A/B/C/D offline evaluator limited to disjoint files |
| 14 | L4 | `REWORK -> RETURNED -> FRONTIER_CHECK -> ACCEPTED` | Immutability/non-finite/shape gaps fixed; root reran 31 tests and Ruff |
| 15 | L7 | `PLANNED -> DISPATCHED` | Exact task roster; conservative static dependency-closure census |
| 16 | K1 | `DISPATCHED -> RETURNED -> FRONTIER_CHECK -> ACCEPTED_WITH_CORRECTIONS` | 558 s, exit 0, source report SHA-256 `c5463bc0...`; concurrent L0 writer identified; Metis status count corrected from three to four entries |
| 17 | L7 | `DISPATCHED -> RETURNED -> FRONTIER_CHECK -> REWORK` | Whole-tenant closure accepted; initial task-local leakage signatures rejected because all 30 share one 201-input ancestor |
| 18 | L0 | `STRUCTURAL_PATH -> EXECUTED` | Read-only corpus `197/197`, errors `0`, two byte-identical isolated builds, 170 endpoints; semantic seal remains open |
| 19 | L7 | `REWORK -> RETURNED -> FRONTIER_CHECK -> ACCEPTED` | Exact tracked recomputation; all 30 tasks share one 201-input leakage group; poisoned task OID and group-drift mutations rejected |
| 20 | L5 | `DISPATCHED -> RETURNED -> REWORK x2 -> FRONTIER_CHECK -> ACCEPTED` | Exact family-oracle registry, deterministic provenance/splits and SFT-positive-only materialization; L0 reran mutations |
| 21 | L6 | `DISPATCHED -> RETURNED -> REWORK -> FRONTIER_CHECK -> ACCEPTED` | Per-task prompt roster, complete typed identity/evidence, critical failure taxonomy and all paired deltas; L0 fixed schema and veto edge cases |
| 22 | L8 | `PLANNED -> DISPATCHED -> RETURNED -> FRONTIER_CHECK -> ACCEPTED` | `201/201` exact closure-derived assets; L0 caught and fixed per-record schema mismatch before acceptance |
| 23 | L9 | `PLANNED -> DISPATCHED -> RETURNED -> FRONTIER_CHECK -> ACCEPTED` | Real processor rendered 7,414 tokens and batch retained 1,004 completion tokens at length 1,024 |
| 24 | L0 | `W4_SEQ1024 -> EXECUTED` | Rank-8 step1/resume-step2 and rank-16 step1 finite; peaks 94.43-95.04 GB; payload hashes matched manifests |
| 25 | L0 | `O-005/O-006 -> RATIFIED` | Pre-candidate four-config grid/700-step cap and measured atomic local artifact policy; O-003 remains sole W5 decision blocker |
| 26 | L10 | `PLANNED -> DISPATCHED` | Read-only integrated validation and explicit blocked-readiness command |
| 27 | L10 | `DISPATCHED -> RETURNED -> FRONTIER_CHECK -> ACCEPTED` | L0 reviewed exit semantics, added unreadable-fixture hardening, formatted and reran `make check`: 105 passed |
| 28 | K2 | `PLANNED -> VERIFIED -> DISPATCHED` | Existing Kimi capability pin reused; no local writer remains; final read-only integration brief dispatched through protocol wrapper |
| 29 | K2 | `DISPATCHED -> RETURNED -> FRONTIER_CHECK -> REWORK` | 1,015 s; K2 confirmed P0 standalone closure/assets poisoning, ten P1 coverage gaps and eight P2 hardening items; source report hash `23d11be2...` |
| 30 | L11/L12/L13 | `PLANNED -> DISPATCHED -> RETURNED -> FRONTIER_CHECK -> ACCEPTED` | Disjoint remediation lanes; L0 integrated exact Git reanchor, policy constants and 29 additional regression tests |
| 31 | K3 | `PLANNED -> DISPATCHED -> RETURNED -> FRONTIER_CHECK` | 538 s; both P0 attacks and all enumerated remediations re-executed; report hash `3756f117...` |
| 32 | L0/L12 | `FRONTIER_CHECK -> REWORK` | Root found same-split parent-example group inflation missed by K3; child must share parent split and leakage group |
| 33 | K3 | `RESUMED -> RETURNED -> FRONTIER_CHECK -> ACCEPTED` | 183 s; 9/9 lineage assertions, 16/16 focused tests, K3 corrected its earlier statement; report hash `863807b0...` |
| 34 | L14 | `DISPATCHED -> RETURNED -> FRONTIER_CHECK -> ACCEPTED` | Pinned census 199/199 `.metis` files, three syntactic roots, at most two defensible ancestry roots; current corpus cannot reach 563 |
| 35 | L0 | `FINAL_GATES -> COMPLETE_WITH_W5_BLOCKED` | `make check` green with 134 tests; validate exit 0, assess exit 1; five evidence blockers retained; no commit/push |
| 36 | L0/W4 L6-L8 | `FULL_STATE_FINDINGS -> FIXED -> CLEAN -> BIT_EXACT_RECHECK` | Current wrapper `af6053b...`; independent audit no P0/P1; uninterrupted 4 versus split 2+resume 4 report `504508b6...`; final gates and Metis no-write invariant reconfirmed |
