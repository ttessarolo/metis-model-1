# Roadmap di delivery

## 1. Strategia

Il lavoro procede per wave con exit gate espliciti. Le attività meccaniche
(censimenti, materializzazione, dedup, run ripetitivi) possono essere delegate;
architettura, semantica, leakage, gate adversarial e promotion verdict restano a
revisione frontier.

## 2. Wave e dipendenze

| Wave | Obiettivo | Dipende da | Exit principale |
|---|---|---|---|
| W0 | Contratto e repository | — | piano ratificato, fonti e scope fissati |
| W1 | Frozen benchmark | W0 | task, oracle, leakage group e checksum sigillati |
| W2 | Corpus/provenance census | W0 | manifest sorgenti completo e sensitivity review |
| W3 | Dataset builder v0 | W1, W2 | pilot dataset oracle-clean e contamination-clean |
| W4 | Qwen3.8 MLX qualification | W0 | 600+ iterazioni, save/reload/resume, memoria stabile |
| W5 | Pilot QLoRA | W3, W4 | miglioramento dev e nessuna regressione bloccante |
| W6 | Adversarial/internal test | W5 | failure taxonomy, checkpoint finalista, no leakage |
| W7 | Candidate Model 1 | W6 | report A/B/C/D e gate proposti soddisfatti |
| W8 | Packaging locale | W7 | adapter disattivabile, manifest/card/runbook completi |
| W9 | Manutenzione | W8 | policy di aggiornamento Metis/Qwen e drift monitoring |

W1 e W2 possono avanzare in parallelo dopo W0, ma la generazione W3 aspetta
l'assegnazione dei leakage group. W4 può avanzare in parallelo a W1-W3 perché usa
un micro-dataset non sensibile e non decide la semantica del benchmark.

## 3. Deliverable per wave

### W0 — Foundation

- decision log D-001…D-012;
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

### W5 — Pilot

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

- launcher locale con adapter on/off;
- context/compile loop fail-closed;
- model/data card;
- operator runbook;
- rollback test;
- nessuna write autonoma abilitata per default.

## 4. Definition of done complessiva

Model 1 è done quando:

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
| O-003 | soglie numeriche finali e tolleranze statistiche | prima di W5 |
| O-004 | versione `mlx`/`mlx-vlm` pin | RATIFICATA: `0.32.1` / `0.6.15` |
| O-005 | rank/alpha/LR/seed grid | RATIFICATA: 4 config, 700 step max |
| O-006 | formato artifact store locale | RATIFICATA: local-only, atomico, cap 40 GiB |
| O-007 | adapter unico multi-task o adapter separati | dopo il pilot W5 |
| O-008 | interfaccia CLI/editor/agent | prima di W8 |
| O-009 | policy di distribuzione oltre local-only | dopo W7, con review dedicata |
| O-010 | soglia di drift che richiede un nuovo adapter | prima di W9 |

## 7. Backlog eseguibile corrente

Con W0 e il percorso tecnico W4 completati:

1. chiudere dependency graph, diritti e oracle delle 30 allocazioni W1;
2. sigillare la slice soltanto dopo l'esecuzione degli oracle task-specifici;
3. implementare i generatori W3 author/edit/repair con provenance immutabile;
4. produrre pilot dataset e contamination report senza payload proprietari in
   questo repository;
5. ratificare O-003 dai denominatori frozen e dalla varianza delle baseline;
   O-005/O-006 sono già ratificate e non bypassano i gate dati;
6. autorizzare ed eseguire W5 soltanto dopo questi gate.

## 8. Aggiornamento continuo

Una nuova versione Metis non sovrascrive Model 1. Si apre una candidate successiva
che dichiara:

- diff grammatica/validator/compiler;
- percentuale di corpus e benchmark interessata;
- esempi invalidati o migrati;
- compatibilità dell'adapter precedente;
- necessità di retrieval refresh, nuovo fine-tuning o entrambi.

Lo stesso vale per nuove revisioni Qwen o MLX: nessun floating `latest` in un
artefatto promosso.
