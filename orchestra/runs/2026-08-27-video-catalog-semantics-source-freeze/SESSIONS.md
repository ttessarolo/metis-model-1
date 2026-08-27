# Video catalog semantics source-freeze ledger

| Lane | Owner | Model / effort | Scope | Writable surface | Verification | Status |
|---|---|---|---|---|---|---|
| L0 | Root coordinator | frontier / maximum | Architecture, privacy, semantic/gate integration, run board, CLI integration and publication | root pointer, this run directory, explicitly integrated source/test files | independent upstream rerun, diff inspection, privacy scan, real CLI, `make check` | active |
| L1 | Grammar gate auditor | `gpt-5.6-luna` / high | Read-only promoted grammar evidence census | none | same-SHA HEAD/remote check plus four-gate evidence roster | complete; accepted after L0 rerun |
| L2 | Private-I/O gap auditor | `gpt-5.6-luna` / high | Read-only P0/P1 implementation-gap census | none | `39` targeted tests plus source/API inspection | complete; findings accepted |
| L3 | Snapshot auditor | frontier reviewer / maximum | Read-only structural tenant snapshot census | none | clean snapshot, aggregate structure roster, fail-closed P2 verdict | complete; P2 remains open |
| L4 | Private-I/O implementer | `gpt-5.6-luna` / high | Synthetic-only secure store primitives and tests | `src/metis_model1/video_private_io.py`, `tests/test_video_private_io.py` | `29/29` plus L7 exact race reruns | complete after L0 repair and independent acceptance |
| L5 | Source-acquisition implementer | `gpt-5.6-luna` / high | Synthetic-only bounded roster, private envelope and receipt builder | `src/metis_model1/video_source_acquisition.py`, `tests/test_video_source_acquisition.py` | `32/32`, deterministic identity, benign-ancestor stability, unsafe-mode rejection, safe public output and bool/int tamper rejection | complete; accepted by L0 and L7 |
| L6 | Integration runner | L0 frontier / maximum | Private bundle persistence, freeze, source extraction, ontology validation and CLI | `src/metis_model1/video_semantics_private_runner.py`, CLI/contracts and integration tests | real acquire/freeze/extract plus idempotent independent replay and Git-ignore proof | P0 and source-text preflight complete; ontology open |
| L7 | Independent security reviewer | frontier / maximum | Leak, race, CLI and integrated-gate review | none | adversarial review plus `180/180` exact integrated roster, Ruff/format/diff and final gate verdict | complete; P0/source-freeze/extraction-preflight accepted, ontology remains open |
| L8 | Source-text extraction implementer | `gpt-5.6-luna` / high | Synthetic-only bounded local extraction primitives | dedicated extraction source/test files only | `24/24`, real macOS canaries, declared parser-family smoke, private envelope validation | complete; accepted by L0 and L7 |
| L9 | Local ontology-worker designer | frontier reviewer / maximum | Read-only exact-model no-egress design and model-routing decision | none | worker/profile/canary/receipt gap roster | complete; base-only decision accepted, implementation open |
| L10 | Upstream retrieval observer | `gpt-5.6-luna` / high | Read-only successor schema-2 status census | none | commit/status/test evidence without consuming dirty state | complete; candidate green, promotion and test-chain adoption open |
| L11 | Ontology-worker harness implementer | frontier / maximum | Synthetic-only dedicated worker harness | two proposed new source/test files | explicit tracked-only reads and synthetic tests | invalidated and interrupted after reported private-metadata scope crossing; no output accepted |
| L12 | Extraction integrator | `gpt-5.6-luna` / high | Wire bounded source extraction into the fixed private runner and CLI | runner, CLI/contracts and dedicated integration tests | `14/14`, Ruff and diff check before L0 integration | complete; integrated and reverified by L0 |
| L13 | Unit-disposition implementer | `gpt-5.6-luna` / high | Exact private disposition roster for every extracted unit | tooling/private runner and their dedicated tests | `46/46`; exact in/out/distinct/gaps plus partial-unit and no-roster adversarial repros | complete; accepted by L0 and L7 |
| L14 | Git-boundary provenance implementer | `gpt-5.6-luna` / high | Pin and sterilize the Git authority used by private-store pre/postflight | private-artifact boundary and its dedicated tests | `15/15`; fake-PATH, hostile `GIT_*` environment and user-owned authority adversaries | complete; accepted by L0 and L7 |

## Global exclusions

No delegate may open confidential source content, inspect ignored private
artifacts, read credentials or `.env`, call live services, write another
repository, commit, push or promote a gate. Confidential acquisition and any
future local no-egress semantic processing remain L0-controlled operations.
