# Metis Brain latency promotion ledger

| Lane | Owner | Model / effort | Scope | Writable surface | Verification | Status |
|---|---|---|---|---|---|---|
| L0 | Root coordinator | frontier / maximum | architecture, semantics, implementation, live benchmark, VS Code proof, promotion and delivery | integrated Model 1 source/tests/docs/config/board | focused gates, frozen live roster, `make check`, post-push alignment | active |
| L601 | MLX speculative census | delegated `gpt-5.6-luna` / medium | installed prompt-lookup/speculative API and compatibility | none; read-only | file/line evidence and fail-closed verdict | done: speculative STOP, prefix candidate only |
| L602 | Benchmark census | delegated `gpt-5.6-luna` / medium | same-snapshot A/B receipt and timing seams | none; read-only | file/line evidence and minimal runner plan | done |
| L603 | Isolation/progress census | delegated `gpt-5.6-luna` / medium | cache isolation, heartbeat/events and VS Code seam | none; read-only | P0/P1/P2 audit and test roster | done |
| L604 | Latency fixture migration and final roster census | delegated `gpt-5.6-luna` / high | mechanical migration to shape oracle/two-preflight receipt; final read-only diff census | latency test files only during implementation; none during census | focused pytest, Ruff, `in/out/distinct/gaps` | done: focused GREEN; roster `27/0/27/0`, P0=0 P1=0 |
| L605 | Adversarial red-team | delegated frontier / maximum | output authority, receipt lineage, SSE ordering, cache and telemetry claims | none; read-only | P0/P1/P2 findings and closure re-audit | done: P0=0 P1=0; receipt publication GREEN |
| L606 | Lossless renderer reception audit | delegated frontier / maximum | handover identity, evidence, probes, independent byte claim and Brain seam | none; read-only | 13-file census, five pinned probes, P0/P1 verdict | done: local artifact GREEN; Brain pin/wiring STOP, P0=0 P1=4 |

## Global exclusions

Delegated lanes may not edit, commit, push, promote, execute the model, access a
tenant, use network/Ollama/remote fallback, read credentials/`.env`/Keychain,
download payloads, train, Apply or modify another repository. L0 alone may run
the bounded local model and read-only tenant/VS Code qualification authorized by
the owner.
