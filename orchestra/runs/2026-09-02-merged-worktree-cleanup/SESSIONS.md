# Merged worktree and branch cleanup ledger

| Lane | Owner | Model / effort | Scope | Writable surface | Verification | Status |
|---|---|---|---|---|---|---|
| L0 | Root coordinator | frontier / maximum | target validation, destructive cleanup, independent recomputation and final verdict | exact merged worktree/branch metadata plus this board | ancestry, clean status, normal remove/delete, post-state | done: 7 worktrees removed, 35 local branches removed, 1 record pruned; main-only worktree state |
| L701 | Cleanup preflight | delegated `gpt-5.6-luna` / medium | exact merged target and safe order census | none; read-only | branches, worktrees, dirty/untracked, prune dry-run | done: 31 merged branches, 3 clean physical worktrees, 1 prunable record |
| L702 | Unmerged branch census | delegated `gpt-5.6-luna` / high | four unmerged histories and patch-equivalence analysis | none; read-only | ahead/behind, merge-base, unique commits/files | done: four one-commit tips all patch-equivalent; DO NOT MERGE |
| L703 | Unmerged intent audit | delegated `gpt-5.6-luna` / medium | historical purpose and successor evidence | none; read-only | branch boards/docs/logs versus current main | done: all four historical lanes already absorbed and later evolved on main |

## Global exclusions

No delegated lane may edit, fetch, merge, delete, prune, commit, push, run a
service, access a tenant or read credentials. The four unmerged worktrees and
all remote refs are immutable in this wave.
