# Video catalog semantics private-preparation ledger

| Lane | Owner | Model / effort | Scope | Writable surface | Verification | Status |
|---|---|---|---|---|---|---|
| L0 | Root coordinator | frontier / maximum | Architecture, semantic decisions, privacy boundary, CLI/foundation integration and gates | root pointer, this run directory, `src/metis_model1/cli.py`, `src/metis_model1/contracts.py`, integration tests and plan reference | inspected integrated diff; real CLI boundary; combined `96/96`; privacy scan; Ruff/format/diff; `make check` | verified; publication pending |
| L1 | Local tooling delegate | `gpt-5.6-luna` / high | Pure private-roster, bounded ontology and deterministic local-freeze tooling | `src/metis_model1/video_semantics_tooling.py`, `tests/test_video_semantics_tooling.py` | 24 dedicated tests, finite errors, Unicode/size/record/roster caps, public-output allowlist | accepted by L0 and L3 |
| L2 | Artifact-boundary delegate | `gpt-5.6-luna` / high | Public policy and executable fail-closed sentinel boundary | `manifests/video-private-artifact-policy-v1.json`, `src/metis_model1/video_private_artifacts.py`, `tests/test_video_private_artifacts.py` | 13 dedicated tests, global tracked-root and hardlink races, real CLI receipt, empty-root check | accepted by L0 and L3 |
| L3 | Independent reviewer | frontier / maximum | Read-only local-snapshot structure census plus semantic/security/privacy review | none | sanitized snapshot verdict; initial `REJECT` drove corrections; final `ACCEPT` for commit and boundary gate | complete |

## Global exclusions

No delegate may read confidential editorial inputs, emit source-specific
provenance, use network/live services, inspect credentials, write another
repository, or commit/push. L0 does not promote a delegated claim without an
independent check.
