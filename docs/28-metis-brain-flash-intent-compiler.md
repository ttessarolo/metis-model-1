# Metis Brain Flash intent compiler

Status: **implemented and locally qualified for the Mac development demo;
distribution approval remains open**.

## Purpose

The Flash intent compiler is a small, fast, local language model inside Metis
Brain. It segments an operator request into a closed Intent IR before the
existing semantic retrieval path retries an otherwise unsupported request.
Its purpose is recall and latency: it helps Brain understand natural Italian
phrasing without moving tenant knowledge or executable authority into a second
model.

Flash is not Model 1, a DSL generator, a catalog oracle, a public server, a
remote fallback or a persistent-memory component. The only public loopback API
remains Metis Brain.

## Runtime and pinned identity

| Property | Qualified value |
|---|---|
| MLX checkpoint | `mlx-community/gemma-4-e4b-it-4bit` |
| Checkpoint revision | `475b9088d29754a3379866cf5aeb6b41acd313c2` |
| Upstream | `google/gemma-4-E4B-it@fee6332c1abaafb77f6f9624236c63aa2f1d0187` |
| Model type | Gemma 4 E4B, affine 4-bit, group size 64 |
| Decoder | `llguidance 1.8.0` token masks |
| Runtime | CPython 3.12.10, MLX 0.32.1, MLX-VLM 0.6.15 |
| Worker SHA-256 | `12a7966ec8acd8f4386f6df57fd1165a1456c152f4707e3d5b2a6cee4b4f8b69` |
| Manifest SHA-256 | `195b2af4ce0b34e57643a7f64cc7493968334e9cfc03f0059850e4b5f1ae5507` |
| Intent schema canonical SHA-256 | `972eb339d8f0f22f4d5dd43aa9f4f74ae49e2a6e2b3b7ff536a60444edd864fa` |
| License | Gemma; external distribution gate **OPEN** |

The tracked manifest is
[`brain-flash-gemma4-e4b-v1.json`](../manifests/brain-flash-gemma4-e4b-v1.json).
It contains the exact ten-file checkpoint roster, byte sizes and hashes. The
approximately 5.18 GB model payload remains under the ignored `artifacts/`
boundary and never enters Git.

Local qualification for this development wave is not permission to bundle or
redistribute Gemma weights. Packaging must close O-008 and distribution must
close O-009 after a license review for the intended delivery channel.

## Execution path

```text
operator request
      |
      v
deterministic output orchestration ---- owns total/page/fallback contract
      |
      v
schema-2 reviewed retrieval
      |
      +---- resolved ------------------------------+
      |                                            |
      +---- unsupported                            |
              |                                    |
              v                                    |
       Flash Intent IR                             |
              | exact host-validated spans only   |
              v                                    |
       schema-2 retrieval retry                    |
              |                                    |
              +---- unresolved -> fail closed      |
                                                   v
                                      Model 1 or deterministic renderer
                                                   |
                                                   v
                                      exact grounding + pinned compiler
                                                   |
                                                   v
                                             Draft, never Apply
```

Flash is invoked only when the first deterministic retrieval result is
`unsupported`. It is not called for an already resolved request, and it cannot
replace a catalog clarification. A successful retry resumes the unchanged
Model 1, grounding and compiler pipeline.

## Closed Intent IR

The JSON Schema is
[`metis-brain-flash-intent-ir.schema.json`](../schemas/metis-brain-flash-intent-ir.schema.json).
The decoder applies its grammar as a token mask during every generated token;
prompted JSON plus post-hoc parsing is not considered constrained output.

The IR contains only:

- the server-declared operation and target scope;
- at most 12 editorial concepts, each with an exact contiguous `source` span,
  an advisory `query` and include/exclude polarity;
- bounded concept logic, response-format classification, fallback
  classification and ambiguity labels.

The schema contains no tenant, catalog, field, value, endpoint, path, Metis
source, session, revision, confidence or fast-path member. `operation` and
`target_scope` must equal the already admitted request.

The generated `query` is never executable. Retrieval receives only exact
operator text from `concepts[].source`; a regression test deliberately sets
`source=Film` and `query=Sport` and proves that only `Film` can be selected.
Small deterministic normalizations may retain an exact subspan, such as
removing `24` from `24 film` or the generic role head from `protagonista
femminile`. They never invent a token and never select a catalog member.

## Authority matrix

| Decision | Sole authority |
|---|---|
| create/edit/repair/review/migrate operation | admitted Brain request |
| existing target, path and base hash | client request plus session snapshot |
| total results versus page size | deterministic output parser and typed clarification |
| fallback preservation/default | deterministic output orchestration plus inspected source/basis |
| catalog choice | reviewed retrieval plus operator clarification when required |
| field/value choice | reviewed schema-2 catalog projection |
| Metis syntax and standard library | pinned grammar/toolchain context |
| candidate source | Model 1 or eligible deterministic renderer |
| validity | exact candidate grounding and pinned compiler |
| workspace mutation | client-side human-confirmed Apply, outside this flow |

Flash has no row in this table. It only provides a bounded segmentation hint.

## Host-side safety gates

Brain validates the constrained object again and rejects it when:

- an operation or target scope differs from the admitted request;
- a source is not an exact substring of the operator instruction;
- a source or query contains authority-bearing DSL characters;
- prompt-control words, endpoint/catalog scaffolding, result-count, pagination,
  response or ordering controls are presented as editorial concepts;
- concepts or ambiguities are duplicated or exceed their bounds;
- logic is `any`, `mixed` or `unknown`, or a concept is negative. These forms
  remain non-executable until retrieval and DSL have a first-class equivalent;
- the model, schema, decoder, worker, manifest, lock or model-file roster
  differs from the qualified identity.

A rejection cannot grant a weaker path. Brain returns the existing safe
unsupported/error result; it does not consult Ollama, a remote model, a guessed
catalog member or generated DSL.

## Warm lifecycle and isolation

The demo configuration uses `warmup=on_start` for both Model 1 and Flash. Brain
loads each in its own persistent JSONL worker before binding the HTTP port.
Flash uses the same local sandbox policy as Model 1: network is denied, writes
are restricted to the bounded evaluation cache, and `.env`, AWS/SSH material
and Keychains are denied.

One Flash worker is reused for up to 240 requests. Timeout, cancellation,
malformed responses, identity mismatch, crash, controlled recycle and shutdown
are supervised by the parent. Shutdown terminates the process group and leaves
no worker orphan. There is no Ollama process and no `mlx-lm.server` in this
path.

The worker is stateless between requests. The validated IR may be retained only
inside the owning Brain session, is excluded from the client payload hash, is
bound to the current model/schema/revision identity and disappears on session
close, idle expiry or service shutdown.

## Health and progress

`GET /v1/health` exposes one bounded `intent_compiler` object:

- `enabled` and mode;
- `model_loaded`;
- pinned model revision, schema hash and decoder;
- warmup policy, state, duration and worker load time.

Paths, prompts, generated queries, catalog values, tenant data and hidden
reasoning are never exposed. Turn progress adds `intent.started` and
`intent.completed`; the terminal result remains the only proposal authority.

## Local qualification evidence

All measurements below are read-only and no Apply was invoked.

- final worker roster: `5/5` constrained cases schema-valid and host-executable;
- warm Flash generation: `1.202–1.588 s`, `73–101` generated tokens,
  `79.26–82.65 token/s`, about `5.797 GB` peak Metal;
- host adversarial suite: `74/74`;
- worker lifecycle suite: `43/43`;
- Brain wiring suite: `10/10`;
- retrieval authority seam: advisory `query=Sport` cannot override exact
  `source=Film`;
- independent final audit: `0 P0`, `0 P1`; its documentation P2 is closed by
  this document and the linked runbook/roadmap updates.

The final complex edit used this operator request:

> Modifica l'endpoint demo.a_b_test sul catalogo video: voglio 24 risultati
> totali di film con mood romantico, protagonista femminile e umano; mantieni
> response.expanded e l'ordinamento per data di pubblicazione.

The retry grounded exactly four reviewed values: `tipologia=Film`,
`mood=Romantico`, `protagonistaSesso=Femmina` and
`protagonistaSpecie=Umano`. Model 1 emitted `take 24`, preserved descending
publication-date ordering and `response.expanded`, and the pinned compiler
accepted the first candidate. The turn took `56.420 s`; Model 1 generation was
`42.369 s` for 4,409 prompt and 215 generated tokens. The service startup,
including both warm workers, took `31.540 s`. The target tenant commit, clean
status and target-file SHA-256 were identical before and after.

This proves a compiled Draft, not editorial semantic approval: the terminal
correctly reports `semantic_grounded=true`, `compile_clean=true`,
`tenant_modified=false` and leaves `semantic_correctness=false` for human
review.

An earlier request containing awards, open ending and masterplot Revenge failed
closed because the current reviewed catalog did not provide exact authority for
all requested concepts. Flash did not fabricate the missing metadata. That is
expected behavior and identifies catalog work rather than a weight injection.

## Verification

```bash
uv run pytest -q \
  tests/test_brain_intent_ir.py \
  tests/test_brain_flash_runtime.py \
  tests/test_brain_flash_wiring.py \
  tests/test_brain_semantic_retrieval.py \
  tests/test_brain_orchestrator.py \
  tests/test_brain_turns.py \
  tests/test_brain_server.py
uv run ruff check src tests
uv run ruff format --check src tests
make check
git diff --check
```

The authoritative repository gate completed with foundation `85/85`, global
Ruff and formatting green, and `2771 passed, 2 skipped, 0 failed` in the test
harness. The active Orchestra board records the complete evidence wire.

## Rollback and nonclaims

Remove the `intent_compiler` object from the Brain configuration to restore the
previous deterministic retrieval plus Model 1 behavior. This does not alter the
Model 1 checkpoint, adapter, tenant, protocol or session format.

This wave does not claim external redistribution, macOS app packaging, VSIX or
Metis Fast completion, remote fallback, persistent memory, universal semantic
coverage, support for disjunction/exclusion, or a reduction in Model 1's own
generation time. Flash made intent segmentation fast; the measured residual
latency remains dominated by the 27B Model 1 generation path.
