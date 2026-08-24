# L66 — native proof rework and production declassification

## Status

OPEN — tests-first rework. L64 product bytes are the frozen input, not accepted
production authority. L63, source repin, payload materialization and training
remain stopped.

## Baseline and ownership

- repository: `/Users/tommasotessarolo/Developer/metis-model-1`
- branch: `codex/model1-local-99-foundation`
- baseline HEAD: `2d519d90be9eae0c562a10becbe2bc7e9ac4bbb0`
- inherited state: the complete uncommitted L64 21-path implementation plus
  L0-owned board, ledger and L63/L64 briefs; preserve it exactly except for the
  paths explicitly owned below.
- one product writer only; L0 remains the architecture, security, integration
  and promotion authority.
- Kimi K3 and Qwen 3.8 Max review the final frozen bytes independently. They do
  not write product files or promote the wave.

## Objective

Close the complete frozen L64 audit without weakening its threat model:

1. fix the real v3 runtime-root remeasurement contradiction;
2. bind the combined launcher policy, exact loader/runner identities and exact
   capsule roles across schema, qualifier, bridge and public verifier;
3. replace the vacuous 18+7 mutation evidence with positive controls and
   mutation-specific failures;
4. declassify the legacy in-process `ProductionW3Adapter` and every production
   execution entry until an external protected execution broker exists;
5. retain deterministic, metadata-only closure, observation and 15-row parity
   evidence that can be regenerated and independently verified without placing
   source/package payload bytes in Git.

This wave may accept only **reference closure/parity infrastructure**. It may
not claim executed-preimage identity, production smoke success, dataset
qualification, training readiness or semantic accuracy.

## Frozen architecture decisions

### Same-UID boundary

Modes, retained inode descriptors, double snapshots and copies owned by the
same UID do not prove bytes consumed through pathname exec/load. macOS offers no
usable executable-FD route in this environment. Therefore:

- production v3 qualification/replay/adapter entrypoints fail before any
  filesystem materialization, runner import or subprocess while the protected
  broker authority is absent;
- reference-only tools may measure closure/parity, but their receipts state the
  exclusive-host assumption and `executed_preimage_authority=false`;
- no code or test may relabel same-UID pathname execution as byte-atomic;
- a distinct-UID/root broker with non-caller-writable ancestry is a separate,
  explicitly authorized future wave.

### Bounded parity execution amendment

L0 explicitly authorizes one reference-only parity reconstruction because the
prior actual result/diagnostic rows were not retained. Its exact boundary is:

- three fresh rounds of the five public-synthetic F-1/F-2/F-3 smoke roles,
  `in=15 out=15 distinct=15 gaps=0`;
- pinned Metis Git objects/tree, registered TypeScript/package installation and
  pinned Node only; no mutable checkout content and no checkout write;
- native side under the final deny-fork policy; TSX side is a separately labelled
  reference comparator with its required child/temp permission and receives
  zero production credit;
- native temp remains exactly empty; TSX comparator temp is expected and must be
  enumerated as a bounded symlink-free roster with file/directory/byte counts
  and a full roster hash, then removed and independently verified absent. Its
  receipt section is explicitly reference-only and cannot satisfy any production
  temp/process invariant;
- capture actual input/result/diagnostic hashes and loader-observation URLs;
- temporary execution roots stay outside Git and are removed after the receipt
  is emitted and verified;
- no production entrypoint, authority registration, source repin, semantic
  accuracy, dataset or training claim is permitted.

This is the only runner execution allowed in L66. It is evidence generation for
the reference receipt, not L63 qualification or a protected execution claim.

After the wrapper STOP and the first comparator-temp STOP, at most one final
retry is permitted, and only after a dedicated tests-first comparator-temp
roster/cleanup regression is GREEN. Any subsequent execution failure closes
the L66 parity receipt as blocked; no fourth attempt is allowed.

The final attempt did close the semantic/diagnostic comparisons in process but
failed before publication because the inherited hook observed 337 unique URLs
instead of the historical debug-trace denominator 338. No dynamic row survived
in a durable receipt and therefore the whole `15/15` receives zero evidence
credit. L66 must now emit only a deterministic **blocked** evidence manifest:

