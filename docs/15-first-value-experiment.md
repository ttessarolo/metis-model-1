# W5-XS: esperimento first-value

Status: **RATIFICATO — 24 agosto 2026**.

## 1. Obiettivo

W5-XS risponde a una sola domanda: l'adapter Metis aggiunge valore alla stessa
Qwen3.8 che usa già contesto corrente, retrieval e compiler loop?

Il risultato corretto può essere `NO_TRAIN`. Se la variante B soddisfa il gate
di prodotto, Model 1 viene consegnato come sistema base+toolchain e non si crea
un adapter solo per rispettare il piano originario.

W5-XS è `RESEARCH_ONLY`, `LOCAL_ONLY`, `NON_PROMOTABLE` e `NON_99`. Non chiude
e non indebolisce il piano Accuracy-99.

## 2. Traguardi distinti

| Traguardo | Significato | Gate |
|---|---|---|
| `MODEL1_USABLE_LOCAL_NO_TRAIN` | B soddisfa il bisogno pratico | baseline B |
| `MODEL1_USABLE_LOCAL_WITH_ADAPTER` | D migliora B senza regressioni | confronto B/D |
| `STOP_NO_UPLIFT` | il tuning non aggiunge valore dimostrato | stop definitivo W5-XS |
| `STOP_NO_JUSTIFIED_TRAINING` | i dati non sostengono un micro-tuning affidabile | stop definitivo W5-XS |
| `STOP_TECHNICAL` | il run supera un limite o perde riproducibilità | stop definitivo W5-XS |
| `ACCURACY99_PROMOTED` | claim statistico e candidato distribuibile | piano Accuracy-99 separato |

Nessuno dei primi cinque esiti autorizza il sesto.

## 3. Sequenza chiusa

### XS0 — Contratto

- base e runtime restano quelli già pin e qualificati;
- scope iniziale limitato a F-1/F-2/F-3;
- prompt, sampling, reasoning mode, retrieval, contesto e budget di due repair
  vengono congelati prima degli output;
- `manifests/w5-xs-plan.json` è il contratto machine-readable canonico e deve
  validare insieme alla decisione O-011 ratificata;
- la wave esecutiva costruisce prima un thin batch/compiler-loop runner, congela
  l'esatto roster B12 e aggiunge le nove task/spec mancanti rispetto alle tre
  fixture riusabili; nessun risultato del modello può entrare nel roster;
- gli artefatti restano sotto `artifacts/w5-xs/` e fuori da Git;
- nessun network, download, privilegio, servizio, live ARES, credenziale,
  upload, promotion, commit o push.

Exit: `XS_CONTRACT_VALID`.

### XS1 — Baseline B diagnostica

Eseguire esattamente 12 task public-synthetic, quattro per F-1/F-2/F-3, con:

- adapter disattivato;
- contesto/retrieval corrente;
- compiler loop identico al prodotto;
- massimo due repair;
- verdetto semantico, minimalità, identificatori inventati e latenza.

Pubblicare `NO_TRAIN` quando almeno `11/12` task sono semanticamente corretti
post-repair, non esiste alcun veto critico o identificatore inventato accettato
e non esiste una classe di errore ricorrente. Questo è un gate di prodotto
direzionale, non una stima di popolazione.

Una classe è ricorrente soltanto quando la stessa `failure_category` registrata
compare su almeno due task appartenenti a parent/template group distinti. I
veto sono esattamente i sette `forbidden_critical_failures` di
`manifests/accuracy-target.json`; `require_zero_unlisted_critical_failures=true`
si applica anche qui.

Exit: `MODEL1_USABLE_LOCAL_NO_TRAIN` oppure `FAILURE_MINING_REQUIRED`.

### XS2 — Baseline B24 e micro-dataset

Soltanto dopo `FAILURE_MINING_REQUIRED`:

1. congelare 24 task di valutazione accoppiata, otto per F-1/F-2/F-3, con
   parent, template e leakage group esclusi da train/dev;
2. eseguire B24 prima di creare dati: con almeno `22/24`, zero critical failure
   totali e zero identificatori inventati accettati, pubblicare
   `MODEL1_USABLE_LOCAL_NO_TRAIN`;
3. aprire il micro-dataset soltanto con B al massimo `21/24` e almeno tre
   failure semantiche correggibili già osservate in B12; B24 fornisce solo il
   segnale binario go/no-go e i suoi dettagli non possono guidare i dati;
4. costruire esattamente 64 esempi train accepted-by-oracle: 48 guidati soltanto
   dalla taxonomy B12, senza derivare parent/template da B12 o B24, e 16 replay
   canonici;
