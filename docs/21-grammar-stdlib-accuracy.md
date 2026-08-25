# Grammar and standard-library accuracy

Status: **D18 CLOSED NO_RETRAIN — T30-v1 DIAGNOSED — T30-v2 CLOSED 29/30
DIAGNOSE — PROMPT-ONLY T30-v3 CURE ACTIVE**.

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

The recovery implementation preimage is published as commit
`baf10f565ac6246b9fa682aac1c2e67c176c6a5b`, tree
`13b11351a0091a13e4291119f6cc65de30a25085`. The materialized recovery freeze
has canonical self-hash
`sha256:440f706f9152cc11a9d4790e38ffde47ec301beab1676be8d5267977af0bbfd0`
and raw file hash
`sha256:e4d64014afc34d949075b7ddb91e1325e4aee56ffc9e727503a9382533c059bb`.
Two independent audits return P0=0/P1=0/P2=0. The seal must itself be
committed, pushed and exactly reopened before the zero-model rescore may write
the previously absent report.

The seal was published as commit `d547441c4ab4a028192c70f682fbe1aa64b68bbf`,
tree `9c3154cd3cb0b0e20b71cdc7280f3c52694e4135`, before recovery. Recovery made
zero additional model calls and produced a 28,174-byte report with self-hash
`sha256:58421babac0fa688c7dcc8ef56cd6699481e2a79a9c037d37a2fe408783799c3`.
Independent evidence then reproduced every automatic observation and gate
decision; its self-hash is
`sha256:4c672aa39139ac71a8a2d3fbb2416572d628e66398d184cba08a8b353eb3e2b4`.

Base and adapter both score `8/9` on the automatic semantic denominator:
F-1 `3/3`, F-2 `3/3`, F-3 `2/3`, with zero critical failures and zero paired
regressions. Both miss the same F-3 endpoint-variant surface because the
retrieval context lacks the generic `variant <name> use block.<name>`
micro-skeleton. Both also miss one literal diagnostic-marker echo in F-4,
which is diagnostic-only. L0 review accepts all twelve base/adapter decisions
for the six F-5/F-6 tasks (`12/12 ACCEPT`, `0 REJECT`, `0 UNCLEAR`) without
converting them to automatic semantic or training credit.

The L0 human adjudication, including a task-specific rationale and exact target
binding for each F-5/F-6 decision, is
`sha256:1c17c12d03e9b89c2c901427be1b98a42a62d195d8b5af490c1a4ec5cb753eec`.
The raw delta census is one task, one family and one independent root against
the required `3/2/2`; after classifying the missing surface as a retrieval
context gap, training-eligible failures are zero. The terminal D18 decision is
`GRAMMAR_STDLIB_D18_NO_RETRAIN`: retain the current adapter, add only the two
generic retrieval instructions, and test them on fresh held-out T30 tasks.

### G2 — decision and held-out T30

The immutable T30-v1 contract is tracked at the following paths:

- `manifests/grammar-stdlib-accuracy-t30-policy-v1.json` — ratified one-shot
  policy, thresholds and explicit nonclaims;
- `fixtures/grammar-stdlib-accuracy-v1/t30-tasks.json` and
  `fixtures/grammar-stdlib-accuracy-v1/t30-reference-context.md` — fresh
  public-synthetic roster and retrieval-owned grammar/stdlib context;
- `src/metis_model1/grammar_stdlib_t30.py` and
  `tests/test_grammar_stdlib_t30.py` — sealed truth/freeze/run/evidence
  implementation and focused contract tests.

Its pinned-oracle truth is materialized at `30/30` distinct tasks with canonical
self-hash
`sha256:febbde8bbf2b2ca1fa2a7cf667791acfa889080cada6d9322537dfa678e9546a`.
L0 independently verified canonical bytes, counts and the exact coverage union.
The preimage is published at
`a4d6e68168a787695dd287676d929fbefa81928e`. The canonical pre-output freeze
has self-hash
`sha256:cb8d5cd4c9899ae55f964096c29621f0754d37093f105527473db3e7f50f9703`
and binds 26 current inputs. Retraining, delta QLoRA, dataset derivation and
promotion remain unauthorized. The denominator
explicitly includes all ten top-level grammar alternatives, all three Metis
standard-library modules, all twelve public members and `time.timezone`.

The T30 freeze reopens the historical adapter lineage without comparing old
training-source blobs to the evolving live worktree. It derives the original
28-file roster from the trainer source at its recorded Git preimage, verifies
every historical blob there, and requires the training freeze to be byte-exact
at its recorded execution commit. Separately it replays the current base,
step-25, selected step-50 and adapter-off-restored dev bundles. The portable
package is verified internally at `11/11`; its eight payload-backed members are
byte-equal to the live dataset, adapter, receipts and runtime lock. The package
is also anchored to the tracked backup preimage, archive hash and fully checked
versioned S3 receipt. This preserves historical immutability while permitting
later source and contract maintenance.

The published freeze was consumed once. Base and adapter each returned exactly
`30/30` candidates with zero gaps and zero paired regressions. The immutable
automatic score is `10/20` on both sides: F-2 and F-3 are `5/5`, while F-1 and
F-4 are `0/5`; provisional F-5 is `3/5` and F-6 is `0/5`. Evidence self-hash is
`sha256:e6e4d4d015c8086203c81a69800a3a14c136c01d3c66304d99df74b84349f0ac`.

