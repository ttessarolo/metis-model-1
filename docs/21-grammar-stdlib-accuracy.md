# Grammar and standard-library accuracy

Status: **D18 CANDIDATES COMPLETE — SEALED ZERO-MODEL REPORT RECOVERY PENDING; TRAINING FALSE**.

This wave closes the largest known limitation of the delivered local adapter:
its optimizer saw a narrow catalog-domain training slice, not the complete
Metis language surface. The successor treats the grammar and the Metis
standard library as two separate, versioned coverage authorities.

It does not rewrite or enlarge the claims of `INITIAL_LOCAL_QLORA_V1`, B12, or
`DEMO_ACCURACY_V1/V2`. Their rosters, outputs, scores, and receipts remain
immutable and may not be used as training examples.

## Authority and pin

The executable authority remains Metis revision
`5e112f9148f40e7e792052e896c5a9efe8eaf0a2`, tree
`41c7a2b6890fa42d8123bd93f6560d0b9bfae8af`. The successor pin adds the
standard-library registry and its validator/compiler/test closure to the
already qualified grammar/compiler pin.

The overlay binds eight exact Git blobs: the handwritten grammar, generated
grammar, stdlib registry, language version, guard evaluator, corpus-validation
test, time-rule test, and compiler-regression test. The verifier requires the
exact ID/path roster as well as each blob OID and SHA-256; a same-sized but
different evidence list is rejected.

The current read-only Metis HEAD observed at wave opening is
`c1aca0f629ec96a5ea1f52eea5b4561d0c41f6b5`. Its grammar and
`stdlib-schema.ts` Git blobs are byte-identical to the executable pin. This
permits the smaller stable pin to remain the benchmark authority without
silently absorbing unrelated later changes. The external checkout and all
tenant repositories remain read-only; untracked paths, tenant payloads,
credentials, and live data are excluded.

The initial deterministic inventory has these independent denominators:

- grammar productions: `172`;
- top-level alternatives: `10` (`Tenant`, `Catalog`, `Property`, `Endpoint`,
  `Preset`, `List`, `Transformer`, top-level `Block`, `SettingsDecl`, and
  `ValueSet`);
- registered standard-library modules: `3`;
- registered public standard-library members: `12`;
- standard-library settings: `1`.

The full 172-rule inventory is a change and gap detector. It is not converted
into a false claim that a small benchmark independently tests every parser
production. Model-facing tasks declare the exact rules and semantic constructs
they exercise, and the report publishes both the covered and uncovered sets.

## Standard library is first-class

The standard library is not a tenant `lib/` directory and is not inferred from
the play examples. Its normative source is
`tooling/src/language/stdlib-schema.ts`:

- ambient `time`, enabled through `needs time`: `now`, `month`, `day`, `hour`,
  `hhmm`, `weekday`, and `fractional_second`;
- pure `std.codec`: `decode` and `encode`;
- pure `std.text`: `slugify`, `truncate`, and `normalize`;
- setting `time.timezone`.

The benchmark must distinguish four independent behaviors:

1. valid ambient capability declaration and use;
2. valid pure `std.<module>.<member>(...)` calls;
3. rejection and repair of unknown modules or members;
4. rejection and repair of an ambient module incorrectly called through
   `std.` or used without `needs`.

Module coverage and member coverage are reported separately. Merely mentioning
`time`, `codec`, or `text` in a prompt earns no semantic credit.

Every base/adapter request receives the same tracked compact retrieval context
at `fixtures/grammar-stdlib-accuracy-v1/reference-context.md`. It contains the
ten top-level skeletons, the current catalog-domain surface, and the complete
stdlib registry/usage boundary, but no D18 identifier, answer, tenant payload,
or historical model output. Its bytes and every resulting message hash are
bound before inference. This keeps mutable language knowledge retrieval-owned
while the adapter supplies stable author/edit/review behavior.

## Execution sequence

### G0 — inventory and existing-coverage audit

The pin verifier reconstructs the grammar and standard-library inventory from
Git objects at the exact Metis revision. A separate baseline matrix records
what appears in INITIAL train/dev, B12, and DEMO V1/V2. Historical model output
is never opened or copied to create this matrix.

### G1 — fresh D18 diagnosis

`D18` contains exactly 18 fresh public-synthetic tasks, three per F-1 through
F-6. Before any model output it binds:

- all ten top-level alternatives across task inputs and truths;
- all three standard-library modules and all twelve public members;
- author, minimal edit, diagnostic repair, review, migration, and structural
  explanation;
- exact prompt, expected source or JSON, parser/linker/validator/compiler
  evidence, construct coverage, and provenance;
- fresh identifiers, template roots, and source roots disjoint from INITIAL,
  B12, DEMO V1/V2, and future T30.

The Qwen3.8 base and selected step-50 adapter receive identical current
grammar/stdlib context, generation settings, and oracle loops. Raw generations
remain ignored under one single-use artifact directory and are never training
data.

Seven tasks select a named endpoint and therefore bind compiled IR as well as
AST/diagnostics. Non-endpoint constructs use source mode and cannot claim IR
credit. F-5/F-6 remain explicitly human-review authority; their raw mechanical
matches cannot by themselves authorize a dataset or delta QLoRA.

