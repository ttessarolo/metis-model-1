# W0 foundation blackboard

## Objective

Turn the ratified Metis Model 1 plan into a fail-closed, executable repository
foundation and provide a bounded feasibility estimate.

## Acceptance

- W0 source/model manifest and open-decision register are machine-readable.
- The first `source-model-revisions` and `benchmark-task` contracts are validated.
- Artifact boundaries are enforced against tracked and non-ignored candidate files.
- Frontier/delegated lane ownership and closure gates are durable.
- `make check` is green from an isolated project environment.
- Feasibility separates observed facts, engineering inference, and W4 unknowns.

## Scope / out of scope

In scope: W0 repository structure, contracts, manifests, offline validation,
blackboards, feasibility, and W1/W4 entry gates.

Out of scope: model downloads, dependency pin O-004, MLX inference/backward,
600-iteration qualification, corpus materialization, benchmark sealing, training,
commit, push, publication, and writes to the Metis repository.

## Baseline

- Repository: `ttessarolo/metis-model-1`
- Branch/commit at entry: `main` / `ad7a116`
- Worktree at entry: clean
- Metis evidence commit: `a2dde2b191f6b78c2003d74875560da782470968`
- Coordination mode: frontier orchestra -> delegate -> control

## Established

- FACT — The entry repository contained only `.gitignore`, `README.md`, and eight
  planning documents; no executable scaffold existed. Evidence: `git ls-files`
  at entry, L1 census.
- FACT — The pinned Metis commit exists locally and is the current clean tracked
  baseline; pre-existing untracked `tmp/` and VSIX checksums were not touched.
  Evidence: `git -C /Users/tommasotessarolo/Developer/ares-matioska/metis status`
  and `rev-parse`.
- FACT — The pinned source declares Metis language `0.43` and package `0.23.87`.
  This observation does not ratify O-001. Evidence:
  `tooling/src/language/version.ts` and `tooling/package.json` at the pinned commit.
- FACT — The base and community MLX checkpoint are public at the revisions in
  `manifests/source-model-revisions.json`; the checkpoint is 4-bit and declares
  conversion with MLX-VLM 0.6.8. Evidence: official Qwen and Hugging Face model
  cards, L3 evidence lane.
- RISK — MLX-VLM supports the `qwen3_5` architecture family and documents QLoRA,
  but stable Qwen3.8 backward/save/reload/resume on this machine is not proven.
- STOP — W5 cannot start before W4 demonstrates at least 600 stable iterations
  and adapter save/reload/resume. Foundation status is therefore:
  `INFERENCE PLAUSIBLE / TRAINING UNQUALIFIED / W4 REQUIRED`.
- DONE — L1 document census returned all nine planning surfaces and W0/W1/W4
  deliverables. `in=9 out=9 distinct=9 gaps=0`.
  `evidence=docs/06-delivery-roadmap.md:31;docs/04-training-runbook.md:54;session:/root/l1_phase0_census`.
- DONE — L2 coordination-pattern census covered Metis handovers, Cibo AGENTS, and
  the Orchestra protocol. `in=4 out=4 distinct=4 gaps=0`.
  `evidence=/Users/tommasotessarolo/Developer/recipe-as-graph/AGENTS.md:68;/Users/tommasotessarolo/Developer/recipe-as-graph/orchestra/protocol/MASTER-PROTOCOL.md:56;session:/root/l2_blackboard_patterns`.
- DONE — L3 checked model, checkpoint, MLX-VLM and Apple MLX evidence with
  primary/official sources. `in=4 out=4 distinct=4 gaps=0`.
  `evidence=manifests/source-model-revisions.json;docs/11-feasibility-and-risks.md;session:/root/l3_feasibility_evidence`.
- FACT — L0 independently rechecked both Hugging Face revisions, Qwen's
  `model_type=qwen3_5`, the MLX-VLM QLoRA options, and the current `qwen3_5`
  implementation through primary APIs and repository sources.
- DONE — The frontier gate passed contracts, cross-contracts, artifact policy,
  lint, format, package build, local Markdown links, and eight tests.
  `in=7 out=7 distinct=7 gaps=0`.
  `evidence=command:make check;command:uv build;command:local Markdown link audit`.
- RISK — L4 adversarial audit found four closure gaps: artifact path/content
  bypasses, insufficient sealed-task oracle coverage, missing durable lane
  transitions, and ratified manifests retaining open decisions.
  `evidence=session:/root/l4_foundation_audit`.
- FIX — The repository gate now rejects nested environment files, common
  key/model/checkpoint/data payloads, symlinks, binary content, private-key
  markers, and files above 5 MiB. `evidence=src/metis_model1/contracts.py;tests/test_contracts.py`.
- FIX — Sealed source/patch tasks now require ratified language, closed evidence
  for every oracle, parse pass, structural stage coverage, and semantic/human
  pass. Ratified source manifests require zero open decision references.
  `evidence=schemas/benchmark-task.schema.json;schemas/source-model-revisions.schema.json`.
- FIX — The lane ledger now records each dispatch, return, frontier check,
  rework, and acceptance transition. `evidence=orchestra/runs/2026-08-20-foundation/SESSIONS.md`.
- DONE — L4 independently rechecked artifact boundaries, sealed-task coverage,
  ratified-manifest closure, hardware snapshot reconciliation, and the current
  ledger. `in=5 out=5 distinct=5 gaps=0`.
  `evidence=session:/root/l4_foundation_audit;command:make check`.

## Open

- OPEN — O-001 and O-002 block W1 sealing.
- OPEN — O-004 blocks W4 execution until the isolated environment and exact CLI
  surface have been probed.
- OPEN — The strict end-to-end success hypothesis remains experimental; see
  `docs/11-feasibility-and-risks.md`.

## Ruled out

- Reusing global Conda packages for W4.
- Treating the Ollama bundle as training provenance.
- Treating compile-clean as semantic correctness.
- Copying the draft benchmark contract fixture into a frozen benchmark.
- Selecting a floating MLX-VLM `latest` version.

## Outcome

CLOSED — W0 repository foundation accepted after adversarial recheck. W1 remains
gated by O-001/O-002 and W4 by O-004. No model payload was downloaded, no
training was started, no source Metis file was changed, and no commit or push was
performed.
