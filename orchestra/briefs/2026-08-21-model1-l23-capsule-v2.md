# L23 capsule-v2 bridge — frontier implementation brief

## Objective

Implement the payload-free contract that can later qualify the real F-1/F-2/F-3
bridge from immutable external bundles. Replace neither the accepted L22 fixture
contract nor its evidence. Do not materialize the Python dependency bundle or
Metis capsule, execute the real runner, register a source authority, build W1
data, download a model, train, or claim accuracy in this wave.

Baseline project SHA and remote branch SHA:
`4ec625fcec8a9c41423bc048688d17775e57353c`.

Metis remains strictly read-only at revision
`a2dde2b191f6b78c2003d74875560da782470968`, tree
`75473e26deff4084a0eb077a4c3e27d52dc07998`, expanded-status SHA-256
`ea7eb74f131f8d8e1fd3f785da7941bce2c21dc239d06ccd17a389e7ed6beb54`.

Kimi K3 independently accepted L22 and ratified only the three frozen semantic
rows. Its external report SHA-256 is
`a810598d9b62143f6172a4faa58f91879d4ac19f097cc19255a6ce43356fb83a`.
The frozen candidate and registry hashes are respectively
`sha256:4ee3e735179194b838ec38b0c11f1f9a166d640fcfece1eee68b6f9b6dd63bc5`
and
`sha256:9b9aa14836eb6924e61df0ab1e0a7b7224f9958b78056ae66fd27f59868cc7c3`.

## Required architecture

1. Keep the five W3 production authorities `None` in source and on every fresh
   import. Authority v2 is an external canonical manifest plus an independently
   supplied digest; it binds the Kimi report SHA and exact verdict/scope, project
   SHA, candidates/registry, launcher/worker code, Python runtime, dependency
   bundle, Metis capsule, runner/Node/tooling and expected `3/3` + `5/5` roster.
2. Separate the source bundle from an external content-addressed CPython 3.13.3
   arm64 dependency bundle. The latter has exactly `144` regular files,
   `1,799,002` bytes and roster digest
   `db649bc14ee947ff43a2e5dbd540585123a259bb771a087692b72a4c0d463f42`.
   The digest preimage is the concatenation of one row per lexicographically
   sorted POSIX-relative path:
   `path.encode() + b"\0" + decimal_size + b"\0" + lowercase_raw_sha256_hex + b"\n"`.
   There is no `sha256:` prefix and no mode field in this aggregate; path type,
   mode and symlink constraints are independently validated.
   Reject missing/extra files, symlinks, mode/size/hash drift and wrong ABI.
3. Define an immutable Metis runtime capsule containing only the pinned Git
   archive/tooling closure, registered runner, qualified Node and exact
   manifests. Reject `.git`, `.env`, untracked content, symlinks and any byte,
   mode, path, revision or tree drift. Never read the live Metis checkout from a
   production worker.
4. Add a low-level run-from-capsule boundary. It receives a canonical request,
   creates only a per-run workspace below the declared process root, executes
   only the exact capsule Node/tsx/runner path under the outer deny-default
   Seatbelt policy, and returns a canonical Oracle envelope bound to the request
   and capsule. It must not call the live-checkout snapshot builder.
5. Extend the clean launcher with a v2 mode that allowlists reads only from the
   exact source bundle, dependency bundle, capsule, interpreter roots and run
   root; writes only below the run root; network denied; external/source reads
   and writes denied; descendants cannot detach or execute an unregistered
   binary. Preserve the complete L22 v1 behavior and tests.
6. Add a standalone bridge gate that runs two fresh qualifications, requires
   byte-identical canonical reports and five artifacts after excluding only an
   explicitly modeled run nonce, and emits a canonical replay report. Each run
   is candidates `3/3`, executions `5/5`, exact roles
   `author/before/after/mutated/fixed`, gaps `0`; two runs mean `10/10` physical
   invocations but only five registered semantic identities.
7. Claims and schemas distinguish fixture v1 from production-capsule v2. Even a
   green v2 report grants only the three ratified smoke specifications. It does
   not close W1 `15/15`, F-4/F-5/F-6, benchmark v1, W5 or semantic accuracy.

## Writable roster

Sequential ownership; no overlapping writers:

1. `runtime/w3_qualifier.py`
2. `runtime/w3_production_worker.py` (new)
3. `runtime/w3_bridge_gate.py` (new)
4. `src/metis_model1/oracles.py`
5. `schemas/w3-qualification.schema.json`
6. `schemas/w3-production-authority.schema.json` (new)
7. `schemas/w3-bridge-replay.schema.json` (new)
8. `src/metis_model1/contracts.py`
9. `tests/test_w3_qualifier.py`
10. `tests/test_oracles.py`
11. `tests/test_w3_production_worker.py` (new)
12. `tests/test_w3_bridge_gate.py` (new)
13. `tests/test_contracts.py`

L0 alone may update this brief, the active blackboard and session ledger after
implementation evidence freezes.

Off limits: `w3_builder.py`, `w3_oracles.py`, `w3_production_adapter.py`, the two
frozen manifests, every model/data payload and the Metis checkout.

## Payload-free verification

- Exact schemas and canonical hash self-checks.
- Mutation matrix for Kimi-report/authority, Python closure, ABI, capsule,
  request, role, artifact, report and replay drift.
- Symlink/path/mode/missing/extra-file attacks for both external bundles.
- Exec/network/read/write/detach/timeout/output-cap failures are typed and
  fail-closed.
- V1 L22 regression suite remains green.
- All source authorities remain `None` before and after.
- Focused non-live tests, Ruff, format and `git diff --check`. Existing Oracle
  tests that invoke the live checkout must be selected only by an enumerated
  capsule-only node-id roster; never run `tests/test_oracles.py` wholesale in
  this sub-wave. Repository-wide `make check` is deferred until L0 explicitly
  opens the later real-run integration wave, because the current suite contains
  live read-only Oracle calls.

Fixture bundles and fake runners may exist only below pytest temporary roots.
No test may read credentials, `.env`, live data or model payloads.

## STOP conditions

- Any requirement to mutate/read unregistered content from the live Metis
  checkout, register an authority in source, weaken L22, or enter payload bytes
  in Git stops the wave.
- Any green that is self-authorized, same-process-only, schema-only, compiler-
  clean-only or missing exact `3/3`, `5/5`, two-run and repository invariants is
  invalid.
- Real bundle/capsule materialization and real runner execution remain a later
  explicitly recorded wave after independent frontier review of this code.
