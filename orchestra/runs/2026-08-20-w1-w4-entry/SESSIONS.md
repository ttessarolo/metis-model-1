# W1/W4 entry lane ledger

| Lane | Owner | Model | Enumerated task / roster | Exclusive scope | Verification | Status | Session |
|---|---|---|---|---|---|---|---|
| L0 | Root coordinator | Frontier | O-001/O-002/O-004 ratification, integration, W4 execution and gates | Current repo writes and local ML runtime | Diff, source recheck, staged telemetry, `make check` | completed | `/root` |
| L1 | Delegate | `gpt-5.6-luna` / high | Metis structural census and held-out proposal | Read-only Metis corpus | Denominators, leakage groups, rare/critical constructs | accepted | `/root/w1_o002_census` |
| L2 | Delegate | `gpt-5.6-luna` / xhigh | Exact MLX-VLM pin and CLI compatibility evidence | Read-only official/runtime evidence | Version constraints, CLI surface, known blockers | accepted | `/root/w4_o004_pin` |
| L3 | Delegate | `gpt-5.6-luna` / high | Non-sensitive micro-dataset and W4 harness contract | Read-only design review | Serializer/CLI fit, stop rules, artifact paths | accepted | `/root/w4_fixture_harness` |
| L4 | Delegate | `gpt-5.6-luna` / high | Adversarial W1/W4 foundation audit | Read-only code/contract review | Seven findings with path/telemetry/identity/seam checks | accepted | `/root/w1_w4_adversarial_audit` |
| L5 | Delegate | Frontier / xhigh | Full-state resume design and implementation | `qualification/train_full_state.py` | Toy optimizer/RNG continuation and root review | accepted after fixes | `/root/w4_full_resume_design` |
| L6 | Delegate | Frontier / xhigh | Strict full-state code audit | Read-only wrapper audit | P1/P2 findings, toy bit-exact control | accepted | `/root/full_state_code_audit` |
| L7 | Delegate | `gpt-5.6-luna` / high | Mechanical resume hardening checklist | Read-only current-file checklist | Precise P1/P2 locations | accepted | `/root/resume_hardening_checklist` |
| L8 | Delegate | Frontier / inherited | Final full-state adversarial audit | Read-only final wrapper audit | Model/runtime binding, RNG/sampler, manifest, finiteness | accepted / CLEAN | `/root/full_state_final_audit` |
| L9 | Delegate | `gpt-5.6-luna` / high | O-004 closure inventory | Read-only manifests/docs/tests inventory | Closure fields and boundary checklist | accepted | `/root/o4_closure_inventory` |

## Transition log

