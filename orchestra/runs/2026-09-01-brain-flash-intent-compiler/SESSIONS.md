# Metis Brain Flash intent compiler ledger

| Lane | Owner | Model / effort | Scope | Writable surface | Verification | Status |
|---|---|---|---|---|---|---|
| L0 | Root coordinator | frontier / maximum | architecture, board, implementation, integration, local qualification, semantic verdict and promotion | Model 1 source/tests/docs/config/board; ignored public model/runtime artifacts only after pin review | focused suites + adversarial schema/semantic benchmark + local no-Apply E2E + `make check` | done — local development seal GREEN |
| L401 | Flash runtime census | `gpt-5.6-luna` / high | current Brain integration, lifecycle, config, health and test seams | none | exact path/line report and risk verdict | done — `in=1 out=1 distinct=1 gaps=0` |
| L402 | Runtime/checkpoint qualification | `gpt-5.6-luna` / high | constrained-decoder/runtime and Gemma 4 E4B checkpoint provenance/license/pin audit | none | primary-source evidence and reproducible qualification gates | done — static qualification; mlxcel rejected, direct llguidance selected |
| L403 | Intent IR semantic design | `gpt-5.6-luna` / high | closed IR, authority boundary, Italian ambiguity and adversarial roster | none | invariants, schema proposal and test census | done — `in=1 out=1 distinct=1 gaps=0` |
| L404 | Worker/IR red-team | `gpt-5.6-luna` / high | constrained worker, IR fail-closed and provenance attack review | none | P0/P1/P2 evidence and adversarial rerun | done — GREEN, prompt/control and logic findings closed |
| L405 | Brain wiring census | `gpt-5.6-luna` / high | exact lifecycle, session, answer, event and retrieval integration seams | none | path/line wiring roster | done — `in=1 out=1 distinct=1 gaps=0` |
| L406 | Direct local Flash probe | `gpt-5.6-luna` / high | bounded warmup plus five constrained local generations | ignored local checkpoint read only | JSON/schema/latency/Metal and host rejection evidence | done — `in=5 out=5 distinct=5 gaps=0` |
| L407 | Intent IR adversarial tests | `gpt-5.6-luna` / high | strict host validation suite | `tests/test_brain_intent_ir.py` only | Ruff + focused pytest | done — `74/74` green after frontier additions |
| L408 | Flash runtime lifecycle tests | `gpt-5.6-luna` / high | persistent worker supervision and failure modes | `tests/test_brain_flash_runtime.py` only | Ruff + focused pytest | done — `43/43` green |
| L409 | Brain Flash wiring tests | `gpt-5.6-luna` / high | config/startup/health/retrieval/orchestrator/session integration | `tests/test_brain_flash_wiring.py` only | Ruff + focused pytest | done — `10/10` green |
| L410 | Independent final audit | `gpt-5.6-terra` / high | full diff, authority, lifecycle, provenance and safety audit | none | P0/P1/P2 plus independent pin/test recomputation | done — final GREEN, `P0=0 P1=0 P2=0` |
| L411 | Documentation census | `gpt-5.6-luna` / medium | exact charter/roadmap/runbook/architecture integration map | none | stale-claim and insertion roster | done — `in=7 out=7 distinct=7 gaps=0` |
| L412 | Retrieval authority seam | `gpt-5.6-luna` / medium | prove exact source authority and advisory-query non-authority | `tests/test_brain_semantic_retrieval.py` only | targeted pytest + Ruff + diff-check | done — `65/65` retrieval suite green |
| L502 | Bounded edit renderer (successor-wave addendum) | `gpt-5.6-luna` / high | lossless source-span edit subset over host-issued grounding references | `src/metis_model1/brain_bounded_edit.py`, `tests/test_brain_bounded_edit.py`, append-only board/ledger entries | focused pytest + Ruff + format | done — transferred to active low-latency board; unintegrated |

## Global exclusions

Delegated lanes are read-only. No lane may train, mutate weights/adapters,
download a model, use Ollama or remote fallback, read credentials/`.env`/
Keychain/live data, require VPN, write or Apply to a tenant, touch external
repositories, commit, push or promote independently.
