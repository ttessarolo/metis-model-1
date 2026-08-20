# K3 remediation audit — Accuracy-99 pilot

You are the second frontier team. Work read-only in both repositories and
adversarially verify the remediation of your K2 findings. Do not trust green
claims, do not edit either repository, and do not start training.

## Fixed scope

- Model 1: `/Users/tommasotessarolo/Developer/metis-model-1`
- Metis evidence checkout, strictly read-only:
  `/Users/tommasotessarolo/Developer/ares-matioska/metis`
- Model 1 baseline HEAD remains
  `ad7a1169104c22fa8736b7463a93f65ea9f670f8` plus the authorized dirty wave.
- Metis HEAD must remain
  `a2dde2b191f6b78c2003d74875560da782470968` with exactly its four pre-existing
  untracked status entries.
- Source K2 report:
  `/Users/tommasotessarolo/Developer/ai-multi-team-orchestra/runs/metis-model1-accuracy99-integration-audit/artifacts/kimi-final-integration-audit.md`
  SHA-256 `23d11be2cd3cd41beb135c4b381ec11f49841f146472d6103f2483b70a25003e`.

## Required adversarial checks

1. Re-run the K2 P0 closure/assets poisoning attack against `validate-pilot`:
   - changed non-task OID with stale leakage identity;
   - changed non-task OID with recomputed leakage identity propagated through
     closure tasks/shared closure and a regenerated, self-consistent asset
     register.
   Both must now fail. Confirm the tracked closure is rebuilt exactly from the
   pinned Metis Git objects, not working-tree payloads.
2. Point `--metis-root` at a missing checkout. `validate-pilot` must exit
   non-zero and report the missing Git anchor rather than degrading to a
   structural pass.
3. Verify cross-split derivation where a child names another example ID as a
   provenance parent is rejected in both row orders; a caller-supplied wrong
   split-manifest identity must be rejected.
4. Verify standalone hyperparameter and artifact-store validators reject
   sequence 2048, positive dropout, non-atomic publication and automatic
   deletion. Verify stop-rule and non-claim text drift is schema-rejected.
5. Confirm K2 P1-1 through P1-9 now have focused regression tests. For P1-10,
   confirm direct Git tests skip explicitly if the source checkout is absent
   while the integrated pilot gate itself still fails closed.
6. Confirm open W5 decisions are derived from the decision register, the
   report names both project and Metis roots/revision, and `assess-w5` still
   exits `1` for the current five blockers.

Run `make check`, `validate-pilot --json`, and `assess-w5 --json` directly;
capture every exit code. Recompute relevant denominators. Compare exact HEAD and
`git status --short` before/after for both repositories.

## Output

Write `kimi-remediation-audit.md` in the wrapper activity artifacts directory.
Return `CLEAN`, `REWORK`, or `STOP`, with ranked P0/P1/P2 findings, exact
commands/counts, remaining declared limitations, and the four protocol closing
sections. A remaining lack of real independent data, task-specific semantic
oracles, A/B baseline or evidence-artifact anchoring is not a code bypass; keep
it as an explicit W5 blocker/non-claim.
