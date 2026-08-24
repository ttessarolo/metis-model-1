# L64 native TypeScript loader and retained runtime root

## Objective

Replace the non-executable TSX/esbuild production-capsule path with a truthful,
hash-bound, stdlib-only Node loader and split the qualified Node preimage into a
dedicated retained runtime root. Preserve the accepted deny-fork, single-exec,
no-network and process-root-only-write boundary. Prove semantic equivalence to
the former TSX reference on all fifteen ordered smoke executions before L63 may
materialize an authority or run the bridge.

Baseline at wave open:
`2d519d90be9eae0c562a10becbe2bc7e9ac4bbb0`.

This is a payload-free product rework. It authorizes tmp-only public-synthetic
runner parity against the pinned Git object, but no production bridge,
authority registration, W1/W2 population, model download, training or accuracy
claim.

## Frozen facts

1. Qualified Node is v22.22.3 arm64, raw SHA-256
   `5d9d3872911e2340a43b707962e68143de8a4e8d54628845c0c4f2de1fb7cd5c`
   and exact size `112,915,776` bytes.
2. The frozen v2 launcher fails before the runner: TSX first writes an ambient
   cache; with `TMPDIR` redirected below process root it invokes esbuild and is
   denied by `deny process-fork`. Production policy is correct and must not be
   broadened for TSX.
3. The retained prototype loader is 48 lines, imports only Node stdlib, uses
   `stripTypeScriptTypes({mode: "transform"})`, and resolves existing relative
   `.js` specifiers to `.ts/.mts/.cts`. Under the exact production Node policy
   it imports the pinned Metis module/compiler/serializer with rc0, empty
   stderr/temp and no child process.
4. The first regex-derived Git-object census reported 29 TypeScript files,
   909,608 bytes and 77 import/export edges, but the first real parity launch
   correctly rejected it: a multiline import with an inline comment in
   `metis-validator.ts` was omitted, leaving `pipes-census.ts` outside the
   capsule. Those counts and their roster hash are explicitly retracted and
   cannot become authority. The final closure must be derived with the exact
   registered TypeScript parser, recursively resolved to a fixed point, then
   independently checked against runtime loader observations. Regex import
   extraction is forbidden for authority.
5. A conservative package-manifest runtime closure contains 15 packages, 1,790
   regular files, 7,710,543 bytes and zero symlinks. Full Metis and full
   node_modules are forbidden because they exceed retained-root caps and include
   non-roster/symlink content.
6. Kimi K3, Qwen and L0/frontier choose the native loader. A deterministic
   precompiled bundle is only the fail-closed fallback if parity or the frozen
   loader canary fails. A production esbuild broker is rejected.

## Architecture decision

1. Production protocol and public schema identifiers advance to capsule v3.
   Fixture v1 remains supported. No production v2 authority instance exists or
   receives compatibility credit.
2. The capsule contains only the pinned selective Metis/package closure, the
   registered runner and a dedicated `loader` role. Every `tsx` runtime identity
   is replaced atomically by exact `loader_path` and `loader_sha256` fields.
   Residual production `tsx` keys or roles fail closed.
3. The loader derives the capsule root from its own fixed location. Every
   resolved `file:` URL must remain below that root; builtins use `node:`; bare
   packages must resolve to rostered files inside the capsule. Parent/absolute
   escape, ambient fallback and non-roster package resolution are blocked.
4. The exact launch includes the pinned warning-suppression flag required for
   clean canonical stderr. The flag, loader bytes, loader location and Node
   binary hash are all authority-bound. No experimental behavior is claimed for
   any other Node binary.
5. Node is not placed in `production-trusted-root` and its cap is not raised.
   The qualifier captures the registered external Node bytes into a new
   `production-runtime-root` anchored below the retained run root, verifies the
   exact size/hash/mode, seals it and double-snapshots it once per qualification.
   Caps are at most 8 files, 8 directories, 128 MiB total and 128 MiB per file.
   The root may contain only the canonical Node preimage and its directories.
6. Qualified retained order is exactly process, runtime, trusted. Blocked
   prefixes, schemas, manual validators and bridge fd-root remeasurement use the
   same order and exact root classes. Node executes only from the sealed runtime
   preimage; the mutable source path is never executed.
7. The Node Seatbelt template admits read/exec only for that registered runtime
   preimage, reads the sealed capsule and process root, writes only below process
   root, denies network and denies all process creation. Runtime-root ancestry,
   policy bytes and parameter bindings are measured and authority-bound.

## Writable roster

Product/schema/test writes are limited to:

