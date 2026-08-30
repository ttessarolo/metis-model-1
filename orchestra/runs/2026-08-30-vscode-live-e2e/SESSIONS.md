# Metis Brain VS Code live E2E session ledger

| Lane | Owner | Model / effort | Scope | Writable surface | Verification | Status |
|---|---|---|---|---|---|---|
| L0 | Root coordinator | frontier / maximum | Architecture, boards, integration, real runtime/E2E, gates and promotion | active board plus explicitly integrated files | independent diff review, live receipts, full gates | E2E and promotion in progress |
| L90 | MLX runtime adapter | `gpt-5.6-luna` / high | Persistent qualified worker adapter and bounded lifecycle tests | `src/metis_model1/brain_mlx_runtime.py`, `tests/test_brain_mlx_runtime.py` only | fake-worker protocol/adversarial lifecycle suite; L0 real load | done — `in=3 out=3 distinct=3 gaps=0` |
| L91 | Semantic snapshot retriever | `gpt-5.6-luna` / high | Snapshot-bound schema-2 bundle adapter, reviewed/draft and ownership tests | `src/metis_model1/brain_semantic_retrieval.py`, `tests/test_brain_semantic_retrieval.py` only | strict bundle/snapshot identity and retrieval tests | done — `in=6 out=6 distinct=6 gaps=0` |
| L92 | VSIX E2E packaging | `gpt-5.6-luna` / high | Isolated worktree version/package and real consumer harness | `/Users/tommasotessarolo/Developer/ares-matioska/metis-brain-visix/tooling` only | typecheck/build/chat/vsix tests and package-content audit | done — `in=3 out=3 distinct=3 gaps=0` |

## Global exclusions

No lane may read credentials, `.env`, Keychain or raw live data; write a tenant;
start training; mutate or download weights; use Ollama/remote fallback; touch
Metis Fast or unrelated repositories; commit, push or promote without an
explicit L0 mandate.
