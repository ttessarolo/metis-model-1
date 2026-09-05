# Metis Brain: runbook locale Mac

Stato: **SERVER LOCALE, MODEL 1 E RETRIEVAL COLLEGATI; LA VSIX `0.24.1` CON
PARTICIPANT, PROVIDER LOCALE E APPLY ESPLICITO È INSTALLATA; IL CONTRATTO
APPLY/ROLLBACK/UNDO È VERIFICATO SU FIXTURE ISOLATO, MENTRE L'APPLY NATIVO SUL
TENANT REALE RICHIEDE ANCORA IL CONSENSO DELL'OPERATORE; NON È ANCORA L'APP MAC
DISTRIBUIBILE**.

Questa è la consegna storica della VSIX, non un'attestazione di interoperabilità
con le nuove operazioni G5. Il client esterno verificato in questa wave gestisce
ancora i chiarimenti v1: il consumer del dialogo v2 e la relativa prova live
restano da integrare. Vedere l'[handover G5](handover-g5-visix-dialogue-v2.md).

## 1. Cosa avvia

Il comando `brain-serve` avvia un processo HTTP soltanto su `127.0.0.1`, crea
un bootstrap casuale valido per quel solo avvio e serve sessioni tenant isolate.
Con la configurazione demo qualificata collega il checkpoint base e l'adapter
Model 1, il retrieval semantico schema 2, il compilatore Metis pinnato e il
Flash intent compiler Gemma 4 E4B. Model 1, Flash e le proiezioni semantiche di
tutti i tenant autorizzati vengono riscaldati prima del bind HTTP. Il warmup
Model 1 accetta solo l'operazione versionata `warmup`,
verifica checkpoint/adattatore e fa prefill del prefisso pubblico immutabile,
senza generare token utente. Se prefill, identità o timeout falliscono, health
non diventa ready e il worker parziale viene chiuso. Il server non scrive il
tenant: genera e compila una proposta che il client apre come Draft o diff.

## 2. Configurazione demo

[`examples/metis-brain-config.play-demo.local.json`](../examples/metis-brain-config.play-demo.local.json)
è la configurazione non-secret riproducibile delle demo VS Code e Metis Fast su questo Mac.
La variante [`examples/metis-brain-config.local.json`](../examples/metis-brain-config.local.json)
resta il fixture compiler-only. La configurazione demo contiene soltanto:

- address loopback e runtime ignorato sotto `artifacts/`;
- root Git Metis usata in sola lettura e binario Node pinnato, installato nella
  runtime ignorata sotto `artifacts/metis-brain-runtime/` e verificato per
  versione `v22.22.3`, dimensione `112915776` e SHA-256
  `5d9d3872911e2340a43b707962e68143de8a4e8d54628845c0c4f2de1fb7cd5c`
  prima dell'avvio;
- alias del tenant pubblico sintetico;
- path locali qualificati di checkpoint, adapter e Flash, mai i pesi dentro
  Git;
- retrieval semantico schema 2;
- grant/capability distinti ma equivalenti per i client `visix` e `metis-fast`;
- limiti di sessione e compiler.

Non inserire token, password, `.env`, credenziali AWS o path di tenant non
autorizzati. Per un tenant reale si aggiunge un alias server-side con root
canonica e `tenant_id` uguale a `[tenant].id` del suo `metis.toml`; il client
continua a inviare soltanto l'alias.

## 3. Avvio

Dal repository:

```bash
uv run metis-model1 brain-serve \
  --config /Users/tommasotessarolo/Developer/metis-model-1/examples/metis-brain-config.play-demo.local.json
```

Per la prova nativa in VS Code non serve avviare prima questo comando: la VSIX
avvia e mantiene il processo caldo alla prima richiesta `@metis`. Il workspace
locale gitignored deve dichiarare i tre setting seguenti, con percorsi canonici:

```jsonc
"metis.brain.executablePath": "/Users/tommasotessarolo/Developer/metis-model-1/.venv/bin/metis-model1",
"metis.brain.configPath": "/Users/tommasotessarolo/Developer/metis-model-1/examples/metis-brain-config.play-demo.local.json",
"metis.brain.clientId": "visix"
```

Il fixture demo lega l'alias `play-demo` alla stessa copia aperta nella VSIX,
`/Users/tommasotessarolo/metis-tenants/play-demo`; usare una seconda clone
anche se momentaneamente allineata renderebbe la base del Draft silenziosamente
stale.