- `runtime/metis_oracle/native_ts_loader.mjs`;
- `runtime/metis_oracle/runner.ts`;
- `runtime/w3_qualifier.py`;
- `runtime/w3_bridge_gate.py`;
- `runtime/w3_production_worker.py`;
- `src/metis_model1/oracles.py`;
- `src/metis_model1/w3_oracles.py`;
- `src/metis_model1/contracts.py`;
- `schemas/oracle-result.schema.json`;
- `schemas/w3-run.schema.json`;
- `schemas/w3-production-authority.schema.json`;
- `schemas/w3-qualification.schema.json`;
- `schemas/w3-bridge-replay.schema.json`;
- `tests/test_oracles.py`;
- `tests/test_w3_qualifier.py`;
- `tests/test_w3_bridge_gate.py`;
- `tests/test_w3_production_worker.py`;
- `tests/test_contracts.py`;
- `tests/test_w3_builder.py`;
- `tests/test_w3_oracles.py`;
- `tests/test_w3_production_adapter.py`.

This brief, the canonical board and session ledger are the only additional
tracked status writes. The initial 19-path roster was expanded once, before the
file was touched, to include `src/metis_model1/w3_oracles.py`: it constructs and
validates the production adapter/runtime receipt identity and otherwise would
retain `tsx_path` in conflict with the v3 schemas. The writable product, schema
and test roster was therefore 20 paths. Any further path is a STOP and requires
an explicit L0 scope amendment before editing. L0 subsequently
adds only `tests/test_w3_production_adapter.py` as path 21 after its broad
read-only run exposes two stale schema-v2 production assertions. This is a
test-only port required for truthful v3 validation; no additional product or
schema surface is authorized. The final roster is exactly 21 paths.

## Tests-first and evidence contract

1. Capture RED before product changes for: exact production v3 discriminator;
   residual `tsx` key/role rejection; loader hash/path/flag drift; resolver
   escape/ambient package; missing/extra closure byte; Node in trusted root;
   runtime-root wrong size/hash/mode/roster/order; runtime-root fd/path swap;
   schema/manual/bridge disagreement; fork/write/network/temp/stderr canaries.
2. Recompute the selective Git and package closure algorithms independently.
   The Git importer uses the registered TypeScript AST, not regex or line-based
   extraction, and iterates to a fixed point. The AST all-import source closure
   is an authority-bearing conservative superset: runtime loader observations
   may omit type-only branches, but every observed Metis module must belong to
   that source closure and every observed capsule file URL must belong to the
   exact capsule roster. Report the static and runtime-loaded denominators
   separately and explain every static-only source edge. The package-manifest
   closure is likewise a conservative superset, not an observation-equality
   target; Node loader hooks need not expose internal package-manifest reads.
   Observed outside or ambient modules must remain exactly zero, with exact
   capsule-roster verification plus Seatbelt containment as the boundary.
   Report `in=N out=N distinct=N gaps=0`, total/max bytes, modes, symlinks and
   canonical roster hashes. Inputs come only from the pinned Git object and
   registered tooling installation; no live checkout or ambient package earns
   authority.
3. Run the frozen loader import canary under the exact final Seatbelt template.
   Require rc0, canonical stdout, empty stderr, empty temp, zero child/residual
   process and no out-of-root read/write or network success.
4. Run a separate reference-only TSX lane over the same immutable public
   synthetic inputs. Its narrowly permissive child/temp policy is evidence only
   and never becomes production authority. Compare TSX and native normalized
   results byte-for-byte over three candidates and five ordered roles:
   `in=15 out=15 distinct=15 gaps=0`. F-3 mutated diagnostics must match exactly,
   including range, line and character.
5. Recompute runner, loader, qualifier, bridge, policy, runtime-closure and
   schema hashes only after formatting. The bridge pin must equal the frozen
   qualifier bytes. All five source authorities remain `None`.
6. Run focused attacks, historical executable matrix, safe-only suites, all
   schema validators, compile/Ruff/format/diff checks, then mandatory hermetic
   `make check`. Kimi, Qwen and an independent frontier lane review frozen bytes
   and parity evidence before acceptance.

## STOP conditions

- Any TSX/native output or diagnostic mismatch, unresolved import, loader
  warning/stderr, child, network success, temp/out-of-root write or residual PID.
- Any loader resolution outside the sealed capsule or use of an ambient package.
- Any Node executed from the mutable source, Node placed in the trusted root,
  trusted-root cap increase, production process-fork allowance or second
  executable authority.
- Any closure byte not derived from the pinned Git/tooling sources, missing or
  extra roster entry, symlink, file above its class cap or manifest mismatch.
- Any regex-derived or otherwise non-parser-complete import closure, including
  recurrence of the retracted 29-file roster.
- Any v2/v3 mixed report, residual production TSX identity, schema/manual/bridge
  disagreement, authority source registration or false compatibility claim.
- Any Metis checkout write, credential/live-data access, network use outside a
  denied canary, tracked payload, model/data download, training, commit/push or
  accuracy claim during L64.

L64 acceptance only reopens L63 materialization. It grants no smoke result,
dataset, training or semantic-accuracy evidence by itself.
