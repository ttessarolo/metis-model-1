# Feasibility and risks

Snapshot date: **21 August 2026**.

## 1. Verdict

**Conditional GO.** The exact bounded W4 technical path is now qualified, so the
project is feasible enough to continue W1-W3 and prepare a controlled W5 pilot.
It is not yet justified to fund a full pilot as if Metis semantic uplift,
benchmark closure or redistribution rights were established facts.

The concise state is:

```text
INFERENCE AND BOUNDED TRAINING QUALIFIED / SEMANTIC UPLIFT UNTESTED
```

Decision estimate for executing a bounded local W5 pilot once data gates close:
**85% with a ±10 percentage-point uncertainty band**. Decision estimate for a
defensible global 99% semantic claim under the preregistered contract: **20%
with a ±15 point band**. These are planning judgments, not measured
probabilities. W4 removes a concrete compatibility risk, while the current
benchmark ancestry supplies only `1/563` independent groups and no B/D semantic
evidence. Independently sourced data and a clean paired uplift would materially
raise the second estimate; inability to source that diversity correctly stops
the claim even if training runs.

Under the narrower constraint "use only the currently tracked Metis corpus",
the 563-group requirement is infeasible rather than merely low-confidence. A
read-only pinned-commit census found `199/199` distinct `.metis` paths/OIDs,
three syntactic roots and at most two defensible ancestry roots. Even the
incorrect file-as-group upper bound is `199 < 563`. The 20% ±15 planning
estimate therefore presupposes newly authored or independently sourced groups;
it does not apply to a repo-only strategy.

## 2. Feasibility by surface

| Surface | Estimate | Confidence | Main reason |
|---|---:|---|---|
| W0 repository foundation | 95% | high | Contracts, source pins and offline gates are bounded and locally verifiable |
| W1/W2 benchmark and census | 45% with new sources; infeasible repo-only | medium | Exact 201-input closure is known, but all 30 tasks share one ancestor; the complete tracked corpus has at most two defensible roots versus 563 required, plus task-specific oracles remain absent |
| W3 deterministic dataset builder | 80% | medium-high | Two independent frontier replays accept the fail-closed F-1/F-2/F-3 contract at P0/P1/P2=0; all four production authorities, real isolated-runner receipts, independently grouped semantic examples and F-4/F-5/F-6 remain absent |
| W4 recorded Qwen3.8 MLX-VLM path | 95% | high | Exact pins passed backward, 10/50/600 iterations, save/reload, adapter-off, topology-bound LoRA targeting and bit-exact full-state resume at batch 1 / sequence 128 |
| W4 bounded sequence-1024 ranks 8/16 | 90% | high | Real public-synthetic backward/checkpoint probes and rank-8 resume passed at 94.43-95.04 GB peak Metal; 2,048, positive dropout and accumulation variants remain unqualified |
| W5 meaningful D-B semantic uplift | 50% | low | This is the central scientific hypothesis, not an implementation certainty |
| W7/W8 strict candidate and packaging | 55% | low-medium | Conditional on W4, leakage-clean data, reproducibility and no material regression |

The percentages are deliberately not multiplied: the waves are dependent and
new evidence changes later estimates.

## 3. Confirmed inputs

