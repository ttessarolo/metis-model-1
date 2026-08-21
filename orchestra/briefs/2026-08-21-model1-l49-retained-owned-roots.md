# L49 retained owned roots — frontier architecture brief

## Objective

Close the two L48 cleanup P1 classes without weakening the active same-UID
mutation threat model. The qualification and replay boundaries must never
delete a mutable filesystem name automatically. They must close and reap all
processes and file descriptors, seal and measure every owned runtime root, keep
those roots as bounded retained artifacts, and report `cleanup_deferred`.

This is infrastructure qualification only. It does not register a production
authority, materialize the real dependency/capsule payload, run the real Metis
runner, build W1/W3 data, start W5, train, claim semantic accuracy, commit or
push.

Project baseline remains
`4ec625fcec8a9c41423bc048688d17775e57353c`. The current L47 qualifier candidate
`sha256:3c61238ca581f39ed2749fb09d73da9b2c6f9af810b8966b462676d3b3f6218b`
is REWORK evidence only and must not be treated as a trust root.

## Why the architecture changes

L48 independently proved that bounded scans, `F_GETPATH`, `lstat`, quarantine
renames and name-based `rmdir`/`unlink` cannot provide compare-and-delete
against an active same-UID mutator. The helpers false-greened `2/2`, the public
v1/v2/bridge paths false-greened `3/3`, and non-owned replacement content was
deleted. Oracle error cleanup separately closed descriptors but deleted a
replacement and retained the owned partial `2/2`.

No further rescan heuristic is accepted. A true hostile same-UID deletion
guarantee requires a separately isolated UID or a kernel capability unavailable
to this boundary. The active threat model is not downgraded.

## Required contract

1. Remove automatic name deletion from every capsule qualification, replay and
   Oracle capsule success/error path. No `unlink`, `rmdir`, path-based tree
   removal, quarantine deletion or replacement cleanup may target an owned
   runtime name after creation.
2. Always close descriptors and reap supervised processes. Resource closure is
   distinct from filesystem deletion and remains mandatory.
3. Keep every owned top-level root retained under its already authorized
   external anchor:
   - v1: one worker-process root under the artifact root;
   - v2: one production-process root and one production-trusted root under the
     run root;
   - bridge: one replay-holder root under the replay artifact root;
   - Oracle partial streams/preimages remain inside the retained invocation
     root and are never removed by error cleanup.
4. Before a successful return, recursively seal regular files to `0444` and
   directories to `0555`, then take two identical descriptor-rooted snapshots.
   Each retained-root descriptor records an exact bounded physical roster and a
   normalized roster suitable for semantic replay. Any seal, cap, type, mode,
   symlink, count or snapshot drift blocks qualification.
5. A descriptor contains exact `kind`, logical location root, observed relative
   locator, file/directory/byte counts, physical roster SHA-256, normalized
   roster SHA-256 and `root_id`; `root_id` is the canonical hash of the
   descriptor body without `root_id`. The locator is an observation for later
   GC, not a claim that a hostile parent cannot rename it after return.
6. Qualified and blocked reports carry an exact cleanup object:

   ```json
   {
     "status": "cleanup_deferred",
     "gc_policy": "separately_ratified_quiescent_exclusive_v1",
     "retained_roots": []
   }
   ```

   A failure before root creation uses an empty list. A failure after creation
   reports every root whose descriptor could be sealed and measured; an
   unmeasurable partial remains blocked and is reported as such without any
   deletion attempt.
7. Physical execution metadata must not weaken replay truth. The bridge validates
   both physical reports independently, binds their manifest hashes, and
   compares a canonical normalized qualification projection. Only root locator,
   physical roster and execution-specific root ID may be excluded; root kind,
   counts, normalized roster and all pre-existing semantic/runtime fields remain
   comparison-authoritative. The replay report binds both physical run manifests
   and the normalized projection hash.
8. The bridge retains, seals and measures its full holder. A green replay report
   explicitly states that cleanup is deferred. It must not require an empty
   artifact root.
9. GC is a separate future wave. It may delete only after quiescence and exclusive
   authority are independently ratified. L49 does not implement or invoke GC.

