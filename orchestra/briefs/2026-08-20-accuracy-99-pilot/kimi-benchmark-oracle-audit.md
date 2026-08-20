# BRIEF — adversarial accuracy-99 benchmark and oracle audit

Repo under review: `/Users/tommasotessarolo/Developer/metis-model-1`.
Metis evidence checkout: `/Users/tommasotessarolo/Developer/ares-matioska/metis`.
Run commands from the Model 1 repository unless a read-only `git -C` command
names the Metis checkout explicitly.

Read first, completely:

1. `/Users/tommasotessarolo/Developer/metis-model-1/AGENTS.md`
2. `/Users/tommasotessarolo/Developer/metis-model-1/orchestra/runs/2026-08-20-accuracy-99-pilot/BLACKBOARD.md`
3. `/Users/tommasotessarolo/Developer/metis-model-1/docs/00-charter-and-decisions.md`
4. `/Users/tommasotessarolo/Developer/metis-model-1/docs/02-dataset-and-provenance.md`
5. `/Users/tommasotessarolo/Developer/metis-model-1/docs/03-evaluation-and-gates.md`
6. `/Users/tommasotessarolo/Developer/metis-model-1/docs/04-training-runbook.md`
7. `/Users/tommasotessarolo/Developer/metis-model-1/docs/06-delivery-roadmap.md`
8. `/Users/tommasotessarolo/Developer/metis-model-1/manifests/benchmark-plan.json`

Both repositories are READ-ONLY for this lane. Do not edit, format, generate,
checkout, clean, commit or create files in either repository. Do not read any
`.env`, credential, keychain, private-key, raw production or live ARES source.
The only permitted writes are the wrapper-provided ignored activity blackboard,
journal and artifact/report directory. Do not start model training or download.

Baseline identities:

- Model 1: `main@ad7a1169104c22fa8736b7463a93f65ea9f670f8`, with an existing dirty
  working tree owned by the user/current coordinator.
- Metis: `main@a2dde2b191f6b78c2003d74875560da782470968`, with three pre-existing
  untracked paths that must remain byte-for-byte untouched.
- Target model family: Qwen3.8 only.
- Requested product target: defensible 99% end-to-end correctness, not training
  accuracy or compile-only pass rate.

## Item 1 — Statistical and semantic contract

Derive a rigorous target contract for 99% from the current docs. It must name:

1. primary success predicate per task;
2. eligible population and denominator;
3. first-shot versus post-repair treatment;
4. confidence rule (Wilson 95% is the current project convention);
5. global and per-family reporting;
6. critical-failure vetoes;
7. minimum sample size implications, including the all-success case;
8. what 250, 400 and any larger denominator can and cannot support.

Recompute the interval math independently with a small read-only Python command.
Do not pick a looser rule because it is easier to pass.

## Item 2 — Current 30-allocation closure audit

Enumerated roster: the 30 exact `slice_30.tasks` entries in
`manifests/benchmark-plan.json`, five each for F-1 through F-6.

For all 30, verify with read-only Git/object and filesystem commands:

- task IDs and source paths are distinct;
- the pinned blob OID matches the file at Metis commit `a2dde2b...`;
- no source is missing;
- which dependency-closure information can be computed without executing or
  mutating the Metis toolchain;
- which intended oracle has a concrete executable entrypoint today and which
  remains only a label;
- whether local/internal-only use is technically separable from distribution
  rights (do not issue legal conclusions).

Coverage must close arithmetically: `in=30 out=30 distinct=30 gaps=0`, or STOP.

## Item 3 — W3/W5 minimum evidence path

Produce the smallest rigorous dependency-ordered implementation roster that can
move from the current state to:

1. a sealed smoke slice;
2. a contamination-safe W3 pilot dataset;
3. A/B baseline evaluation;
4. O-003/O-005/O-006 ratification;
5. a bounded W5 pilot and B/D comparison.

For every proposed unit, name exact input/output contracts, the deciding command,
the fail-closed condition, and whether it may use Metis only in read-only mode.
Identify any point at which the 99% request is scientifically blocked rather
than merely unimplemented.

## Item 4 — Adversarial review

Try to falsify these claims:

- a 400-task frozen benchmark is automatically sufficient for a 99% claim;
- compile-clean can proxy for semantics;
- one seed can select a pilot config;
- the existing 30 allocations are already a benchmark;
- an adapter that wins D-B on dev may be called 99% accurate;
- source-level read-only access makes redistribution rights irrelevant.

## Verification and output

Before reporting, compare exact `git status --short` output for both repositories
against your preflight snapshots. Any changed line is a STOP.

Write one report under the wrapper activity artifacts directory named
`kimi-accuracy99-audit.md`. End your response using the protocol wire and the
four required sections. Include commands, arithmetic, STOPs and what could not
be established. Do not repeat large source blocks; reference absolute paths.
