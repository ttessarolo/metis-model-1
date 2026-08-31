# Metis Brain: interactive session memory wave

Status: **IMPLEMENTED**. The universal Brain contract and first VS Code
consumer are delivered; the final rendered-draft observation in the installed
extension is pending only because the Mac locked after the live turn completed.

## Outcome

Any authorized UX can continue one tenant-scoped conversation with Brain. The
native VS Code `@metis` participant is the first consumer; Metis Fast will use
the same wire contract. Brain asks only questions derived from a concrete
ambiguity, consumes each answer once, remembers the accepted decision for the
current session and removes all addressable conversation state when that
session closes or expires after 20 minutes of inactivity.

This is volatile working memory, not a persistent user profile. It is not
training data and never enters Model 1 weights.

The interactive contract uses turn schema 2. Turn schema 1 remains accepted
for legacy clients and receives only its representable legacy behavior: Brain
never sends it numeric `result_count` or `response_shape` questions. Active and
terminal turn envelopes mirror the submitted turn schema. Health advertises
both accepted turn versions explicitly.

The universal resume surface is
`POST /v1/sessions/{session_id}/turns/{parent_turn_id}/answer`. Its closed
schema contains only `schema_version: 1`, a fresh `request_id`, the server-issued
`clarification_id` and one typed `answer` (`option_ref` or `integer`). Brain
recovers instruction, intent, target, basis and both revisions from the parent
turn. A client therefore never reconstructs or resubmits the original prompt
envelope when Giulia answers a question.

## Volatile memory contents

Brain stores only bounded, inspectable product state:

- logical conversation and parent turn identifiers;
- immutable context and semantic revisions;
- request fingerprint and proposal lineage;
- pending typed question, answer schema and expiry;
- accepted option/value decisions;
- visible defaults and assumptions;
- latest proposal reference and compiler result identity.

Brain does not store chain-of-thought. Raw conversational prose remains only in
bounded in-process turn records while the session is alive. There is no disk
serialization, restart recovery or cross-session recall.

## Question policy

Brain asks when a choice changes meaning or runtime behavior and no safe,
source-derived default exists:

| Kind | Ask | Default/fail behavior |
|---|---|---|
| `catalog` | two or more authorized semantic owners remain tied | unique/explicit owner is automatic; no owner fails closed |
| `semantic_choice` | reviewed fields or values remain materially tied | unique reviewed candidate is automatic; draft/open guesses fail closed |
| `semantic_choice` (edit scope) | “title” can mean the endpoint label or catalog metadata | one scope question; endpoint-label edits preserve every reviewed filter, catalog metadata requires an explicit semantic delta |
| `result_count` | a new endpoint has no exact total, or the operator says “some/few/many” | asks for one bounded total; an exact answer emits `take N` |
| `response_shape` | one number is explicitly combined with pagination but it is unclear whether it is a total or a page size | asks “total or per page?” and emits exactly the confirmed form |

`fallback` remains a reserved typed question kind. Brain does not advertise or
ask it until retrieval supplies two or more concrete, authorized alternatives.
Today Brain does not offer a response-format menu and does not add a fallback;
the compiled Draft remains the inspectable response surface. Existing endpoints
that already contain fallback behavior fail closed because exact fallback
preservation is not yet implemented. This avoids both fake choices and a
silent destructive edit.

One question is blocking at a time. A logical request has a maximum of three
questions and cannot repeat the same question/options. After that limit,
critical ambiguity fails closed; Brain never guesses merely to finish.

## Cardinality and pagination

These are different contracts and Brain must never translate one into the
other:

- `take 24 from ...` means 24 results in total;
- `take page from ...` enables pagination;
- `take page default 20 from ...` enables pagination and uses 20 as the local
  page-size fallback when the caller does not send `hitsPerPage`.

For paginated endpoints, page size follows:

1. explicit request `hitsPerPage`;
2. occurrence-local `take page default N`, when deliberately authored;
3. tenant `response.hits-per-page`;
4. the Metis schema fallback.