## L0 ratified amendment after the external review

Qwen `qwen3.8-max` completed the data/schema/replay review with `REWORK`,
`P0=0 P1=9 P2=10`. Its three delegated censuses closed
`in=3 out=3 distinct=3 gaps=0`; the current Oracle file closed
`in=40 out=40 live=22 capsule_only=18 distinct=40 gaps=0`. Kimi K3 exhausted
its current billing-cycle quota with provider `403` after a partial lifecycle
mapping; that run is evidence only, not a verdict. L0 therefore owns the
lifecycle adjudication below and does not weaken or defer any Qwen P1.

The following items replace any less specific wording above.

### Exact cleanup and retained-root model

Every report variant has a required `cleanup` object with exact keys:

```json
{
  "status": "cleanup_deferred",
  "gc_policy": "separately_ratified_quiescent_exclusive_v1",
  "delete_attempts": 0,
  "retained_roots": []
}
```

`delete_attempts` is an exact integer, not self-attested proof; the static and
runtime deletion probes remain authoritative. JSON is decoded duplicate-key
safe. Every count uses `type(value) is int`, every boolean uses identity
semantics, every digest uses `^sha256:[0-9a-f]{64}$`, every object has an exact
key set, and every enum is exact.

A sealed retained-root row has exactly:

```json
{
  "state": "sealed",
  "kind": "worker-process-root",
  "logical_root": "process",
  "anchor": "artifact-root",
  "locator": ".observed-safe-relative-name",
  "counts": {"files": 0, "directories": 1, "bytes": 0},
  "physical_roster_sha256": "sha256:...",
  "normalized_roster_sha256": "sha256:...",
  "snapshot_first_sha256": "sha256:...",
  "snapshot_second_sha256": "sha256:...",
  "sealed": true,
  "root_id": "sha256:..."
}
```

The physical snapshot row grammar is sorted UTF-8
`relative-path NUL type NUL four-digit-octal-mode NUL decimal-size NUL raw-lowercase-sha256 LF`.
It includes regular-file content bytes, not metadata only. Symlinks, devices,
FIFOs, sockets and regular files with `st_nlink != 1` block. Directories must be
`0555`, regular files `0444`. `snapshot_first_sha256` and
`snapshot_second_sha256` are two independently measured fd-rooted physical
rosters and must equal `physical_roster_sha256`. The normalized roster maps
only the random top-level locator to the exact logical root name; all deeper
paths, types, modes, sizes and content hashes remain. The seal claim is only a
bounded point-in-time observation; it never claims the pathname or modes remain
stable after return.

An error after observed root creation may instead carry an exact
`state="unmeasurable"` row containing `kind`, `logical_root`, `anchor`, safe
`locator`, `creation_observed=true`, a bounded non-empty `reason`, and
`root_id`. Such a row is valid only in a blocked report. `root_id` is always the
canonical hash of its row without `root_id`; validators recompute it. Duplicate
`root_id`, duplicate `(kind, logical_root)`, wrong order or wrong roster length
blocks.

Expected qualified order is fixed:

- fixture v1: exactly `worker-process-root`;
- production v2: exactly `production-process-root`, then
  `production-trusted-root`;
- bridge replay v2: exactly `replay-holder-root`.

Blocked qualifier reports may carry the roots reached before failure plus one
`qualification-publication-partial-root`; blocked bridge reports carry zero or
one holder row. Empty `retained_roots` is legal only when no root-creation
attempt occurred. A registry records the kind/anchor/locator before the first
mkdir/open attempt and is carried on both typed and unexpected exceptions via
`QualificationBlocked` or `BridgeGateBlocked`; the CLI must serialize that
payload, not merely `str(error)`. A descriptor failure always blocks.

### Bounded measurement and retention budget

The fd-rooted walker is bounded and rejects cap drift with typed errors:

- worker-process and production-process roots: at most `512` regular files,
  `512` directories and `134217728` aggregate bytes;
- production-trusted root: at most `4096` regular files, `4096` directories and
  `1073741824` aggregate bytes;
