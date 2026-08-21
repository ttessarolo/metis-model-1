# Kimi K3 L49 read-only lifecycle review

You are the Kimi K3 frontier master. Work at maximum configured reasoning effort
and validate any delegated mechanical census yourself. This is a read-only
architecture review; do not edit any repository, board, schema, test or source
file.

Repository: `/Users/tommasotessarolo/Developer/metis-model-1`.
Baseline HEAD: `4ec625fcec8a9c41423bc048688d17775e57353c`.

Read in full, in order:

1. `AGENTS.md`
2. `BLACKBOARD.md` and the active board/session ledger it points to
3. `docs/00-charter-and-decisions.md`
4. `docs/06-delivery-roadmap.md`
5. `orchestra/briefs/2026-08-21-model1-l23-capsule-v2.md`
6. `orchestra/briefs/2026-08-21-model1-l49-retained-owned-roots.md`

Your exclusive slice is lifecycle completeness and trust binding. Enumerate
every automatic deletion/cleanup callsite in the qualifier, bridge and public
capsule Oracle boundary, including creation failure, error unwind, internal
success and public finalizers. Decide which paths must become retained and how
blocked cleanup evidence propagates without globals or hidden residue.

Challenge specifically:

- descriptor/FD closure versus filesystem deletion;
- sealing partial roots after an error without converting a block into green;
- process reap and output caps when no files are deleted;
- nested invocation retention inside the v2 process root;
- bridge holder retention and both-run trust binding;
- Oracle stdout/stderr/preimage partial ownership;
- exact writer roster, qualifier repin sequence and non-live gate denominators;
- whether any current success/error path would still auto-delete a mutable name.

Reproduce only payload-free/static or tmp-only findings. No Metis checkout,
real runner, network, credentials, model/data payload, training, make check,
whole `tests/test_oracles.py`, commit or push. Do not alter the shared snapshot.

Return a ranked `ACCEPT|REWORK|STOP` verdict with P0/P1/P2, exact callsite census,
file:line evidence, blocked-report propagation design, gap-free test denominator
and a concise implementation recommendation to L0. Never promote.