- retain the fully recomputable source/package/capsule metadata rosters and all
  pins;
- set parity status `blocked`, available `false`, durable rows `0`, expected
  rows `15`, with a stable reason code for observation-denominator drift;
- do not include console-only result/diagnostic hashes or claim the 337 URL set
  as a retained observation;
- distinguish the static composition expectation (loader preimage plus hook
  candidates) from any actually observed roster;
- make two blocked `--emit` outputs byte-identical and make `--verify`
  independently recompute every retained static row/hash.

Synthetic complete-parity fixtures may test schema/verifier mutation handling,
but they are labelled test-only and never count as project evidence. Closing
this blocked receipt does not satisfy the parity gate or L66 handoff condition;
it preserves the useful boundary/static-evidence work for audit while L63 stays
stopped.

The loader-observation trace uses an explicitly inherited write FD consumed by
the already-pinned native loader. The harness sets that FD only for reference
evidence; production commands prove the trace variable/FD is absent. Do not load
an auxiliary tracing wrapper by pathname and do not widen process-root or broad
ancestor read permissions to make such a wrapper start.

### Production adapter

`ProductionW3Adapter.identity()` and `.evaluate()` fail closed before any
legacy `run_oracle`, filesystem, artifact or process operation. The legacy
helper is reference-only. A future production adapter consumes independently
validated external qualifier+bridge receipts; it is not another launcher.

### Per-kind retained modes

Bridge remeasurement takes the root kind and uses exactly:

- `production-runtime-root`: regular files `0555`;
- process, trusted, replay-holder and publication roots: regular files `0444`.

It does not accept both modes generically. A real-shape Node-only runtime root
must have byte-identical qualifier/bridge roster and digest.

## Exact writable product/schema/test roster — 22 paths

1. `runtime/metis_oracle/native_ts_loader.mjs`
2. `runtime/w3_qualifier.py`
3. `runtime/w3_bridge_gate.py`
4. `src/metis_model1/oracles.py`
5. `src/metis_model1/w3_oracles.py`
6. `src/metis_model1/w3_production_adapter.py`
7. `src/metis_model1/contracts.py`
8. `schemas/w3-production-authority.schema.json`
9. `schemas/w3-qualification.schema.json`
10. `schemas/w3-bridge-replay.schema.json`
11. `schemas/w3-run.schema.json` (loader-hash cascade only)
12. `schemas/w3-native-loader-evidence.schema.json` (new)
13. `manifests/w3-native-loader-evidence.json` (new, metadata only)
14. `runtime/w3_native_evidence.py` (new)
15. `runtime/metis_oracle/native_evidence_census.mjs` (new)
16. `tests/test_w3_qualifier.py`
17. `tests/test_w3_bridge_gate.py`
18. `tests/test_oracles.py`
19. `tests/test_w3_oracles.py`
20. `tests/test_w3_production_adapter.py`
21. `tests/test_contracts.py`
22. `tests/test_w3_native_evidence.py` (new)

Only L0 may additionally write this brief, the canonical board and the session
ledger. No other source, schema, test, manifest or artifact path is writable.

## Explicitly off-limits

- `runtime/metis_oracle/runner.ts`
- `runtime/w3_production_worker.py`
- `schemas/oracle-result.schema.json`
- `src/metis_model1/w3_builder.py`
- `tests/test_w3_builder.py`, `tests/test_w3_production_worker.py`
- Metis checkout, external dependency installation and payload/artifact roots
- credentials, `.env`, keychains, live data and model material
- commit, push, authority registration, source repin, L63 resume and training

## Tests-first RED contract

Capture all failures before the first product/schema edit. Denominators are
reported separately from pytest collection.

1. **Runtime root** — real Node-shaped `0555` tree produces the same physical
   roster and digest in qualifier and bridge; `0444` Node is rejected. The
   current bridge must fail the positive `0555` control.
2. **Combined policy** — qualifier launcher identity and bridge expectation are
   recomputed from `outer + NUL + node` and match `1/1`; the current bytes fail.