- qualification-publication partial: at most `128` regular files, `128`
  directories and `33554432` aggregate bytes;
- bridge replay holder: at most `16384` regular files, `16384` directories and
  `3221225472` aggregate bytes;
- every regular file keeps its existing stricter class cap and has a hard
  ceiling of `268435456` bytes.

One production replay therefore retains at most 3 GiB, below the O-006 40 GiB
artifact-store cap. This wave authorizes no repeated production materialization;
any later repeated-run or GC policy is a separate ratified wave.

### Two physical runs and one normalized replay truth

Replay becomes schema version `2` with replay id
`w3-f1-f3-production-capsule-replay-v2`. Qualification versions remain v1/v2;
their newly required cleanup field is forward-only, while historical evidence
continues to exist under its own bytes and hashes.

Each physical qualification report is schema/manual validated before comparison.
The bridge report contains an ordered `runs` array of exactly two rows. Each row
binds exact `run_index`, physical `qualification_manifest_sha256`, exact
`report_bytes_sha256`, and the qualifier's physical cleanup object. The bridge
also binds the common `normalized_projection_sha256`, the existing five
normalized artifact digests, and its own holder cleanup descriptor.

The normalized report body is the physical report body without its self-hash
`manifest_sha256`, with same-type constant substitution at exactly these paths:

1. `cleanup.retained_roots[*].locator` -> empty string;
2. `physical_roster_sha256` -> the all-zero SHA-256 value;
3. `snapshot_first_sha256` -> the all-zero SHA-256 value;
4. `snapshot_second_sha256` -> the all-zero SHA-256 value;
5. `root_id` -> the all-zero SHA-256 value.

No key is deleted. `kind`, `state`, `logical_root`, `anchor`, all counts,
`normalized_roster_sha256`, `sealed`, and every pre-existing semantic, runtime,
role, count and execution field remain comparison-authoritative. The bridge
recomputes both projections; a child-declared projection is never trusted. The
old single `qualification_manifest_sha256` and `reports_sha256` fields are
removed. `nonce_model` is an exact new constant naming upstream nonce removal
and retained-root physical substitution.

The qualified bridge independently resolves and remeasures each reported root
inside its own `run-N` subtree, then seals and double-snapshots the full holder.
The blocked bridge path does the same after kill/reap. Its blocked report has an
ordered `observed_runs` array: for every attempted run it records exact
`run_index`, status `qualified|blocked|no-report`, nullable physical report and
manifest hashes, and the child's cleanup object when a schema-valid blocked
report existed. The holder descriptor remains the coarse physical receipt when
the child timed out or emitted no valid report.

### Oracle and deletion boundary

`run_oracle_from_capsule` keeps its existing canonical envelope unchanged. Its
invocation workspace already persists; L49 removes stream, preimage and atomic
publication cleanup, closes every descriptor, reaps every process and retains
partials under the caller-owned process root. Typed `OracleError` may carry the
observed retained relative paths for diagnostics, but those fields never enter
the frozen Oracle envelope. The enclosing qualifier/bridge retained-root
descriptor is the production receipt. No standalone cleanup or persistence
claim is added.

The exact in-scope deletion-expression/call roster is `29`: qualifier `18`
(creation rollback `1`, helper deletion expressions `2`, helper call sites `13`,
child canary unlinks `2`), bridge `4` (creation rollback `1`, helper deletion
expressions `2`, helper call site `1`), capsule Oracle `7` (preimage deletion
expressions `2`, target rmdir `1`, atomic-publication unlinks `2`, stream unlinks
`2`). L49 must leave zero in-scope automatic deletion attempts. The six live
non-capsule Oracle cleanup sites in `_assert_sandbox_policy`,
`_build_isolated_snapshot` and `run_oracle` remain explicitly outside L49; no
whole Oracle file or live runner is executed.

### Durable capsule-only Oracle roster

The historical count `22` had no durable list and is superseded. The current
tree is classified `42/42`: `22` live-checkout functions remain forbidden and
`20` tmp/pure functions are enumerated by `29` exact quoted selectors that
collect `32` pytest items. The tracked roster is:

