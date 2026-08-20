# Metis Model 1

**Metis Model 1** è il progetto per costruire un modello locale specializzato
nella programmazione del DSL Metis, basato esclusivamente su **Qwen3.8-27B** e
destinato a girare su Apple Silicon tramite MLX.

L'obiettivo non è produrre semplicemente codice dall'aspetto plausibile. Model 1
deve imparare stabilmente la grammatica, le forme canoniche e i comportamenti di
authoring, editing, repair e review di Metis, continuando però a usare il checkout
corrente e il toolchain Metis come autorità sulla realtà del progetto.

## Idea centrale

“Programmare nativamente in Metis” significa che il modello sa:

- trasformare un requisito in codice `.metis` canonico;
- applicare modifiche locali senza riscrivere parti estranee;
- interpretare diagnostici reali e correggere il sorgente;
- distinguere validità sintattica, linking e correttezza semantica;
- evitare di inventare simboli assenti dal contesto disponibile;
- spiegare concretamente perché un'implementazione è errata o incompleta.

Non significa memorizzare nei pesi ogni configurazione tenant o decisione
mutevole. Il sistema è deliberatamente composto da tre livelli:

```text
Qwen3.8-27B + adapter Metis versionato
                  +
checkout e contesto corrente
                  +
parser / linker / validator / compiler / semantic oracle
```

Il compilatore è necessario, ma non sufficiente: un risultato che compila può
comunque implementare la semantica sbagliata. Per questo il piano separa sempre
il gate `compile-clean` dai controlli di diff semantico e parità.

## Base tecnica

Le decisioni iniziali del progetto sono:

- base model unico: `Qwen/Qwen3.8-27B`;
- checkpoint MLX candidato: `mlx-community/Qwen3.8-27B-4bit`;
- training locale candidato con MLX-VLM;
- QLoRA come prima strategia di adattamento;
- vision encoder congelato: Model 1 è text/code-first;
- adapter separato dal base model per ablation, rollback e versionamento;
- nessun full fine-tuning e nessuna fusione prematura dei pesi.

La compatibilità del checkpoint specifico con un training MLX-VLM lungo non viene
data per scontata. Prima del pilot è obbligatoria una qualification di almeno 600
iterazioni che verifichi backward, stabilità della memoria, salvataggio, reload e
resume dell'adapter.

## Perimetro di Model 1

Model 1 copre inizialmente:

- creazione di file e blocchi Metis;
- editing minimale di sorgenti esistenti;
- repair guidato dai diagnostici del toolchain;
- review e spiegazione di errori sintattici e semantici;
- migrazioni e canonicalizzazioni con oracle verificabile;
- spiegazione della relazione fra DSL, AST, IR e comportamento compilato.

Non include nella prima release:

- programmazione TypeScript o Rust generica nello stesso adapter;
- accesso live ad ARES o uso di credenziali per costruire il corpus;
- pubblicazione esterna automatica di dataset o adapter proprietari;
- modifiche autonome ai repository senza revisione umana;
- pesi, checkpoint o dataset materializzati dentro Git.

## Dataset e valutazione

Il corpus sorgente non viene trattato come un semplice dump testuale. Ogni
esempio di training deve dichiarare origine, trasformazioni, versione Metis,
oracle applicati, sensibilità e leakage group.

Il benchmark viene congelato prima della generazione del training set. Lo split
non è casuale per file: sorgenti, AST, IR, golden, mutazioni e altri derivati
dello stesso antenato semantico devono restare nella stessa partizione.

La valutazione confronta quattro configurazioni:

| Variante | Adapter | Contesto e compiler loop | Misura |
|---|---:|---:|---|
| A | no | no | conoscenza spontanea della base |
| B | no | sì | valore della sola ingegneria di sistema |
| C | sì | no | conoscenza entrata nei pesi |
| D | sì | sì | prodotto locale completo |

Il confronto decisivo è **D contro B**: stessa Qwen3.8, stesso contesto e stessi
strumenti, con e senza adapter Metis.

## Stato del progetto

Il repository contiene attualmente la baseline progettuale verificabile. Il
training non è ancora stato eseguito e nessun adapter è dichiarato qualificato o
promosso.

La roadmap procede attraverso:

1. congelamento del benchmark;
2. census del corpus e provenance graph;
3. dataset builder con oracle Metis;
4. qualification Qwen3.8 su MLX-VLM;
5. pilot QLoRA;
6. valutazione adversarial e contamination audit;
7. candidate Model 1 e verdetto di promozione;
8. packaging e integrazione locale con rollback.

## Documentazione

Il piano completo è in [`docs/README.md`](docs/README.md). I documenti principali
sono:

- [charter e decisioni fondative](docs/00-charter-and-decisions.md);
- [architettura del sistema](docs/01-architecture.md);
- [dataset, provenance e split anti-leakage](docs/02-dataset-and-provenance.md);
- [benchmark, metriche e gate](docs/03-evaluation-and-gates.md);
- [qualification e training runbook](docs/04-training-runbook.md);
- [riproducibilità, sicurezza e governance](docs/05-reproducibility-and-governance.md);
- [roadmap di delivery](docs/06-delivery-roadmap.md);
- [evidenza locale e fonti primarie](docs/07-evidence-and-sources.md).

I documenti distinguono esplicitamente fra stato **VERIFICATO**, **DECISO**,
**PROPOSTO** e **DA VERIFICARE**.

## Governance degli artefatti

Questo repository deve contenere codice, manifest, configurazioni, checksum,
data/model card e report di valutazione. Non deve contenere:

- base weights o adapter binari;
- checkpoint e optimizer state;
- dataset proprietari materializzati;
- credenziali, `.env`, token o payload di produzione.

Dataset e adapter restano local-only e internal-only per default. Qualunque upload,
fusione o distribuzione esterna richiede una decisione e una review separate.

## Prossimo milestone

La prima milestone operativa è duplice e parallelizzabile:

1. sigillare il benchmark Metis con task, oracle e leakage group;
2. qualificare il checkpoint Qwen3.8-27B-4bit su MLX-VLM per almeno 600
   iterazioni, senza usare dati sensibili.

Solo il superamento di entrambi consente di avviare il pilot QLoRA di Model 1.
