# Training runbook

## 1. Scopo del runbook

Questo documento definisce l'ordine fail-closed degli esperimenti. Il percorso
tecnico pubblico batch-1 / sequence-128 è stato eseguito e qualificato; il report
è [`W4-QUALIFICATION.md`](../orchestra/runs/2026-08-20-w1-w4-entry/W4-QUALIFICATION.md).
Una successiva espansione tecnica ha provato sequence-1024 a rank 8, resume rank
8 e rank 16; resta esclusa ogni configurazione, stochasticità o dataset Metis
non eseguito.

## 2. Ambiente target osservato

**VERIFICATO — 20 agosto 2026:**

- MacBook Pro con Apple M3 Max;
- 16 core CPU, 12 performance e 4 efficiency;
- 128 GB di memoria unificata;
- circa 567 GiB liberi sul volume dati al momento del grounding.

La capacità nominale non prova stabilità di backward, optimizer, checkpoint o
run lungo. Nessuna stima teorica sostituisce la qualification.

## 3. Versioni e isolamento

Regole:

- usare un ambiente `uv`/virtualenv dedicato al repository;
- non aggiornare l'installazione Python/Conda globale;
- fissare Python, `mlx`, `mlx-vlm` e dipendenze in un lockfile;
- fissare revisioni Hugging Face per upstream e checkpoint MLX;
- registrare macOS, chip, memoria e versioni toolchain senza identificatori
  hardware personali;
- non leggere `.env`, keychain, token o credenziali;
- download soltanto da repository pubblici identificati, con checksum/revision.

Revisioni fissate o osservate il 20 agosto 2026:

```text
upstream: Qwen/Qwen3.8-27B
revision: 1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0

mlx checkpoint: mlx-community/Qwen3.8-27B-4bit
revision: 3e6447f082e89cc7f0bc6e5441afd38dfce760ff
conversion declared by model card: mlx-vlm 0.6.8
```

**VERIFICATO E DECISO — 20 agosto 2026:** MLX-VLM `v0.6.15`, insieme a MLX
`0.32.1`, è il pin O-004 del percorso qualificato. La scelta deriva dalla prova
eseguita, non dal solo fatto che la release sia recente.

La versione di `mlx-vlm` usata per il training non è automaticamente quella di
conversione. Va scelta durante la qualification, fissata nel lock e riportata
insieme all'eventuale patch applicata.

## 4. WQ — Qualification obbligatoria

### Obiettivo

Dimostrare che il checkpoint specifico, con versioni pin e configurazione
text-only, esegue un ciclo QLoRA completo e stabile sulla macchina target.

### Configurazione bounded ratificata per il pilot

La griglia O-005 usa questa base comune:

```yaml
model: mlx-community/Qwen3.8-27B-4bit
model_revision: 3e6447f082e89cc7f0bc6e5441afd38dfce760ff
method: qlora
train_vision: false
train_on_completions: true
batch_size: 1
gradient_accumulation_steps: 1
max_seq_length: 1024
gradient_checkpointing: disabled
iterations: 100_max_per_screen_or_finalist_seed
adapter_fusion: false
```

Il long-run qualificato resta batch 1, accumulation 1, sequence length 128,
rank 8, alpha 16, learning rate `1e-5`, seed 17 e dropout 0. L'espansione
sequence-1024 ha poi eseguito davvero rank 8 step 1 e resume step 2, oltre a rank
16/alpha 32 step 1, con picco Metal 94,43-95,04 GB. O-005 fissa rank 8/16,
alpha 2x, LR `1e-5`/`2e-5`, seed 17 per lo screening e 17/29/43 per il finalista.
Sequence 2.048, accumulation diversa da 1 e dropout positivo restano esclusi.

### Sequenza di prova

1. verificare revisioni e checksum dei file scaricati;
2. caricare modello e processor;
3. generare con adapter disattivato e salvare la baseline;
4. eseguire forward e prima backward su un micro-dataset non sensibile;
5. controllare loss finita e gradienti finiti;
6. continuare per almeno 600 iterazioni, con telemetry di memoria periodica;
7. verificare trend della loss senza usare la sola training loss come qualità;
8. salvare adapter e optimizer state;
9. terminare il processo, ricaricare e generare;
10. riprendere il training dal checkpoint;
11. disattivare l'adapter e verificare la baseline attesa;
12. eseguire 30-50 task Metis held-out di smoke evaluation prima di autorizzare
    il pilot semantico;
13. produrre un report con memory curve, tempi, errori e artifact hash.

### Perché almeno 600 iterazioni

Issue pubbliche dell'ecosistema MLX/Qwen `qwen3_5` riportano sia errori alla prima
backward sia problemi che compaiono dopo decine o centinaia di iterazioni. Tali
issue non provano un bug nel nostro percorso MLX-VLM, ma rendono insufficiente uno
smoke test di poche iterazioni.

