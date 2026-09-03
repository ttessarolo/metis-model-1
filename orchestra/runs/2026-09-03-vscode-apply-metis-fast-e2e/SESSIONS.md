# VS Code Apply and Metis Fast real E2E ledger

| Lane | Owner | Model / effort | Scope | Writable surface | Verification | Status |
|---|---|---|---|---|---|---|
| L0 | Root coordinator | frontier / maximum | architecture, source-role decision, gates, integration and final verdict | Model 1 board/docs plus reviewed integration | independent diff/gate recomputation | done |
| L801 | VSIX Apply census | delegated `gpt-5.6-luna` / high | current client Apply/CAS/recompile/undo implementation and safe gate | none; read-only | exact source/test roster | done |
| L802 | Metis Fast protocol census | delegated `gpt-5.6-luna` / high | schema-1 versus universal Brain schema-2 delta | none; read-only | contract/UI/test matrix | done |
| L803 | Metis Fast runtime census | delegated `gpt-5.6-terra` / high | preview, acceptance, runtime/palinsesto ownership and E2E boundary | none; read-only | architecture/source evidence | done |
| L804 | VSIX Apply closure | delegated `gpt-5.6-luna` / high | executable Apply/CAS/post-compile/rollback/Undo contract | isolated Metis worktree, Apply-related extension source/tests only | brain-chat, typecheck, esbuild, diff check | done |
| L805 | Metis Fast universal protocol | delegated `gpt-5.6-luna` / high | strict schema 2, `/answer`, SSE, recovery and multi-turn UX | isolated Metis Fast worktree, client/UI/fake/tests/README only | test 7/7, typecheck, build, diff check | done |
| L806 | `@video_pg` projection v2 | delegated `gpt-5.6-terra` / high | exact finite-domain compatibility and current read-only receipt | Model 1 projection source/test/policy/manifest plus `docs/25` only | focused tests, contracts, ruff, current CLI replay, diff check | done |
| L807 | Metis Fast trusted acceptance/runtime | delegated `gpt-5.6-terra` / high | BFF credential boundary, volatile tenant materialization, compile/preview and temporary channel | isolated Metis Fast worktree after L805 | deterministic adversarial E2E, test, typecheck, build, diff check | done |
| L808 | Lossless parser-limit determinism | delegated `gpt-5.6-luna` / high | make the renderer fail-closed at the same explicit nesting limit on supported Node runtimes | isolated Metis worktree, `tooling/src/lossless/**` and focused lossless tests only | focused Node 22 + Node 26, typecheck, diff check, then full suite by L0 | done |
| L809 | Metis Fast adversarial review | delegated `gpt-5.6-terra` / high | independent read-only authority, process, cleanup and wire-shape review | none; read-only | source anchors plus focused gate replay | done |
| L810 | Metis `0.24.1` release census | delegated `gpt-5.6-luna` / high | version, generated-asset pin, tag and post-merge command audit | none; read-only | exact diff/hash/tag roster | done |
| L811 | Fast -> real Brain multi-turn Draft | delegated `gpt-5.6-luna` / high, completed by L0 | real local BFF, complex existing-endpoint proposal and proposal-based refinement; no materialization | no tracked writes; local services only | compiled/grounded terminal receipts, source assertions, tenant unchanged, teardown | done |
| L812 | Brain toolchain pin 0.24.1 | L0 frontier + delegated read-only audit | versioned current pin after live startup exposed v1/runtime mismatch | Model 1 pin/schema/tests/current addendum only | 29 evidence, 9 archive probes, startup and full repository gate | done |
| L813 | Dual test authority closure | L0 frontier + delegated `gpt-5.6-luna` review | keep active Brain 0.24.1 and historical oracle runtime independently pinned after release | Model 1 Makefile, harness and focused tests only | real harness probe, full `make check`, independent fail-closed audit | done |

## Global delegated exclusions

No delegated lane may start services, install a VSIX, use network or credentials,
read `.env`/Keychain, write a tenant, run `tenant:vendor`, download a model,
train, commit, push, merge, delete or clean administrative Git state unless a
later ledger row gives an exact disjoint writable mandate.
