# Metis Brain: typed CREATE authority and cumulative refinement

Status: **G5 CORE VERIFIED; CLIENT AND ADVANCED PACKS OPEN**.
This document is the normative design for
creating and refining complex endpoints without exposing a golden endpoint to a
model, accepting arbitrary source as authority, or mutating the tenant.

This document implements D-017: typed CREATE is a general Metis capability,
not a collection of tenant- or benchmark-specific shortcuts.

## Why whole-source generation is not the product path

The frozen complex corpus contains endpoints between 122 and 588 lines
(approximately 4.1--20.4 KB).  Model 1 is deliberately bounded to 512 output
tokens per call.  Raising that ceiling would increase interactive latency and
would still not prove that a structural change was requested, grounded, or
preserved across refinement.

CREATE therefore uses a compact typed plan.  Model 1 selects only host-issued
opaque references under a closed JSON schema.  A deterministic private builder
expands the admitted plan, the pinned compiler validates the complete isolated
snapshot once, and Brain publishes a Draft only when the compiler receipt and
the expected structural delta agree exactly.

## Authority chain

```text
operator messages plus typed clarification decisions
    -> immutable session context and semantic snapshot
    -> host-issued requirement, structure, catalog, field, value and stdlib refs
    -> schema-constrained CreateDeltaPlan proposed by Model 1
    -> exact coverage and role validation by Brain
    -> one-shot CreateDeltaPermit
    -> deterministic typed expansion in an isolated tenant snapshot
    -> compiler receipt, candidate manifest, normalized IR and canonical delta
    -> atomic compare-and-swap of the private conversation head
    -> public Draft proposal
```

The model never receives a filesystem path, raw reference endpoint, golden
source, hidden template, compiler IR, bearer token or Apply capability.  A
compiler-clean candidate is necessary but not sufficient.

## D-017 — generalità e autorità dei descrittori

Il runtime possiede grammatica, standard library, compilatore, diagnostica,
limiti e orchestrazione. Non possiede la conoscenza del dominio. Catalogo,
campo, valore, alias, mappatura fra cataloghi e lessico operativo devono
provenire dalla proiezione Schema2 del tenant attivo, con stato `reviewed`,
value-set/domain e revision binding verificabili. Il modello riceve soltanto
riferimenti opachi e contesto bounded; il builder risolve quei riferimenti
contro lo snapshot e non accetta stringhe di dominio come autorità.

Sono vietati shortcut basati su nome del campo, tenant, endpoint, valore o
frase italiana. Un nome familiare non autorizza alcuna scelta semantica. Se un
ruolo strutturale — per esempio identità, similarità, recenza, grouping o
relazione fra cataloghi — non è dichiarato dai descrittori o da un oracle
tipizzato, la proposta deve produrre una decisione tipizzata dell'operatore o
uno `STOP` fail-closed. Non è ammesso dedurlo dal nome né copiarlo da una
recipe della demo.

Le recipe chiuse storiche e i loro profili di qualifica sono soltanto strumenti
di regressione: vivono nelle fixture test-only `tests/legacy_*`, non nel
pacchetto di prodotto. Non conferiscono autorità al runtime, non hanno un
percorso di attivazione e i loro punteggi non descrivono il nuovo default.

## CreateDeltaPlan v1

The plan has exact context, semantic and structural-surface revisions, a
role-typed target reference, an optional current-basis reference, a complete set
of requirement references, and source-ordered operations with contiguous
ordinals.  Every operation names at least one requirement.  The union of
operation requirements must equal the declared requirement set: omissions and
extras are both errors.

Il seguente è il vocabolario riservato dal contratto del piano, non una
dichiarazione che ogni operazione sia già una capability G5 attiva:

- endpoint creation and metadata;
- input and context declaration;
- block declaration, parameters and instantiation;
- query catalog, reviewed predicate, ordering, take and pagination;
- view-all, response and output pipeline;
- substitute or append fallback;
- bounded repeat and matrix expansion over typed scalar bindings.

Raw Metis, arbitrary strings, paths and template bodies are not plan values.
All executable values are opaque refs with server-verified roles.  Dependencies
must point backward, so the operation graph is deterministic and acyclic.

