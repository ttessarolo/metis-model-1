# Metis Brain: hard headless qualification

Status: **ACTIVE**. This wave measures the frozen complex endpoint corpus
through Brain's real local HTTP surface without VS Code and without Apply.

## Scope

The authority is
[`metis-brain-hard-prompts.play-prod-v1.json`](../examples/metis-brain-hard-prompts.play-prod-v1.json),
whose SHA-256 is
`6022ea8104a0b01deacd81bf4f46bd78d72154a308278081ecddfcc6f1bc119c`.
It contributes three distinct denominators:

- 10 existing-endpoint edit prompts;
- 10 create-from-zero journeys;
- 40 ordered logical messages inside those journeys, comprising 10 expected
  clarification turns and 30 assessed generated-Draft turns.

The full operator-message denominator is therefore 50. Typed answers emitted
through Brain's `/answer` route are protocol continuations and are counted
separately; they do not silently replace a corpus message.

The successor `play-prod-v2` corpus and plan are a **diagnostic profile**, not a
promotion profile. They exercise the enriched tenant authority and the private
compiler manifest while the create/refinement path is still acquiring typed
structural edit authority. Because that plan deliberately does not require
final normalized-IR equivalence to each pinned reference endpoint, even a
complete run with every declared turn check satisfied emits
`promotion_gate.status=NOT_PROMOTABLE` and `qualification_green=false`. This
prevents turn-local cardinality or containment checks from being reported as
end-to-end accuracy. Promotion requires a later sealed profile with exact
cumulative structural equivalence (or an equally strong reviewed oracle) and
cannot be inferred from the v2 receipt.

## Runtime boundary

The tracked non-secret config
[`metis-brain-config.play-prod-hard-qualification.local.json`](../examples/metis-brain-config.play-prod-hard-qualification.local.json)
binds one minimal client to the clean pinned play-prod source tenant. The client
has no Apply, compile or cancellation capability. Brain itself may retrieve and
compile its private candidate against the immutable session snapshot, but the
runner never calls `apply-preflight` and never writes a tenant.

The original corpus remains unchanged and continues to record that its census
wave did not authorize model execution. The owner's 2026-09-04 instruction is
the separate one-run local authorization consumed by this successor wave.

## Execution model

One Brain process warms Model 1, Flash and retrieval before binding an ephemeral
numeric-loopback port. The headless client then uses only the public product
protocol:

1. health;
2. bootstrap-authenticated session open;
3. schema-2 turn submit and terminal polling;
4. server-owned typed clarification answers;
5. proposal-basis refinement;
6. session close.

Each edit gets an isolated session. Each create journey gets one isolated
session so that its proposal lineage and volatile memory are real. The exact
next corpus message may supply deterministic evidence for a pending catalog,
semantic or cardinality choice; the typed answer and the subsequent natural
message remain distinct recorded operations. A question that cannot be
answered exactly from that message stops the dependent path rather than being
guessed.

## Verdicts

Every edit receives exactly one of:

- `PASS_DRAFT`: the proposal is byte-exact to the declared edit oracle, the
  pinned compiler is green, grounding is complete and tenant invariance held;
- `FAIL_SEMANTIC_ORACLE`: a compile-clean Draft differs from its declared edit
  oracle;
- `SAFE_FAIL_CLOSED`: Brain rejected or declared unsupported without mutation;
- `FAIL`: the result is unsafe, malformed or mutation-bearing.

Every logical create message receives exactly one of:

- `PASS_CLARIFICATION`: the corpus expected a question and Brain emitted one
  typed, session-bound question that the next frozen message can answer
  exactly;
- `PASS_STRUCTURAL_ORACLE`: Brain returned a first-attempt compile-clean,
  fully grounded proposal whose private compiler IR passes the closed turn
  oracle; the final turn must also be normalized-IR equivalent to the pinned
  reference endpoint;
- `FAIL_SEMANTIC_ORACLE`: the Draft compiles but fails a structural fact,
  refinement-delta or final normalized-IR check;
- `FAIL_ACTION_MISMATCH`: Brain asked or proposed at the wrong point in the
  frozen interaction, even if the resulting Draft is otherwise sound;
- `SAFE_FAIL_CLOSED`: Brain rejected or declared unsupported without mutation;
- `BLOCKED_BY_PREDECESSOR`: an earlier logical turn produced no proposal on
  which this required refinement could be based;
- `FAIL`: an unsafe, malformed, semantically false or mutation-bearing result.

Safe failure is product safety evidence but not accuracy success. Aggregate
accuracy reports `PASS_DRAFT` and expected clarification separately from
fail-closed coverage; compile-clean alone cannot promote a Draft.

Receipt completeness and promotion are independent dimensions. A run that
records all 10 edits, all 10 journeys and all 40 logical create turns writes
`status=MEASURED` and `measurement_status=COMPLETE` even when its terminal
health, cleanup or invariance gate fails. In that case `terminal_gate` records
only a bounded phase/code, `qualification_green` is unconditionally false and
the CLI exits 2. A run interrupted before the closed denominator writes a
create-only `*.incomplete-<uuid>.json` receipt with
`measurement_status=PARTIAL`, preserves the completed per-case evidence and
exits 1. No terminal failure can be converted into a promotion success.
The receipt also exposes a closed `promotion_gate`: it records whether the
selected profile is eligible for promotion, and a bounded reason code when it
is not. Profile eligibility is fixed in code alongside the pinned corpus and
plan digests; the input JSON cannot opt itself into promotion.

## Evidence policy

The detailed local transcript is stored under ignored
`artifacts/metis-brain-hard-qualification/`. It may contain the frozen prompts
and generated Drafts for local inspection, but never tokens, bootstrap data,
paths outside the declared authorities, hidden reasoning or credentials. The
tracked board receives only counts, bounded timing, failure taxonomy and
cryptographic digests.

The suite records Model 1 and tenant Git guards before and after every case.
Any drift in repository commit/tree/status, snapshot roster or target hash is
a terminal suite failure even if the generated source compiles.

`compile-structure` is a private qualification-only bridge: it is not exposed
as a Brain HTTP capability. Its receipt binds a canonical SHA-256 to the exact
provenance-free compiler IR consumed by the oracle. Compile-clean alone never
counts as semantic success.

## Command

The runner refuses to start unless the repository is committed and clean, the
output does not already exist and the explicit local-execution authorization
flag is present:

```bash
uv run metis-model1 brain-hard-qualification \
  --config /Users/tommasotessarolo/Developer/metis-model-1/examples/metis-brain-config.play-prod-hard-qualification.local.json \
  --corpus /Users/tommasotessarolo/Developer/metis-model-1/examples/metis-brain-hard-prompts.play-prod-v1.json \
  --plan /Users/tommasotessarolo/Developer/metis-model-1/examples/metis-brain-hard-qualification.play-prod-v1.json \
  --output /Users/tommasotessarolo/Developer/metis-model-1/artifacts/metis-brain-hard-qualification/play-prod-v1.json \
  --authorize-local-model-execution
```

The CLI prints only bounded progress and the final denominator/scorecard. The
output is create-only and self-hashed. Reusing a completed filename fails
closed. A measured but non-green qualification still writes its receipt and
returns exit code 2, so automation cannot confuse measurement completion with
promotion success. An interrupted measurement writes a distinct incomplete
receipt and leaves the requested final path unused. Any retry remains an
explicitly authorized local-model invocation and should use a distinct output
name when preserving prior complete evidence.
