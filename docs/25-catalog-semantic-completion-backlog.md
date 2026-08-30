# Chiusura semantica dei cataloghi `play-demo`

Stato: **`SEMANTIC_CATALOG_READY`**.

Data di riferimento: 29 agosto 2026.

Autorità tenant: `play-demo/main@bef4071d3dc21198b7f68617e2ec9bef77d037c7`.

La coda semantica del tenant corrente è chiusa: tutti i cataloghi e tutti i
campi dichiarati hanno una descrizione reviewed, i domini hanno una
disposizione esplicita e i valori editoriali restano posseduti dal catalogo
canonico. Questo gate non equivale alla prova end-to-end di Metis Brain, del
compilatore in sessione o della UI della demo.

## 1. Denominatore globale

Il checkout contiene cinque cataloghi:

| Catalogo | Field node | Stato | Disposizione dominio |
|---|---:|---|---|
| `play-demo.video` | 113 | 113 reviewed | 49 finiti, 26 open, 38 none |
| `play-demo.users` | 19 | 19 reviewed | 19 none, inclusi 10 subfield object |
| `play-demo.video_pg` | 40 | 40 reviewed | 12 open, 18 finiti proiettati da `@video`, 10 none |
| `play-demo.smart_index` | 3 | 3 reviewed | 3 open |
| `play-demo.user_session` | 2 | 2 reviewed | 2 none |

Chiusura misurata:

- Catalog node: `in=5 out=5 distinct=5 gaps=0`, tutti reviewed;
- Field node: `in=177 out=177 distinct=177 gaps=0`, tutti reviewed;
- stati campo: `reviewed=177 draft=0 unannotated=0`;
- domini fisici nel tenant: `inline=26 enum=23 open=41 none=87`;
- collisioni di alias campo nello stesso catalogo: `0`;
- deriva di tipo o modificatore rispetto al baseline: `0`.

I campi object di `@users` vengono contati sia come contenitore sia come
subfield. Il totale corretto è quindi 177 e non soltanto i 167 campi top-level.

## 2. Valori canonici di `@video`

`@video` resta l'unica autorità per i suoi valori editoriali:

- campi finiti: `49`;
- ValueItem: `in=1792 out=1792 distinct=1792 gaps=0`;
- stati: `reviewed=1775 draft=17 unannotated=0`;
- equivalenze fisiche esplicite: `57` concetti su `132` literal;
- alias di campo discriminativi: `59` superfici su `36` campi;
- alias di valore riusati fra campi diversi: `8`, mantenuti fail-closed.

I diciassette valori draft restano nel censimento, ma non sono autorità di
grounding. Sette sono literal `paesiorigine` con serializzazione `val ... val`:
restano visibili per audit, senza alias naturali, e non possono entrare nel
codice proposto. Il resolver non accetta neppure il literal tecnico esatto di
un ValueItem draft: il valore è conservato e quarantinato fino a una futura
normalizzazione che ne dimostri l'eventuale rilevanza senza esporre la codifica
di storage.

## 3. Ereditarietà semantica `@video` -> `@video_pg`

`@video_pg` è un mirror di esecuzione PostgreSQL, non una seconda ontologia.
Per questo non esiste un duplicato dei 1.792 valori e non è stato creato un
`video_pg.values.metis`.

Il tenant corrente usa il costrutto first-class `semantics from @video`: il
toolchain risolve quindi nel `describe` execution anche i domini finiti e i
ValueItem ereditati. Il roster osservato same-name è:

- source fields disponibili: `113`;
- execution fields: `in=40 out=40 distinct=40 gaps=0`;
- domini finiti execution: `18`;
- ValueItem osservati: `in=521 out=521 gaps=0`;
- stati osservati: `reviewed=514 draft=7`;
- differenze di modificatore: una sola, `genere_mcm` scalare nella fonte e
  multi nel mirror.

Il replay storico precedente al costrutto first-class è implementato in
`src/metis_model1/catalog_semantic_projection.py` e fissato dalla policy v1
`manifests/catalog-semantic-execution-play-demo-video-pg-v1.json`. Quel gate:

1. richiede tenant e soglie identici;
2. richiede che i 40 campi execution siano un sottoinsieme same-name dei 113
   campi semantici;
3. confronta tipo, nesting e modificatori;
4. consente una sola eccezione di cardinalità: `genere_mcm`, scalare in
   `@video` e multi nel mirror;
5. richiedeva una disposizione esplicita per i domini finiti che il vecchio
   scheletro execution esponeva come `none`;
6. trasferisce i ValueItem ordinati soltanto dalla fonte canonica;
7. produce un receipt standard consumabile dal percorso V2 e un secondo
   receipt che lega fonte, execution describe, policy e risultato;
8. richiede binding esterno: un self-hash isolato non è autorità;
9. conserva i draft per audit ma ne impedisce ogni risoluzione.