The measured complex-corpus lower bounds for a single endpoint are 16
containers, 11 top-level blocks, 9 variants, nesting depth 2, 11 context
fetches, 1 context transform, 32 fetches, 428 clauses, 451 predicates, 16 output
steps, 7 direct fallbacks, 6 materialized fallbacks, 12 block uses, 22 instance
arguments, 4 templates, 2 formal parameters per template, and an 11 by 2
parameter matrix.  Contract bounds include small explicit headroom but the
builder rechecks the fully expanded roster against independent resource limits.

## Permit and receipt

The private one-shot permit binds:

- session, turn, request and exact instruction digests;
- context revision, semantic revision and toolchain binding;
- target ref and target identity;
- conversation identity and next generation;
- optional current-head proposal, source, manifest and normalized-IR digests;
- structural outline, plan, grant roster and ordered operation seals;
- issue time, expiry and nonce.

Parent fields are all absent for generation zero and all present for a
refinement.  Consumption retires the permit before any validation, including a
malformed or stale attempt.  The receipt contains hashes and counts only.

## Latest-head refinement

Brain keeps exactly one volatile private head for a conversation target:

```text
initial create: no head plus absent target -> generation 0
refinement: supplied basis equals current head -> generation N+1
publication: compare-and-swap head N to N+1 with private attachments
```

An older proposal is `PROPOSAL_STALE`; implicit branching is not supported.
Exact idempotent replay of an already admitted request returns the original
turn even after the head advanced.  A failed, cancelled or clarification turn
does not advance the head.  Closing, expiry, cancellation cleanup and shutdown
erase proposal source, manifest, IR, permit state and head.

## Structural builder boundary

The builder consumes resolved typed objects, never model-authored source.  It
must refuse an existing initial target, an absent/stale parent, unknown or
role-swapped refs, unsupported operations, expansion beyond bounds, and any
payload containing raw DSL or path authority.

One isolated compiler call returns an exact receipt containing:

- rendered source and its SHA-256;
- candidate manifest and digest;
- provenance-free normalized IR and digest;
- canonical parent-to-child delta and digest;
- untouched-parent preservation proof;
- compiler/toolchain identity and diagnostics.

No HTTP route exposes this bridge.  Brain returns source only as a Draft; Apply
remains a separate explicit capability and is excluded from qualification.

## Historical fixtures and G5 capability status

Closed recipes have been physically removed from production. Their complete
historical behavior is retained only by `tests/legacy_*` fixtures, which may
import product primitives but are never imported by product code. There is no
compatibility flag, callback, registry entry or server configuration that can
activate a historical recipe at runtime. Historical scores are regression
evidence only, never a score for the descriptor-native default.

The G5 core engine is **VERIFIED** by the complete 4,444-case gate (4,442
passed, two explicit opt-in skips, zero failures/errors). This is a software
receipt, not a model, client or complex-demo qualification. Its generic
capability
surface currently offers: add a filtered block with a total count; add a
filtered page with `page_default` only as a new root variant (never on a
`NamedBlock`); change an existing take's total count; explicit ordering by a
reviewed field; a return projection whose
name is declared by the target catalog for that take; same-Draft block fallback;
and `similarity_from_input` using a catalog-declared profile and an explicit
seed input. Each remains bound to the active reviewed/technical authority and
the immutable session revision.

Before a Draft, an operator can correct a bound choice. Candidate rosters are
paged rather than silently truncated above 64 entries, and the private dialogue
has an explicit maximum of 32 rounds/decisions and 64 messages, without
increasing the previous total-byte allowance; it is not an indefinite chat history.
New substantive requirements invalidate a prior answer and require a new
bound decision.

The renamed-tenant real-compiler evidence for `similarity_from_input` is two
passing cases included in the complete core gate, not a client gate. Named
return projections are
implemented only through the catalog-declared roster above; `view-all`,
external fallback, grouping and arbitrary inter-catalog relations are not
claimed as implemented capabilities. Until their independently bound roles and
gates exist, the engine must ask a typed question or stop closed.

A pool-only shape can compile green without emitting a response. The corrected
first CREATE and add-block therefore emit an explicit variant/use, with
normalized-IR emission assertions. Natural-answer integration re-runs retrieval
at every message: only fully covered adjacent server-admitted answers retain
original reviewed selections; labels never introduce new domain authority.
Full gate receipts and outstanding client/demo qualification are distinct;
see the [G5 VSIX handover](handover-g5-visix-dialogue-v2.md).

## Honest oracle for the ten complex journeys

