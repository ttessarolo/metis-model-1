# Kimi K3 brief — W3/W4 hostile clean-SHA audit

## Mandate

Audit the exact clean `HEAD` supplied by the orchestra wrapper. This is a
read-only second-frontier review. Do not edit, commit, push, download a model,
load model weights, deserialize safetensors, start training or materialize a
dataset.

Repositories:

- project, read-only:
  `/Users/tommasotessarolo/Developer/metis-model-1`;
- Metis evidence source, strictly read-only:
  `/Users/tommasotessarolo/Developer/ares-matioska/metis` at
  `a2dde2b191f6b78c2003d74875560da782470968`;
- orchestra source, read-only except its ignored `runs/` evidence:
  `/Users/tommasotessarolo/Developer/ai-multi-team-orchestra`.

Never read credentials, `.env` files, keychains, private keys, live ARES data
or model/checkpoint tensor payloads. Capture project and Metis HEAD plus an
expanded status invariant before and after. A moving project tree is `STOP`,
not `ACCEPT`.

Read `AGENTS.md`, `BLACKBOARD.md`, the active board/ledger,
`docs/00-charter-and-decisions.md`, `docs/03-evaluation-and-gates.md`,
`docs/06-delivery-roadmap.md`, `docs/12-accuracy-99-execution-plan.md` and the
files named below.

## Unit K1 — W3 registered trust and contamination boundary

Inspect:

- `src/metis_model1/w3_builder.py`;
- `src/metis_model1/w3_oracles.py`;
- `schemas/w3-source-register.schema.json`;
- `schemas/w3-run.schema.json`;
- `tests/test_w3_builder.py`;
- `tests/test_w3_oracles.py`.

Independently attack all of these claims:

1. Benchmark, source-register, Oracle adapter and Oracle identity authorities
   are `None` at clean import and fail closed. Public build/replay/invoke
   signatures accept no caller-supplied adapter, identity, output row or Oracle
   sidecar.
2. Adapter authority binds exact class code, the actually resolved callables,
   canonical instance state and the pinned runtime/toolchain/sandbox identity.
   Swap a same-class differently configured instance, inject an instance
   method, mutate state during evaluation and tamper the per-candidate runtime
   receipt. Each must fail.
3. F-2 and F-3 user messages carry the entire canonical training input; F-2
   before/after and F-3 mutated/fixed no-ops fail. Semantic, minimality and
   repair evidence cannot contradict their pass predicates.
4. Frozen copies of the F-1 target, F-2 after source and F-3 fixed source are
   detected as atomic ancestry. Oracle AST or IR equality with a frozen root is
   a fatal trust error. Genealogical/text/AST/IR overlap cannot cross splits.
5. Rehash a forged accepted output, messages, split, provenance, Metis
   revision, Oracle evidence and rejected reason. Deterministic replay must
   reject every attack. Malformed nested objects, extra schema fields, unsafe
   IDs and `None` iterables must fail without raw `KeyError`/`TypeError`.

Do not misstate this core as six-family W3: the current authorized scope is
F-1/F-2/F-3 only, with F-4/F-5/F-6 still open.

Run the focused W3, dataset and independence tests plus schema and formatting
checks. Report exact numerators, denominators and distinct counts.

## Unit K2 — W4 exact-resume hardening

Inspect only code, metadata, tests and the small ignored JSON reports; do not
open any safetensors or model payload:

- `qualification/train_full_state.py`;
- `qualification/test_full_state.py`;
- `qualification/runtime-pin.json`;
- `qualification/checkpoint-pin.json`;
- `qualification/uv.lock`;
- `qualification/README.md`;
- `orchestra/runs/2026-08-20-w1-w4-entry/W4-QUALIFICATION.md`;
- `artifacts/w4/2026-08-21-target-roster-bit-exact.json` if present.

Recompute and attack:

1. Current wrapper SHA-256 must equal
   `0fb908e6dc80f9f2d888d7692932f585d81b3ba8dad95f317a5fb099983e2e3a`
   and the runtime pin must bind it, the exact lock and the full package map,
   including NumPy.
2. The processor load passes `trust_remote_code=False` at the top level. Model
   identity binds revision, config and every payload hash.
3. Resume derives the ordered exact LoRA target roster from the verified model
   topology and validates exact equality before `apply_lora_layers`; arbitrary,
   non-empty subset and extra-key attacks fail.
4. Non-finite sampler/gradient/model/optimizer state, symlinks, size/hash
   mismatch and incomplete atomic publication fail closed.
5. Run the payload-free `qualification.test_full_state` suite. Recompute the
   ignored comparison-report SHA-256
   `4d23e0f1f7f27945d0071113fbd0984e84c2cc4ca9f4a9cff70069826c01b27c`
   and its recorded semantic-state SHA-256
   `4bee697cb4179f82d6623a8ceeca2c1a6366e0fd950f94726fc87f2dc2c40581`.
   Do not infer semantic accuracy from this technical evidence.

## Unit K3 — integrated repository and claim audit

Run the documented repository gate with hostile ambient `PATH` and the pinned
Node override if needed. Run `git diff --check` and enumerate tracked or staged
files that look like model weights, adapters, optimizer state, checkpoints,
materialized datasets or secrets. There must be none.

Confirm that no code or documentation claims measured semantic accuracy, a
finished six-family W3, W5 readiness or `TARGET_99_CONFIRMED`. The correct state
remains: technical local QLoRA continuation works; semantic accuracy is
unmeasured; benchmark v1, independent population, production W3 authority,
A/B, O-003 and semantic training remain open.

## Required output

For each unit emit `FACT`, `RISK`, `STOP` and `DONE` records with concrete
paths/commands. Close with:

- `in=3 out=3 distinct=3 gaps=0` only if every unit was actually completed;
- `P0`, `P1`, `P2` counts;
- `ACCEPT|REWORK|STOP`;
- before/after project and Metis invariants;
- exact commands and test counts.

Any P0/P1, moving tree, repository write, payload access or unverified claim is
`REWORK` or `STOP`, never an advisory acceptance.
