# Qwen L49 read-only architecture review

You are the Qwen `qwen3.8-max` frontier master. Work at maximum available
reasoning effort and delegate only bounded mechanical checks to your own
subagents. This is a read-only architecture review; do not edit any repository,
board, schema, test or source file.

Repository: `/Users/tommasotessarolo/Developer/metis-model-1`.
Baseline HEAD: `4ec625fcec8a9c41423bc048688d17775e57353c`.

Read in full, in order:

1. `AGENTS.md`
2. `BLACKBOARD.md` and the active board/session ledger it points to
3. `docs/00-charter-and-decisions.md`
4. `docs/06-delivery-roadmap.md`
5. `orchestra/briefs/2026-08-21-model1-l23-capsule-v2.md`
6. `orchestra/briefs/2026-08-21-model1-l49-retained-owned-roots.md`

Your exclusive slice is the retained-root data model, schema truth and replay
normalization. Inspect current runtime/schema/tests completely enough to answer:

- Can the exact proposed descriptor prove a bounded point-in-time seal without
  claiming stable pathname ownership under same-UID mutation?
- Which descriptor fields must be physical, normalized, deterministic and
  separately bound?
- Can v1 and v2 qualified and blocked reports carry cleanup evidence without
  allowing a false green or losing the physical receipt on error?
- What exact normalization exclusions preserve two-run semantic equivalence
  without excluding semantic/runtime/role/count evidence?
- How must the bridge schema bind two physical qualification manifests and one
  normalized projection?
- What caps, type checks, duplicate-key checks, schema mutations and replay
  attacks are missing from the L49 brief?

Reproduce only payload-free/static or tmp-only findings. No Metis checkout,
real runner, network, credentials, model/data payload, training, make check,
whole `tests/test_oracles.py`, commit or push. Do not alter the shared snapshot.

Return a ranked `ACCEPT|REWORK|STOP` verdict with P0/P1/P2, exact file:line
evidence, exact proposed schema fields/projection algorithm, a gap-free test
denominator and a concise implementation recommendation to L0. Never promote.
