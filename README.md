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

Per un futuro aggiornamento della grammatica, il default ratificato è il
percorso minimo: aggiornare pin, retrieval e oracle, provare l'adapter esistente
sul benchmark di manutenzione e scegliere `NO_RETRAIN` se i gate restano verdi.
Solo un fallimento compatibile apre un piccolo delta QLoRA; un successore pieno
richiede una rottura AST/IR/semantica o il fallimento dimostrato del percorso
leggero. Dataset, benchmark e adapter precedenti restano immutabili e
rollbackabili.

## Base tecnica

Le decisioni iniziali del progetto sono:

- base model unico: `Qwen/Qwen3.8-27B`;
- checkpoint MLX pin: `mlx-community/Qwen3.8-27B-4bit@3e6447f0...`;
- runtime locale tecnicamente qualificato con MLX `0.32.1` e MLX-VLM `0.6.15`;
- QLoRA come prima strategia di adattamento;
- vision encoder congelato: Model 1 è text/code-first;
- adapter separato dal base model per ablation, rollback e versionamento;
- nessun full fine-tuning e nessuna fusione prematura dei pesi.

La compatibilità non è stata data per scontata: il percorso sintetico delimitato
ha superato 600 iterazioni, backward, stabilità della memoria, save/reload,
adapter-off e resume full-state bit-exact. Questa qualifica tecnica non sostituisce
il benchmark Metis né prova uplift semantico.

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

Il primo gate di prodotto è però B da sola. Se base+contesto+compiler loop
soddisfa il bisogno pratico, l'esito corretto è `NO_TRAIN` e l'adapter non viene
creato. Il tuning si apre soltanto per failure semantiche ripetibili e deve poi
dimostrare un vantaggio D−B.

## Stato del progetto

Il repository contiene la baseline progettuale, la foundation W0 eseguibile, la
prima allocazione W1, il core contrattuale W3 e il packet tecnico W4: manifest di
revisioni, registro delle decisioni, contratti JSON Schema, gate offline, policy
degli artefatti, harness e lavagne di orchestrazione. È stato eseguito soltanto
training pubblico sintetico di qualifica; nessun adapter Metis è promosso e
nessun uplift di prodotto è dichiarato.

Il core W3 oggi copre esattamente F-1/F-2/F-3 ed è stato accettato da due replay
frontier indipendenti dopo attacchi a identità, genealogia, schema e replay. Non
è ancora un dataset produttivo: le quattro autorità di benchmark, source
register, adapter Oracle e identità Oracle sono intenzionalmente non registrate,
le receipt reali sono `0/15` e F-4/F-5/F-6 restano aperte.

Il broker protetto ha raggiunto `PHASE_B_INSTALLABLE_UNEXECUTED`: il pacchetto
è materializzato, ma non sono stati installati utenti o servizi privilegiati e
non è stata prodotta evidenza host o di produzione. Il pacchetto W1/W2 rende
invece
riproducibili i blocchi correnti: task `30/30`, asset `201/201`, celle Oracle
`0/160`, review diritti `0/201` e un solo gruppo di leakage rispetto al minimo
`563`. Il relativo seal è quindi intenzionalmente `unsealed_evidence_only`.

Sul percorso di prodotto più stretto, `INITIAL_LOCAL_QLORA_V1` è stato
consegnato e sottoposto a backup; la wave catalog-domain ha chiuso 12/12 sia per
base sia per adapter e la wave grammar+standard-library T30-v3 ha chiuso 30/30
per entrambi con verdetto `NO_RETRAIN`. Questi risultati non equivalgono alla
promotion statistica Accuracy-99 sul benchmark 600/563, che resta separata.

La wave Metis Brain ha inoltre consegnato il core locale v1: API autenticata su
loopback, sessioni tenant isolate con TTL idle di 20 minuti, snapshot immutabili,
capability, stale guard e compilazione contro grammar/stdlib pinnate. Il core è
eseguibile ma non carica ancora Model 1 (`model_loaded=false`): inferenza,
retrieval progressivo, chat/VSIX, Metis Fast e packaging Mac restano separati e
non sono dichiarati completati.

I gate locali non privilegiati non scaricano modelli e non toccano l'ambiente
Conda globale:

```bash
make setup
make validate
make lint
make format-check
uv run metis-model1 validate-pilot
uv run metis-model1 assess-experiment  # exit 0: piano pronto; serve mandato W5-XS
uv run metis-model1 assess-w5          # exit 1: promotion Accuracy-99 bloccata
```

`EXPERIMENT_PLAN_READY` non autorizza inferenza, dataset o optimizer: dichiara
solo che il protocollo baseline-first può ricevere una wave esecutiva. Il gate W5
storico conserva integralmente i cinque blocker della promotion Accuracy-99.

`make check` include anche le suite che usano il runtime Node qualificato e va
eseguito soltanto in una wave che lo autorizza. Versione
e SHA-256 del binario vengono comunque verificati fail-closed dal bridge. Su un
altro host già qualificato, indicare esplicitamente il binario equivalente con
`make check PINNED_NODE=/percorso/assoluto/node`. Le invocazioni dirette del
bridge possono usare `METIS_MODEL1_NODE`; senza override, il resolver considera
tutti i `node` nel `PATH` e accetta soltanto quello che coincide con il pin.

Questo comando serve alla foundation e non scarica né riesegue i payload W4. Il
runtime ML separato è fissato in `qualification/`; O-004 è ratificato.

Lo stato tecnico sintetico resta:

```text
INFERENCE AND BOUNDED TRAINING QUALIFIED / SEMANTIC UPLIFT UNTESTED
```

La roadmap di primo valore procede attraverso:

1. 12 task di baseline B e possibile `NO_TRAIN`;
2. solo se necessario, B su 24 task accoppiati e poi `64 train + 16 dev`
   failure-driven se B resta sotto soglia;
3. un solo micro-QLoRA rank 8 fino a 100 step;
4. confronto B/D e chiusura entro cinque giorni della wave esecutiva.

La certificazione Accuracy-99 resta una corsia successiva e separata.

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
- [orchestrazione e lavagne](docs/08-orchestration-and-blackboards.md);
- [struttura repository e policy artefatti](docs/09-repository-and-artifact-policy.md);
- [registro delle decisioni aperte](docs/10-open-decisions.md);
- [stima di fattibilità e rischi](docs/11-feasibility-and-risks.md).
- [piano esecutivo Accuracy-99](docs/12-accuracy-99-execution-plan.md).
- [broker di esecuzione protetto](docs/13-protected-execution-broker.md).
- [pacchetto di evidenza e seal W1/W2](docs/14-w1-w2-evidence-package.md).
- [esperimento first-value W5-XS](docs/15-first-value-experiment.md).
- [report tecnico W4](orchestra/runs/2026-08-20-w1-w4-entry/W4-QUALIFICATION.md).
- [contratto sessioni Metis Brain v1](docs/22-metis-brain-session-wave.md).
- [runbook locale Metis Brain](docs/23-metis-brain-local-runbook.md).

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

La prossima milestone di prodotto è collegare a questo core l'inferenza Model 1
con un solo runtime condiviso e il retrieval progressivo dei cataloghi, senza
cambiare l'isolamento delle sessioni. Seguono integrazione VSIX/Metis Fast e
packaging dell'app Mac. La promotion Accuracy-99 su benchmark 600/563 resta una
corsia statistica separata e non blocca il primo server locale dimostrabile.
