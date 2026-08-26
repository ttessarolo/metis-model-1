# Metis Brain tenant-session wave ledger

| Lane | Owner | Model / effort | Scope | Writable surface | Verification | Status | Session |
|---|---|---|---|---|---|---|---|
| L0 | Root coordinator | frontier / maximum | Architecture, plan, implementation, integration, gates, board and final verdict | project repository only | Rerun gates, recompute delegated claims, inspect diff | completed: `METIS_BRAIN_SESSION_CORE_V1` | `/root` |
| L1 | Internal delegate | `gpt-5.6-luna` / medium | Existing API/session seam census and deterministic test matrix | none; read-only | Exact routes, state invariants and tests | accepted after L0 source review | `/root/brain_session_api_census` |
| L2 | Internal delegate | `gpt-5.6-terra` / high | Pinned compiler and catalog retrieval reuse census | none; read-only | Exact pins, call sites, caps and smoke commands | accepted with L0 correction of 64-source cap | `/root/brain_compiler_census` |
| L3 | Internal security reviewer | `gpt-daybreak-blue-latest` / high | Local service/session threat model and hostile gate matrix | none; read-only | P0/P1 threats, TTL/races, secrets, paths and logs | accepted as implementation contract | `/root/brain_security_threats` |
| L4 | Internal security auditor | `gpt-daybreak-blue-latest` / xhigh | Independent hostile source/diff review after implementation | none; read-only | Raw HTTP reproduction, cleanup races, full finding roster | accepted: `in=3 out=3 distinct=3 gaps=0`, `P0=0 P1=0 P2=0` | `/root/brain_core_security_review` |
| L5 | Internal semantic auditor | `gpt-5.6-sol` / xhigh | Independent semantics, TTL, isolation and compiler nonclaim review | none; read-only | Focused replay, live compiler receipt, claim audit | accepted: `in=5 out=5 distinct=5 gaps=0` | `/root/brain_core_semantic_review` |
| L6 | Internal test/document census | `gpt-5.6-luna` / medium | Hostile test gaps, then canonical document drift census | none; read-only | Exact gap roster and `in/out/distinct/gaps` | accepted: `in=60 out=60 distinct=60 gaps=0` | `/root/brain_test_census` |
