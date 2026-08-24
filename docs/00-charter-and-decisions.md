# Charter e decisioni fondative

## 1. Missione

**DECISO —** Metis Model 1 è un modello locale specializzato nel DSL Metis,
costruito esclusivamente a partire dalla famiglia **Qwen3.8**. Il primo target è
`Qwen/Qwen3.8-27B`; la prima strategia di adattamento è QLoRA su checkpoint MLX
quantizzato, mantenendo separati base model e adapter.

Il prodotto non è “un autocomplete che produce testo plausibile”. Il prodotto è
un sistema che, su task Metis ben definiti:

1. comprende un requisito o una modifica richiesta;
2. produce una patch o un file Metis canonico;
3. usa il toolchain Metis come feedback eseguibile;
4. corregge gli errori entro un budget limitato di cicli;
5. dimostra la correttezza semantica con un diff o un oracle distinto dalla sola
   compilazione.

## 2. Perimetro di Model 1

### Incluso

- authoring di file `.metis` a partire da requisiti strutturati;
- modifica locale e minimale di file esistenti;
- riparazione a partire da sorgente invalido e diagnostici reali;
- review con spiegazione concreta del problema e proposta di correzione;
- migrazioni fra versioni o forme canoniche quando esiste un oracle verificabile;
- spiegazione di AST/IR e comportamento compilato, se il riferimento deriva dal
  toolchain corrente;
- integrazione locale su Apple Silicon attraverso MLX.

### Escluso dalla prima release

- fine-tuning completo di tutti i pesi;
- addestramento della componente vision;
- pretraining generale o ampliamento del tokenizer;
- mescolare nello stesso adapter iniziale programmazione TypeScript/Rust generica;
- memorizzare nei pesi configurazioni tenant o simboli operativi destinati a
  cambiare;
- pubblicazione esterna di corpus proprietario, adapter o pesi fusi;
- scrittura autonoma su repository ARES/Metis senza revisione e autorizzazione
  umana;
- uso di credenziali o interrogazioni live per costruire il corpus.

Un eventuale adapter futuro per compiler TypeScript o runtime Rust sarà una
decisione separata: condivide la famiglia Qwen3.8, non necessariamente il medesimo
adapter Metis.

## 3. Decisioni ratificate

| ID | Decisione | Razionale | Conseguenza |
|---|---|---|---|
| D-001 | Unica famiglia base: Qwen3.8 | Rende comparabili i risultati ed evita una gara fra modelli non richiesta | Ogni baseline e adapter usa Qwen3.8 |
| D-002 | Target iniziale: Qwen3.8-27B | Compromesso fra capacità, coding e fattibilità su 128 GB unified memory | Nessun downgrade silenzioso a 9B/14B, nessun passaggio a Nemotron |
| D-003 | Runtime locale qualificato: MLX `0.32.1` + MLX-VLM `0.6.15` | Il checkpoint pin ha superato il percorso tecnico W4 delimitato | Non usare l'artefatto Ollama come sorgente di training e non estendere la qualifica oltre la config eseguita |
| D-004 | QLoRA prima di LoRA/full tuning | Riduce memoria, rischio e costo di iterazione | Il full fine-tuning è fuori perimetro |
| D-005 | Vision encoder congelato | Model 1 è text/code-first | `train_vision=false` salvo nuova decisione motivata |
| D-006 | Adapter separato e versionato | Consente rollback, ablation e confronto con la base | Niente fusione prematura |
| D-007 | Compiler come oracle eseguibile | La plausibilità testuale non prova la validità del DSL | Ogni esempio generato e ogni eval attraversano gli oracle applicabili |
| D-008 | Correttezza semantica distinta da compile-clean | Un file può compilare ed essere semanticamente sbagliato | I gate includono diff semantico/parità |
| D-009 | Benchmark congelato prima del dataset di training | Evita target leakage e benchmark retrofittato | Le famiglie held-out non generano derivati di train |
| D-010 | Pesi per abilità stabili, retrieval per stato mutevole | Riduce obsolescenza e allucinazioni di simboli | Checkout corrente e contesto restano componenti del sistema |
| D-011 | Dati e artefatti local-only per default | Il corpus Metis può essere proprietario | Ogni upload o distribuzione richiede autorizzazione separata |
| D-012 | Nessun peso o dataset voluminoso in Git | Mantiene il repository ispezionabile e sicuro | Git contiene manifest, config, report e checksum, non i payload |