- [`Qwen/Qwen3.8-27B`](https://huggingface.co/Qwen/Qwen3.8-27B) is public at
  revision `1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0`, declares Apache-2.0,
  uses `model_type=qwen3_5`, and is a multimodal conditional-generation model.
- [`mlx-community/Qwen3.8-27B-4bit`](https://huggingface.co/mlx-community/Qwen3.8-27B-4bit)
  is a public 4-bit community conversion at revision
  `3e6447f082e89cc7f0bc6e5441afd38dfce760ff`; its card declares conversion with
  MLX-VLM 0.6.8.
- [MLX-VLM's LoRA guide](https://github.com/Blaizzy/mlx-vlm/blob/main/mlx_vlm/LORA.MD)
  documents QLoRA, completion-only training, gradient accumulation/checkpointing,
  adapter resume, and freezing vision training. The current code has a
  [`qwen3_5` implementation](https://github.com/Blaizzy/mlx-vlm/tree/main/mlx_vlm/models/qwen3_5),
  but the guide does not name Qwen3.8 explicitly.
- [MLX uses unified memory](https://ml-explore.github.io/mlx/build/html/usage/unified_memory.html):
  CPU and GPU workloads share the same 128 GB pool. Free disk or model size alone
  cannot predict training peak memory.
- The target host is Apple M3 Max / 128 GB. The planning snapshot recorded about
  567 GiB free; the W0 control later observed about 554 GiB on the same date.
  This ordinary 13 GiB disk-use drift is recorded rather than normalized away.
  Neither figure estimates unified-memory training headroom. At planning time,
  the 4-bit payload supported only an inference hypothesis and did not by itself
  prove backward feasibility.
- The exact local qualification subsequently proved finite backward and a
  600-iteration run at batch 1 / sequence length 128. It completed in `926.65 s`
  with `15.724 GiB` maximum process-tree RSS, `20.282 GB` peak Metal memory,
  corrected live-tail growth of `0.000626 GiB`, and no residual process. The
  bounded packet is
  [`W4-QUALIFICATION.md`](../orchestra/runs/2026-08-20-w1-w4-entry/W4-QUALIFICATION.md).
- A fail-closed local wrapper also produced byte-identical canonical model and
  optimizer state for uninterrupted 4 steps versus 2 steps plus fresh-process
  resume to step 4. Native MLX-VLM resume remains adapter-only.
- The hardened current wrapper independently derives `496/496` ordered LoRA
  target keys from the verified model topology. A fresh one-step run plus
  fresh-process resume to step two is byte-identical to an uninterrupted
  two-step reference; this requalification remains technical evidence only.
- A public-synthetic sequence-1024 expansion rendered 7,414 raw tokens, retained
  1,004 completion tokens in the exact 1,024-token batch, and completed rank-8
  step 1/resume step 2 plus rank-16 step 1 with finite loss. Peak Metal was
  94.43-95.04 GB; every checkpoint payload matched its SHA-256 manifest.
- The pinned tenant's 30 planned tasks close over the same 201 build inputs and
  therefore form one leakage group. This is a blocker for the 563-group
  population claim, not a reason to multiply cosmetic tasks.
- The complete pinned repository contains 199 tracked `.metis` files:
  197 in the same whole-program tenant, one isolated v0.42 diagnostic demo and
  one generated settings template. These provide three syntactic roots and at
  most two defensible ancestry roots; they cannot fund the 563-group claim.
- The W3 F-1/F-2/F-3 contract is executable and accepted after hostile adapter,
  replay, genealogy, schema and malformed-input attacks. Its focused gate is
  `112/112`; an independent malformed-input matrix rejected `141/141` cases
  without raw exceptions. This is contract evidence only: its four production
  authorities are unset, real W1 receipts are `0/15`, and F-4/F-5/F-6 are open.

## 4. Principal risks and stop rules

| Risk | Evidence needed | Stop / response |
|---|---|---|
| Instability outside the executed batch-1, sequence-1024, rank-8/16, dropout-0 path | finite loss/gradients and memory curve for every new setting | `BLOCKED`; do not extrapolate to 2,048, positive dropout, accumulation or a new model family |
| Descriptor or memory growth during W5 sequence-1024 runs | periodic process and MLX telemetry | hard stop above 110 GB or before OOM; preserve the last valid report and reduce only through a declared experiment |
| Adapter/full-state regression after dependency or wrapper change | terminate, reload, generate, resume and compare canonical state | reopen O-004; W5 cannot use the changed runtime |
| Output corruption after LoRA | adapter-on/off smoke comparison | reject the changed pin or patch; do not inherit qualification |
| Compile improves but semantics do not | paired B/D semantic benchmark | `REWORK` or `REJECT`; do not scale iterations |
| Leakage or ambiguous oracle | genealogical audit and frontier adjudication | invalidate the affected score and rebuild the split/task |

Public issue reports for adjacent Qwen3.5/MLX paths justify these tests but do not
prove failure of this exact checkpoint. They remain risk signals, not verdicts.

## 5. Effort envelope

Assuming one frontier coordinator, delegated mechanical lanes, and no upstream
trainer defect:

- W0: less than one focused engineering day;
- W1 and W2 in parallel: roughly 6-12 weeks only after a source-acquisition or
  new-authoring mandate can supply 600 reviewed tasks and at least 563 genuinely
  independent groups; the current repository cannot, so this is the dominant
  uncertainty rather than file enumeration;
- W3 production adapter and F-1/F-2/F-3 smoke: roughly 1-3 weeks after the
  semantic specifications and source authorities stabilize; F-4/F-5/F-6 and
  independent population authoring are additional work;
- W4 bounded path: completed; the measured 600-iteration wall time was about
  15.44 minutes, excluding model download, harness implementation and audit;
- W5-W7: roughly 3-8 weeks if W3 and W4 are green;
- W8: roughly 1-2 weeks after promotion evidence exists.

With W0, the W3 contract core and the bounded W4 paths complete, the remaining
credible envelope is approximately **10-24 focused engineering weeks** if the
independent benchmark/data population exists. Safe W1/W2/W3 parallelism can
compress calendar time, but cannot manufacture independence. Data-rights
review, failure to source 563 groups, or weak D-B uplift can extend the schedule
or correctly terminate the 99% claim.

## 6. Next evidence that changes the estimate

1. Establish an authorized source-acquisition/new-authoring plan for at least
   563 independent groups; the current tracked corpus is arithmetically
   insufficient.
2. Register the production W3 adapter and independently reviewed semantic
   specifications; close dependency graphs, rights review and real Oracle
   receipts for the allocated W1 slice before sealing it.
3. Extend the accepted F-1/F-2/F-3 contract to F-4/F-5/F-6, then materialize W3
   examples with immutable provenance and fail-closed Oracle results; do not
   copy proprietary payloads into this foundation repository.
4. Ratify O-003 from frozen denominators and baseline variance. O-005/O-006 are
   already preregistered and remain subordinate to this gate.
5. Execute paired B/D held-out evaluation and require a meaningful semantic
   uplift without critical regressions before scaling training.
6. Keep 2,048-token, positive-dropout or accumulation settings excluded unless
   a separately preregistered technical qualification proves them.