Therefore an answer of 20 to “Quanti risultati complessivi vuoi?” authorizes
`take 20`, never `take page default 20`. Brain emits a page form only when the
operator explicitly asks for pagination; a bare page inherits the tenant size.
The terminal response states the exact cardinality/pagination contract and its
source.

Semantic retrieval and output orchestration consume one shared deterministic
parse. Validated count/page phrases are removed before catalog grounding while
semantic nouns are retained (`24 film` still grounds the reviewed `Film`
value). The resulting parsed object is carried into orchestration; it is not
reinterpreted by a second parser. Two distinct totals, page sizes, or a mixed
total/page request produce one concrete choice instead of silently taking the
first number. Page ranges with the repeated noun omitted, such as “tra 20 e 30
per pagina”, still preserve both choices. Qualified ranges such as “circa 20–30”
or “almeno 20–30” fail closed: neither endpoint of a non-exact range becomes an
exact `take` authority.

When editing an existing endpoint, omission is not permission to change its
cardinality. Brain reads the exact target endpoint from the pinned source and
preserves its single `take N`, `take page`, or `take page default N` surface.
An explicit operator request may replace it. A missing/duplicate endpoint or
missing/duplicate `take` fails closed; Brain neither asks for a replacement
count nor invents one.

## Security and lifecycle

A pending question is server-owned and bound to session, parent turn, request
fingerprint, context revision, semantic revision, kind, bounded answer schema,
expiry and single use. A client cannot manufacture options or move an answer
to another tenant/session.

Close, exact session idle expiry, service shutdown and stale snapshot cleanup
remove all conversation, turn, pending-question and proposal state. Pending
questions retain their own bounded expiry, but accepted decisions do not run a
second independent idle clock: their lifetime is exactly the tenant session.
An admitted semantic operation keeps the session active until its worker
boundary and starts a fresh 20-minute inactivity window when it completes.
An already-admitted running call frame, or a cancelled queued work item waiting
for the current bounded call to drain, may retain its arguments until that
worker boundary. Queued futures are cancelled on session close, so they never
start model/retrieval work and do not multiply retention by their own timeouts.
These frames are no longer addressable, cannot publish or recreate session
state, and are not persistent or reusable memory.
A retry with the same idempotency key may replay its already-recorded terminal
response while the session exists; it cannot consume a clarification twice.

Each UX conversation opens its own Brain session. The UX may retain in RAM only
the session credentials required by the transport, the parent turn identifier
and the visible typed question needed to render the next interaction. The
pending decision, original request and one-shot authority remain server-owned.
VS Code `conversation_ref` is only a local routing hint; Metis Fast may use its
own UI conversation identifier without changing Brain semantics.

## VS Code behavior

The selected workspace tenant opens the Brain session. Giulia is never asked
to restate it. Catalog, semantic and total-versus-page questions are written in
the Chat as an ordinary Brain message; the next `@metis` message is interpreted
only as its answer. Choices are numbered and also accept the exact visible
label; result count accepts a bounded integer. A future fallback question will
use the same chat-turn protocol only after authoritative alternatives exist.
No InputBox or Quick Pick interrupts the conversation. After an answer Brain
resumes the original request from the server-owned parent turn, not a
client-reconstructed prompt.

Presentation refinement is deliberately narrow. “Rendi più chiara l'etichetta
dell'endpoint” preserves the reviewed filter basis. The ambiguous “rendi il
titolo più chiaro” asks whether `title` means the endpoint label or catalog
metadata. Generic response-format changes remain unsupported until retrieval
can offer at least two real toolchain-certified formats; Brain does not invent
that menu.

Create continues to open a single Draft document. Replace continues to open a
before/after diff. Apply remains an explicit, separately guarded operator
action and is excluded from the live gate for this wave.

## Verification

The wave closes only with adversarial one-shot/cross-session/replay/stale/
expiry tests, observable zero-state cleanup, focused protocol/orchestrator/
retrieval/client suites, the repository-wide Model 1 gate, a rebuilt installed
VSIX and one real no-Apply dialogue in VS Code.
