# Metis Brain local-latency ledger

| Lane | Owner | Model / effort | Scope | Writable surface | Verification | Status |
|---|---|---|---|---|---|---|
| L0 | Root coordinator | frontier / maximum | Architecture, implementation, integration, performance verdict, live VS Code | Model 1 source/tests/docs/board | focused + full gates + real no-Apply smoke | active |
| L201 | MLX latency audit | `gpt-5.6-luna` / high | worker/load/generation/repair census | none | current-source evidence | done |
| L202 | Toolchain latency audit | `gpt-5.6-luna` / high | pin/isolation/retrieval/compiler census | none | timings and source evidence | done |
| L203 | E2E latency contract audit | `gpt-5.6-luna` / high | public events, UI phases and SLO proposal | none | server/client source evidence | done |
| L204 | Latency patch review | `gpt-5.6-luna` / high | authority lifecycle and telemetry red-team | none | exact findings + focused tests | done |
| L205 | Live benchmark harness | `gpt-5.6-luna` / high | safe direct-session benchmark design | none | API/path evidence | done |
| L206 | Latency implementation note | `gpt-5.6-luna` / high | bounded architecture/operations document | `docs/27-metis-brain-local-latency.md` | diff check | done |
| L207 | Deterministic fast-path red-team | `gpt-5.6-luna` / high | semantic bypass and candidate-surface audit | none | reproductions + focused tests | done |
| L208 | Final integrated latency audit | `gpt-5.6-luna` / high | read-only final diff review across authority, renderer, grounding, telemetry and lifecycle | none | actionable file/line verdict | done |

## Global exclusions

No lane may train, mutate/download weights, downgrade the model family, use a
remote or Ollama fallback, read credentials/`.env`/Keychain/live data, require
VPN, write or Apply to a tenant, touch Metis Fast, commit or push independently.
