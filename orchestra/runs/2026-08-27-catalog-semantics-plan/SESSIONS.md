# Catalog Semantics planning ledger

| Lane | Owner | Model / effort | Scope | Writable surface | Verification | Status |
|---|---|---|---|---|---|---|
| L0 | Root coordinator | frontier / maximum | Architecture, surgical reconciliation, source placement, ambiguity/apply policy and final review | plan plus active boards/ledger | inspect diff, independently verify source, stale-contract roster and grammar dirty set | completed: `CATALOG_SEMANTICS_PLAN_SURGICALLY_RECONCILED` |
| L1 | Semantic contract delegate | `gpt-5.6-terra` / high | File-backed semantic schema, provenance, review states and gates | none; read-only | toolchain and plan evidence | completed and reviewed |
| L2 | Catalog census delegate | `gpt-5.6-luna` / medium | Enumerate tracked catalogs, values and current description mechanisms | none; read-only | exact tracked-file/AST census | accepted: `in=8 out=8 distinct=8 gaps=0` |
| L3 | Plan consistency delegate | `gpt-5.6-terra` / high | Protocol, wave, DoD and ambiguity review | none; read-only | independent finding roster | accepted after `P1=3 P2=2` closure |
| L4 | Native-source feasibility delegate | `gpt-5.6-terra` / high | Minimal in-source catalog/value description surface | none; read-only | grammar, hover, sync and retrieval evidence | accepted: `in=4 out=4 distinct=4 gaps=0` |
| L5 | Surgical plan contract delegate | `gpt-5.6-terra` / high | Canonical label/means/aka/state contract and stale occurrence roster | none; read-only | plan/source cross-check | completed and reconciled by L0 |
| L6 | Surgical protocol contract delegate | `gpt-5.6-terra` / high | Target preflight, idempotency, freshness, proposal/apply and CAS rollback | none; read-only | protocol/DoD cross-check | completed and reconciled by L0 |
| L7 | Grammar board handoff delegate | `gpt-5.6-luna` / high | Current grammar/sync delta and bounded G1/G2/G3 handoff | none; read-only | grammar diff and active-board cross-check | completed and reconciled by L0 |
| L8 | Grammar readiness auditor | `gpt-5.6-luna` / high | Current dirty-set implementation, missing G2/G3/schema-2 work and exact start/wait boundary | none; read-only | source, tests and grammar-board evidence | final `ACCEPT`; P1/P2 roster closed |
| L9 | Model 1 plan integration auditor | `gpt-5.6-luna` / high | Locate the vertical plan, reuse canonical gates and prevent historical-plan reopening | none; read-only | roadmap, active board and Brain/VSIX plan cross-check | final `ACCEPT`; one P2 tool-version ambiguity closed by L0 |
| L10 | Security/eval plan auditor | `gpt-5.6-luna` / high | SecretStorage bridge, read-only census, provenance, benchmark, rollback and hidden failure modes | none; read-only | code and contract evidence | final `ACCEPT`; atomicity, signed role, egress and CAS findings closed |
