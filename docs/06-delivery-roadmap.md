# Roadmap di delivery

## 1. Strategia

Il lavoro procede per wave con exit gate espliciti. Le attività meccaniche
(censimenti, materializzazione, dedup, run ripetitivi) possono essere delegate;
architettura, semantica, leakage, gate adversarial e promotion verdict restano a
revisione frontier.

## 2. Wave e dipendenze

Il percorso di primo valore precede e non dipende dalla promotion:

| Wave | Obiettivo | Dipende da | Exit principale |
|---|---|---|---|
| XS0 | Contratto first-value | W0, W4 | `XS_CONTRACT_VALID` |
| XS1 | Baseline B | XS0 | `MODEL1_USABLE_LOCAL_NO_TRAIN` oppure failure taxonomy |
| XS2 | Micro-dataset F-1/F-2/F-3 | XS1 fallita | 64 train + 16 dev oracle-clean |
| XS3 | Micro-QLoRA | XS2 + mandato esplicito | adapter rank-8, massimo 100 step |
| XS4 | Verdetto B/D | XS3 | `MODEL1_USABLE_LOCAL_WITH_ADAPTER` oppure stop |

Queste wave qualificano soltanto `MODEL1_USABLE_LOCAL`. Le wave W1-W9 seguenti
governano invece candidate, promotion e manutenzione:

| Wave | Obiettivo | Dipende da | Exit principale |
|---|---|---|---|
| W0 | Contratto e repository | — | piano ratificato, fonti e scope fissati |
| W1 | Frozen benchmark | W0 | task, oracle, leakage group e checksum sigillati |
| W2 | Corpus/provenance census | W0 | manifest sorgenti completo e sensitivity review |
| W3 | Dataset builder v0 | W1, W2 | pilot dataset oracle-clean e contamination-clean |
| W4 | Qwen3.8 MLX qualification | W0 | 600+ iterazioni, save/reload/resume, memoria stabile |
| W5 | Pilot QLoRA promotion-scale | W3, W4, uplift XS4 | miglioramento dev e nessuna regressione bloccante |
| W6 | Adversarial/internal test | W5 | failure taxonomy, checkpoint finalista, no leakage |
| W7 | Candidate Model 1 | W6 | report A/B/C/D e gate proposti soddisfatti |
| W8 | Packaging locale | W7 | adapter disattivabile, manifest/card/runbook completi |
| W9 | Manutenzione | W8 | policy di aggiornamento Metis/Qwen e drift monitoring |

W1 e W2 possono avanzare in parallelo dopo W0, ma la generazione W3 aspetta
l'assegnazione dei leakage group. W4 può avanzare in parallelo a W1-W3 perché usa
un micro-dataset non sensibile e non decide la semantica del benchmark.

## 3. Deliverable per wave

### W0 — Foundation

- decision log D-001…D-013;
- source/model revision manifest;
- repository structure e policy artifact;
- open decision register.

### W1 — Benchmark

- benchmark specification;
- 600 task preregistrati e almeno 563 gruppi genealogici distinti per il claim
  di popolazione al 99%;
- oracle registry;
- held-out family map;
- sealed checksum e access policy;
- evaluator capace di A/B/C/D.

### W2 — Corpus e provenance

- census riproducibile;
- data source registry;
- sensitivity/license classification;
- provenance DAG;
- gruppi strutturali e temporali;
- report di costrutti rari e lacune.

### W3 — Builder

- generatori deterministici versionati;
- mutation library plausibile;
- formatter/oracle harness;
- dedup testuale, AST e genealogico;
- JSONL serializer aderente alla versione MLX-VLM pin;
- data/split manifest e data card v0.

### W4 — Bounded technical qualification (completed)

- environment lock;
- 600+ iteration report;
- memory curve;
- adapter save/reload and full-state resume evidence;
- technical verdict `TECHNICALLY_QUALIFIED|BLOCKED`.

The 30-50-task Metis smoke evaluation is not part of O-004 runtime
ratification. Together with a sealed W1 slice, it is a pre-W5 entry gate and
remains open.

### W5 — Pilot di promotion

- pre-entry: sealed W1 slice and 30-50-task Metis smoke evaluation;
- sweep config e seed;
- dev scorecard;
- curve qualità/costo;
- failure taxonomy;
- decisione sulla crescita del dataset.

### W6-W7 — Candidate e promotion

- candidate immutable manifest;
- internal test report;
- A/B/C/D frozen benchmark;
- contamination e regression audit;
- frontier adversarial review;
- `PROMOTE|REWORK|REJECT`.

### W8 — Packaging

