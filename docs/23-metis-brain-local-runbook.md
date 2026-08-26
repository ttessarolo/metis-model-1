# Metis Brain: runbook locale Mac v1

Stato: **RUNBOOK DEL CORE SESSIONI/COMPILER; NON È ANCORA L'APP DISTRIBUIBILE**.

## 1. Cosa avvia

Il comando `brain-serve` avvia un processo HTTP soltanto su `127.0.0.1`, crea
un bootstrap casuale valido per quel solo avvio e serve sessioni tenant isolate.
Il processo non carica ancora Qwen/adapter: `model_loaded` resta correttamente
`false`. La route compile usa invece il toolchain Metis pinnato reale.

## 2. Configurazione demo

[`examples/metis-brain-config.local.json`](../examples/metis-brain-config.local.json)
è la configurazione non-secret riproducibile su questo Mac. Contiene soltanto:

- address loopback e runtime ignorato sotto `artifacts/`;
- root Git Metis usata in sola lettura e binario Node pinnato, installato nella
  runtime ignorata sotto `artifacts/metis-brain-runtime/` e verificato per
  versione `v22.22.3`, dimensione `112915776` e SHA-256
  `5d9d3872911e2340a43b707962e68143de8a4e8d54628845c0c4f2de1fb7cd5c`
  prima dell'avvio;
- alias del tenant pubblico sintetico;
- grant/capability per `metis-vsix` e `metis-fast`;
- limiti di sessione e compiler.

Non inserire token, password, `.env`, credenziali AWS o path di tenant non
autorizzati. Per un tenant reale si aggiunge un alias server-side con root
canonica e `tenant_id` uguale a `[tenant].id` del suo `metis.toml`; il client
continua a inviare soltanto l'alias.

## 3. Avvio

Dal repository:

```bash
uv run metis-model1 brain-serve \
  --config /Users/tommasotessarolo/Developer/metis-model-1/examples/metis-brain-config.local.json
```

La prima riga stdout è un JSON redatto con host, porta effettiva e path del file
bootstrap. Non contiene il token. Il processo chiamante (in futuro l'app Mac)
legge quel file con lo stesso UID, apre la sessione, poi usa solo il token
specifico della sessione. Il bootstrap non è valido sulle route di sessione.

Interrompere con `Ctrl-C` o `SIGTERM`. Il server revoca sessioni, elimina
overlay/bootstrap e chiude il socket. Una sessione non usata semanticamente per
1.200 secondi viene eliminata dal reaper; status, health e errori di
protocollo/auth/schema non rinnovano il timer.

## 4. Sequenza client esatta

1. `GET /v1/health` e verifica `service=metis-brain`, `protocol=v1`.
2. Leggi il bootstrap con permesso `0600` e invia
   `POST /v1/sessions` con client ID, alias e capability richieste.
3. Conserva in memoria `session.id`, `session.token` e
   `session.context_revision`; non loggare il token.
4. Usa la revisione in ogni `context`/`compile`. Un `STALE_CONTEXT` obbliga ad
   aprire un nuovo snapshot, non a ignorare il conflitto.
5. Tratta `compiler.status=invalid` come diagnostica da correggere; `ok` non
   prova da solo la correttezza editoriale.
6. Chiudi con `DELETE /v1/sessions/{id}` anche nel percorso di errore.

Brain non scrive file tenant. VSIX/Metis Fast mostreranno preview/diff e
applicheranno una patch soltanto dopo conferma umana e controllo CAS sul
workspace corrente.

## 5. Health e interpretazione

- `status=ready`: il servizio/session manager accetta richieste;
- `compiler_configured=true`: pin Git, runtime `node_modules` e Node sono stati
  verificati, e l'eseguibile sandbox è presente; la policy viene provata durante
  la compilazione reale;
- `compiler_executions`: compilazioni archiviate completate dall'avvio;
- `model_loaded=false`: inferenza Model 1 non appartiene a questa wave.

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
| `SESSION_LIMIT` / `COMPILER_BUSY` | limite locale raggiunto | backoff delimitato |
| `CONTEXT_TOO_LARGE` / `CONTEXT_UNSUPPORTED` | oltre il contratto compiler v1 | riduci la dependency closure |
| `COMPILER_FAILED` | toolchain sandbox non eseguibile | verifica pin/runtime, non fare fallback implicito |

Le risposte di errore generate dall'API sono JSON e non includono header, token,
sorgenti, root, environment o diagnostica interna. Un overload di trasporto o
un errore del parser HTTP sottostante può invece chiudere la connessione senza
una risposta applicativa.

## 7. Limiti dichiarati

- Mac e IPv4 loopback soltanto;
- host cooperativo per stesso UID; Keychain/code-signing nella wave app;
- massimo 64 sorgenti workspace e 512 KiB per sorgente nel compiler pinnato;
- nessun retrieval `catalog:describe`/`catalog:values` ancora esposto;
- nessuna inferenza, chat, streaming thinking, VSIX o Metis Fast ancora collegati;
- nessun packaging, firma, notarizzazione, updater o fallback remoto.

La prossima wave collega inferenza e retrieval progressivo senza cambiare il
contratto di isolamento delle sessioni consegnato qui.
