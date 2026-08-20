# Evidenza e fonti

## 1. Snapshot e data

Questa baseline è stata groundata il **20 agosto 2026**. Le fonti web possono
cambiare; le revisioni esatte vanno quindi conservate nei manifest di run.

## 2. Evidenza locale Metis

Repository osservato:

```text
/Users/tommasotessarolo/Developer/ares-matioska/metis
branch: main
commit: a2dde2b191f6b78c2003d74875560da782470968
```

Lo snapshot aveva file untracked preesistenti (`tmp/` e tre checksum VSIX), che
non sono stati modificati né usati come fonte del piano.

### Censimento

```text
all .metis files: 199
all .metis lines: 15,586

examples/play-prod-v2:
  properties:   176
  catalogs:       7
  transformers:   6
  settings:       4
  lib:            3
  _tenant.metis:  1
  total:         197
```

Comandi di verifica:

```bash
git rev-parse HEAD
rg --files -g '*.metis'
rg --files examples/play-prod-v2 -g '*.metis'
```

### Oracle identificati

```text
tooling/src/language/metis.langium
tooling/src/language/metis-validator.ts
tooling/src/language/metis-formatter.ts
tooling/src/compiler/compile.ts
tooling/src/compiler/ir.ts
tooling/test/corpus-validation.ts
```

### Corpus validation osservata

Eseguita dal working directory `metis/tooling`:

```bash
npm exec -- tsx test/corpus-validation.ts
```

Esito osservato:

```text
manifest/corpus: 0.43
files: 197
ERROR: 0
WARN: 123
embedded negative tests: pass
VALIDAZIONE CORPUS: VERDE
```

I 123 warning non vengono cancellati dal racconto: vanno classificati prima di
decidere se un file è un positivo, un caso di review o un'esclusione. Il verde
del corpus non prova la correttezza semantica di ogni futuro task sintetico.

## 3. Hardware locale osservato

```text
Apple M3 Max
16 CPU cores (12 performance, 4 efficiency)
128 GB unified memory
~567 GiB free on the data volume at observation time
```

Non vengono registrati serial number, UUID o altri identificatori personali.

## 4. Qwen3.8 upstream

- [Qwen/Qwen3.8-27B — model card](https://huggingface.co/Qwen/Qwen3.8-27B)
- [Qwen3.8 README](https://huggingface.co/Qwen/Qwen3.8-27B/blob/main/README.md)
- [Qwen3.8 config.json](https://huggingface.co/Qwen/Qwen3.8-27B/blob/main/config.json)
- [Qwen3.8 LICENSE](https://huggingface.co/Qwen/Qwen3.8-27B/blob/main/LICENSE)

**VERIFICATO al 20 agosto 2026:**

```text
repository: Qwen/Qwen3.8-27B
revision: 1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0
license: Apache-2.0
parameters: 27B
model_type: qwen3_5
architecture: Qwen3_5ForConditionalGeneration
layers: 64
hidden size: 5,120
attention pattern: three linear-attention layers followed by one full-attention layer
attention heads: 24
KV heads: 4
native max_position_embeddings: 262,144
declared extension: up to 1M through RoPE/YaRN configuration
```

Il context dichiarato non è il context di training consigliato. Il piano parte da
1.024/2.048 token per rendere diagnosi e memoria controllabili.

## 5. Checkpoint MLX

- [mlx-community/Qwen3.8-27B-4bit](https://huggingface.co/mlx-community/Qwen3.8-27B-4bit)
- [MLX checkpoint README](https://huggingface.co/mlx-community/Qwen3.8-27B-4bit/blob/main/README.md)
- [Ollama qwen3.8:27b-mlx](https://ollama.com/library/qwen3.8:27b-mlx) — solo
  riferimento per l'alias di inferenza, non fonte di training.

**VERIFICATO al 20 agosto 2026:**

```text
repository: mlx-community/Qwen3.8-27B-4bit
revision: 3e6447f082e89cc7f0bc6e5441afd38dfce760ff
quantization: 4-bit
base model: Qwen/Qwen3.8-27B
conversion version declared by card: mlx-vlm 0.6.8
```

## 6. MLX-VLM training

- [MLX-VLM repository](https://github.com/Blaizzy/mlx-vlm)
- [MLX-VLM LoRA/QLoRA guide](https://github.com/Blaizzy/mlx-vlm/blob/main/mlx_vlm/LORA.MD)
- [MLX-VLM v0.6.15 release](https://github.com/Blaizzy/mlx-vlm/releases/tag/v0.6.15)

La guida documenta LoRA/QLoRA e opzioni per sequence length, gradient
checkpointing, completion-only training, accumulation, rank, alpha, adapter path
e training della vision component. Elenca Qwen2/3/3.5 VL fra i modelli
supportati. Qwen3.8 non è nominato esplicitamente, anche se la sua config usa
`model_type=qwen3_5`. La compatibilità del checkpoint specifico è stata
**VERIFICATA** nel percorso W4 delimitato, non dedotta dalla lista di supporto.

La release pubblica più recente osservata è `v0.6.15`, pubblicata il 18 agosto
2026. Il checkpoint MLX dichiara invece di essere stato convertito con `0.6.8`:
sono due fatti differenti. La qualification ha ratificato `0.6.15` come trainer
pin, mantenendo `0.6.8` come sola provenienza della conversione.

## 7. Issue pubbliche rilevanti

- [MLX-VLM #1584 — Qwen3.5 LoRA/SFT backward failure](https://github.com/Blaizzy/mlx-vlm/issues/1584)
- [mlx-lm #1185 — qwen3_5 LoRA descriptor leak](https://github.com/ml-explore/mlx-lm/issues/1185)
- [mlx-lm #1206 — qwen3_5 backward/OOM report](https://github.com/ml-explore/mlx-lm/issues/1206)
- [MLX #3539 — residency/OOM report](https://github.com/ml-explore/mlx/issues/3539)

La prima è chiusa ed è uno storico del trainer MLX-VLM. Le altre riguardano
`mlx-lm` o MLX e non provano che `mlx-vlm` fallirà su Model 1. Sono segnali di
rischio che giustificano il run lungo di qualificazione; non sono blocker già
dimostrati.

## 8. Claim non ancora verificati

- memoria di picco e throughput reali con 1.024/2.048 token;
- migliore rank/alpha/LR;
- dimensione ottimale del dataset;
- vantaggio D−B e C−A;
- soglie finali del benchmark;
- distribuibilità dell'adapter derivato dal corpus proprietario;
- compatibilità con futuri aggiornamenti Metis, Qwen o MLX.

La stabilità a 600 iterazioni, i picchi della configurazione sequence-128 e il
resume full-state wrapper sono verificati nel
[`W4-QUALIFICATION.md`](../orchestra/runs/2026-08-20-w1-w4-entry/W4-QUALIFICATION.md).

Questi elementi devono restare esplicitamente aperti finché non esiste evidence
prodotta dalle wave corrispondenti.
