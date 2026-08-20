# Piano di Metis Model 1

Stato del piano: **baseline iniziale — 20 agosto 2026**.

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

> **Qwen3.8-27B + adapter Metis versionato + contesto corrente + ciclo
> compiler/diagnostic/fix**

## Cosa non dichiara questa baseline

Questo repository, allo stato iniziale, non dichiara che:

- il training sia già stato eseguito;
- Qwen3.8-27B sia già qualificato per un training MLX-VLM lungo su questa macchina;
- le soglie proposte siano state raggiunte;
- un output compiler-clean sia semanticamente equivalente all'intento;
- dataset o adapter possano essere distribuiti fuori dal perimetro autorizzato.

Questi claim diventano veri solo attraverso gli evidence gate descritti nei
documenti successivi.
