# Demo accuracy closure v1

Status: **V1 TERMINAL DIAGNOSE — verified evidence on 25 August 2026; fresh
successor prompt cure required**.

`DEMO_ACCURACY_V1` is the smallest catalog-domain accuracy gate for the macOS
development demo. It qualifies neither a general model nor a released product.
Its purpose is to decide whether the already selected local adapter is accurate
and non-regressing on the declared catalog-domain surface. Adapter uplift was
already established separately on dev16; parity with a green base is acceptable
here and is reported honestly as parity, not new uplift.

## Scope

The fresh public-synthetic roster contains exactly 12 tasks: two each for
F-1 authoring, F-2 minimal editing, F-3 diagnostic repair, F-4 review,
F-5 migration/canonicalization, and F-6 structural explanation. Every task
has fixed oracle truth and a distinct public-synthetic task record. Exact task IDs
and the reserved `demoacc_` symbol namespace do not occur in the consumed
INITIAL_LOCAL_QLORA_V1 train/dev sets or W5-XS B12 roster. This exact-namespace
check does not claim semantic-template independence: the gate intentionally
tests the same product abilities on fresh identifiers and compositions.

The roster must include the realistic demo actions that the prior surface did
not measure: review with a concrete finding, a bounded canonical migration,
and a normalized structural inventory. Every expected driver, identifier,
cardinality, tenant threshold, controlled diagnostic code/path grammar, JSON
vocabulary or value needed for a unique answer is stated before inference; an
under-specified oracle is a benchmark defect, not a model failure.

## Freeze and paired execution

Before any output, `truth` and `freeze` publish the complete ordered roster,
oracle policy, model/checkpoint identities, prompt, retrieval presentation,
sampling, reasoning mode, token limit, and repair budget. The base and the
selected adapter then run the same frozen tasks with every generation setting
identical except `adapter_path` / `adapter_enabled`.

The semantic oracle must compare normalized AST/IR and declared structural
invariants, not parser coordinates, whitespace, or formatting layout. If
canonical rendering is required, it is a separately reported formatter gate;
it must not turn an IR-equivalent source into a semantic failure. Parse, link,
validation, compile, minimal-patch, invented-identifier, diagnostic, and
family-specific oracles remain independently visible.

The authorized sequence is single-use and ordered:

```bash
uv run python -m metis_model1.demo_accuracy truth
uv run python -m metis_model1.demo_accuracy freeze
uv run python -m metis_model1.demo_accuracy run
uv run python -m metis_model1.demo_accuracy evidence
```

Raw prompts, generations, repair attempts, and model outputs remain in a
fresh ignored run directory. They are never appended to training data, never
used for checkpoint selection, and cannot amend a frozen roster or oracle.
The run is single-use: a partial worker failure is retained as a consumed failed
attempt and requires a separately frozen benchmark ID rather than deleting or
reusing the directory.

## Gate

`DEMO_ACCURACY_V1_PASS` requires all of the following:

- adapter semantic success is at least `11/12`;
- each F-1…F-6 family has at least `1/2` semantic successes;
- adapter critical failures, accepted invented identifiers and roster gaps are
  all zero; normalized target equality rejects unrelated semantic edits while
  whitespace/layout differences are not model failures;
- the adapter loses no base-green task and does not regress the aggregate
  paired base result;
- identities, receipts, hashes, and offline execution evidence verify.

Otherwise the gate is `DEMO_ACCURACY_V1_DIAGNOSE`. It does not permit a retry
of the consumed run.

## V1 observed result

The single sealed run is terminal at base `10/12` and adapter `10/12`. Both
variants score `0/2` on F-1 and `2/2` on each of F-2...F-6, with zero critical
failures, invented identifiers, roster gaps, aggregate regressions, or paired
base-green regressions. Evidence self-hash is
`sha256:8057c5fb96726e974dbebb57846d583f928e9e58d1467a9759c0a3dc7fcdf6ab`.

L0 and three independent read-only audits classify both F-1 misses as genuine
structural failures, not retrieval or oracle defects. All four base/adapter
answers omit the literal braces required around the catalog and `fields`
blocks, so pinned `describe` retains at most the id field and drops the requested
domain fields; the adapter also leaves one index unquoted. The prompt names all
required semantic values, but the shared system contract does not render the
literal structural scaffold. The smallest lawful next action is therefore a
generic prompt/retrieval cure plus a separately sealed fresh successor roster,
not rescoring V1 and not training on its outputs.

## Fresh successor V2

V2 keeps the same 12-task/family/output-kind arithmetic, thresholds, pinned
retrieval, model identities, runtime, and semantic oracle. It changes only:

- a generic source-system rule saying that catalog and `fields` are literal
  brace-delimited blocks and that `index` takes a double-quoted string;
- a fresh `demoacc_v2_` task/identifier namespace, with new cardinalities and
  values, scanned against train64, dev16, B12, and the consumed V1 roster;
- V2-specific truth/freeze/evidence IDs, authority, verdict, and ignored run
  directory.

The prompt cure contains no catalog name, task identifier, expected value,
cardinality, field order, or complete target. V1 remains the immutable terminal
diagnosis. V2 uses the same pass predicate and may prove only the same bounded
catalog-domain Mac demo accuracy claim.

The successor restores the V1 default configuration on every exit path; the
terminal V1 evidence remains reproducible from its published historical commit.
V2 runs as:

```bash
uv run python -m metis_model1.demo_accuracy_successor truth
uv run python -m metis_model1.demo_accuracy_successor freeze
uv run python -m metis_model1.demo_accuracy_successor run
uv run python -m metis_model1.demo_accuracy_successor evidence
```

## Training decision

Delta QLoRA remains prohibited by default. Its adjudication threshold is met
under this accuracy-closure mandate only if the
frozen run observes at least three genuine, reproducible, oracle-correctable
semantic failures across at least two families. Formatting-only differences,
under-specified requests, retrieval/tool failures, and defective oracle truth
are diagnosis inputs, not training labels. Any eligible retune still requires a
new frozen provenance-safe dataset, stable replay, an independent dev split,
and an adapter-on versus adapter-off regression gate before optimizer startup.
The automated report can only request L0 oracle adjudication; it never grants
training eligibility or optimizer authority by itself.

V1 observes only two genuine failures in one family. Its delta threshold is
therefore not met and the recorded action is `no_retrain`.

## Explicit non-claims

This contract does **not** claim global `ACCURACY99_PROMOTED`, full endpoint
workflow accuracy, population accuracy, tenant-data competence, live ARES
execution, Companion delivery, VS Code integration, remote fallback,
distribution, or Windows support. It does not promote the adapter or replace
the frozen Accuracy-99 benchmark.