L'hash
`adde34cb70dee35008604ca8733151a3a75488ae0407fe78e92ccd4931f9d622`
appartiene esclusivamente al replay storico sul tenant `6d6ce2c…`: non è una
receipt della revisione corrente. Il generic join corrente rifiuta correttamente
il `describe` execution che materializza valori inline; di conseguenza la
projection receipt current è **`UNVERIFIED`**. Non è corretto aggiornare alla
cieca il manifest v1. La chiusura richiede una policy v2 esplicita per i domini
già materializzati, `finite_to_none_fields=[]`, implementazione del join e nuova
receipt riproducibile.

Prove storiche di grounding sul catalogo execution, da ripetere nel gate v2:

- `mood Romantico` -> `@video_pg.mood = "Romantico"`;
- `ultimo canale Italia 1` -> `@video_pg.last_live_channel_code = "I1"`;
- `tipologia Film` -> `@video_pg.tipologia = "Film"`;
- `title` -> lookup esatto lazy, posseduto dal retrieval engine;
- `codice canale FT` -> `unsupported`, perché `FT` è draft.

## 4. Domini aperti, tecnici e dati utente

`open` significa che il dominio è l'indice live e che il retrieval engine deve
fare lookup on-demand; non autorizza a materializzare o inventare valori.
Questa è la disposizione di `@smart_index` e dei dodici campi realmente aperti
del mirror video.

Gli identificatori, i fingerprint e le collezioni evento di `@users` e
`@user_session` restano invece `none`. Sono dati tecnici o personali da usare
soltanto nel lookup autorizzato della sessione, non domini editoriali da
enumerare, suggerire o consegnare al modello. Le descrizioni chiariscono anche
che non si possono dedurre attributi personali o demografici.

Resta una verifica privacy separata: il tenant versiona identificatori demo
mentre una sua nota descrive un confine local-only più restrittivo. Questa wave
non li ha copiati o ampliati e non maschera la discrepanza come problema
semantico.

## 5. Ambiguità tra cataloghi

Il resolver indicizza sempre per `(catalog, field)`, mai per nome globale.

- i 40 nomi condivisi fra `@video` e `@video_pg` sono un mirror intenzionale;
- `fingerprint` compare in quattro cataloghi;
- `title` compare in tre cataloghi;
- `user_id` compare in `@users` e `@user_session`;
- 25 superfici `aka` sono condivise soltanto dalle coppie mirror
  `@video`/`@video_pg`.

La sessione Brain deve conoscere il catalogo o chiedere conferma quando la
richiesta non lo rende determinabile. Non è ammessa una scelta fuzzy globale.

## 6. Invarianti verificati

Sul tenant fissato:

- parser e validator: `29` documenti, zero errori;
- runtime context prima/dopo: byte-identico,
  SHA-256 `4b238459546f087a2a7aa365b9f12ab2fca48bc9931b872042da8487cfed5f8a`;
- endpoint IR: `10/10`, stesso roster e zero drift;
- R8 Catalog/Field/ValueItem/ListEntry: verde;
- semantic surface, describe/values schema 2, sync rewrite/merge, object fields,
  KV, driver PostgreSQL `19/19` e formatter idempotente: verdi;
- test Model 1 storici della proiezione, quarantena draft, nested path, tamper e
  grounding downstream: verdi; non sostituiscono la receipt current v2 ancora
  aperta;
- gate storico alla chiusura della sola coda semantica: `make check` con
  `2188 passed, 2 skipped`, exit code zero; gli skip sono quelli già previsti
  dalla suite e non riguardano la coda semantica. I gate di integrazione Brain
  successivi sono registrati nella rispettiva lavagna attiva e non vanno
  confusi con questo denominatore storico.

## 7. Confine con i pesi e lavoro successivo

Nessun catalogo, chiave o valore è stato iniettato nei pesi di Model 1. Sono
contesto tenant-owned recuperato a runtime. Questa chiusura non richiede
retraining; un delta QLoRA resta consentito soltanto se un benchmark dimostra
un errore compatibile dei pesi dopo retrieval, grounding, compilazione e oracle
corretti.

Restano fuori da `SEMANTIC_CATALOG_READY`:

- receipt current v2 dell'ereditarietà `@video` -> `@video_pg`;
- chiusura del wiring Brain già implementato con guardia candidate, compilazione
  e prova end-to-end Visix senza Apply;
- prova end-to-end Metis Fast e fallback remoto;
- hardening operativo della demo, inclusi M6, cold start PostgreSQL e
  navigazione log/trace;
- eventuali cataloghi aggiunti da future revisioni del tenant, che entreranno
  nel denominatore solo quando realmente dichiarati.

Questi sono passi applicativi o operativi successivi. La coda semantica dei
cataloghi presenti nel tenant del commit fissato è chiusa.
