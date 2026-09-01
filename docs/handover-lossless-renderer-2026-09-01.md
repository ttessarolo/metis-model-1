# Lossless compiler renderer — external delivery from the Metis compiler team

Status: **DELIVERED, NOT WIRED**. This document is a handover record. It is not a
promotion request, not a run-board entry, and it does not modify any active wave.
Nothing outside this file has been changed in this repository.

## What this delivers

The compiler-owned lossless renderer that the Brain boards named as the blocking
precondition for deterministic edits and EditPlan:

> «A lossless compiler renderer parses and renders unchanged source to the exact
> same bytes and, for an edit, preserves every untouched source span. … A string
> rewrite, whole-file regeneration or merely compile-clean output is not
> equivalent.»
> — `orchestra/runs/2026-09-01-brain-latency-promotion/BLACKBOARD.md:41-45`

It arrives as API + tests + documentation. **Nothing here is wired to Metis
Brain**: no `hostref:` resolution, no participant integration, no mapping between
compiler node-ids and host-issued opaque references. That mapping stays host
responsibility, by design and not by omission.

## Identity

Per `docs/09-repository-and-artifact-policy.md:49-54` — identity is revision and
checksum, never a local path.

| field | value |
|---|---|
| repository | `ares-matioska/metis` |
| revision | `2ad60b3c804fb1c45e45883b0479a46f660d98f6` |
| tree | `ea29b935934fadd5f99711c0470566a2484b35f6` |
| language_version | `0.43` |
| tooling_version | `0.23.97` |

The revision is committed locally on `main` in the compiler repository. Confirm it
is reachable on your expected remote ref before pinning it.

## The guarantee, precisely

1. Round-trip with no edit is **byte-identical** — measured over the whole tracked
   corpus (200/200 files, 606,654 bytes), not asserted by construction.
2. An edit preserves **every byte outside the touched spans**. The method: source
   text is the truth; each edit is a span replacement anchored to the CST; the rest
   is copied. No regeneration from the AST.
3. Identity is **byte** identity (`Buffer.compare`), never string identity. Source
   enters as bytes; non-reversible UTF-8, BOM, unclean parse and partial CST
   coverage are refused at the door.
4. Where preservation is not demonstrable, the renderer **refuses**: no output, no
   write. The pure API never touches the filesystem on any outcome.

## Contracts

Three closed, versioned contracts:

- **`metis-lossless-inventory/v1`** — node inventory: deterministic AST-path
  node-ids (`$/elements@3/variants@2/steps@0`), spans in both UTF-16 units and
  UTF-8 bytes, per-node preimage hash, complete toolchain pin.
- **`metis-lossless-edit-plan/v1`** — `replace | insert | delete`; contiguous
  ordinals from 0; ceiling of 32 operations; preimage per replace/delete;
  `baseSha256` binding the plan to one source revision. Structurally aligned with
  your `metis-brain-edit-plan/v1`; the compiler side is deliberately unaware of
  opaque host references.
- **`metis-lossless-receipt/v1`** — outcome (`APPLIED | IDENTITY | REJECTED`),
  complete toolchain pin, sha before/after, touched spans in both offset systems,
  diagnostics, closed-set rejection reasons, rendered text.

Node-ids are **not stable across edits** and do not pretend to be: they are valid
for the revision they were emitted on, and a plan declares that revision.

## Fail-closed surface

17 rejection reasons in a closed set; every one exercised by a test. The ones worth
knowing before you drive it:

| reason | meaning |
|---|---|
| `PARSER_LIMIT` | the parser can die of **resources** (stack exhaustion on deeply nested expressions), not only of syntax — caught and mapped, never escaping as a native exception |
| `STALE_SOURCE` / `PREIMAGE_MISMATCH` | a plan is bound to one revision, at document and at span granularity |
| `LINE_NOT_OWNED` | `delete own-lines` never silently degrades to `exact` |
| `OVERLAP` | strict intersection; two inserts at one offset are refused rather than ordered by invention |
| `RENDER_NOT_PARSEABLE` / `RENDER_NOT_VALID` / `BASELINE_NOT_CLEAN` | the result must re-parse, and optionally validate clean in its whole tenant — with the precondition that the baseline validated clean first |

## The adversarial finding you should carry across the seam