3. **Cleanup mutations** — unmutated process→runtime→trusted cleanup first
   passes in qualifier and bridge, then each of the existing 18+7 cases applies
   one mutation, canonical-rehashes it and fails for that mutation. Exact
   denominator `25/25`; order failure cannot satisfy another case.
4. **Schema/manual/public identity** — canonically rehashed attacks for loader
   SHA, loader path, runner SHA, alternate runner path, `role:tsx` and
   `role:node` are rejected by schema, qualifier, bridge and public verifier.
5. **Adapter and production STOP** — spies prove zero `run_oracle`, `Popen`,
   artifact and filesystem calls when adapter/qualifier/bridge production
   entrypoints fail for missing protected broker authority.
6. **Same-UID non-claim** — transient module/Node/runner rewrites remain a
   reference-path vulnerability proof; every production entry blocks before
   spawn. No test may turn this red canary into production credit.
7. **Durable evidence** — missing/extra/reordered roster row; size/mode/hash/
   count drift; unexplained static-only source; observed outside/ambient URL;
   parity/result/diagnostic-range mismatch; parser/generator/Node/loader/runner/
   policy pin drift all fail closed.

## Metadata-only evidence contract

The committed manifest and schema contain no source/package payload bytes. They
bind:

- source AST fixed-point rows: path, size, mode, SHA-256, Git blob OID, import
  edges, runtime-observed flag and explicit type-only explanation for every
  static-only row;
- package rows: package identity, path, size, mode, SHA-256 and observed flag;
- exact capsule rows and the complete observed URL roster, with
  outside/ambient counts fixed to zero;
- 15 ordered parity rows: candidate/family/role, input, result and diagnostic
  hashes plus TSX-reference/native equality;
- full hashes for the generator, TypeScript parser, Node, loader, runner and
  oracle/execution policy templates;
- exact non-claims, including `executed_preimage_authority=false`, no
  production, dataset, training or accuracy evidence.

`--emit` from two fresh destinations must be byte-identical. `--verify`
recomputes from the pinned Git object/tree and registered tooling installation,
not the mutable checkout HEAD. Authority, qualification and replay schemas bind
the evidence manifest SHA even though production remains fail-closed.

## Required gates

- exact RED-to-GREEN roster with `in=N out=N distinct=N gaps=0`;
- two byte-identical evidence emissions and independent `--verify`;
- schema/manual/qualifier/bridge/public agreement for every mutation;
- complete safe unit suites for every owned test file;
- historical executable mutation matrix kept separate;
- JSON Schema Draft 2020-12 meta-validation;
- `py_compile`, Node `--check`, Ruff check/format, `git diff --check`;
- hermetic `make check` against pinned Metis Git objects and pinned Node;
- final process/FD census and exact dirty-path ownership census;
- frozen-byte independent reviews by L0 frontier, Kimi K3 and Qwen 3.8 Max.

No compile-only, prose-only or inherited `800/1` result closes any gate.

## Stop rules

- Any product write before exact RED capture stops the writer.
- Any proposal to solve same-UID integrity with modes, inode-only checks,
  snapshots or a same-UID copy stops the wave.
- Any production spawn without registered protected broker authority stops the
  wave.
- Any receipt that omits full rosters, uses truncated hashes or cannot be
  regenerated byte-identically stops the wave.
- Any auxiliary pathname tracing loader or broad policy widening stops the
  wave; observation must use the reference-only inherited FD above.
- Any source repin, production authority, L63 materialization, runner execution
  other than the exact bounded reference-only `3×5` parity amendment above,
  network, credential, payload, model download or training action stops the
  wave.

## Handoff condition

L66 may be marked accepted only when the 22-path diff is frozen, all required
gates pass, all three independent reviewers return no P0/P1/P2 in the named
surface, and the board says explicitly that production execution remains
blocked pending a protected broker. Acceptance does not resume L63 by itself.
If the committed evidence manifest has parity status `blocked`, the maximum L66
outcome is `PARTIAL / STOP`; passing code and static gates cannot promote it.
