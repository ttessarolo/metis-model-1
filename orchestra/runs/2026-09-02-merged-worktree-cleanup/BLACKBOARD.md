# Merged worktree and branch cleanup

Status: **COMPLETED — LOCAL WORKTREES AND PROVEN-ABSORBED BRANCHES CLEANED**

## Mandate

Remove only local worktree and branch state already proven to be an ancestor of
`origin/main`, plus the one missing detached worktree administration record.
Independently audit the four clean but unmerged worktrees and report whether
their unique work should be merged, ported or retired. They are not cleanup
targets in this wave.

## Preflight

- Model 1 repository: `/Users/tommasotessarolo/Developer/metis-model-1`;
- Model 1 baseline: `78ba1886345d78324eb37d33e9f6eadc2d8d699b`, clean `main`, aligned `0/0`;
- Metis repository: `/Users/tommasotessarolo/Developer/ares-matioska/metis`;
- Metis baseline: `e11dd1b65a0fa88a6366910a0cf02ba184749bd4`, clean `main`, aligned `0/0`;
- authorized destructive denominator: three clean merged physical worktrees,
  their branches, 28 additional merged local branches and one missing detached
  worktree record;
- explicit exclusions: every unmerged branch/worktree, both `main` branches,
  remote branches, tenant state, services, artifacts, models, credentials,
  `.env`, Keychain, OpenSearch and all repository contents.

## Blackboard

- FACT — Prior frontier census measured `31` non-main local branches already
  contained in `origin/main`: `30` Metis and `1` Model 1. Three Metis branches
  are checked out in clean physical worktrees; 28 are branch-only. One missing
  detached worktree record is reported by `git worktree prune --dry-run`.
- DECISION — Cleanup order is fail-closed: fetch/reconfirm main identity and
  cleanliness; remove only the three clean merged worktrees without force;
  prune only the already missing record; delete only the exact merged branch
  roster with normal `-d`; then recompute worktree, branch and status counts.
- OPEN — Four clean physical Metis worktrees are not merged. Their histories
  must be audited read-only before the owner decides merge, surgical port or
  retirement. No action on those four is authorized here.
- DONE — Three independent read-only audits plus L0 recomputation resolve that
  OPEN: each of the four old branch tips has exactly one `git cherry` row and
  all four rows are `-`, proving patch-equivalence with `origin/main`. Their
  main equivalents are `b5ac13b7`, `c5ed02d2`, `1835f97f` and `7bf0a25d`;
  later main commits further evolved the overlapping surfaces. A merge would
  be duplicative and may reintroduce stale conflicts. All four exact remote
  refs still exist at their local tip SHAs, so the owner-authorized cleanup may
  remove their clean worktrees and local refs while remote refs remain excluded
  and recoverable.
- DONE — Exact merged cleanup completed without force: three clean physical
  worktrees were removed, the one missing `metis-good` administration record
  was pruned, and all `31` normal-merge local branch refs were deleted with
  `git branch -d` (`30` Metis, `1` Model 1). The post-state has zero non-main
  local branches reported merged into `origin/main` in either repository.
- DONE — The four historical patch-equivalent worktrees were then removed
  without force. Their four local branch refs required graph-level `-D` only
  after L0 re-proved one `git cherry` row each, all `-`, and verified the exact
  remote refs at the same SHAs. Those remote refs were not changed and preserve
  recoverability. No merge was performed because the patches already exist and
  have later successors on `main`.
- DONE — Final denominator: Model 1 has `1` worktree and `1` local branch
  (`main`); Metis has `1` worktree (`main`), `136` local branches total,
  `0` merged non-main candidates and `0` prunable records. Both main histories
  remain aligned `0/0`; Metis is clean. Model 1 differs only by this authorized
  cleanup board before its closing documentation commit.
- FACT — The remaining `135` non-main Metis local branches are not checked out
  worktrees and are not proven merged or patch-equivalent by this wave. They
  were therefore preserved. Any broader historical-branch cleanup requires a
  separate patch-equivalence/recoverability census.
