# Orchestration and blackboards

## 1. Operating model

Metis Model 1 uses one frontier coordinator. The coordinator decomposes work,
assigns bounded and non-overlapping lanes, reviews their evidence, integrates the
result, and owns every semantic, leakage, architecture, and promotion verdict.

Mechanical inventories, deterministic generation, formatting, and repetitive
checks should use lower-cost models. Model capacity is not authority: every lane
must have a current mandate recorded in `SESSIONS.md`.

## 2. Activity artifacts

Every coordinated activity lives under:

```text
orchestra/runs/<date>-<activity>/
  BLACKBOARD.md
  SESSIONS.md
```

The root `BLACKBOARD.md` points to the active activity. It does not duplicate the
activity state.

The activity board contains exactly these durable sections:

1. Objective;
2. Acceptance;
3. Scope / out of scope;
4. Baseline;
5. Established;
6. Open;
7. Ruled out;
8. Outcome.

The session ledger records lane, owner, declared model, enumerated roster,
exclusive scope, planned verification, status, and session identifier.

## 3. Lane lifecycle

```text
PLANNED -> DISPATCHED -> IN_PROGRESS -> RETURNED
                                      -> FRONTIER_CHECK
                                      -> ACCEPTED | REWORK | STOP
                                      -> CLOSED | ABANDONED
```

`RETURNED` is not acceptance. A delegated answer becomes usable only after the
frontier seam gate.

## 4. Wire and evidence

Board entries use `FACT`, `FIX`, `DONE`, `RISK`, `OPEN`, `STOP`, or `Q`.

An accepted `DONE` includes a bounded denominator:

```text
DONE: <claim> | in=N out=N distinct=N gaps=0 | evidence=<path/hash/command>
```

When a denominator is not meaningful, the entry must explain why and use a
different tag. A percentage without its numerator, denominator, and population
is not closure evidence.

## 5. Anti-interference rules

- One writable lane owns one disjoint file surface.
- If two lanes must write the same surface, run them sequentially or use separate
  worktrees and let L0 integrate.
- Delegates do not commit, push, publish, or broaden scope by inference.
- Long or destructive runs require an explicit activity mandate and stop rules.
- Pre-existing changes and untracked files are user-owned and remain untouched.
- The source Metis repository is read-only unless a separate task authorizes a
  change there.

## 6. Frontier seam gate

Before accepting a lane, L0 must:

1. compare the returned roster with the assigned roster;
2. independently recompute at least one material claim;
3. inspect every changed file in the lane's writable scope;
4. run the smallest contract-relevant checks, then the repository gate;
5. separate offline evidence from live or hardware evidence;
6. preserve blockers and unknowns instead of converting them into green prose;
7. update the board outcome and session status.

For Model 1, compilation and schema validity are structural gates. They do not
prove semantic correctness, non-contamination, trainability, or product value.
