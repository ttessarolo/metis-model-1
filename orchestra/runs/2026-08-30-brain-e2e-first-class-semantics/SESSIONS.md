# Metis Brain end-to-end session ledger

| Lane | Owner | Model / effort | Scope | Writable surface | Verification | Status |
|---|---|---|---|---|---|---|
| L0 | Root coordinator | frontier / maximum | Architecture, semantic contract, trust boundary, integration, gates and promotion | active board/docs and explicitly assigned integration files | diff review, independent denominator, focused adversarial gates, full gates, real E2E | in progress |
| L81 | Metis native semantics census | delegated frontier-compatible / inherited | Read-only grammar, AST, validator, formatter, retrieval and runtime-invariance census | none | exact paths, current concurrency, minimal test matrix | completed / accepted |
| L82 | Brain inference census | delegated frontier-compatible / inherited | Read-only Brain/session/retrieval/model/compiler/API census | none | exact reusable modules, sealed exclusions, proposed E2E seam | completed / accepted |
| L83 | Consumer census | delegated frontier-compatible / inherited | Read-only Visix and Metis Fast/atomic player repository and protocol census | none | repo identity, ownership conflicts, launch/test seam | completed / accepted |
| L84 | Native `semantics from` implementation | `gpt-5.6-luna` / high | Grammar, effective semantic resolver, validator, formatter, retrieval and invariance tests in isolated Metis worktree | bounded Metis language/retrieval/test files only | positive/negative resolver matrix, formatter idempotence, schema-2 provenance, R8 and full gates | completed / accepted / pushed `e42d7a40` |
| L85 | Brain turn runtime implementation | `gpt-5.6-luna` / high | Additive async turn protocol, safe events, injected retrieval/model/compiler orchestration and apply preflight | bounded Brain runtime modules/tests only | fake dependency E2E, idempotency/cancel/repair/SSE/adversarial tests | completed / accepted as protocol foundation; production MLX and semantic retrieval remain open |
| L86 | Metis Fast bounded vertical slice | `gpt-5.6-luna` / high | New successor UI and typed Brain client; predecessor read-only | `/Users/tommasotessarolo/Developer/metis-fast` only | typecheck, unit contract tests, build, fake/gateway smoke | completed / accepted / pushed `ee9e05b` |
| L87 | Visix `@metis` implementation | `gpt-5.6-luna` / high | Native Chat Participant, Brain lifecycle/client, diff/apply boundary | isolated `metis-brain-visix` tooling/extension/test surface only | typecheck, focused contract tests, VSIX build and Extension Host smoke | completed / accepted / pushed `c9f410a9` |
| L88 | `video_pg` semantic-source migration | delegated frontier-compatible / inherited | Replace duplicated field semantics with native `semantics from @video` | `play-demo/catalogs/video_pg.metis` only | 40-field exact roster, effective domains/values, whole-tenant validation and R8 invariance | completed / accepted / pushed `6b263c0` |
| L89 | Brain toolchain pin | `gpt-5.6-luna` / high | New immutable Brain-specific Metis pin and fail-closed verifier | four new manifest/schema/module/test files only | schema/hash/version/commit/tree verification plus tamper negatives | completed / L0 corrected delegate SHA and verified live against `c9f410a9` |

## Global exclusions

No delegate may read credentials, `.env`, Keychain, live data or raw production
payloads; start training or download a model; mutate weights; commit, push or
promote; write another lane's files; or accept compile-clean as semantic proof.