5. costruire esattamente 16 esempi dev con parent distinti;
6. assegnare split e leakage group prima di generare derivati;
7. accettare ogni esempio soltanto con provenance, rights local-only e oracle
   semantico applicabile; compile-clean da solo non basta.

Il batch W5-XS è fisso a `64 train + 16 dev = 80` esempi, non 3.000. Train deve
contenere almeno 16 esempi per ciascuna famiglia; dev usa la distribuzione
F-1/F-2/F-3 `5/5/6`. Sono ammesse al massimo quattro derivazioni per ogni
parent/template group; i 48 esempi failure-driven richiedono quindi almeno 12
gruppi nuovi distinti. Nessun gruppo può attraversare train, dev o B24.

`candidate_count` conta ogni candidato sottoposto all'oracle una sola volta;
`manual_adjudication_count` ne conta il sottoinsieme che richiede giudizio
umano. Il percorso si ferma se `accepted_count / candidate_count < 0.50`, se
`manual_adjudication_count / candidate_count > 0.20` o se non esistono almeno
tre failure semantiche B12 correggibili su almeno due parent/template group.

Exit: `XS_DATA_READY` oppure `STOP_NO_JUSTIFIED_TRAINING`.

### XS3 — Micro-QLoRA

Una sola configurazione:

```yaml
rank: 8
alpha: 16
learning_rate: 1e-5
seed: 17
max_seq_length: 1024
batch_size: 1
gradient_accumulation_steps: 1
dropout: 0
steps: 25_then_50_then_100_if_dev_improves
```

Il run arriva inizialmente a step 25; procede a 50 soltanto se i successi
semantici dev aumentano di almeno uno rispetto ad adapter-off, e procede a 100
soltanto se aumentano ancora di almeno uno rispetto a step 25. Non è ammessa
una seconda configurazione o rework.

Budget cumulativo: massimo quattro ore, quattro checkpoint pubblicati e 8 GiB
di nuovi artefatti.
Stop immediato su NaN/Inf, OOM, picco Metal oltre 110 GB, drift di identità,
errore save/reload/resume o adapter-off non ripristinabile.

Exit: `XS_ADAPTER_CANDIDATE` oppure `STOP_TECHNICAL`.

### XS4 — Verdetto B/D

Eseguire B e D sugli stessi 24 task accoppiati congelati. Conservare l'adapter
soltanto se:

- D ottiene almeno tre successi netti più di B;
- D chiude almeno `ceil(fallimenti_semantici_B / 2)` fallimenti semantici di B;
- nessun task verde in B diventa semanticamente errato in D;
- critical failure totali, identificatori inventati accettati e modifiche
  estranee sono tutti zero in D;
- adapter-off ripristina la baseline attesa.

Un miglioramento solo sintattico è `STOP_NO_UPLIFT`. Non è ammessa una rework:
il percorso termina dopo questo singolo confronto.

## 4. Tempi e stop temporale

- decisione `NO_TRAIN`: entro uno o due giorni operativi dalla wave esecutiva,
  includendo thin runner e roster;
- primo micro-adapter e verdetto B/D: 3-5 giorni lavorativi;
- hard stop W5-XS: cinque giorni lavorativi complessivi.

Le settimane appartengono esclusivamente alla successiva certificazione
Accuracy-99, non al primo valore di prodotto.

## 5. Autorità richiesta per l'esecuzione

La ratifica di questo documento chiude il piano ma non avvia inferenza, Node,
Metis, dataset o training. Una singola wave successiva può autorizzarli insieme
con questo perimetro esatto:

> Autorizzo W5-XS local-only: inferenza sul checkpoint locale; Node/Metis
> unprivileged soltanto su public-synthetic; scrittura sotto artifacts/w5-xs;
> massimo 80 esempi; un QLoRA rank-8 fino a 100 step, quattro ore, 110 GB Metal
> e 8 GiB di nuovi artefatti. Vietati network/download, privilegi/servizi, live
> ARES/tenant/credenziali, upload, promotion, commit e push.

Prima di quel mandato, `EXPERIMENT_PLAN_READY` significa soltanto che il piano è
completo e può ricevere la wave esecutiva; non verifica il checkpoint fisico e
non autorizza baseline, dataset o training.

## 6. Relazione con Accuracy-99

Il benchmark da 600 task, i 563 gruppi indipendenti, F-4/F-5/F-6, O-003 finale,
multi-seed, broker protetto, receipt production-grade, dossier completo e
packaging W6-W8 restano invariati nel piano Accuracy-99. Entrano nel percorso
critico solo dopo un eventuale uplift W5-XS e una decisione separata di
finanziare promotion/certificazione.
