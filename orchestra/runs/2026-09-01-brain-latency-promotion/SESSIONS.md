# Metis Brain latency promotion ledger

| Lane | Owner | Model / effort | Scope | Writable surface | Verification | Status |
|---|---|---|---|---|---|---|
| L0 | Root coordinator | frontier / maximum | architecture, semantics, implementation, live benchmark, VS Code proof, promotion and delivery | integrated Model 1 source/tests/docs/config/board | focused gates, frozen live roster, `make check`, post-push alignment | checkpointed for host restart; resume only at installed `@metis` Draft gate |
| L601 | MLX speculative census | delegated `gpt-5.6-luna` / medium | installed prompt-lookup/speculative API and compatibility | none; read-only | file/line evidence and fail-closed verdict | done: speculative STOP, prefix candidate only |
| L602 | Benchmark census | delegated `gpt-5.6-luna` / medium | same-snapshot A/B receipt and timing seams | none; read-only | file/line evidence and minimal runner plan | done |
| L603 | Isolation/progress census | delegated `gpt-5.6-luna` / medium | cache isolation, heartbeat/events and VS Code seam | none; read-only | P0/P1/P2 audit and test roster | done |
| L604 | Latency fixture migration and final roster census | delegated `gpt-5.6-luna` / high | mechanical migration to shape oracle/two-preflight receipt; final read-only diff census | latency test files only during implementation; none during census | focused pytest, Ruff, `in/out/distinct/gaps` | done: focused GREEN; roster `27/0/27/0`, P0=0 P1=0 |
| L605 | Adversarial red-team | delegated frontier / maximum | output authority, receipt lineage, SSE ordering, cache and telemetry claims | none; read-only | P0/P1/P2 findings and closure re-audit | done: P0=0 P1=0; receipt publication GREEN |
| L606 | Lossless renderer reception audit | delegated frontier / maximum | handover identity, evidence, probes, independent byte claim and Brain seam | none; read-only | 13-file census, five pinned probes, P0/P1 verdict | done: local artifact GREEN; Brain pin/wiring STOP, P0=0 P1=4 |
| L607 | Lossless pin migration | delegated Codex frontier / inherited maximum | migrate Brain authority to exact Metis lossless delivery and execute the sealed probe roster | pin source/schema/manifest/tests only | 29/29 evidence, 9/9 real probes, focused Ruff/pytest | done: GREEN; probe receipt `03a3c626...` |
| L608 | Hard-prompt census | delegated Codex frontier / inherited maximum | read-only census of ten complex play-prod endpoints; edit prompt plus create/refine journey per endpoint | `examples/metis-brain-hard-prompts.play-prod-v1.json` only | tenant before/after identity, SHA/value/capability census, `10/10/10/0` | done: GREEN; no tenant write/model/network |
| L609 | Lossless/telemetry red-team | delegated Codex frontier / inherited maximum | adversarial hostref, inventory, receipt, event, preservation and fallback review | none; read-only | P0/P1/P2 reproduction and closure rerun | done: GREEN; P0=0 P1=0 P2=1 conservative refine restriction |
| L610 | Installed-proof target census | delegated `gpt-5.6-luna` / medium | read-only census of current `play-demo` endpoints for exact lossless eligibility | none; read-only | endpoint roster, source evidence and tenant identity | done: no persisted endpoint admitted; installed positive proof uses create Draft without pretending it is lossless |

## Global exclusions

Delegated lanes may not edit, commit, push, promote, execute the model, access a
tenant, use network/Ollama/remote fallback, read credentials/`.env`/Keychain,
download payloads, train, Apply or modify another repository. L0 alone may run
the bounded local model and read-only tenant/VS Code qualification authorized by
the owner.
