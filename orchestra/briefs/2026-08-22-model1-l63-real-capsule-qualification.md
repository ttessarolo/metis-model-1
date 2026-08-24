# L63 real capsule qualification — external materialization brief

## Objective

Materialize, outside Git, the already accepted W3 production-capsule inputs and
run the standalone bridge exactly once. The bridge must itself produce two
fresh qualifications over the three independently ratified public-synthetic
F-1/F-2/F-3 candidates: `2/2` fresh processes, `10/10` physical invocations,
five ordered semantic roles per process, byte-identical normalized replay and
zero gaps.

This wave grants only production-capsule smoke evidence for the three ratified
semantic rows. It does not close W1 `15/15`, F-4/F-5/F-6, benchmark v1,
dataset population, W5, training or semantic accuracy.

Project HEAD at wave open:
`2d519d90be9eae0c562a10becbe2bc7e9ac4bbb0`.

## Frozen authorities and input identities

1. The Model 1 source bundle is a path-exact subset of `git archive` at
   `5a5d817bb3df817fbd5d47b7bc4edd4517f8d9b7`: six regular files,
   `141,507` bytes and canonical file-array roster SHA-256
   `0d58e69823d5edd46624874a6488526362665a4f08e7354e9f6e6ede596d5b82`.
2. The dependency bundle is copied only from the durable local CPython `3.13.3`
   arm64 environment. It contains the six package directories `attr`, `attrs`,
   `jsonschema`, `jsonschema_specifications`, `referencing`, `rpds` and the five
   matching distribution-metadata directories: exactly `144` regular files,
   `1,799,002` bytes, no symlinks and dependency-roster SHA-256
   `db649bc14ee947ff43a2e5dbd540585123a259bb771a087692b72a4c0d463f42`.
   The interpreter is the resolved uv CPython
   `cpython-3.13.3-macos-aarch64-none/bin/python3.13`; no ambient or Homebrew
   Python may substitute for it.
3. The capsule is built from the Metis Git object
   `a2dde2b191f6b78c2003d74875560da782470968`, tree
   `75473e26deff4084a0eb077a4c3e27d52dc07998`, plus only the registered tooling
   closure, qualified Node and registered runner. Tooling pins remain package
   `f8130a67...f2fb80`, lock `fed109b6...2edc9fb`, node_modules
   `1cea5f2f...e6e463`; Node is v22.22.3 with raw SHA-256
   `5d9d3872911e2340a43b707962e68143de8a4e8d54628845c0c4f2de1fb7cd5c`;
   runner raw SHA-256 is
   `484dd9518afe1dcf712bde80e367aa70f175c9dd28a3a214243616c1a298cbe5`.
4. The external authority binds the accepted qualifier SHA-256
   `7303d59b65af90e3fef2c9e01c53cd4916b724f5b6e155298651db06ab937421`,
   Kimi report SHA-256
   `a810598d9b62143f6172a4faa58f91879d4ac19f097cc19255a6ce43356fb83a`,
   candidate manifest `4ee3e735...dd63bc5`, semantic registry
   `9b9aa148...68cc7c3`, exact worker bytes, Python identity and all three
   external tree descriptors. The authority is canonical JSON with an
   independently supplied digest and never becomes a source constant.
5. All five production source authorities remain `None` before and after every
   run.

## External writable surface

Tracked writes are limited to this brief, the active blackboard and session
ledger. External materialization is limited to the ignored retained root:

`artifacts/w3-production-v2/l63-source-5a5d817/`

Its required children are:

- `inputs/source-bundle/` with canonical `bundle.json`;
- `inputs/dependency-bundle/` with canonical `bundle.json`;
- `inputs/metis-capsule/` with canonical `capsule.json`;
- `authority/w3-production-authority.json` plus its out-of-band digest record;
- `bridge-artifacts/`, created empty and mode `0700` for the bridge;
- `evidence/`, containing the retained materializer, exact commands, pre/post
  inventories, stdout/stderr, process census and final replay report.

Payloads, bundle manifests, authority instance and execution artifacts stay
ignored and are never committed. Published or retained evidence is not deleted
automatically.

## Execution order and review split

1. L0/frontier freezes the brief, input algorithm and claims.
2. A lower-cost mechanical lane independently recomputes file rosters, bytes,
   modes, symlink absence and aggregate hashes.
3. L0 materializes the source, dependency and capsule trees; normalizes files
   to exact `0444`/`0555` modes; validates canonical manifests and runs isolated
   import/runtime canaries without the production runner.
4. Kimi K3 and Qwen read only the complete materialized descriptors, authority
   and commands. Both must return no blocking finding before execution.
5. L0 invokes `runtime/w3_bridge_gate.py` once with the pinned qualifier
   preimage and all external roots. The gate, not a wrapper assertion, must
   report two fresh runs, ten physical invocations, five semantic identities,
   candidates `3`, artifacts per run `5`, gaps `0` and exact role roster.
6. L0 independently remeasures reports, artifacts, cleanup receipts, source
   authorities, project status and Metis revision/tree/status after the run.
   Kimi and Qwen then perform a final read-only evidence review.
7. Only the brief/board/ledger checkpoint may be committed and pushed. External
   payloads remain retained outside Git for audit and explicit later cleanup.

## Required verification

- Source `in=6 out=6 distinct=6 gaps=0`, exact bytes from Git object only.
- Dependency `in=144 out=144 distinct=144 gaps=0`, `1,799,002` bytes, registered
  aggregate digest, isolated `-I -B -S` imports and schema validation.
- Capsule exact path/type/mode/hash roster, no `.git`, `.env`, untracked file or
  symlink; exact revision/tree/tooling/Node/tsx/runner identities.
- Authority canonical bytes, Draft 2020-12 schema validation, external digest,
  exact launcher/worker/input bindings and non-claims.
- Denied network, unregistered executable, detached-child, source write,
  dependency write, capsule write and out-of-root write canaries.
- Bridge canonical stdout only; qualified replay schema-valid and independently
  rehashed; `2/2` processes, `10/10` invocations, `5/5` semantic identities,
  roles `author/before/after/mutated/fixed`, gaps `0`.
- Project HEAD/status and Metis revision/tree/status byte-identical pre/post;
  zero residual qualifier/worker/Node/sandbox processes.
- Repository static gates and `make check` remain green after tracked status
  updates; no whole live Oracle suite is used as execution evidence.

## STOP conditions

- Any missing/extra/drifted byte, wrong mode, symlink, noncanonical path,
  unregistered executable or authority mismatch stops before the runner.
- Any access to credentials, `.env`, keychain, live ARES data or network stops
  the wave.
- Any Metis checkout write, project source-authority registration, tracked
  payload, detached/residual process, noncanonical output, incomplete cleanup
  receipt or repository drift stops the wave.
- A blocked bridge result, one-process-only result, compiler-clean-only result,
  self-authored `matched=true` or failed Kimi/Qwen review grants no evidence.
- No model download, dataset construction, training, adapter mutation, commit of
  payload bytes or 99% claim is authorized by L63.

## Disposition at runtime preflight

L63 is paused before materialization. The registered TSX launcher cannot run
under the accepted deny-fork policy, and the qualified Node binary cannot be
retained under the current `8 MiB` trusted-root per-file cap. Kimi K3, Qwen and
the internal frontier review converge on a stdlib-only native TypeScript loader
after its real pinned import graph succeeds under the exact policy.

No L63 authority, capsule or bridge report exists. The prerequisite product
rework is isolated in L64; every L63 execution step remains STOP until L64 is
independently accepted and checkpointed.