That number is terminal diagnostic evidence, not a valid accuracy denominator.
F-1 asked for open authoring but compared the answer with hidden exact names and
literals. F-4/F-6 exposed only source-surface labels while the evaluator required
undisclosed AST class names and stripped standard-library registry IDs; legal
aliases were incorrectly reported as invented symbols. The result is preserved
without rescore or retroactive promotion. The genuine model-attributable
failures remain below the ratified `3 tasks / 2 families / 2 roots` delta gate,
so T30-v1 does not authorize training.

T30-v2 is a wholly fresh `30=5x6` successor. Before any output it must publish:

- fully determined F-1 names, literals, order, cardinality and endpoint target;
- separate, exact F-4 and F-6 JSON serialization contracts;
- the source-token to AST-kind map, recursive `NamedBlock` traversal, registry
  member normalization, endpoint selection semantics and list deduplication;
- parser-clean generic grammar cues for external values and both compact variant
  forms;
- successful-task denominators for all ten grammar top levels, all three stdlib
  modules, all twelve members, `time.timezone`, and the ambient/pure/namespace/
  `needs` interaction boundary.

Only the existing base and adapter are compared. T30-v1 tasks, messages, roots,
semantic targets and outputs are freshness inputs, never v2 labels.

The fresh pinned truth is now materialized at `30/30` distinct tasks, zero gaps
and five tasks per family, with canonical self-hash
`sha256:3c4139c0d763e131be7c18332af2c5a8dd847865db4097e1b98c53823647f216`.
It binds the terminal non-promotable v1 diagnosis, policy
`sha256:169414ccb36b2d9c29b173a124296d97534bf9d97c52bfbae7709b7ef0d6ac74`,
the complete grammar/stdlib reference and the fresh roster. F6 structurally
exercises `implicit`, `external-enum`, retained tiny `inline` and `open` catalog
domains while serializing size but never inline literal values. Model outputs,
training and delta QLoRA were zero/false at truth construction.

The published one-shot T30-v2 run is complete at base `30/30` and adapter
`30/30` outputs with zero gaps. After all fifteen preregistered F-2/F-5/F-6
human reviews, base is `30/30` and the adapter is `29/30`: F-1 is `4/5`, while
F-2 through F-6 are each `5/5`. The twenty-nine successful adapter tasks still
cover all ten grammar top levels, all three standard-library modules, all
twelve public members, `time.timezone`, and all ten interaction classes.

The sole failure is a paired base-green adapter regression on one F-1 author
task: three endpoint attributes were emitted after an unbraced `attributes`
keyword. The pinned grammar permits that compact form only for one assignment,
so the second assignment is rejected. This is one genuine model root, not
retrieval, prompt-target or Oracle drift. Final adjudication self
`sha256:43c345ffd8106f7319fdc521280cf9c644299de3db44181e9844d8845f823015`
therefore preserves `GRAMMAR_STDLIB_T30_V2_DIAGNOSE`; the critical and paired-
regression vetoes cannot be waived by the otherwise green score.

Delta eligibility requires at least three genuine, reproducible,
oracle-correctable semantic failures across at least two task families and two
independent provenance roots. The automated evaluator may request
adjudication; it cannot authorize an optimizer.

The bounded T30 gate requires:

- at least `29/30` semantic successes;
- every family above its preregistered minimum;
- all ten top-level alternatives, all three stdlib modules, all twelve members,
  `time.timezone`, and every preregistered stdlib interaction class covered by
  at least one semantically correct task;
- zero critical, invented-symbol, unauthorized-write, or retrieval-truth
  failures;
- no adapter regression on a base-green task;
- exact adapter-off restoration and reproducible receipts.

This is a bounded product-coverage result, not the separate 600-task/563-root
`ACCURACY99_PROMOTED` population claim.

### G3 — conditional delta QLoRA

T30-v2 establishes only one task, one family and one independent failure root,
below the ratified `3 tasks / 2 families / 2 roots` threshold. It authorizes no
dataset or optimizer step. Only after a future valid fresh adjudication
establishes delta eligibility may a delta dataset be created. It must use new
public-synthetic roots,
accepted-by-oracle targets, an independent dev split, and a small stable replay
set that is not derived from D18, T30-v1 or T30-v2. Selection uses dev only. The
existing adapter remains the rollback; full retraining and base-weight fusion
remain outside this path.

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

At this document state D18 is closed as `NO_RETRAIN`; T30-v1 and T30-v2 are
immutable benchmark diagnoses. Their outputs remain ignored and ineligible for
training. The only active accuracy path is a fresh T30-v3 successor using the
same pinned grammar, standard library, base and adapter plus one generic
retrieval instruction: unbraced `attributes` is allowed for exactly one
assignment, while two or more assignments require a braced group. T30-v3 must
re-demonstrate the complete `10/3/12/1/10` grammar/stdlib denominator and may
not replay or relabel a v2 task. No optimizer step, dataset derivation,
checkpoint, package or S3 payload change, external Metis mutation, Companion,
Windows work or population-accuracy promotion is authorized.
