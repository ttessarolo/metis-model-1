# Riproducibilità e governance

## 1. Principio

Un adapter valido ma non attribuibile o non ricostruibile non è un Model 1
promuovibile. Riproducibilità, sicurezza e licenze sono gate di prodotto.

## 2. Artefatti obbligatori

Per ogni candidate:

- `run-manifest.json` — identità completa del run;
- `environment.lock` — Python e dipendenze pin;
- `training-config.yaml` — config senza default impliciti;
- `dataset-manifest.jsonl` — example ID, provenance, split, sensitivity;
- `split-manifest.json` — leakage groups e regole;
- `adapter/` nell'artifact store, con checksum;
- `model-card.md` — scopo, base, metriche, limiti e uso previsto;
- `data-card.md` — origine, trasformazioni, copertura, sensibilità e licenze;
- `evaluation-report.md` — A/B/C/D, denominatori e failure case;
- `contamination-report.md` — audit testuale, strutturale e genealogico;
- `licenses/` — Apache-2.0 upstream e notice/attribuzioni applicabili;
- `reproduce.md` — comandi verificati e requisiti hardware.

Il Git repository conserva manifest, config, card, report e checksum. Dataset,
base weights, checkpoint optimizer e adapter restano fuori da Git.

## 3. Run manifest minimo

```json
{
  "run_id": "metis-model-1/...",
  "base_model": {
    "id": "Qwen/Qwen3.8-27B",
    "revision": "1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0"
  },
  "mlx_checkpoint": {
    "id": "mlx-community/Qwen3.8-27B-4bit",
    "revision": "3e6447f082e89cc7f0bc6e5441afd38dfce760ff"
  },
  "software": {
    "python": "PINNED",
    "mlx": "PINNED",
    "mlx_vlm": "PINNED"
  },
  "metis": {
    "repository": "ttessarolo/metis",
    "commit": "PINNED",
    "language_version": "PINNED"
  },
  "dataset_manifest_sha256": "...",
  "split_manifest_sha256": "...",
  "training_config_sha256": "...",
  "seed": 0,
  "hardware_class": "Apple M3 Max / 128 GB",
  "status": "candidate"
}
```

Nessun campo `PINNED` può restare tale in un run reale.

## 4. Sensibilità e confini dei dati

Classi proposte:

| Classe | Esempio | Uso |
|---|---|---|
| public | grammatica/tool pubblico, documentazione pubblica, upstream model card | secondo licenza |
| internal | sorgenti Metis proprietari approvati per training locale | ambiente autorizzato soltanto |
| restricted | payload, dati tenant o evidence con contenuto operativo sensibile | esclusi salvo processo dedicato |
| prohibited | credenziali, token, `.env`, private key, secret, raw production payload | mai nel dataset o nei log |

Default per il corpus tenant: `internal` finché un'autorità esplicita non stabilisce
altro.

## 5. Confine credenziali

- nessun agente o script legge o trasporta secret;
- `.env` e archivi equivalenti sono intoccabili;
- niente token in prompt, argv, env globale, log, report, Git o URL;
- download pubblici senza autenticazione quando possibile;
- eventuale autenticazione futura usa setup umano no-echo e capability broker;
- telemetry e stack trace passano sentinel/redazione prima di diventare evidence;
- nessuna chiamata live ARES è necessaria per costruire Model 1.

## 6. Licenze e attribuzione

**VERIFICATO —** `Qwen/Qwen3.8-27B` dichiara licenza Apache-2.0.

Prima della distribuzione:

- conservare LICENSE e attribution upstream;
- verificare la licenza e i termini del checkpoint convertito;
- classificare separatamente diritti sui sorgenti Metis e sui derivati;
- descrivere nel model card che l'artefatto è un adapter derivato;
- non assumere che la licenza permissiva del base model renda distribuibile il
  dataset proprietario o il suo adapter;
- eseguire una review legale/organizzativa prima di ogni distribuzione esterna.

## 7. Politica di distribuzione

Default: **local-only, internal-only, adapter separato**.

Richiedono una decisione separata:

- upload del dataset a un provider;
- pubblicazione dell'adapter;
- fusione adapter+base;
- packaging Ollama o altra redistribuzione;
- uso su codice o tenant non inclusi nell'autorizzazione iniziale;
- uso come agente con capacità di scrittura autonoma.

## 8. Reproducibility gate

Un secondo run, sullo stesso hardware class o su una classe dichiarata
equivalente, deve:

- ricostruire l'ambiente dal lock;
- risolvere gli stessi input per revision e checksum;
- produrre un adapter caricabile;
- ottenere metriche entro tolleranze predefinite;
- non richiedere file locali non dichiarati;
- produrre lo stesso provenance e contamination verdict.

La tolleranza non si decide dopo aver visto la divergenza.

## 9. Retention e cancellazione

Proposta:

- base model: cache ricostruibile, non artefatto unico;
- dataset frozen: retention secondo policy interna, checksum in Git;
- checkpoint intermedi: retention limitata ai finalisti e ai failure diagnostici;
- adapter promoted/rejected: conservati con card e motivazione;
- log raw: retention breve, poi report redatto;
- benchmark frozen: accesso ristretto e versionato.

Le cancellazioni materiali devono essere autorizzate e registrate; i checksum in
Git non devono consentire di ricostruire contenuto sensibile.

## 10. Audit trail

Ogni promozione collega:

```text
decisione -> benchmark version -> dataset/split -> run -> adapter
           -> evaluation -> contamination -> governance approval
```

Se un anello manca, lo stato massimo è `candidate`, mai `promoted`.
