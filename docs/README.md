# Piano di Metis Model 1

Stato del piano: **adapter locale `INITIAL_LOCAL_QLORA_V1` consegnato; gate
accuracy catalog-domain della demo Mac attivo con truth pre-output fissata;
direzione Mac Companion/VS Code ratificata ma non implementata — 25 agosto
2026**.

Questo indice è il contratto di navigazione del progetto. I documenti distinguono
sempre quattro livelli epistemici:

- **VERIFICATO** — osservato direttamente nel checkout o in una fonte primaria,
  con data e riferimento;
- **DECISO** — scelta già ratificata per Model 1;
- **PROPOSTO** — default operativo da confermare con una misura o una decisione;
- **DA VERIFICARE** — rischio o compatibilità che non può essere presentato come
  fatto acquisito.

## Documenti

1. [`00-charter-and-decisions.md`](00-charter-and-decisions.md) — obiettivo,
   perimetro, decisioni fondative e definizione di successo.
2. [`01-architecture.md`](01-architecture.md) — architettura del sistema locale,
   confini fra pesi, contesto e compilatore, ciclo di inferenza.
3. [`02-dataset-and-provenance.md`](02-dataset-and-provenance.md) — costruzione
   del dataset, famiglie di task, provenienza, deduplicazione e split anti-leakage.
4. [`03-evaluation-and-gates.md`](03-evaluation-and-gates.md) — benchmark,
   baseline A/B/C/D, metriche semantiche, soglie e stop rule.
5. [`04-training-runbook.md`](04-training-runbook.md) — qualificazione di
   Qwen3.8 su MLX-VLM, QLoRA pilota, training completo, checkpoint e rollback.
6. [`05-reproducibility-and-governance.md`](05-reproducibility-and-governance.md)
   — identità degli artefatti, sicurezza, licenze, data/model card e distribuzione.
7. [`06-delivery-roadmap.md`](06-delivery-roadmap.md) — ordine delle wave,
   dipendenze, exit criteria, deliverable e decisioni ancora aperte.
8. [`07-evidence-and-sources.md`](07-evidence-and-sources.md) — snapshot locale,
   comandi di grounding, fonti primarie e limiti dell'evidenza corrente.
9. [`08-orchestration-and-blackboards.md`](08-orchestration-and-blackboards.md)
   — modello frontier/delega/controllo, lane, lavagne e seam gate.
10. [`09-repository-and-artifact-policy.md`](09-repository-and-artifact-policy.md)
    — struttura canonica, confine Git, identità e stati degli artefatti.
11. [`10-open-decisions.md`](10-open-decisions.md) — vista umana del registro
    machine-readable delle decisioni e dei blocchi per wave.
12. [`11-feasibility-and-risks.md`](11-feasibility-and-risks.md) — verdetto
    condizionato, stima, rischi e prossima evidence che cambia la stima.
13. [`12-accuracy-99-execution-plan.md`](12-accuracy-99-execution-plan.md) —
    metrica preregistrata, sequenza esecutiva e stato dei gate verso il 99%.
14. [`13-protected-execution-broker.md`](13-protected-execution-broker.md) —
    disegno accettato del broker protetto, confine Phase A/Phase B e nonclaim.
15. [`14-w1-w2-evidence-package.md`](14-w1-w2-evidence-package.md) — sidecar
    fail-closed, denominatori correnti e gate per il seal W1/W2.
16. [`15-first-value-experiment.md`](15-first-value-experiment.md) — percorso
    baseline-first, dataset minimo, micro-QLoRA, tempi e stop rule W5-XS.
17. [`16-accuracy-wave-catalog-domain-maintenance.md`](16-accuracy-wave-catalog-domain-maintenance.md)
    — manutenzione della superficie cataloghi e policy `NO_RETRAIN`/delta.
18. [`17-catalog-prompt-cure-successor.md`](17-catalog-prompt-cure-successor.md)
    — cura prompt cataloghi e relativo confine diagnostico.
19. [`18-initial-local-qlora.md`](18-initial-local-qlora.md) — contratto ed
    evidenze della prima QLoRA locale consegnata.
20. [`19-local-companion-and-vscode-direction.md`](19-local-companion-and-vscode-direction.md)
    — direzione della demo Mac con app/server locale ed estensione Metis VS Code.
21. [`20-demo-accuracy-closure.md`](20-demo-accuracy-closure.md) — gate fresco e
    paired base/adapter per l'accuracy catalog-domain circoscritta della demo
    Mac.

## Tesi operativa

“Imparare Metis nativamente” non significa comprimere nei pesi ogni dettaglio
mutevole del repository. Significa far apprendere al modello:

- grammatica e forme canoniche del DSL;
- trasformazione da intento a codice Metis;
- comportamento corretto di editing, repair e review;
- uso disciplinato dei diagnostici del compilatore;
- rifiuto dell'invenzione di simboli non disponibili.

I simboli e le decisioni che cambiano nel tempo restano nel checkout corrente o
nel retrieval; parser, linker, validator, compiler e controlli di parità restano
l'autorità eseguibile. La formula di Model 1 è quindi:

> **Qwen3.8-27B + adapter Metis soltanto se utile + contesto corrente + ciclo
> compiler/diagnostic/fix**

## Cosa non dichiara lo stato corrente

Questo repository, allo stato corrente, non dichiara che:

- l'adapter locale consegnato costituisca una promotion Accuracy-99;
- esistano già Companion, API locale o integrazione VS Code;
- il supporto Windows faccia parte della demo corrente;
- il backup S3 sia un canale autorizzato di distribuzione ai client;
- `EXPERIMENT_PLAN_READY` autorizzi inferenza, dataset o training;
- la qualifica sintetica batch-1 / sequence-128 e i probe delimitati a 1.024
  token si estendano automaticamente a 2.048 token o ad altre configurazioni;
- le soglie proposte siano state raggiunte;
- un output compiler-clean sia semanticamente equivalente all'intento;
- dataset o adapter possano essere distribuiti fuori dal perimetro autorizzato;
- un fallback remoto possa ricevere codice o dati senza policy e consenso.

Questi claim diventano veri solo attraverso gli evidence gate descritti nei
documenti successivi.

Il percorso tecnico W4 delimitato è invece verificato nel
[`W4-QUALIFICATION.md`](../orchestra/runs/2026-08-20-w1-w4-entry/W4-QUALIFICATION.md).
