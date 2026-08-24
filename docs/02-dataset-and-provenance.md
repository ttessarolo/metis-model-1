# Dataset e provenance

## 1. Principio guida

Le 15.586 righe Metis osservate sono abbastanza per iniziare un progetto serio,
ma non diventano un dataset utile copiandole in un file JSONL. Il dataset di
Model 1 è una collezione di **task verificati**, non un dump di sorgenti.

Ogni esempio deve avere:

- un obiettivo esplicito;
- input e output separati;
- origine e trasformazioni tracciate;
- versione del linguaggio e commit del toolchain;
- esito degli oracle applicabili;
- famiglia strutturale, simboli e dipendenze;
- classificazione di sensibilità;
- split assegnato per gruppo di provenance, non casualmente per file.

## 2. Snapshot sorgente iniziale

**VERIFICATO — 20 agosto 2026.** Sul commit Metis
`a2dde2b191f6b78c2003d74875560da782470968` sono presenti:

- 199 file `.metis`, 15.586 righe complessive;
- 197 file tenant sotto `examples/play-prod-v2`;
- 176 `properties`, 7 `catalogs`, 6 `transformers`, 4 `settings`, 3 `lib` e
  `_tenant.metis`;
- grammatica, validator, formatter, compiler, IR e corpus validation utilizzabili
  come fonti e oracle.

Questa fotografia è evidence, non un diritto implicito di distribuire il corpus.
Il manifest deve classificare proprietà e destinazione di ogni sorgente prima
della materializzazione del dataset.

## 3. Unità di provenance

Ogni asset riceve un identificatore stabile:

```text
source_asset_id = sha256(repository + commit + path + content)
derived_asset_id = sha256(generator + generator_version + parameters + parents)
example_id       = sha256(task_schema_version + normalized_input + normalized_output)
```

Il provenance graph collega:

- sorgente `.metis`;
- eventuale AST, IR, manifest, census o golden derivato;
- mutazione applicata;
- diagnostico atteso;
- fix canonico;
- esempio conversazionale finale.

Due asset con lo stesso antenato semantico sono nello stesso leakage group anche
se il testo è molto diverso.

Quando `provenance.parents` nomina un altro example ID presente nel dataset,
parent e child devono dichiarare sia lo stesso split sia lo stesso leakage
group. Il controllo è indipendente dall'ordine delle righe: una derivazione non
può creare un nuovo gruppo restando semplicemente nello split del parent.

## 4. Famiglie di task

### F-1 — Authoring

Trasforma un requisito verificabile in un file o blocco Metis canonico.

Fonti ammesse:

- intent sintetico generato da AST/IR corrente e poi verificato;
- specifiche correnti con mapping non ambiguo;
- descrizioni create manualmente per coprire costrutti rari.

L'output deve attraversare parser, linker, validator e compiler quando
applicabili. Il reverse rendering del file sorgente non può finire in uno split
diverso dal proprio sorgente.

### F-2 — Editing minimale

Trasforma `sorgente + richiesta di modifica` in una patch locale.

Metriche specifiche:

- righe/tokens estranei modificati;
- preservazione del formatter canonico;
- equivalenza delle sezioni non coinvolte;
- correttezza del diff semantico atteso.

### F-3 — Repair da diagnostico

Parte da una mutazione plausibile e dal diagnostico reale emesso dal toolchain.
Esempi di mutazioni:

- simbolo esistente ma usato nel contesto sbagliato;
- riferimento mancante o tipo incompatibile;
- ordine/forma non canonica quando semanticamente rilevante;
- conflitto di impostazioni;
- rottura di una relazione fra property, catalog o transformer;
- costrutto storico da migrare.

Non si addestra su errori casuali privi di valore, salvo un piccolo set per
robustezza del parser. Il fix deve essere ottenuto o approvato da un oracle, non
dedotto dalla semplice scomparsa del primo errore.

### F-4 — Review e spiegazione

Input: codice plausibile, obiettivo atteso e contesto pertinente.

Output:

- finding localizzato;
- valore o simbolo concreto coinvolto;
- perché il comportamento diverge;
- patch proposta;
- prova applicabile e limite della prova.

Questa famiglia insegna a non confondere “compila” con “fa la cosa giusta”.

### F-5 — Migrazione e canonicalizzazione

Comprende:

- prima/dopo storico soltanto se entrambi i lati sono verificabili;
- rewrite prodotto da migrator versionato;
- formatter input/output;
- sintassi legacy etichettata esplicitamente con versione di origine.

Il lato legacy non va riutilizzato come positivo di authoring corrente.

### F-6 — Spiegazione strutturale

Mappa DSL verso AST/IR o spiega l'effetto compilato. Serve a rendere più forte il
modello mentale, ma non deve dominare il dataset: grammatica, AST e IR sono spesso
duplicati semantici della stessa sorgente.

## 5. Schema logico degli esempi

Formato concettuale, indipendente dal serializer richiesto dalla versione
MLX-VLM fissata:

```json
{
  "example_id": "sha256:...",
  "task_family": "repair",
  "messages": [
    {"role": "system", "content": "contratto Model 1 versionato"},
    {"role": "user", "content": "sorgente, richiesta e diagnostico"},
    {"role": "assistant", "content": "patch e spiegazione richiesta"}
  ],
  "metis": {
    "source_commit": "...",
    "language_version": "...",
    "paths": ["..."],
    "symbols": ["..."]
  },
  "provenance": {
    "parents": ["source_asset_id:..."],
    "generator": "mutation-rule/...",
    "generator_version": "...",
    "leakage_group": "..."
  },
  "oracles": {
    "parse": "pass",
    "link": "pass",
    "validate": "pass",
    "compile": "pass",
    "semantic": "pass"
  },
  "sensitivity": "internal",
  "split": "train"
}
```

