# Play-prod semantic readiness ledger

| Lane | Owner | Model / effort | Scope | Writable surface | Verification | Status |
|---|---|---|---|---|---|---|
| L0 | Root coordinator | frontier / maximum | authority, architecture, integration, gates, commit/push and verdict | bounded cross-repo surfaces declared on board | independent diff, compile/semantic gates, sealed replay | active |
| L1001 | Metis semantics contract audit | delegated frontier peer | grammar-to-projection inheritance and structural gaps | none; read-only | exact source/test anchors and P0/P1/P2 | done; first-class inheritance reaches schema-2 retrieval |
| L1002 | Play-prod semantic census | delegated frontier peer | catalog/source compatibility, semantic/domain denominators and provenance | none; read-only | deterministic census and file-level patch plan | done; controlling disposition recorded in L1006 |
| L1003 | Brain semantic gate audit + bounded repair | delegated frontier peer | schema-2 validation, authoritative existing-source catalog roster and universal catalog overflow | Brain runtime/retrieval/clarification/tests plus this board/ledger; no tenant/model/network | 862 Brain tests, synthetic cross-layer runner, upstream semantics-from gate, diff/lint/format | done bounded scope; compiler-IR occurrence manifest remains STOP; full make check awaits clean shared Metis authority |
| L1004 | Compiler-owned occurrence grounding | delegated frontier peer | private single-compile candidate manifest and adversarial structural comparison | Brain runner/compiler bridge/grounding plus focused tests and board evidence; no orchestrator/model/network | 160 focused tests, real read-only complex compile, Ruff/Prettier/digest/diff | done; orchestrator/output-contract hook handed to L0 |
| L1005 | Compiler-manifest orchestration integration | delegated frontier peer | one candidate compile, private baseline/basis manifest lifecycle and complex preservation | Brain orchestrator/turn store/output contract, named session-isolation fake plus focused tests; no model/network/tenant mutation | 498 Brain integration tests, Ruff/format/diff, independent L0 review | done; hard-qualification fake remains with L0 |
| L1006 | Catalog/list authority audit | delegated lower-cost mechanical lane | prove whether questioned video fields have canonical exhaustive same-tenant domains | none; read-only | exact catalog/list/endpoint census, byte parity and semantic domain probes | done; 2 SAFE already complete, 6 NOT SAFE to materialize |
| L1007 | Hard qualification v2 census | delegated lower-cost mechanical lane | exact v1-to-v2 sealed profile patch map and fairness census | none; read-only | paths, hashes, assertions and 10-journey denominator | done; immutable v1 preserved, v2 patch map delivered |
| L1008 | Compiler manifest adversarial audit | delegated frontier peer | full IR coverage, exact catalog authority, create refinement and qualification soundness | none; read-only | 421 focused tests, Ruff, pin/diff audit and P0/P1/P2 verdict | done; RED on three architectural P0s |
| L1009 | Static retrieval preflight | delegated lower-cost mechanical lane | frozen 40-message retrieval/grounding census without Model 1 | none; read-only | exact action/status roster and enrichment disposition | done; diagnostic only, no catalog patch justified |
| L1010 | Explicit v2 oracle adversarial audit | delegated lower-cost mechanical lane | cumulative exact oracle coverage without hidden reference | none; read-only | ten-journey false-green matrix and minimal patch map | done; exact edit oracles sealed, CREATE remains non-promotable |
| L1011 | Typed incremental delta architecture | delegated frontier peer | production-safe existing EditPlan and CREATE refinement authority | none; read-only | concrete types, lifecycle, invariants and test map | done for existing edits; CREATE successor remains STOP |
| L1012 | Compiler edit-surface bridge | delegated bounded implementation lane | deterministic private projection for the four real edit primitives | `runtime/metis_brain/runner.mts`, `tests/test_brain_runner_schema2.py` only | focused runner tests, format, digest handoff | done; runner `f20c5fe8` |
| L1013 | DeltaPermit contract | delegated bounded implementation lane | closed single-use revision-bound delta capability | new permit module and its new focused test only | adversarial unit matrix, Ruff | done; one-shot and exact-role gates green |
| L1014 | Private turn lifecycle hardening | delegated bounded implementation lane | atomic private manifest/permit publication and close/cancel/TTL erasure | turn store and named lifecycle tests only | concurrent lifecycle tests, Ruff | done; close/cancel/TTL erasure green |
| L1015 | Real ten-edit planner preflight | delegated lower-cost mechanical lane | exact edit-surface selection and full-source render against play-prod-v2 | none; read-only | 10/10 byte-exact oracle, tenant/hash guards | done; 10/10 in 58.742 s |
| L1016 | Lossless qualification route | delegated bounded implementation lane | bind v2 PASS_DRAFT to compiler proof and exact touched count | qualification runtime/tests only | positive path plus 14 proof mutations | done |
| L1017 | Authority cleanup hardening | delegated bounded implementation lane | bounded ENOTEMPTY retry and visible terminal cleanup failure | compiler bridge and focused tests only | synthetic retry/failure plus real capsule close | done |
| L1018 | Dual-pin full-suite certification | L0 plus delegated audit | isolate legacy and Brain Metis authorities; exact catalog answer | test harness/clarification/tests and board | 1120 Brain; 3271 pass + 2 skip; P0=0/P1=0 | done |
| L1019 | Sealed public HTTP ten-edit replay | L0 frontier / maximum | Draft + lossless apply + compile + exact oracle through Brain loopback | ignored runtime/evidence only; no Apply/tenant write | 10/10 PASS_DRAFT and before/after guards | pending after tested-tree commit |
| L1020 | Structural semantic-delta reconciliation | L0 plus delegated frontier audit | reconcile structural proof with reviewed terminal grounding without mutating raw retrieval | Brain lossless/structural/orchestrator modules, focused tests and docs/board | 1126 Brain tests, adversarial authority matrix, sealed replay | implemented; sealed replay pending |
| L1021 | Structural Flash bypass | L0 plus delegated read-only diagnosis | keep Flash out of compiler-owned structural instructions while preserving fail-closed ledger | orchestrator, focused tests and board | exact TVOD case plus 10-case sealed replay | implemented; sealed replay pending |

Delegated lanes may not edit, run models, use network/live data, touch tenants,
commit or push. L0 alone integrates after independent evidence converges.

L1003's writable surface was expanded explicitly by L0 after its read-only
audit; it made no commit or push and did not access a live tenant or model.

L1005's writable surface was expanded explicitly by L0 to the named
`tests/test_brain_session_isolation.py` fake only.  The lane made no commit or
push and did not run MLX, network, a live tenant or Apply.
