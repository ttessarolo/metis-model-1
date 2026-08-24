# Valutazione e gate

## 1. Regola principale

Il confronto decisivo non è “base senza contesto contro adapter con tutti gli
strumenti”. È **la stessa Qwen3.8, con lo stesso contesto e lo stesso compiler
loop, senza e con adapter**.

## 2. Matrice A/B/C/D

| Variante | Adapter Metis | Contesto corrente | Compiler loop | Domanda |
|---|---:|---:|---:|---|
| A | no | no | no | Quanto sa la base in modo spontaneo? |
| B | no | sì | sì | Quanto otteniamo con sola ingegneria di sistema? |
| C | sì | no | no | Cosa è entrato davvero nei pesi? |
| D | sì | sì | sì | Qual è il prodotto completo? |

Confronti obbligatori:

- C−A misura l'apprendimento “nativo” isolato;
- D−B misura il valore aggiunto dell'adapter nel prodotto reale;
- B−A misura il valore di retrieval e compiler loop;
- D−C misura quanto il prodotto dipende dal contesto corrente.

Prompt, sampling, reasoning mode, context budget e limiti di repair devono essere
identici nelle coppie confrontate.

## 3. Benchmark frozen

Il benchmark viene definito e checksumato prima della generazione del training
set. Deve includere:

- tutte le famiglie F-1…F-6 rilevanti;
- costrutti comuni, rari e composti;
- famiglie endpoint/template completamente held-out;
- task compiler-clean ma semanticamente errati;
- richieste impossibili o sottospecificate, dove il comportamento corretto è
  chiedere contesto o rifiutare l'invenzione;
- patch piccole e trasformazioni multi-file;
- esempi di sintassi/versione legacy chiaramente etichettati.

Ogni risultato pubblica numeratore, denominatore e intervallo di confidenza; una
percentuale aggregata senza breakdown non è evidence sufficiente.

Un maintenance benchmark per una nuova revisione Metis è distinto e versionato:
non modifica il frozen benchmark precedente e viene sigillato prima di qualsiasi
delta training. I suoi risultati qualificano soltanto la candidate e il commit
dichiarati.

Il comando integrato `validate-pilot` rigenera inoltre la closure tracciata dagli
oggetti Git della revisione Metis fissata e richiede uguaglianza esatta. La sola
coerenza interna del manifest o un asset self-hash ricalcolato non sostituiscono
questo anchor; se il checkout sorgente manca, il gate diventa invalido.

I due semafori successivi non sono intercambiabili:

- `assess-experiment` verifica soltanto che pin W4, source anchor, contratto
  W5-XS e confine repository siano coerenti. `EXPERIMENT_PLAN_READY` non è
  execution authority e porta i nonclaim
  `nonpromotable` e `non99`;
- `assess-w5` resta il gate rigoroso `ACCURACY99_PROMOTION`. Termina non-zero
  sugli stessi cinque blocker: popolazione indipendente, oracle W1 non sigillati,
  W3 reale assente, O-003 aperta e baseline A/B assente.

Il primo ignora deliberatamente 563 gruppi, Phase B, F-4/F-5/F-6 e O-003 perché
misura la necessità del tuning; non li dichiara chiusi.

## 4. Metriche

### Validità first-shot

- parser pass rate;
- linker pass rate;
- validator clean rate;
- compile-clean rate.

Ogni stadio ha come denominatore tutti i task ai quali è applicabile, non soltanto
quelli sopravvissuti allo stadio precedente. Si può aggiungere una metrica
condizionata, purché sia etichettata.

### Correttezza semantica

- exact semantic diff per task deterministici;
- equivalenza IR normalizzata;
- invarianti/parità specifici del dominio;
- preservazione delle sezioni non coinvolte;
- adjudication umana blind per i casi non completamente automatizzabili.

Compiler-clean è un prerequisito, mai un sostituto di queste metriche.

### Editing quality

- patch minimality: linee/tokens modificati oltre il necessario;
- unrelated-change rate;
- formatter churn;
- precision/recall delle regioni attese.

### Repair

- successo al primo fix;
- successo entro due cicli;
- numero medio e distribuzione dei cicli;
- regressioni introdotte dal fix;
- casi terminati per budget.

### Grounding e simboli

- unknown-symbol generation rate;
- invented-identifier accepted rate;
- richiesta corretta di contesto quando il simbolo non è risolvibile;
- attribution del file/simbolo usato.

La soglia zero riguarda identificatori inventati **accettati come risultato
valido dal sistema**. Gli output grezzi vengono comunque misurati per capire se
l'adapter riduce l'errore invece di affidarsi sempre al filtro.

### Efficienza

- time-to-first-token e latenza totale;
- token input/output;
- memoria di picco e andamento della resident memory;
- tempo per task valido e semanticamente corretto;
- costo addizionale del repair loop.

### Regressione generale