The ten production endpoints are complexity exemplars, not runtime templates.
A compiler census found that every existing reference contains business rules
not stated by its four-message test dialogue.  Across the references there are
153 fetches, 1,803 clauses and 1,952 predicates; the prompts specify the visible
structure but not every filter, preset, guard, boost, ordering tie-break,
projection, metadata payload, context fan-out or materialized fallback binding.

Consequently, exact equality to those source endpoints would be invalid:
feeding their missing details to Brain would leak the oracle, while rejecting a
smaller prompt-faithful endpoint would be a false negative.

The v3 profile therefore assesses thirty independently reviewed, inspectable
T2/T3/T4 stage contracts across ten journeys.  A stage is either a prompt-
authorized exact spec or an explicit roster of authority gaps.  An exact stage
contains only what follows from cumulative operator messages, typed
clarification decisions, reviewed catalog/stdlib authority, and explicit
code-pinned defaults.  Its sealed proof includes exact normalized IR, exact
parent IR, exact canonical delta and provenance digest.  A blocked stage has no
spec and can pass only when Brain asks about one of its sealed missing
contracts; an arbitrary clarification is not accepted.

The clean-room authority review currently admits six exact stages and marks
twenty-four as authority-blocked.  The live run sees neither roster while Brain
is active.  After every session and the model worker are closed, the harness
loads the sealed stage contracts and compares hash-only private Draft receipts
or redacted clarification-gap receipts.  A detail found only in a production
reference is never silently promoted into a stage golden.

## Promotion gates

The following gates govern the sealed complex-journey qualification profile,
not the independent G5 core software receipt. The order is core validation,
implementation commit/push/alignment, then sealed qualification from that
immutable revision. Qualification evidence is delivered in a subsequent commit.
That profile is green only when all of the following hold:

1. every plan is schema-valid, fully covered and has zero unknown refs;
2. every permit is consumed once under the exact live binding;
3. each Draft compiles on the full immutable snapshot in one admitted builder
   execution;
4. actual normalized IR and parent-to-child delta equal the sealed stage oracle,
   with zero extra and zero missing nodes;
5. each refinement names the current private head and advances it atomically;
6. golden/reference sentinels are absent from all model and retrieval payloads;
7. ten initial clarifications, six exact Drafts and twenty-four gap-specific
   safe blocks traverse the real loopback HTTP protocol with no Apply
   capability and no tenant/model mutation;
8. focused adversarial suites, the complete Brain suite, formatting, lint,
   repository checks and an independent frontier diff audit are green;
9. the implementation and evidence are committed, pushed, and aligned to clean
   `main` before the sealed qualification run.

This profile measures the exact coverage Brain can honestly support today; it
does not claim that all ten complex endpoints are complete.  Safe refusal is
safety evidence, not accuracy success, and every remaining gap stays in the
delivery queue.  The diagnostic v2 profile remains non-promotable even when its
`gte` and `contains_all` checks pass.

### Second disjoint demo cohort (`play-prod-v4`)

The successor profile adds ten different production-complexity exemplars and
forty new operator-visible messages. It is not selected by trusting fields in a
plan: v3 and v4 are two code-owned exact `(prompt, plan)` pairs, each with its
own digests, scenario roster, target namespace, first-question map, blueprint
roster and denominator. Mixed pairs and unknown paths fail before any input is
opened.

The v4 prompts exercise parameterized multi-block pages, subscription-driven
candidate pools, smart-index selection, multi-route search, multi-stage
similarity, positional injection, merged and nested materialized fallbacks,
root error substitution, twenty view-all rails and a 26-instance parameter fan-
out. The production endpoints establish complexity and test diversity only;
their source and IR are absent from the model-visible prompt wire and are not
used as an equivalence golden.

A separate clean-room review of the frozen messages admits nine exact stages
and identifies twenty-one structural-authority gaps. Those counts define the
v4 qualification denominator, not product completion: a green `9/9 + 21/21`
run proves that Brain generates every currently authorized Draft exactly and
asks a bounded question for every unsupported stage. It does not mean that all
ten final T4 endpoints are generated. Final-demo completion remains a separate
metric and can become green only when the last turn of each journey is an exact,
first-attempt compiling Draft.

The operator-facing prompt pack is
[`32-metis-brain-complex-create-demo-prompts.md`](32-metis-brain-complex-create-demo-prompts.md).
