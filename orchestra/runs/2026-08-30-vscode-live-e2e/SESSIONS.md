# Metis Brain VS Code live E2E session ledger

| Lane | Owner | Model / effort | Scope | Writable surface | Verification | Status |
|---|---|---|---|---|---|---|
| L0 | Root coordinator | frontier / maximum | Architecture, boards, integration, real runtime/E2E, gates and promotion | active board plus explicitly integrated files | independent diff review, live receipts, full gates | code and authoritative 2320-test gate green; final VS Code Draft observation waiting on Mac unlock |
| L90 | MLX runtime adapter | `gpt-5.6-luna` / high | Persistent qualified worker adapter and bounded lifecycle tests | `src/metis_model1/brain_mlx_runtime.py`, `tests/test_brain_mlx_runtime.py` only | fake-worker protocol/adversarial lifecycle suite; L0 real load | done — `in=3 out=3 distinct=3 gaps=0` |
| L91 | Semantic snapshot retriever | `gpt-5.6-luna` / high | Snapshot-bound schema-2 bundle adapter, reviewed/draft and ownership tests | `src/metis_model1/brain_semantic_retrieval.py`, `tests/test_brain_semantic_retrieval.py` only | strict bundle/snapshot identity and retrieval tests | done — `in=6 out=6 distinct=6 gaps=0` |
| L92 | VSIX E2E packaging | `gpt-5.6-luna` / high | Isolated worktree version/package and real consumer harness | `/Users/tommasotessarolo/Developer/ares-matioska/metis-brain-visix/tooling` only | typecheck/build/chat/vsix tests and package-content audit | done — `in=3 out=3 distinct=3 gaps=0` |
| L93 | Candidate grounding adjudicator | `gpt-5.6-luna` / high | Exact finite-predicate output guard and adversarial tests | `src/metis_model1/brain_candidate_grounding.py`, `src/metis_model1/brain_orchestrator.py`, `tests/test_brain_candidate_grounding.py`, `tests/test_brain_orchestrator.py` only | exact-set/cardinality/operator/catalog adversarial suite; L0 full gate | done — independent final audit GREEN, P0=0 P1=0 P2=0 |
| L94 | Create Draft UX | `gpt-5.6-luna` / high | Single-document Draft for create; diff retained for replace | `/Users/tommasotessarolo/Developer/ares-matioska/metis-brain-visix/tooling` chat/apply command surface and tests only | focused chat tests, typecheck, VSIX content gate; L0 live UI | done — independent audit GREEN, VSIX 0.23.95 installed |
| L95 | Grounding operator contract audit | `gpt-5.6-luna` / high | Read-only schema-2 type/modifier and scalar/multi lowering census | no writable surface | projection/context reproduction plus grammar/validator/compiler references | done — `in=2 findings out=2 closed=2 gaps=0` |
| L96 | Interactive clarification census | `gpt-5.6-luna` / high | Read-only current protocol/clients census and bounded question policy | no writable surface | server, VSIX and Metis Fast wire evidence | done — catalog seed verified; generalized wave queued |
| L97 | Transaction FIFO preflight audit | `gpt-5.6-luna` / high | Read-only audit of early non-regular-leaf rejection and race safety | no writable surface | focused FIFO tests, Ruff, formatting and diff check | done — independent audit GREEN, P0=0 P1=0 P2=0 |

## Global exclusions

No lane may read credentials, `.env`, Keychain or raw live data; write a tenant;
start training; mutate or download weights; use Ollama/remote fallback; touch
Metis Fast or unrelated repositories; commit, push or promote without an
explicit L0 mandate.
