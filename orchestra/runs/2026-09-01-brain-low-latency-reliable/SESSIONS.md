# Metis Brain reliable low-latency ledger

| Lane | Owner | Model / effort | Scope | Writable surface | Verification | Status |
|---|---|---|---|---|---|---|
| L0 | Root coordinator | frontier / maximum | architecture, semantic authority, integration, benchmarks, gates and promotion | integrated source/tests/docs/config/board | independent replay + full gates + local no-Apply E2E | implementation sealed GREEN; latency promotion open |
| L501 | Runtime/cache lane | delegated lower-cost | MLX in-memory prefix cache, lifecycle and startup prefill | runtime/cache source plus dedicated tests only | focused lifecycle/identity/adversarial tests | complete; L0 live qualification active |
| L502 | Bounded edit lane | delegated lower-cost | pinned AST/edit seam census and deterministic edit renderer | new edit modules plus dedicated tests only | preservation, decline and compiler fixtures | complete; unintegrated pending lossless CST seam |
| L503 | Context/plan red-team | delegated lower-cost | progressive reference and compact EditPlan authority design | new context/plan schema/modules/tests only | schema/adversarial/monotone-expansion tests | complete; v3 authority fixed, deliberately unintegrated |
| L504 | External architecture review | Qwen `qwen3.8-max` | independent critique of latency plan | no repository access; prose review only | tracked receipt + L0 reconciliation | complete; zero tool calls |
| L505 | External architecture review | Kimi `kimi-code/k3` | independent critique of latency plan | no repository access; prose review only | tracked receipt + L0 reconciliation | complete; assistant/meta only |
| L506 | External architecture review | Claude `claude-fable-5` | independent critique of latency plan | no repository access; prose review only | tracked receipt + L0 reconciliation | complete; tools disabled, zero web |

L503 evidence: focused `pytest` `17 passed`; Ruff check and format check green.
L0 independently matched the progressive full view to the live v3 runtime
projection. The lane remains deliberately unintegrated pending its promotion
gates.

## Global exclusions

Delegated lanes may not commit, push, promote, train, download or mutate model
payloads, use network/Ollama/remote fallback, read credentials/`.env`/Keychain,
write or Apply to a tenant, or modify another repository. L0 alone integrates
and issues verdicts.

L504-L506 are the sole exception to the network exclusion: one stateless,
tool-less response each to the common sterilized brief. They may not inspect the
workspace or receive proprietary source/data.