### Exit gate

`TECHNICALLY QUALIFIED` per O-004 solo se:

- nessun NaN/Inf;
- nessun OOM o crescita monotona anomala della memoria;
- save, reload e resume funzionano;
- l'adapter cambia il comportamento e può essere disattivato;
- tutti gli hash e la config sono ricostruibili.

L'autorizzazione W5 richiede inoltre una slice W1 sigillata e il micro-eval
Metis; questi due gate non sono soddisfatti dalla fixture sintetica W4.

Altrimenti stato `BLOCKED`, con causa riproducibile. Non si passa al pilot
riducendo di nascosto sequenza, iterazioni o controlli.

## 5. WP — Pilot QLoRA

### Dataset

- 3.000-8.000 esempi accepted-by-oracle;
- task mix stratificato F-1…F-6;
- train/dev/internal-test per leakage group;
- frozen benchmark già sigillato e non consultato per il tuning.

### Sweep proposto

Il pilot deve essere piccolo ma informativo. Candidati iniziali, da ratificare:

- rank: 8, 16, eventualmente 32;
- alpha: rapporto 1× o 2× il rank;
- learning rate: piccola griglia logaritmica attorno a `1e-5`–`5e-5`;
- sequence length: prima 1.024, poi 2.048 solo dopo stabilità;
- gradient accumulation calibrata per batch effettivo e memoria;
- 2-3 seed sui candidati finalisti.

Non si usa il contesto nativo dichiarato di 262.144 token come lunghezza di
training iniziale. Il valore di contesto del modello e il budget sostenibile di
fine-tuning sono problemi differenti.

### Selezione checkpoint

La scelta usa il dev set e considera insieme:

- semantic correctness;
- compile-clean;
- patch minimality;
- unknown/invented symbols;
- stabilità e costo;
- divergenza fra famiglie.

La training loss da sola non seleziona il checkpoint. Il frozen benchmark non
seleziona iperparametri.

## 6. WV1 — Candidate Model 1

Si avvia soltanto se il pilot mostra miglioramento D−B credibile e non soltanto
memorization. Passi:

1. correggere errori di dataset emersi dal pilot senza leggere i target frozen;
2. ampliare coverage e provenance group, non parafrasi cosmetiche;
3. congelare dataset manifest e training config;
4. eseguire il training candidate con telemetry e checkpoint periodici;
5. valutare internal test una sola volta per la scelta finale;
6. sigillare candidate adapter e artifact identity;
7. eseguire benchmark A/B/C/D;
8. eseguire contamination e reproducibility audit;
9. produrre il promotion report.

## 7. Reasoning mode e template

Qwen3.8 offre modalità di reasoning configurabili. Per evitare un confronto
confuso:

- fissare il chat template esatto;
- marcare ogni esempio come modalità prevista;
- non mescolare thinking traces non controllate nel target di training;
- confrontare le baseline con la stessa modalità;
- misurare separatamente qualità, token e latenza;
- preferire risposte concise e verificabili per repair/editor loop.

Eventuali reasoning traces non devono contenere segreti né diventare un requisito
di audit. L'evidence utile è la patch, il diagnostico, l'oracle e il risultato.

## 8. Telemetry minima

Per ogni run:

- timestamp, run ID e Git state;
- revisioni modelli e dipendenze;
- config completa e seed;
- dataset/split manifest hash;
- iterazione, loss, learning rate e throughput;
- memoria resident/peak e andamento nel tempo;
- tempi di save/reload/resume;
- checkpoint hash e dimensione;
- exit status e stack trace redatto;
- risultati dev per checkpoint valutato.

Log voluminosi e checkpoint non entrano in Git; il repository conserva report,
indici, checksum e posizione nell'artifact store autorizzato.

## 9. Recovery e rollback

- checkpoint atomici in directory run-specific;
- nessun overwrite dell'ultimo checkpoint valido;
- resume testato nella qualification prima di affidargli un run lungo;
- adapter sempre disattivabile;
- base checkpoint immutabile;
- stato `failed`, `qualified`, `candidate`, `promoted`, `rejected` esplicito;
- una versione rejected resta documentata se ha prodotto evidence utile.

## 10. Comandi: policy

I comandi eseguibili saranno aggiunti solo dopo il pin della versione e verificati
con `--help`. La guida MLX-VLM corrente documenta, fra le altre, opzioni per
`--max-seq-length`, `--grad-checkpoint`, `--train-on-completions`,
`--gradient-accumulation-steps`, `--lora-rank`, `--lora-alpha`,
`--adapter-path` e `--train-vision`.

Non si copia un comando da un README mobile dentro un runbook dichiarandolo
riproducibile: il comando finale, il suo output `--help` e il lock fanno parte
della stessa baseline.
