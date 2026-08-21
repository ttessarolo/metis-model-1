# W4 technical qualification report

Status: **QUALIFIED (bounded technical scope)**
Date: **20 August 2026**
Decision: **O-004**

## Qualified identity

- Checkpoint: `mlx-community/Qwen3.8-27B-4bit`
- Revision: `3e6447f082e89cc7f0bc6e5441afd38dfce760ff`
- Model type / quantization: `qwen3_5`, affine 4-bit, group size 64
- CPython: `3.12.10`
- MLX / MLX Metal: `0.32.1` / `0.32.1`
- MLX-VLM: `0.6.15`
- Transformers / Datasets / Jinja2: `5.14.0` / `5.0.1` / `3.1.6`
- NumPy / safetensors / psutil: `2.5.2` / `0.8.0` / `7.2.2`
- Qualification lock SHA-256:
  `e5a39821599ac1f4eba46b3f5ae04040bd4973f3518351bd75f48677f6c9a340`
- MLX-VLM / MLX source provenance:
  `d734bd28b948fa994b8fe1b722f445ff87d9a110` /
  `3a6219917e4535575ce5bce2fc2ba27a483a709b`

The tracked checkpoint pin anchors the config, exact Hugging Face tree metadata,
and all three weight sizes and SHA-256 hashes. The final local verification
report SHA-256 is
`7166e75a6aedaf6a496d0aedf1d83307a41083f6a56afea649287d1d623f0549`.
The checkpoint payload remains ignored under `artifacts/`; no weight is in Git.

## Executed gates

| Gate | Result | Grounded evidence |
|---|---|---|
| Exact live CLI surface | PASS | `lora-help-telemetry/process.log`, SHA-256 `f226711ca94b9c3d6ceccf00b33fcd7fc7de5b409cdef11247963524ddbbd49f` |
| Strict checkpoint load and deterministic generation | PASS | two identical temperature-zero generations; `qwen3_5` asserted |
| First finite backward and save | PASS | loss `0.00137048`; peak Metal `19.713 GB`; max RSS `13.518 GiB`; no residual process |
| 10 iterations | PASS | `20.45 s`; peak Metal `20.277 GB`; max RSS `15.761 GiB`; finite loss; no residual process |
| 50 iterations | PASS | `68.50 s`; peak Metal `20.277 GB`; max RSS `15.803 GiB`; finite loss; no residual process |
| 600 iterations | PASS | `926.65 s`; peak Metal `20.282 GB`; max RSS `15.724 GiB`; `60/60` Metal samples; corrected live-tail growth `0.000626 GiB`; no residual process |
| 600-step adapter integrity | PASS | `992` tensors, `58,363,904` parameters, all finite; final equals numbered checkpoint; adapter SHA-256 `4823dd922f33fedcb4a0635492e89ef81a62bc63d8cd83ee458dea558a003699` |
| Observable adapter effect | PASS | same canonical prompt: base `KESTREL`, adapter `QUAL_A` |
| Adapter-off baseline | PASS | fresh adapter-off process returns exact base text hash `eeac9f0f1cdc4c2d6964569653fe0e21f5aa710621044364b01bcdcb63d32d57` |
| Full-state stop/resume | PASS | uninterrupted 4 steps equals 2 steps + fresh-process resume to 4, byte-for-byte for canonical model/optimizer state, adapter and adapter config; semantic metadata and loss identical |

The corrected 600-step telemetry report is
`artifacts/w4/2026-08-20-qualification/train-0600-telemetry/summary-corrected.json`
(SHA-256
`497e2cb32d4ee83ae7ff026c1bc4649818fd3db075698a605261b4e976773329`).
It supersedes the original post-exit slope calculation; the raw samples remain
unchanged.

The final full-state comparison report is
`artifacts/w4/2026-08-20-qualification/full-state-bit-exact-report-final.json`
(SHA-256
`504508b63f941fca27c4d98b9c1a69b5265527a582e26619daa8ea9f57a96f25`).
At global step 4 it records:

- final loss `5.221731185913086`;
- state SHA-256
  `bfcc42bd191f007eb18cd31b586c1131f7cb246cbeca13901b17a8d6cda3cc77`
  for `700,776,754` bytes;
- adapter SHA-256
  `049d7a3c8a21f436d128e5dbb28b2fcd007d1cedef4e88a80f1f4c7b25d5211e`;
- semantic continuation-state SHA-256
  `c03872ac5066069f58bc5280ebe9308ce29a2353d847f18329fca153e11e7bd4`.

The final behavior reports are bound to the same checkpoint verification hash:

- base generation: SHA-256
  `83804bf3ca0b64169d57b85b6d472d27d9afdda135ae49c6d22e05912c85eab7`;
- adapter generation: SHA-256
  `366bca394da1e36ee4c4d9e43d97d5dac6c49f568ed3007d11046f2555f88869`;
- adapter-off generation: SHA-256
  `45d65b1f91a4e11d8b73619561840c1d469da4daff5e446d594b5421a5f31684`.

## Wrapper control

Native MLX-VLM `0.6.15` resume remains adapter-only: it does not persist
optimizer, RNG, sampler cursor or global step. The local fail-closed wrapper
provides the additional full-state contract used above. Frontier audit found no
P0/P1 findings after the final rerun.

- `qualification/train_full_state.py` SHA-256:
  `0fb908e6dc80f9f2d888d7692932f585d81b3ba8dad95f317a5fb099983e2e3a`
- `qualification/compare_full_state.py` SHA-256:
  `a594c74079d323eea27564982e8eaf0de63506d3a0690556ac151c8d922ba434`

The wrapper verifies the tracked model/runtime policy pins, disallows remote
code, rejects non-finite loss/gradient/model/optimizer state, hashes every
checkpoint payload, restores MLX/NumPy/Python RNG plus optimizer and sampler,
and enforces `global_step == epoch * batch_count + cursor`.

### 21 August 2026 hardening requalification

The current wrapper was requalified after closing the remaining identity and
resume surfaces. It now:

- passes `trust_remote_code=False` at the top-level processor load boundary;
- binds the verified model revision, config and every model payload hash;
- binds the exact Python/platform/package map, including NumPy, the `uv.lock`
  hash and the wrapper's own hash;
- derives the ordered LoRA target keys from the verified model topology and
  requires exact equality before `apply_lora_layers`;
- rejects non-finite sampler, gradient, updated-model and optimizer state;
- rejects checkpoint symlinks or payload size/hash mismatches and fsyncs files
  and directories before atomic promotion.

The payload-free adversarial suite is `8/8`. An independent real-model probe
derived `496/496` distinct target keys and rejected an arbitrary key, a
non-empty proper subset and a superset. A fresh one-step process followed by a
fresh-process resume to step two produced losses `0.0015919279539957643` and
`0.0011641171295195818`; an uninterrupted two-step reference produced the same
loss sequence. The final adapter config, adapter tensors and full state are
byte-identical.

The ignored comparison report is
`artifacts/w4/2026-08-21-target-roster-bit-exact.json`, SHA-256
`4d23e0f1f7f27945d0071113fbd0984e84c2cc4ca9f4a9cff70069826c01b27c`.
It records semantic continuation-state SHA-256
`4bee697cb4179f82d6623a8ceeca2c1a6366e0fd950f94726fc87f2dc2c40581`.
This dated rerun is the current wrapper-control evidence; it does not change
the bounded qualification or authorize W5.

## Qualification boundary

This report qualifies trainability and deterministic continuation only for the
recorded public synthetic path: 8 text-only examples, batch 1, sequence length
128, rank 8, alpha 16, learning rate `1e-5`, seed 17 and dropout 0. It does not
qualify:

- 1,024/2,048-token memory behavior or batch/accumulation variants;
- stochastic resume with positive dropout;
- Metis semantic quality, D-B uplift, benchmark oracles or pilot readiness;
- the unsealed 30-source W1 slice, its dependency closure or data rights;
- checkpoint redistribution (license review remains required).

O-004 may therefore be ratified without authorizing W5 or external
distribution. Any broader configuration is a new experiment, not inherited
qualification.
