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

## 5. Soglie iniziali proposte

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

## 6. Disegno statistico

- intervalli Wilson al 95% per proporzioni;
- paired bootstrap o test appaiato per B contro D sugli stessi task;
- seed multipli almeno per il pilot che decide gli iperparametri;
- macro-average per famiglia accanto al micro-average complessivo;
- report separato per difficoltà e lunghezza;
- nessuna scelta del checkpoint sulla base del frozen benchmark.

Con 250-400 task il breakdown fine può avere intervalli larghi: il report deve
mostrarli e non simulare precisione. I task ad alto impatto possono avere gate
categorici indipendenti dalla significatività aggregata.

## 7. Error taxonomy

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

## 8. Stop rule

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

Non si scala il numero di iterazioni per nascondere una di queste cause.

## 9. Report di promozione

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