The renderer was red-teamed with six independent attack lenses and skeptical
verifiers: 12 raw findings, 6 confirmed, 5 refuted.

The one that matters was not the crash but its aftermath. A parser stack overflow
**corrupted shared parser state**, so the *next* call on a valid file returned
`ok: true` with an inventory truncated to the root node — 8 → 1 → 8 nodes,
deterministic across cycles and across three real fixtures. That is the worst
failure shape for a lossless renderer: not a refusal, but a **declared success over
mutilated data**, precisely in a multi-file scanning scenario.

The fix discards and rebuilds the shared services after any caught parser
exception, and the regression test asserts the **full inventory with exact
node-ids** immediately after a crash — not merely the node count. Any consumer
driving the renderer over many files in one process inherits this invariant and
should keep it under its own test.

The other confirmed findings: an off-by-one in the own-lines extension that
produced an `APPLIED` delete of zero bytes (the silent fallback the contract
forbids); a non-atomic `--write` that could truncate the source after a success
receipt; and an empty `--tenant-dir` that silently disabled the compiler proof.

## A non-obvious property of the IR

The IR is **not line-neutral**: it carries per-node provenance (file and line). A
comment inserted on its own line moves the IR of everything below it; a comment
appended at end-of-line does not. An edit that must be strictly IR-neutral should
prefer the latter. This is a property of the IR contract, not of the renderer.

## Verification

All gates run inside the compiler test chain (`npm test`, exit 0 at this revision):

| gate | what it measures |
|---|---|
| `tooling/test/lossless-roundtrip-corpus.ts` | byte identity on every tracked `.metis`, with an explicit (currently empty) list of gate rejections — no silent skips |
| `tooling/test/lossless-adversarial.ts` | comments, tabs, hand-aligned columns, blank lines, trailing whitespace, CRLF, missing final newline, unicode, deep nesting, state-corruption regression |
| `tooling/test/lossless-editplan.ts` | one violation per rejection reason in the closed set |
| `tooling/test/lossless-edit-minimal.ts` | replace / insert / delete `own-lines` on a real corpus file, byte checks outside the spans, non-idempotence |
| `tooling/test/lossless-compile-proof.ts` | whole-tenant validation on a temporary copy: IR byte-identical on a neutral edit, IR moving on a semantic one |

## Explicitly NOT claimed

- No host integration, no opaque-reference resolution, no wiring of any kind.
- No performance claim under load; no caching design.
- No stability of node-ids across revisions.
- The renderer replaces neither the formatter nor the migration emitter: the
  formatter re-lays-out on purpose; this exists to rewrite nothing that was not
  asked for.

## Evidence

Ready for a toolchain-pin evidence block, in the shape
`manifests/metis-brain-toolchain-pin-v1.json` already uses:

```json
{"id": "lossless_types",           "path": "tooling/src/lossless/types.ts",            "blob_oid": "c9bd23a5d72cccaf7e4e51b6bcac2656b26a30eb", "sha256": "sha256:b0eb1de471f7b92719fdb70b084b21d00f1be0a6127bb6b316e1599bc7db4b8d"},
{"id": "lossless_inventory",       "path": "tooling/src/lossless/inventory.ts",        "blob_oid": "770177d5b0547d1daa3e11b519cba72c08f97cac", "sha256": "sha256:d3e8af05fe39848257ebe7234c6e343c5bb51feb30cca694d82fbd0c023b058e"},
{"id": "lossless_plan",            "path": "tooling/src/lossless/plan.ts",             "blob_oid": "78351e5927aa71d27648710f759a398f1d1b0e20", "sha256": "sha256:1d982994f0c27577553d9d9c63d069409e5b84bb2abe74f12376275884ab5f6e"},
{"id": "lossless_apply",           "path": "tooling/src/lossless/apply.ts",            "blob_oid": "1d25e9faf7d2ebf1e413ac3fde27673b544d5717", "sha256": "sha256:88a7155c5ad342295f03ca563a3e9ae6ccb49dd8498ba0359a254ed9d2c825c5"},
{"id": "lossless_toolchain",       "path": "tooling/src/lossless/toolchain.ts",        "blob_oid": "45ebb166e2b82cfa82bd221e1f7bbc878e1807cc", "sha256": "sha256:f8b1aa6bafd21cd42c9a4a3580f99a13124cfb256a9d88ac4dece2186a8c6127"},
{"id": "lossless_cli",             "path": "tooling/src/cli/lossless.ts",              "blob_oid": "4662c09509faf6c8ae7152ddc3bfb14e458b9576", "sha256": "sha256:8965bcfb5634074e8df6c9b54c303078b8840ee0556d79d6dab9830931accf77"},
{"id": "lossless_spec",            "path": "docs/design/lossless-renderer/spec.md",    "blob_oid": "f2a7139ea61ba6b48bad255f173495a1c2beefe2", "sha256": "sha256:6091ba319005fc26ef4d3276be486efbbe236db2e24ab2fc7434525a116bb717"},
{"id": "lossless_api",             "path": "docs/design/lossless-renderer/api.md",     "blob_oid": "98e871ef50c61329e6a1a7fd9a20fea93b243778", "sha256": "sha256:fcf9812049b4f843c26e21f85370c9827ace650a14b273795c0b1c1c05a473eb"},
{"id": "lossless_gate_roundtrip",  "path": "tooling/test/lossless-roundtrip-corpus.ts","blob_oid": "33cd3bfa24f4007e1f8c122115cc174888680213", "sha256": "sha256:f080e50cb10432809b3fcfce70fd1eac95854d9ca6b6281f371b6bfad865297f"},
{"id": "lossless_gate_adversarial","path": "tooling/test/lossless-adversarial.ts",     "blob_oid": "6e9a5a7ad044086eb7117767c4e5d060f1b3fe97", "sha256": "sha256:8d4aa0b0de7e4d314c4e7a5b592dc7d6fe5807f044224f1db8f0c14cfe820c5f"},
{"id": "lossless_gate_editplan",   "path": "tooling/test/lossless-editplan.ts",        "blob_oid": "2536764739450296f80625a6ad0982bbd0a087da", "sha256": "sha256:d26ac69424361dced94de86c5978b531e2b96f8ba206f6fc6e4516f819c70d85"},
{"id": "lossless_gate_minimal",    "path": "tooling/test/lossless-edit-minimal.ts",    "blob_oid": "219e3b4b0d567161af18e9b123c06b155cdd6075", "sha256": "sha256:d46f91d33382fd09a91fcafbcb2b0011d76ad22ad00019d99e0571b980073dfa"},
{"id": "lossless_gate_compile",    "path": "tooling/test/lossless-compile-proof.ts",   "blob_oid": "2cbb069e325687abf05a93d3f0b10073f57ae2f0", "sha256": "sha256:2f84501b5cb18ffc74fdb5a8ef91f415a7d071cc050c1fb83a4d164174b06a89"}
```

Suggested probes, with their success markers:

```json
{"id": "lossless_roundtrip",  "cwd": "tooling", "argv": ["node","--import","tsx","test/lossless-roundtrip-corpus.ts"], "success_marker": "LOSSLESS_ROUNDTRIP_CORPUS: VERDE ✓"},
{"id": "lossless_adversarial","cwd": "tooling", "argv": ["node","--import","tsx","test/lossless-adversarial.ts"],      "success_marker": "LOSSLESS_ADVERSARIAL: VERDE ✓"},
{"id": "lossless_editplan",   "cwd": "tooling", "argv": ["node","--import","tsx","test/lossless-editplan.ts"],         "success_marker": "LOSSLESS_EDITPLAN: VERDE ✓"},
{"id": "lossless_minimal",    "cwd": "tooling", "argv": ["node","--import","tsx","test/lossless-edit-minimal.ts"],     "success_marker": "LOSSLESS_EDIT_MINIMAL: VERDE ✓"},
{"id": "lossless_compile",    "cwd": "tooling", "argv": ["node","--import","tsx","test/lossless-compile-proof.ts"],    "success_marker": "LOSSLESS_COMPILE_PROOF: VERDE ✓"}
```

## Reception is yours

The shape that fits your existing policy: add these paths as evidence entries to
the toolchain pin manifest with the revision and tree above, add the five gates as
probes, and run your frontier seam gate on the result — recompute at least one
claim independently rather than accepting this document's prose.

The delivering team has deliberately **not** edited your manifest, your run board,
or any other file here: accepting an external artifact is your gate to run, not
ours to pre-empt.
