# Catalog semantic closure session ledger

| Lane | Owner | Model / effort | Scope | Writable surface | Verification | Status |
|---|---|---|---|---|---|---|
| L0-G | Root coordinator | frontier / maximum | Architecture, semantic/privacy decisions, authoring, integration, gates and promotion | active board/docs plus four authorized tenant catalog files | exact census, collision review, schema-2 probes, compiler/R8 and repository gate | completed / accepted |
| L71 | Users/session census | `gpt-5.6-luna` / high | Read-only `users` and `user_session` field/use/privacy roster | none | `19/19` users nodes, `2/2` session fields, gaps `0`; privacy/domain disposition | completed / accepted |
| L72 | PostgreSQL mirror census | `gpt-5.6-luna` / high | Read-only `video_pg`/`video` mapping and current grammar reuse mechanism | none | `40/40` same-name fields, gaps `0`; one modifier exception; PG `19/19` | completed / accepted |
| L72-P | Semantic execution projection | `gpt-5.6-luna` / high | Pure fail-closed `@video` semantic -> `@video_pg` execution projection | two bounded Model 1 module/test files | synthetic exact-roster/tamper/receipt tests; no tenant I/O | completed; frontier-reworked / accepted |
| L73 | Smart/global collision census | `gpt-5.6-luna` / high | Read-only `smart_index` semantics and five-catalog alias risks | none | five catalogs, `167` top-level fields, `41` shared-name groups | completed / accepted |
| L73-R | Projection adversarial review | `gpt-5.6-luna` / high | Read-only fail-open, V2 receipt, binding and nested-roster review | none | found draft literal, receipt/binding and nested negative-test gaps | completed / accepted |

## Global exclusions

Delegates may not read credentials, `.env`, Keychain, live data, raw payloads
or reserved sources; write any repository; start a model; commit; push; or
promote a semantic decision.