- Metis Companion installabile su macOS per sviluppo e demo;
- acquisizione e verifica separate di base model e adapter;
- runtime MLX/MLX-VLM Mac qualificato sul contratto semantico;
- API locale versionata e autenticata;
- estensione Metis VS Code per author/edit/repair/review/migrate;
- fallback remoto/tool-based esplicito, policy-controlled e auditabile;
- launcher locale con adapter on/off;
- context/compile loop fail-closed;
- model/data card;
- operator runbook;
- rollback test;
- nessuna write autonoma abilitata per default.

## 4. Definition of done

`MODEL1_USABLE_LOCAL` è done quando B supera il gate XS1 oppure D supera B nel
gate XS4, il sistema locale è riproducibile nel perimetro dichiarato e nessun
veto critico è aperto. `NO_TRAIN` è una chiusura valida.

`ACCURACY99_PROMOTED` è done soltanto quando:

1. il candidate è riproducibile e attribuibile;
2. il benchmark è contamination-clean;
3. D supera B secondo i gate ratificati;
4. C supera A abbastanza da sostenere il claim “nativo”;
5. semantica held-out, repair e minimalità passano;
6. nessun identificatore inventato viene accettato come valido;
7. adapter off ripristina la base;
8. governance e licenze sono chiuse per l'uso previsto;
9. failure mode e limiti sono documentati;
10. un operatore può installare, verificare e fare rollback dal runbook.

Un run verde non equivale a un prodotto done se mancano benchmark, provenance o
packaging.

## 5. Stop/rollback decision tree

```text
Qwen3.8 non supera qualification?
  -> blocca W5; correggi compatibilità/version pin, non cambiare famiglia in silenzio

Dataset contaminato?
  -> invalida gli score; ricostruisci split e derivati

Pilot non supera base+context?
  -> ferma scaling; analizza task mix, target e qualità degli esempi

Compile migliora, semantica no?
  -> REWORK; ampliare oracle e negativi semanticamente difficili

Regressione generale oltre soglia?
  -> restringi adapter/scope o REJECT

Gate superati ma artefatti non riproducibili?
  -> resta candidate; nessuna promotion
```

## 6. Decisioni e stato

Stato corrente e deadline delle decisioni non ancora ratificate:

| ID | Decisione | Stato / deadline |
|---|---|---|
| O-001 | linguaggio/versione Metis canonica per v1 | RATIFICATA: `0.43` |
| O-002 | famiglie held-out e criticità per famiglia | RATIFICATA; slice ancora da sigillare |
| O-003 | soglie numeriche finali e tolleranze statistiche | prima del W5 di promotion; non blocca W5-XS |
| O-004 | versione `mlx`/`mlx-vlm` pin | RATIFICATA: `0.32.1` / `0.6.15` |
| O-005 | rank/alpha/LR/seed grid | RATIFICATA: 4 config, 700 step max |
| O-006 | formato artifact store locale | RATIFICATA: local-only, atomico, cap 40 GiB |
| O-007 | adapter unico multi-task o adapter separati | dopo il pilot W5 |
| O-008 | protocollo Companion/VS Code e autenticazione locale Mac | prima di W8 |
| O-009 | policy di distribuzione oltre local-only | dopo W7, con review dedicata |
| O-010 | percorso di manutenzione per modifiche Metis | RATIFICATA prima della prima promotion W7; applicata in W9 |
| O-011 | split baseline-first / Accuracy-99 | RATIFICATA: W5-XS separato dalla promotion |

## 7. Backlog eseguibile corrente

Il percorso critico unico per il primo valore è ora:

1. eseguire 12 task B, quattro per F-1/F-2/F-3;
2. chiudere `NO_TRAIN` se B raggiunge il gate XS1;
3. altrimenti congelare ed eseguire B su 24 task distinti da train/dev, chiudendo
   `NO_TRAIN` a `22/24` senza critical failure;
4. solo sotto quella soglia, produrre esattamente 64 train + 16 dev
   failure-driven e oracle-clean;
5. eseguire un solo rank-8 fino a 100 step;
6. confrontare B/D e terminare comunque entro cinque giorni, senza una seconda
   configurazione o rework.

Phase B privilegiata, receipt production-grade, review `201/201`, F-4/F-5/F-6,
benchmark 600/563, O-003, grid e multi-seed non sono cancellati: costituiscono
il backlog separato `ACCURACY99_PROMOTION`. Non bloccano XS0-XS4 e non ricevono
claim di chiusura dal relativo esito.

### Stato corrente della wave grammar + standard library

La chiusura D18 è `NO_RETRAIN`. T30-v1 è stato consumato una sola volta con
`30/30` output base e `30/30` adapter e resta immutabilmente
`GRAMMAR_STDLIB_T30_DIAGNOSE`: entrambi ottengono `10/20` sui gate automatici,
senza regressioni accoppiate. Il risultato non è un'accuracy utilizzabile:
F1 confrontava authoring libero con identificatori e letterali non dichiarati;
F4/F6 richiedevano una serializzazione AST/stdlib non esposta al modello e
classificavano alias legittimi come simboli inventati. F2/F3, determinati, sono
`10/10`. Il manifest diagnostico è pubblicato con self-hash
`sha256:e6e4d4d015c8086203c81a69800a3a14c136c01d3c66304d99df74b84349f0ac`;
non viene rescored né promosso retroattivamente.