Nel formato effettivo di training, la loss si applica soltanto alla completion
assistant (`train_on_completions`); prompt, sorgenti e diagnostici non sono target
da imitare.

## 6. Pipeline di costruzione

Ordine obbligatorio:

1. congelare il benchmark e i suoi leakage group;
2. censire sorgenti, versioni, licenze e sensibilità;
3. costruire il provenance graph;
4. assegnare gruppi a train/dev/test prima delle derivazioni;
5. generare esempi soltanto dentro il proprio gruppo;
6. eseguire formatter e oracle;
7. rifiutare esempi ambigui o privi di prova;
8. deduplicare per testo, struttura e antenato semantico;
9. bilanciare per task, costrutto, difficoltà e dimensione;
10. materializzare JSONL e manifest immutabili con checksum.

Il generatore non deve leggere il benchmark frozen per “migliorare la copertura”:
una lacuna scoperta nel benchmark viene registrata per il ciclo successivo.

Per un aggiornamento Metis, gli esempi nuovi o migrati dichiarano il nuovo
commit e gli oracle target. Il replay del precedente adapter può usare soltanto
gruppi già autorizzati per train, dev o internal test e non può condividere
antenati con il maintenance benchmark. Benchmark, split, provenance e manifest
della candidate precedente restano immutabili.

## 7. Split anti-leakage

Lo split casuale per file è vietato. La concentrazione di 176 property e il riuso
di preset, endpoint, simboli e template renderebbero il punteggio ingannevole.

I gruppi includono almeno:

- famiglia strutturale/template;
- dipendenza o libreria condivisa;
- endpoint/property family;
- simboli distintivi;
- sorgente e tutti i derivati AST/IR/census/golden;
- commit/provenienza temporale per gli esempi storici;
- mutazioni e fix generati dallo stesso originale.

**PROPOSTO —** quattro partizioni:

| Partizione | Scopo | Regola |
|---|---|---|
| train | ottimizzazione dei pesi | nessun antenato del benchmark |
| dev | early stopping e sweep | gruppi distinti dal train |
| internal test | scelta finale del checkpoint | non usato per tuning manuale |
| frozen benchmark | verdetto di promozione | famiglie intere held-out e accesso controllato |

Una distribuzione indicativa train/dev/internal-test di 75/12,5/12,5 per gruppi è
un punto di partenza, non un vincolo superiore alla copertura. Il frozen benchmark
è separato e non deriva da quella percentuale.

## 8. Volumi proposti

Il numero di esempi non è una metrica di qualità. Per rendere però eseguibile il
piano:

- W5-XS first-value: 12 task diagnostici; soltanto se B fallisce, 24 task di
  valutazione accoppiata, 64 esempi train e 16 dev accepted-by-oracle, con cap
  assoluto e fisso di 80;
- benchmark frozen v1: esattamente 600 task preregistrati, con denominatori
  pubblicati per famiglia e difficoltà e almeno 563 gruppi di leakage realmente
  distinti per sostenere il claim Wilson al 99%;
- pilot di promotion Accuracy-99: 3.000-8.000 esempi accettati dagli oracle;
- candidate v1: 10.000-25.000 esempi soltanto se il pilot dimostra valore e la
  crescita aggiunge gruppi/trasformazioni, non duplicati cosmetici;
- preference pairs: aggiunta successiva, se l'errore dominante è la scelta fra
  output validi ma non canonici.

Il volume W5-XS è ratificato come cap di ricerca, non come garanzia di qualità.
I volumi di promotion e candidate restano **PROPOSTI**. Il denominatore
benchmark è invece preregistrato; coverage matrix e gruppi di leakage unici
prevalgono sempre sul conteggio grezzo.

## 9. Quality gate del dataset

Prima del training:

- 100% degli esempi ha source/provenance e split manifest;
- 100% degli output positivi supera gli oracle dichiarati applicabili;
- 0 parent condivisi fra train e frozen benchmark;
- 0 segreti, `.env`, credenziali o raw production payload;
- 0 sintassi storica non etichettata come legacy/migration;
- duplicate rate testuale e strutturale riportato con denominatore;
- distribuzione per famiglia, costrutto, lunghezza e difficoltà allegata;
- audit manuale frontier su un campione stratificato e su tutti i casi ad alto
  impatto semantico.

Ogni violazione di leakage invalida lo score associato: non si corregge soltanto
il report a posteriori.

## 10. Dati sintetici e negativi

I dati sintetici sono ammessi quando la trasformazione è deterministica e
versionata. Devono essere preferibilmente “plausibili ma sbagliati”:

- chosen/rejected fra forma canonica e forma valida ma degradata;
- errore che il compilatore diagnostica in modo specifico;
- errore semanticamente errato ma compiler-clean con oracle dedicato;
- patch troppo ampia rispetto a patch minimale;
- simbolo inventato rispetto a simbolo risolto dal contesto.

Un generatore LLM non può autocertificare il proprio output. Il suo risultato è
soltanto un candidato finché non passa oracle e provenance audit.
