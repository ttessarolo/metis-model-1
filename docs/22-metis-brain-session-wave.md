# Metis Brain: wave sessioni tenant v1

Stato: **IMPLEMENTATO E VERIFICATO NEL PERIMETRO DELLA WAVE**.

## 1. Obiettivo verificabile

Questa wave consegna il nucleo locale di Metis Brain che i futuri client Metis
VSIX e Metis Fast potranno invocare. Un client già abbinato al processo Brain:

1. apre una sessione indicando un alias tenant autorizzato;
2. riceve un token di sessione e la revisione immutabile del contesto;
3. legge il contesto consentito e compila una proposta `.metis` contro lo
   snapshot della sessione;
4. chiude la sessione, oppure la lascia scadere dopo 20 minuti esatti di
   inattività semantica.

Il servizio mantiene N sessioni logiche, anche sullo stesso tenant, ma non N
copie del modello. Questa wave non include ancora inferenza Model 1, UI VS Code,
Metis Fast, distribuzione dell'app o fallback remoto.

## 2. Architettura minima

```text
VSIX / Metis Fast (futuri)
        |
        | HTTP loopback + bootstrap/session bearer
        v
Metis Brain API
  |-- policy client -> tenant alias -> capability
  |-- session manager (TTL, lease, revoke, cleanup)
  |-- immutable tenant snapshot + private overlay
  |-- compiler bridge pinned to grammar/stdlib
  `-- one shared model runtime (next wave)
```

Brain tratta i client come non attendibili. L'alias è risolto da configurazione
locale; nessun path, comando, `argv` o ambiente arriva dal protocollo. Il tenant
è sempre read-only: Brain produce evidenza e candidati, mentre preview, consenso
e applicazione CAS restano al client.

## 3. Contratto della sessione

Una sessione server-side contiene:

- ID e token casuali a 256 bit; del token resta soltanto un digest keyed;
- client ID, alias tenant e capability immutabili;
- identità filesystem della root (`device`, `inode`);
- snapshot di `metis.toml` e sorgenti `.metis`, revisione content-derived;
- directory overlay privata esterna al tenant;
- istanti monotoni di creazione e ultima attività;
- stato monotono `ACTIVE -> CLOSING|EXPIRED -> CLOSED`;
- contatore e cancellazione delle operazioni in corso.

Il timeout è `1_200` secondi. La sessione è viva a `1199.999` ed è scaduta a
`1200.000`. Soltanto un'operazione semantica autenticata e ammessa aggiorna
l'attività; health, status ed errori di protocollo/auth/schema pre-ammissione
non lo fanno. Un'operazione già ammessa aggiorna l'attività anche se il compiler
restituisce un errore e non viene troncata dalla scadenza idle, ma close revoca
subito nuove ammissioni e rende impubblicabile ogni risultato tardivo.

## 4. Snapshot, concorrenza e stale guard

Ogni sessione riceve uno snapshot indipendente. La revisione lega in modo
deterministico:

- byte e path relativi consentiti del tenant;
- identità del tenant;
- versione del protocollo;
- pin di grammatica, standard library e toolchain.

Due sessioni sullo stesso tenant possono lavorare contemporaneamente senza
condividere history, overlay o valori lazy. Ogni risultato è legato alla
revisione attesa. Brain verifica il tenant subito prima dell'ammissione e di
nuovo prima di pubblicare il risultato: ogni drift osservato produce
`STALE_CONTEXT` e nessun risultato viene pubblicato. Il client potrà richiedere
una nuova sessione/snapshot e applicherà eventuali patch soltanto con CAS.

## 5. API v1

Il trasporto usa HTTP/1.1 su `127.0.0.1`, JSON stretto e bearer header. Non usa
cookie, query token o CORS.

| Metodo e route | Auth | Capability | Effetto sul TTL |
|---|---|---|---|
| `GET /v1/health` | nessuna | — | nessuno |
| `POST /v1/sessions` | bootstrap | grant client/tenant | crea sessione |
| `GET /v1/sessions/{id}` | sessione | `session.read` | nessuno |
| `DELETE /v1/sessions/{id}` | sessione | `session.close` | revoca/cleanup |
| `POST /v1/sessions/{id}/context` | sessione | `context.read` | sì |
| `POST /v1/sessions/{id}/compile` | sessione | `compile` | sì |

Campi sconosciuti o duplicati, body oltre soglia, tipi ambigui, `Origin`,
cookie, query string e auth errata sono rifiutati deterministicamente.
La risposta `context` espone manifest, hash e revisioni, non rimanda al client i
byte sorgente che Brain conserva nello snapshot. Cataloghi e valori seguiranno
il retrieval progressivo per costrutto/campo, senza materializzare un dominio
enorme nel prompt o nella risposta.

## 6. Compilazione

La route compile usa il bridge grammar/stdlib già sigillato nel repository. Il
bridge estrae da Git l'esatto commit Metis pinnato in una directory temporanea,
nega write e rete al runner e restituisce diagnostici, AST, IR e hash di
evidenza. Il tooling tracciato proviene dall'archivio Git; `tooling/node_modules`
viene copiato dalla root esterna soltanto dopo verifica contro il digest pinnato,
riverificato dopo la copia e mai eseguito in place dal checkout live.

Il wrapper Python corrente accetta al massimo 64 sorgenti workspace. La wave v1
fallisce esplicitamente oltre quel limite e interrompe il subprocess del
compiler dopo 120 secondi, normalizzando il timeout come `COMPILER_FAILED`; la
selezione per dependency closure dei tenant più grandi è una wave successiva.
“Compila” non equivale a “è semanticamente corretto”: il receipt riporta
entrambe le dimensioni senza promuoverle.

## 7. Sicurezza e limiti

- bind numerico loopback verificato dopo l'apertura del socket;
- bootstrap casuale ruotato a ogni avvio, directory `0700`, file `0600`, no
  symlink;
- token di sessione non scambiabili e capability default-deny;
- root tenant canonicale, allowlisted e senza symlink;
- limiti globali, per client e per tenant;
- log strutturati con soli metadati allowlisted;
- cleanup idempotente e confinato alla runtime root di Brain.

Il confine v1 è un Mac cooperativo per utente: protegge da rete, browser e client
non abbinati, ma non da `root` o da un processo malevolo con lo stesso UID che
può leggere il bootstrap runtime. Keychain, firma e code-signing appartengono
alla wave di packaging.

## 8. Sequenza di implementazione e test

1. protocollo/errori e validazione JSON;
2. registry tenant e snapshot sicuro;
3. manager sessioni, TTL, lease, limiti, stale guard e cleanup;
4. bridge compiler e receipt redatto;
5. server loopback, bootstrap e CLI;
6. test unitari, race e trasporto ostili;
7. live smoke con tenant sintetico e compiler pinnato;
8. `make check`, diff review, board e verdetto.

## 9. Chiusura e prossima wave

Il verdetto di questa wave può essere soltanto
`METIS_BRAIN_SESSION_CORE_V1` oppure `BLOCKED`. Il primo certifica il core
sessioni/compilatore, non il prodotto installabile.

Dopo la chiusura restano, in ordine: collegare l'inferenza Model 1 con scheduler
condiviso; aggiungere il retrieval progressivo cataloghi/valori; integrare il
protocollo nel VSIX e in Metis Fast; quindi packaging, Keychain, firma,
notarizzazione e release channel Mac.
