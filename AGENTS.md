# Metis Model 1 agent contract

This repository uses one frontier coordinator and bounded delegated lanes.

## Required preflight

1. Read `BLACKBOARD.md`, then the active run board and session ledger.
2. Read `docs/00-charter-and-decisions.md`, `docs/06-delivery-roadmap.md`, and the
   documents named by the active lane.
3. Confirm the repository, baseline commit, writable paths, exclusions, model,
   expected output, and verification command before changing files.

## Model routing and ownership

- L0 is the single frontier coordinator. L0 owns architecture, semantic and
  leakage judgments, gates, integration, promotion verdicts, and final closure.
- Bounded census, formatting, deterministic generation, and repetitive checks
  should be delegated to a lower-cost model with the model declared in
  `SESSIONS.md`.
- A delegated lane never promotes, commits, pushes, publishes, downloads model
  payloads, starts training, or changes another repository unless its current
  mandate explicitly authorizes that action.
- Concurrent writers need disjoint file ownership. Use separate worktrees when
  the writable surfaces cannot be made disjoint.

## Blackboard wire

Append evidence to the active board as soon as it is known. Use one of:

- `FACT` — observed fact with a path, command, source, or artifact hash;
- `FIX` — change made and the contract it satisfies;
- `DONE` — completed bounded roster, including `in=N out=N distinct=N gaps=0`;
- `RISK` — unresolved risk and affected gate;
- `OPEN` — decision or evidence still required;
- `STOP` — fail-closed condition that prevents a wave from advancing;
- `Q` — question whose answer changes scope or architecture.

No `DONE` is accepted from prose alone. The frontier coordinator must rerun the
relevant gate, inspect the diff, and independently recompute at least one claim.
Compile-clean evidence never substitutes for semantic evidence.

## Data and artifact boundary

- Never read or copy credentials, `.env` files, keychains, private keys, raw
  production payloads, or live ARES data for this project.
- Base weights, adapters, optimizer state, checkpoints, and materialized datasets
  stay outside Git.
- Model downloads and any MLX training run require a dedicated, explicit wave
  mandate. W0/W1 scaffolding does not authorize them.
- Run `make check` before handing a repository change back to L0.