Il pannello Chat nativo di VS Code risolve il modello selezionato **prima** di
invocare il callback di un Chat Participant. La VSIX `0.24.1` risolve questo
prerequisito registrando il provider locale di sola disponibilità **Metis Chat
Bridge** tramite il contratto stabile Language Model Chat Provider. Il bridge
non è Model 1, non legge né inoltra la conversazione e, se invocato
direttamente, fallisce chiuso invitando a usare `@metis`. In questo modo il
participant può avviare Brain senza Copilot; readiness e identità di Model 1
restano verificate separatamente dal server.

La prima riga stdout è un JSON redatto con host, porta effettiva e path del file
bootstrap. Non contiene il token. Il processo chiamante (in futuro l'app Mac)
legge quel file con lo stesso UID, apre la sessione, poi usa solo il token
specifico della sessione. Il bootstrap non è valido sulle route di sessione.

Interrompere con `Ctrl-C` o `SIGTERM`. Il server revoca sessioni, elimina
overlay/bootstrap e chiude il socket. Una sessione non usata semanticamente per
1.200 secondi viene eliminata dal reaper; status, health e errori di
protocollo/auth/schema non rinnovano il timer. Un'operazione semantica già
ammessa mantiene viva la sessione mentre è in corso e apre una nuova finestra
completa di 1.200 secondi soltanto quando termina; una richiesta lunga non può
quindi far scadere la propria sessione a metà elaborazione.

## 4. Sequenza client esatta

1. `GET /v1/health` e verifica `service=metis-brain`, `protocol=v1`.
2. Leggi il bootstrap con permesso `0600` e invia
   `POST /v1/sessions` con client ID, alias e capability richieste.
3. Conserva in memoria `session.id`, `session.token` e
   `session.context_revision`; non loggare il token.
4. Usa la revisione in ogni `context`/turno/compile. Un `STALE_CONTEXT` obbliga ad
   aprire un nuovo snapshot, non a ignorare il conflitto.
5. Con turn schema 2, rispondi alle sole domande tipizzate restituite da Brain
   usando i riferimenti opachi del server. Una risposta è monouso e resta
   legata alla stessa richiesta, sessione e revisione.
6. Tratta `compiler.status=invalid` come diagnostica da correggere; `ok` non
   prova da solo la correttezza editoriale.
7. Chiudi con `DELETE /v1/sessions/{id}` anche nel percorso di errore.

Brain non scrive file tenant. VSIX/Metis Fast mostreranno preview/diff e
applicheranno una patch soltanto dopo conferma umana e controllo CAS sul
workspace corrente.

## 5. Health e interpretazione

- `status=ready`: il servizio/session manager accetta richieste;
- `compiler_configured=true`: pin Git, runtime `node_modules` e Node sono stati
  verificati, e l'eseguibile sandbox è presente; la policy viene provata durante
  la compilazione reale;
- `compiler_executions`: compilazioni archiviate completate dall'avvio;
- `model_identity`: checkpoint/adapter locali sono configurati senza esporre
  path; nel profilo demo `model_warmup.policy=on_start`, `model_loaded=true`,
  `model_warmup.prefix_cache_ready=true` e un valore positivo e limitato di
  `model_warmup.prefix_tokens` sono prerequisiti della readiness. Il modello
  può restare non caricato soltanto in un profilo esplicitamente `lazy` o dopo
  la morte del worker;
- `intent_compiler`: il worker Flash è abilitato in modalità
  `assist_on_unresolved`, caricato prima del bind e identificato soltanto da
  revisione modello, hash schema e decoder. Non espone path, prompt o valori;
- `semantic_retrieval.enabled=true`, `schema=2`: campi e valori vengono scelti
  dal catalogo tenant pinnato, non memorizzati nei pesi;
- `semantic_retrieval.warmup.policy=on_start`, `status=ready`: le proiezioni di
  tutti i grant sono state costruite prima del bind; `tenant_count` deve
  coincidere con il numero di tenant autorizzati e `duration_ms` resta un
  intero limitato;
- `turn_schema_versions=[1,2]`: v2 abilita dialogo tipizzato e memoria volatile;
- `clarification_answer_schema_versions=[1,2]`: i client possono riprendere una
  domanda tramite la route compatta `/answer` senza reinviare il prompt;
  v1 resta il percorso legacy senza domande numeriche non rappresentabili;
- `metrics`: sessioni, turni, conversazioni e domande pendenti sono osservabili
  senza prompt, token o sorgenti.

Il flusso SSE `GET /v1/sessions/{id}/turns/{turn_id}/events` emette eventi di
fase e heartbeat con id numerici monotoni. Su riconnessione il client invia
`Last-Event-ID` con l'ultimo id ricevuto; il server riproduce soltanto eventi
successivi. Il terminal envelope resta l'autorità del risultato: heartbeat e
progress sono liveness osservabile, non prova di correttezza.

Il compiler materializza il tooling tracciato soltanto dall'archivio Git al pin.
L'unica dipendenza letta dal live root è `tooling/node_modules`: viene copiata in
temporaneo e verificata contro l'hash pinnato prima e dopo; non viene eseguita in
place. Le modifiche tracked/untracked di altri team non entrano nello snapshot.

## 6. Errori operativi principali

| Codice | Significato | Azione client |
|---|---|---|
| `BOOTSTRAP_UNAUTHORIZED` | bootstrap assente/errato/scaduto | riabbina al processo corrente |
| `SESSION_UNAVAILABLE` | sessione/token non validi o già eliminati | apri nuova sessione |
| `CAPABILITY_DENIED` | operazione fuori grant | non ritentare con privilege escalation |
| `STALE_CONTEXT` | revisione richiesta o tenant corrente cambiati | nuovo snapshot e rebase |
| `SESSION_REVOKED` | close durante operazione | scarta il risultato |
| `CLARIFICATION_PENDING` | esiste già una domanda bloccante | rispondi o chiudi la sessione |
| `CLARIFICATION_REPLAY` / `CLARIFICATION_STALE` | risposta già usata o non più legata allo snapshot | non ritentare la risposta; riapri il flusso |
| `SESSION_LIMIT` / `COMPILER_BUSY` | limite locale raggiunto | backoff delimitato |
| `CONTEXT_TOO_LARGE` / `CONTEXT_UNSUPPORTED` | oltre il contratto compiler v1 | riduci la dependency closure |
| `COMPILER_FAILED` | toolchain sandbox non eseguibile | verifica pin/runtime, non fare fallback implicito |
| `FLASH_RUNTIME_CONFIG` / `FLASH_RUNTIME_START_FAILED` | identità, pin, roster o warmup Flash non validi | non dichiarare ready; verifica manifest/runtime, senza Ollama o fallback remoto |
| `FLASH_RUNTIME_DIED` / `FLASH_RUNTIME_TIMEOUT` | worker Flash morto o oltre il timeout | scarta il tentativo; riavvia Brain se health non è ready |
| `FLASH_RESPONSE_INVALID` / `FLASH_INTENT_STALE` | IR non valido o non più legato all'identità di sessione | non usare il contenuto; riparti dal grounding corrente |
| `FLASH_INTENT_UNSUPPORTED` | logica non rappresentabile in sicurezza dal retrieval corrente | chiedi un refine o lascia il caso unsupported; non trasformare OR/negazioni in AND |
| `OUTPUT_CONTRACT_INVALID` | limite, intervallo qualificato o cardinalità non esatta | chiedi/conferma un totale esatto oppure una dimensione pagina esatta |
| `OUTPUT_CONTRACT_UNAVAILABLE` | il `take`, la sorgente o un fallback esistente non è preservabile senza ambiguità | correggi esplicitamente il contratto; Brain non lo sostituisce in silenzio |
| `Language model unavailable` prima di qualunque progresso Metis | la VSIX attiva non espone il provider locale atteso o la finestra non è stata ricaricata dopo l'installazione | verificare VSIX `0.24.1`, selezionare **Metis Chat Bridge**, ricaricare la finestra e ripetere; non modificare Brain o il tenant |

Le risposte di errore generate dall'API sono JSON e non includono header, token,
sorgenti, root, environment o diagnostica interna. Un overload di trasporto o
un errore del parser HTTP sottostante può invece chiudere la connessione senza
una risposta applicativa.

## 7. Limiti dichiarati

- Mac e IPv4 loopback soltanto;
- host cooperativo per stesso UID; Keychain/code-signing nella wave app;
- massimo 64 sorgenti workspace e 512 KiB per sorgente nel compiler pinnato;
- nessuna memoria persistente o cross-session;
- VSIX collegata in sviluppo e indipendente da Copilot tramite il provider
  locale Metis; Apply/recompile è installato e verificato su fixture, mentre il
  gesto nativo dell'operatore e Metis Fast restano gate distinti;
- nessun packaging app Mac, firma, notarizzazione, updater o fallback remoto.

La prossima wave prodotto trasforma questo server di sviluppo nel bundle
“Metis Brain” distribuibile senza cambiare il contratto di isolamento qui
consegnato.