| Seq | Lane | Transition | Evidence |
|---:|---|---|---|
| 1 | L0 | `PLANNED -> IN_PROGRESS` | User mandate received; active board opened |
| 2 | L1 | `PLANNED -> DISPATCHED` | Enumerated O-002 census; session `/root/w1_o002_census` |
| 3 | L2 | `PLANNED -> DISPATCHED` | Enumerated O-004 pin/CLI evidence; session `/root/w4_o004_pin` |
| 4 | L3 | `PLANNED -> DISPATCHED` | Enumerated non-sensitive W4 fixture/harness design; session `/root/w4_fixture_harness` |
| 5 | L0 | `O-001 OPEN -> RATIFIED` | Metis `0.43` rechecked byte-for-byte at pinned commit; manifests updated |
| 6 | L3 | `DISPATCHED -> RETURNED` | Text-only 8-example fixture and four-stage W4 harness proposed; full-state resume gap identified |
| 7 | L1 | `DISPATCHED -> RETURNED` | Pinned census: 197 files, 170 endpoints, 0 validator errors; six families and 30-source allocation proposed |
| 8 | L0 | `O-002 OPEN -> RATIFIED` | Frontier reviewed six-family coverage and fail-closed leakage rules; distinct 30-source allocation contract added unsealed |
| 9 | L2 | `DISPATCHED -> RETURNED` | MLX-VLM `v0.6.15` CLI and compatibility surface returned; exact revision pre-download and adapter-only resume required |
| 10 | L0 | `W4 ENV CANDIDATE -> EXECUTED` | Isolated CPython 3.12.10 lock installed; exact package versions imported and live LoRA help passed |
| 11 | L1 | `RETURNED -> FRONTIER_CHECK -> ACCEPTED` | Root recomputed 30/30 source existence/blob identities, enforced six-by-five coverage and added fail-closed schema/cross-contract tests |
| 12 | L2 | `RETURNED -> FRONTIER_CHECK -> ACCEPTED` | Root resolved and imported the exact lock, executed live CLI help and kept O-004 open pending runtime evidence |
| 13 | L3 | `RETURNED -> FRONTIER_CHECK -> ACCEPTED` | Root generated the 8-row public fixture, loaded it through HF Datasets and implemented guarded telemetry/probe harnesses |
| 14 | L4 | `DISPATCHED -> RETURNED -> FRONTIER_CHECK -> ACCEPTED` | Root fixed all seven adversarial findings: artifact boundary, process-tree telemetry, model binding, static checks, board wording and seam ledger |
| 15 | L0 | `W4 CHECKPOINT -> VERIFIED` | Exact revision downloaded; config/tree metadata plus all three weight sizes and SHA-256 hashes matched the tracked pin |
| 16 | L0 | `FIRST BACKWARD -> BLOCKED` | Missing Jinja2 stopped before forward; failure preserved, no adapter created, Jinja2 `3.1.6` added to isolated lock |
| 17 | L0 | `BACKWARD -> 10 -> 50 -> 600 PASS` | Finite staged runs, corrected 600-sample RSS trend, adapter integrity and zero residual processes |
| 18 | L0 | `BASE -> ADAPTER -> ADAPTER_OFF PASS` | Canonical prompt produced `KESTREL -> QUAL_A -> KESTREL` with deterministic hashes in fresh processes |
| 19 | L5 | `DISPATCHED -> RETURNED` | Full-state atomic wrapper added optimizer, RNG, sampler and global-step persistence; toy continuation bit-exact |
| 20 | L6 | `DISPATCHED -> RETURNED` | Strict audit returned five P1 and P2 hardening findings; O-004 stayed open |
| 21 | L7 | `DISPATCHED -> RETURNED -> ACCEPTED` | Independent checklist confirmed the same remaining code obligations before real execution |
| 22 | L0 | `AUDIT FINDINGS -> FIXED` | Root bound exact model/runtime pins, disabled remote code, added payload manifests/fsync, finite-tree gates and sampler/RNG invariants |
| 23 | L0 | `REFERENCE 4 vs SPLIT 2+RESUME 4 -> BIT_EXACT` | Canonical state, adapter, config, semantic metadata and final loss matched exactly; report SHA-256 `504508b6...` |
| 24 | L8 | `DISPATCHED -> RETURNED -> FRONTIER_CHECK -> ACCEPTED` | Final audit returned `CLEAN` with no P0/P1; bounded dropout-0 limitation retained |
| 25 | L9 | `DISPATCHED -> RETURNED -> ACCEPTED` | Closure inventory reconciled manifests, docs, board, validator and explicit non-claims |
| 26 | L0 | `O-004 OPEN -> RATIFIED` | Exact runtime/checkpoint pin and bounded qualification packet recorded in `W4-QUALIFICATION.md` |
| 27 | L0 | `IN_PROGRESS -> COMPLETED` | Immediate O-001/O-002/O-004 wave closed; W1 slice remains fail-closed and unsealed |
| 28 | L0 | `POST_CLOSURE_RECHECK -> PASS` | Current wrapper hash `af6053b...`; bit-exact report hash `504508b6...`; `make check` 134/134 tests; Metis status invariant unchanged |