Il percorso attivo è un T30-v2 interamente fresco, ancora `30=5x6`, che espone
prima dell'output il contratto JSON completo e rende deterministici i task di
authoring. Oltre ai dieci top-level della grammatica, v2 gatizza esplicitamente
i tre moduli standard-library, i dodici membri, `time.timezone` e le interazioni
fra capability ambient, funzioni pure, namespace e `needs`. Si prova l'adapter
esistente con una sola coppia base/adapter; training e delta QLoRA si aprono
soltanto se fallimenti genuini superano la soglia già ratificata.

Il truth v2 è fissato dal toolchain pinned a `30/30` task distinti, zero gap e
cinque task per famiglia, self-hash
`sha256:3c4139c0d763e131be7c18332af2c5a8dd847865db4097e1b98c53823647f216`.
Include anche la serializzazione strutturale delle quattro forme di dominio
catalogo, compreso l'inline minuscolo con sola taglia. Non esiste ancora un
freeze v2 né output di modello: pubblicazione del preimage e sigillo restano i
prossimi gate obbligatori.

Il mandato corrente autorizza costruzione, sigillo e inferenza locale T30-v2.
Nuovi download, privilegi, live ARES, upload di payload e promotion restano
esclusi; il repository Metis esterno resta strettamente read-only.

## 8. Aggiornamento continuo

Una nuova revisione Metis non sovrascrive un Model 1 o il suo benchmark. Ogni
candidate resta riproducibile contro i propri commit, manifest e receipt;
l'aggiornamento apre una candidate successiva e conserva l'adapter precedente
come rollback.

**Metodo Orchestra permanente.** Ogni aggiornamento mantiene un unico
coordinator frontier responsabile di architettura, semantica, leakage, gate e
verdetto. Le lane interne ricevono roster disgiunti e riportano risultati già
ricontrollati. Kimi e Qwen esterni non appartengono al percorso critico corrente
e non vengono attesi o invocati senza una nuova istruzione esplicita. Evidenze,
STOP e aritmetica di copertura vengono depositati subito nelle lavagne
condivise; il coordinator ispeziona i diff, riesegue i gate rilevanti e
ricomputa almeno una claim prima di accettare una consegna. Capacità del team non
equivale ad autorizzazione per training, download, privilegi, promotion o
pubblicazione.

**Percorso minimo per default.** Per una modifica grammaticale limitata, il
coordinator:

1. fissa il nuovo commit Metis e misura il diff di grammatica, validator,
   compiler, IR e oracle;
2. aggiorna retrieval e contesto correnti, quindi classifica esempi, costrutti,
   famiglie e leakage group interessati;
3. rigenera gli oracle applicabili e sigilla un maintenance benchmark versionato
   sul nuovo commit, prima di creare esempi di training derivati;
4. valuta l'adapter precedente con retrieval aggiornato sul maintenance benchmark
   e su un replay stabile non derivato da alcun benchmark frozen;
5. pubblica `NO_RETRAIN` se i gate applicabili restano soddisfatti senza
   regressioni semantiche o critiche;
6. altrimenti esegue soltanto un delta QLoRA dal precedente adapter, con esempi
   nuovi o migrati accepted-by-oracle e un piccolo replay stabile; la selezione
   usa dev, non il maintenance benchmark;
7. ripete valutazione e gate di regressione, poi pubblica un nuovo adapter
   versionato con manifest, hash, receipt e rollback all'adapter precedente.

L'escalation a `FULL_SUCCESSOR` è richiesta soltanto se il diff modifica il
contratto AST/IR o il significato verificato dagli oracle, oppure se retrieval
aggiornato e delta QLoRA falliscono i gate semantici o il replay stabile. Il
numero di file o righe modificate è una misura di impatto, non una scorciatoia
per promuovere o scalare il training.

Il benchmark precedente non viene riscritto né usato per tuning: mantiene il
claim storico sul proprio commit. Il maintenance benchmark è una nuova versione
con denominatori, provenance, leakage policy e limiti dichiarati; non estende
automaticamente il claim della versione precedente.

Una nuova revisione Qwen, MLX o MLX-VLM richiede inoltre le rispettive
qualification e pin: nessun floating `latest`.

Il supporto Windows non appartiene al percorso W8 della demo e non costituisce
un gate corrente. Potrà essere pianificato separatamente dopo l'approvazione del
progetto.