## 4. Ipotesi da dimostrare

Le seguenti non sono decisioni, ma ipotesi sperimentali:

- **H-001:** un adapter QLoRA produce un incremento sostanziale rispetto alla
  stessa base Qwen3.8 con identico contesto e identico ciclo compilatore;
- **H-002:** il vantaggio non è soltanto sintattico, ma resta visibile sui diff
  semantici di famiglie mai viste durante il training;
- **H-003:** un adapter testuale su `Qwen3.8-27B-4bit` può essere addestrato e
  ricaricato stabilmente con MLX-VLM sulla macchina target;
- **H-004:** il miglioramento Metis non causa una regressione materiale sui task
  generici minimi necessari all'uso come coding agent;
- **H-005:** il corpus corrente, aumentato solo con trasformazioni validate e
  provenance-safe, contiene abbastanza varietà per Model 1.

H-003 è confermata nel perimetro pubblico sintetico batch-1 / sequence-128
registrato dal report W4; contesti, batch e stochastic settings diversi restano
nuove ipotesi. H-001, H-002, H-004 e H-005 restano aperte.

Se H-001 o H-002 falliscono, non si scala il training: si rivedono dataset,
task formulation o confine del prodotto.

Prima di tentare H-001, la variante B viene misurata da sola. Se B soddisfa il
gate pratico W5-XS, `NO_TRAIN` è un esito di successo e Model 1 viene consegnato
come sistema Qwen3.8+contesto+toolchain. Un adapter è un'ottimizzazione
sperimentale, non un deliverable obbligatorio.

## 5. Definizione di “nativo”

Per questo progetto, “nativo” è una proprietà misurabile e non uno slogan. Un
modello specializzato deve:

- scegliere spontaneamente forme Metis canoniche senza essere guidato riga per
  riga da esempi nel prompt;
- applicare modifiche locali senza riscrivere sezioni estranee;
- interpretare correttamente diagnostici reali;
- non mascherare l'assenza di simboli inventandone di plausibili;
- distinguere validità sintattica, validità di linking e correttezza semantica;
- mantenere il vantaggio su famiglie strutturali held-out.

Non è necessario, né desiderabile, che i pesi ricordino la fotografia corrente
di ogni tenant.

## 6. Autorità e criteri di verità

Ordine di autorità per costruire esempi ed emettere verdetti:

1. grammatica, validator, compiler, IR e test/oracle eseguibili del commit Metis
   dichiarato;
2. sorgenti `.metis` correnti e validati nel medesimo commit;
3. decisioni e specifiche esplicitamente marcate come correnti;
4. documentazione storica, soltanto come contesto e mai come train truth implicita.

Un documento narrativo non prevale su un oracle corrente senza una decisione
esplicita che riconcili la divergenza.

## 7. Successo di Model 1

Model 1 ha due livelli di chiusura non intercambiabili.

`MODEL1_USABLE_LOCAL` richiede che B, oppure D dopo un micro-adapter, soddisfi
il gate semantico W5-XS senza veto critici. Non implica un claim statistico o
distribuibilità.

`ACCURACY99_PROMOTED` richiede invece che:

- la catena di training è riproducibile da manifest e hash;
- il benchmark frozen non è contaminato;
- l'adapter supera la baseline base+context sugli indicatori concordati;
- compilation e semantica superano gate separati;
- i failure case e i limiti sono documentati, non eliminati dal report;
- l'adapter può essere disattivato senza modificare il base model;
- licenze, sensibilità e destinazione degli artefatti sono esplicite.

Le soglie numeriche iniziali sono proposte in
[`03-evaluation-and-gates.md`](03-evaluation-and-gates.md); diventeranno contratto
soltanto dopo la ratifica del benchmark.
