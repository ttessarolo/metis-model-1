# Metis Brain interactive session memory ledger

| Lane | Owner | Model / effort | Scope | Writable surface | Verification | Status |
|---|---|---|---|---|---|---|
| L0 | Root coordinator | frontier / maximum | Architecture, session-memory semantics, integration, live VS Code, full gates, commit/push | board/docs plus integrated Model 1 files | independent diff, focused/full gates, real no-Apply UI | active |
| L101 | Page semantics audit | `gpt-5.6-luna` / high | Exact `take page default N` and tenant precedence census | none | grammar, IR, runtime and tenant setting evidence | done |
| L102 | Interactive core census | `gpt-5.6-luna` / high | Pending-question/session-memory state machine and server roster | none | current-source file/range audit | done |
| L103 | Visix consumer census | `gpt-5.6-luna` / high | Typed question UI and same-session client delta | none | current-source/client contract audit | done |
| L104 | Interactive core implementation | `gpt-5.6-sol` / maximum | One-shot state, lineage, output contract, lifecycle and server wire | bounded Model 1 Brain source/tests | focused Brain suite and L0 diff review | integrated |
| L105 | Output parser fuzz | `gpt-5.6-sol` / inherited | Unicode signs and numeric surface adversarial probes | output parser plus focused tests only | focused parser/orchestrator suite | done |
| L106 | Claim/lifecycle audit | `gpt-5.6-sol` / inherited | Queued answer claims, worker errors and cleanup | none | read-only source audit plus L0 regressions | done |
| L107 | Visix interactive consumer | `gpt-5.6-sol` / inherited | Strict schema-2 parser, native Quick Pick/input and proposal-basis resume | isolated Metis tooling worktree only | Brain chat suite, typecheck and VSIX package | integrated |
| L108 | Final architecture audit | `gpt-5.6-sol` / maximum | Bounded adversarial review of current wave | none | P0/P1/P2 roster and final verdict | done |

## Global exclusions

No lane may persist conversation state; read credentials, `.env`, Keychain or
live data; write/apply to a tenant; start training; mutate/download weights;
use Ollama/remote fallback; touch Metis Fast; commit, push or promote without an
explicit L0 integration decision.