Se Model 1 viene usato dentro un coding agent più ampio, una mini-suite congelata
misura patching, instruction following e lettura di TypeScript/Rust senza
pretendere che l'adapter diventi uno specialista di quei linguaggi.

## 5. Gate W5-XS ratificati

La baseline diagnostica B usa 12 task, quattro per F-1/F-2/F-3. L'esito è
`MODEL1_USABLE_LOCAL_NO_TRAIN` con almeno `11/12` successi semantici post-repair,
zero veto critici, zero identificatori inventati accettati e nessuna classe di
errore ricorrente.

Se B12 fallisce, B viene eseguita anche sui 24 task accoppiati congelati: con
almeno `22/24` e zero critical failure totali si chiude `NO_TRAIN`; il dataset si
apre soltanto sotto quella soglia e con almeno tre failure B12 correggibili. Se
il tuning è giustificato, l'adapter viene conservato soltanto se D ottiene
almeno tre successi netti, chiude almeno `ceil(fallimenti_semantici_B / 2)`, non
perde alcun task già verde e ha zero critical failure, identificatori inventati
accettati o modifiche estranee totali. Queste soglie sono direzionali e
qualificano soltanto W5-XS.

## 6. Soglie Accuracy-99 proposte

Queste soglie sono **PROPOSTE**, da ratificare dopo il benchmark design ma prima
di vedere il risultato finale:

| Gate | Soglia candidata |
|---|---|
| Parser first-shot su task applicabili | ≥ 95% |
| Incremento compile-clean D rispetto a B | ≥ 15 punti percentuali assoluti |
| Repair corretto entro 2 cicli | ≥ 95% |
| Correttezza semantica su famiglie held-out | ≥ 90%, senza famiglia critica < 85% |
| Identificatori inventati accettati come validi | 0 |
| Unrelated-change rate per editing | ≤ 2% dei task |
| Regressione mini-suite generale | non oltre 2 punti percentuali assoluti |
| Leakage train/frozen | 0 antenati condivisi |
| Riproducibilità | 2 run dallo stesso manifest entro tolleranza dichiarata |

Il gate principale è congiuntivo: non si compensa un fallimento semantico con un
punteggio sintattico molto alto.

## 7. Disegno statistico

- intervalli Wilson al 95% per proporzioni;
- paired bootstrap o test appaiato per B contro D sugli stessi task;
- seed multipli almeno per il pilot che decide gli iperparametri;
- macro-average per famiglia accanto al micro-average complessivo;
- report separato per difficoltà e lunghezza;
- nessuna scelta del checkpoint sulla base del frozen benchmark.

Anche con 600 task, i denominatori per famiglia di 80-110 producono intervalli
troppo larghi per un claim 99% per-famiglia: il report deve mostrarli e non
simulare precisione. Il claim preregistrato è globale; i task ad alto impatto
mantengono gate categorici indipendenti dalla significatività aggregata.

## 8. Error taxonomy

Ogni fallimento riceve una causa primaria:

1. misunderstanding dell'intento;
2. errore sintattico;
3. errore di linking/simbolo;
4. errore di validazione;
5. compile failure;
6. semantica errata ma compile-clean;
7. patch non minimale o regressiva;
8. contesto/retrieval insufficiente;
9. loop/tool failure;
10. benchmark ambiguo o oracle difettoso.

La categoria 10 non viene trasformata in errore del modello: il task è sospeso,
corretto e il cambiamento del benchmark è versionato.

## 9. Stop rule

Il ciclo si ferma e torna a diagnosi quando:

- il qualification run mostra NaN, OOM, memory/descriptor leak o impossibilità di
  save/reload/resume;
- viene scoperto leakage nel benchmark;
- D non migliora B in modo sostanziale;
- il guadagno è solo sintattico ma non semantico;
- la crescita del dataset aumenta duplicazione invece di coverage;
- la mini-suite generale regredisce oltre la soglia ratificata;
- l'identità di config, dataset o checkpoint non è ricostruibile;
- un output semanticamente errato viene classificato green solo perché compila.
- B soddisfa già il gate W5-XS o non esistono failure semantiche ripetibili;
- il micro-dataset ha yield accepted-by-oracle sotto il 50% o richiede oltre il
  20% di adjudication manuale;
- W5-XS supera 100 step, quattro ore, 110 GB Metal o 8 GiB di nuovi artefatti;
- viene tentata una seconda configurazione o una rework W5-XS.

Non si scala il numero di iterazioni per nascondere una di queste cause.

## 10. Report di promozione

Il report finale contiene:

- matrice A/B/C/D completa;
- metriche first-shot e post-repair separate;
- denominatori, confidence interval e seed;
- breakdown per famiglia/difficoltà;
- confusion/error taxonomy;
- failure case rappresentativi non cherry-picked;
- contamination audit;
- performance e memoria;
- confronto fra checkpoint candidati;
- decisione `PROMOTE`, `REWORK` o `REJECT` con motivazione.
