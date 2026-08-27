# Video catalog semantics execution ledger

| Lane | Owner | Model / effort | Scope | Writable surface | Verification | Status |
|---|---|---|---|---|---|---|
| L0 | Root coordinator | frontier / maximum | Architecture, integration, gate verdicts and final review | root/active boards, this ledger, `src/metis_model1/contracts.py`, `src/metis_model1/cli.py` | inspected the integrated diff; reran `56/56`; independently recomputed fixture and bridge claims; ran foundation, privacy and publication audits | verified; publication pending |
| L1 | Static-contract delegate | `gpt-5.6-luna` / high | Ten semantic schemas, deterministic synthetic fixtures, contract loaders and structural benchmark builder | `schemas/video-semantics-*.schema.json`, `schemas/video-editorial-*.schema.json`, `schemas/video-catalog-*.schema.json`, `schemas/video-grounding-*.schema.json`, `manifests/video-semantics-sources-v1.json`, `fixtures/video-catalog-semantics-v1/**`, `src/metis_model1/video_semantics_contracts.py`, `src/metis_model1/video_grounding_benchmark.py`, `tests/test_video_semantics_contracts.py`, `tests/test_video_grounding_benchmark.py` | dedicated tests green; ten-schema and `10/10/10/0` fixture roster; digests, self-hashes and invalid fixtures covered | accepted by L0 and L3 |
| L2 | Offline census-boundary delegate | `gpt-5.6-luna` / high | Fail-closed P4A bridge contract and fake/canary boundary tests | `src/metis_model1/video_census_bridge.py`, `tests/test_census_bridge_boundary.py`, `tests/test_frontier_egress_boundary.py` | dedicated tests green; receipt schema/self-hash valid; exact allowlists, profile pins, denial and leakage counters covered | accepted by L0 and L3 |
| L3 | Independent audit | frontier / maximum | Read-only semantic, security, privacy and gate review | none | initial rejection drove corrections; final re-audit `ACCEPT`; no protected or live access | complete |

## Global exclusions

No lane may read or write reserved editorial sources, credentials, `.env`,
credential stores, raw tenant/live payloads, model weights, adapters,
checkpoints, materialized datasets, another repository, or any unlisted path.
Delegates do not commit or push.