`orchestra/briefs/2026-08-21-model1-l49-capsule-only-oracle-nodeids.txt`

It must be read as a quoted zsh array and executed exactly; count-only evidence
or `.pytest_cache` is invalid. Any test-file change requires reclassification
before the gate.

### Required new mutations outside the historical 71

Tests-first must add named cases for: stale report missing cleanup; sealed versus
unmeasurable on qualified; snapshot-one/two drift; content rewrite with restored
mode; symlink/device/FIFO/hardlink; every cap; bool counts; malformed hash;
duplicate JSON key/root id/kind; wrong order and split/merged root rosters;
kind/anchor swaps; locator traversal; `cleanup_deferred`/GC policy drift;
physical descriptor copy across runs; each of the five allowed substitutions;
forbidden substitution of kind/count/normalized roster/semantic/runtime/role;
child blocked cleanup propagation; killed-child no-report holder evidence;
publication-partial retention; and schema/manual/bridge required-key agreement
for all six report variants. These cases are counted separately from the frozen
historical executable matrix `71/71`.

## Proposed writable roster after architecture review

Single frontier writer only:

1. `runtime/w3_qualifier.py`
2. `runtime/w3_bridge_gate.py`
3. `src/metis_model1/oracles.py`
4. `schemas/w3-qualification.schema.json`
5. `schemas/w3-bridge-replay.schema.json`
6. `src/metis_model1/contracts.py`
7. `tests/test_w3_qualifier.py`
8. `tests/test_w3_bridge_gate.py`
9. `tests/test_oracles.py`
10. `tests/test_contracts.py`

`runtime/w3_production_worker.py`, its tests, the production-authority schema,
all frozen manifests, W3 builder/oracle/adapter sources, boards, team registry,
payloads and the Metis checkout remain off limits unless L0 records a narrower
evidence-backed expansion first.

## Tests-first acceptance

- Delete-attempt census after root creation: `0` across all in-scope product
  paths; static call-site roster is explicit and gap-free.
- Retained public success: v1/v2/bridge `3/3`.
- Top-level retained roots: `in=4 out=4 distinct=4 gaps=0`.
- L48 persistent helper/public churn: `5/5` no false green and deletion calls
  `0`; canonical and quarantine replacements keep byte-exact sentinels.
- Recursive replacement attacks: `2/2`, no deletion.
- Oracle stderr-open honest controls: `10/10`, FD delta `0`; replacement attacks
  path/dir-fd `2/2`, both replacement and owned partial preserved.
- Qualified and blocked cleanup schema/type/hash mutations fail closed.
- Two physical qualification reports validate independently; their normalized
  projections are equal; physical manifest hashes remain separately bound.
- Bridge holder seal/roster/cap/path mutation attacks fail closed.
- Historical executable matrix remains a separate exact `71/71` denominator.
- Full safe-only files and the enumerated capsule-only Oracle node IDs are rerun;
  no whole `tests/test_oracles.py`, real runner, Metis or `make check` in L49.
- Three schemas meta-validate, five source authorities remain `None`, Ruff,
  format and `git diff --check` pass, and no W3 process remains.

Any qualifier byte change requires final formatting, raw SHA-256 recomputation,
bridge repinning and a fresh full rerun on the frozen bytes.

## External frontier review split

- Qwen `qwen3.8-max`: challenge retained-root data model, deterministic
  projection, caps and schema mutation coverage. Read-only.
- Kimi K3: challenge lifecycle completeness, every success/error callsite,
  blocked-report propagation and qualification/replay trust binding. Read-only.
- L0: adjudicate conflicts, ratify the final contract, authorize the sole writer,
  replay critical tests and issue the only promotion verdict.

## STOP conditions

- Any automatic deletion of a mutable runtime name remains a STOP.
- Any report that hides an owned residue or omits cleanup state remains a STOP.
- Any normalization that excludes semantic, runtime, role/count or normalized
  retained-content evidence remains a STOP.
- Any real payload, runner, Metis, network, credential, training, commit or push
  action remains outside this wave.