The fixed scoring contract is `metis-semantic-signature/v2`. Raw oracle hashes
remain execution lineage, while model credit uses a domain-separated semantic
signature: exact grammar features, types, literals, ordered constructs, and
resolved reference identities in the AST; canonical IR with only
`provenance.file` and `provenance.line` removed; and diagnostic
filename/code/severity/message multisets with source ranges removed. Selected
endpoint, execution mode, and failure kind are bound too. A live pinned
metamorphic test proves that CRLF and blank-line changes alter raw
AST/IR/diagnostic hashes without altering this signature, while a predicate
literal change does alter it.

Only the nine F-1/F-2/F-3 source tasks have automatic semantic authority. Their
diagnostic gate requires at least `8/9`, at least `2/3` in each of those three
families, zero critical failures, and no paired adapter regression. The three
F-4 JSON contracts are diagnostic-only; the three F-5 migrations and three F-6
reviews require human judgment. None of those nine nonautomatic tasks can enter
delta-threshold arithmetic. Their exact-output mechanics are reported, not
laundered into semantic or training labels.

`D18` is diagnostic, not a final accuracy denominator. A formatting difference,
underspecified request, retrieval failure, tool failure, or defective oracle
cannot become a model failure or training label.

The current pre-output truth is `18/18`, has self-hash
`sha256:0dff3f9279b00d50b3d7d544e0932bf7dcb02f3f26cd2608df2eae5b1048a542`,
binds all ten top levels, all twelve standard-library members and the
`time.timezone` setting, and records zero model outputs and zero training or
delta authority.

The audited zero-output freeze binds published preimage commit
`4c0b32a03b5159e33f9b2c6955ffbc85e5c9e5f9`, tree
`d472c02b1993fefb60504c023f5af183d9aa7595`, and 21 exact input records,
including the transitive catalog-retrieval module and catalog pin
manifest/schema used to construct the grammar/stdlib snapshot. Its self-hash is
`sha256:730fb0ab6954652666ebd1b6d86bc82d392c55e214ff83be3f0c35d976b4df02`.
The fixed ignored run directory was absent when the seal was created. The
freeze was then committed, pushed and exactly reopened before either base or
adapter generated a token.

The freeze was published and consumed once. Both 18-row candidate files were
written, then the original process stopped before `report.json` when its final
bound-input recheck timed out executing the pinned Apple Git while severe host
memory pressure was also observed. The timeout is the recorded failure; the
memory condition is operational context, not a proven root cause. The partial
run contains exactly those two regular, single-link files:

- base: 4,716 bytes,
  `sha256:256b65c346978e3dd01db368d51157dccd20f8fc50c5144afec3ea1a1bd54c38`;
- adapter: 4,359 bytes,
  `sha256:2b254555a1cb991fb59fda39b29ac1b43ae7d1a0fd5feaf6c2b1e4dd22e951cd`.

Recovery is an exact candidate replay, not a second inference and not a clean
retroactive attestation of the interrupted process. A separately published
sidecar must bind the original freeze, all 21 inputs, both candidate files and
the still-absent report; it authorizes only pinned-oracle rescoring and the
single no-clobber publication of `report.json`. It forbids model replay,
training, delta authorization and alternate Git implementations. Normal D18
evidence must then independently rescore the completed report.

### G2 — decision and held-out T30

If D18 does not establish delta eligibility, the current adapter is retained
and a fresh held-out `T30` is sealed and run without retraining. If D18 does
establish eligibility, T30 is sealed before any derived dataset is built and
remains unavailable to training and checkpoint selection.

Delta eligibility requires at least three genuine, reproducible,
oracle-correctable semantic failures across at least two task families and two
independent provenance roots. The automated evaluator may request
adjudication; it cannot authorize an optimizer.

The bounded T30 gate requires:

- at least `29/30` semantic successes;
- every family above its preregistered minimum;
- all ten top-level alternatives and all twelve stdlib members covered by at
  least one semantically correct task;
- zero critical, invented-symbol, unauthorized-write, or retrieval-truth
  failures;
- no adapter regression on a base-green task;
- exact adapter-off restoration and reproducible receipts.

This is a bounded product-coverage result, not the separate 600-task/563-root
`ACCURACY99_PROMOTED` population claim.

### G3 — conditional delta QLoRA

Only after the D18 adjudication and T30 pre-output seal may a delta dataset be
created. It must use new public-synthetic roots, accepted-by-oracle targets, an
independent dev split, and a small stable replay set that is not derived from
D18 or T30. Selection uses dev only. The existing adapter remains the rollback;
full retraining and base-weight fusion remain outside this path.

## Update policy

A future grammar or stdlib change follows the same minimum-intervention rule:

1. pin the new grammar, generated AST, registry, validator, compiler/IR, and
   relevant tests;
2. compute the exact grammar-rule and stdlib module/member diff;
3. refresh task context and applicable oracles;
4. run the existing adapter on a fresh maintenance benchmark;
5. publish `NO_RETRAIN` when gates remain green;
6. otherwise apply only a bounded delta QLoRA to independently demonstrated
   failures, retain rollback, and rerun regression gates.

Grammar and stdlib belong to the current toolchain context as well as to stable
model skills. Tenant symbols, catalog values, and other mutable state remain
retrieval-owned and are never memorized merely to improve a benchmark score.

## Current authority boundary

At this document state, inventory, fixtures, oracle code, tests, manifests,
and Git metadata may be built and verified. No model output may be produced
until a complete truth manifest and Git-published pre-output freeze exist.
No optimizer step, dataset derivation, checkpoint, packaging update, or S3
write is authorized by construction work alone.
