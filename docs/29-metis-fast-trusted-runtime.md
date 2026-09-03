# Metis Fast: trusted local runtime and demo-channel contract

Stato: **CONTRATTO SOFTWARE IMPLEMENTATO E QUALIFICATO NELLA WAVE DEL 3
SETTEMBRE 2026; PROVA LIVE DEI CONTENUTI DIFFERITA CON VPN SPENTA**.

Questo documento fissa il confine che trasforma una proposta compilata di
Metis Brain in una preview e, dopo consenso esplicito, in un fast channel
temporaneo. Non estende l'autorità di Brain e non autorizza scritture sul tenant
canonico.

## 1. Proprietà dei componenti

| Componente | Possiede | Non possiede |
|---|---|---|
| Metis Brain | sessione semantica, retrieval, chiarimenti, generazione, repair limitato, compilazione della proposta | filesystem tenant, preview contenuti, accettazione, palinsesto, pubblicazione |
| browser Metis Fast | conversazione e consenso dell'operatore | credenziali upstream, path host, processi, filesystem, ticket di scrittura |
| gateway locale Metis Fast | sessione client verso Brain, clone Git privato temporaneo, verifica manifest, CAS, invocazione compile Brain, materializzazione artifact set e runtime locali, cleanup | decisioni editoriali autonome, modifica implicita del tenant canonico |
| `metis-serve` | esecuzione dell'endpoint compilato e risposta `/ares` | generazione del codice e consenso utente |
| canale Fast | preview accettata e palinsesto volatile | semantica del catalogo o autorità sul sorgente `.metis` |

Il client attendibile è il processo gateway locale, non JavaScript nel browser.
Il browser può vedere il Draft e i risultati della preview, ma non riceve mai il
bootstrap token, il token di sessione upstream, un path assoluto, il path di un
env-file o un comando eseguibile.

## 2. Flusso normativo

```text
richiesta/refinement dell'operatore
  -> gateway locale -> sessione Brain schema 2
  -> chiarimenti tipizzati via /answer
  -> proposta .metis + grounding + compile receipt
  -> browser mostra Draft, mai un diff per una create
  -> consenso esplicito "Prepara anteprima"
  -> gateway rilegge da Brain il terminale server-owned
  -> apply-preflight e verifica della tupla completa
  -> clone Git locale privato del tenant allowlisted
  -> verifica esatta del manifest pubblico Brain e della revisione Git
  -> CAS della proposta nello snapshot
  -> compile autorevole Brain sul candidato
  -> bundle build pinnato materializza gli artifact set, incluse le varianti
  -> metis-serve sugli artifact set dello snapshot
  -> preview contenuti
  -> refine oppure consenso esplicito "Crea canale"
  -> palinsesto volatile deterministico
  -> close/TTL: processo, file e memoria vengono eliminati
```

La preview non promuove il file nel checkout dell'utente. Una futura funzione
di persistenza canonica richiederà un'azione e un gate separati, equivalenti al
contratto Apply/Undo dell'estensione VS Code.

## 3. Sessione e credenziali

Il gateway virtualizza ogni sessione Brain:

1. apre la sessione upstream usando il bootstrap token conservato soltanto nel
   processo;
2. conserva `upstream_session_id` e token in memoria;
3. restituisce al browser un riferimento e un token UI casuali e opachi;
4. sostituisce l'Authorization UI con quella upstream su ogni richiesta;
5. verifica sempre corrispondenza fra token, sessione, tenant e path;
6. revoca e cancella la mappatura su close, TTL o errore terminale.

Le sessioni restano limitate a 20 minuti di inattività. I cap sono 8 sessioni,
64 turni per sessione (risposte ai chiarimenti incluse), 4 materializzazioni e
1 canale volatile; gli slot vengono riservati prima degli `await` upstream per
impedire oversubscription concorrente. Nessuna memoria viene persistita oltre
la sessione.

## 4. Tupla di accettazione

Il browser invia soltanto riferimenti bounded. Non è autorità per sorgente,
target o hash. Prima di materializzare, il gateway recupera il terminale da
Brain e confronta esattamente:

- sessione, tenant e `turn_id`;
- `proposal_ref`, operation, endpoint, reference e target relativo;
- `context_revision` e `semantic_source_revision`;
- `base_sha256` e `source_sha256`;
- stato compilatore `ok` e relativo receipt;
- claim `tenant_modified=false` e `semantic_grounded=true`;
- ticket apply-preflight non scaduto e legato alla stessa proposta.

Qualunque assenza, campo inatteso, mismatch, replay o scadenza chiude la
richiesta senza creare lo snapshot.

Mode, path relativo, endpoint, reference e base hash ammessi sono una policy
esatta del launcher. Il payload browser può soltanto ripeterla: un'altra tupla
viene rifiutata prima di interrogare Brain. Solo il più recente `turn_id`
accettato nella sessione può essere materializzato o ricevere una risposta di
chiarimento; un refinement accettato invalida workspace, preview e canale
precedenti.

## 5. Snapshot tenant Git volatile

Il tenant viene scelto da una configurazione server-side allowlisted. Nessun
path arriva dal browser o dal modello. Per la demo Mac la sorgente deve essere
un checkout Git pulito con `HEAD` a 40 cifre esadecimali. Lo snapshot è un
clone locale privato senza hardlink: una copia dei soli file correnti non è
equivalente, perché perderebbe i ref `exp__*` necessari alla build delle
varianti. Lo snapshot:

- vive in un envelope temporaneo privato, mai dentro il checkout canonico; il
  repository è nel figlio `tenant`, così anche i worktree di variante creati
  come sibling dalla build restano dentro lo stesso confine di cleanup;
- deriva soltanto dal repository allowlisted, mediante eseguibile Git e
  argomenti fissati dal gateway; prima del clone l'intero repository locale,
  inclusa la storia Git, è limitato a 20.000 entry e 128 MiB, mentre il manifest
  pubblico Metis ha limiti separati di numero e byte;
- rifiuta symlink, device, socket, FIFO, traversal, nomi non UTF-8 e hardlink
  sospetti;
- prima del clone esegue una scansione metadata bounded e rifiuta `.env*`,
  directory di credenziali e nomi tipici di chiavi private, inclusi i path
  ignorati da Git;
- dopo il clone riproduce esattamente il manifest di contesto pubblico Brain e
  ne verifica path, hash e revisione prima di qualunque scrittura;
- applica una create soltanto su assenza esatta e una replace soltanto sul
  `base_sha256` esatto;
- usa write temporanea, `fsync` e rename atomico.

Il repository allowlisted deve essere privo di segreti anche nella storia Git.
Questa è una precondizione esplicita: il clone trasporta necessariamente la
storia e i ref richiesti dalle guardie delle varianti, ma il gateway non ne
interpreta né espone gli oggetti. La scansione dei nomi correnti impedisce il
caso operativo comune; non pretende di certificare semanticamente ogni blob
storico.

Un eventuale env-file locale può essere passato al processo runtime soltanto
come path configurato e non viene mai aperto, copiato o mostrato dal gateway.

## 6. Build ed esecuzione

La compilazione della proposta resta autorità di Metis Brain. Dopo il suo
receipt verde, il gateway invoca il bundle self-contained
`metis-build-tenant` della stessa release Metis pinnata: questa seconda fase
non sostituisce il giudizio di Brain, ma materializza gli artifact set che
`metis-serve` richiede per il ramo principale e per ogni variante Git
dichiarata. Bundle, Node, Git e `metis-serve` sono qualificati con path assoluti
e digest SHA-256 verificati. I byte verificati del bundle vengono eseguiti da
una nuova copia owner-only; il suo `PATH` privato risolve soltanto lo stesso Git
pinnato usato per il clone. Il gateway usa spawn con array di
argomenti chiuso: niente shell, comando testuale, working directory o env
forniti dal browser.

La build deve essere verde dopo la materializzazione e deve produrre tutti gli
artifact set attesi; un ref variante assente è un errore terminale, non una
degradazione alla sola `main`. Il runtime:

- effettua bind su `127.0.0.1` e porta privata assegnata dal sistema;
- espone al gateway soltanto le rotte necessarie alla preview;
- non è raggiunto direttamente dal browser;
- ha timeout, limite di corpo e cleanup su exit/error;
- produce receipt bounded con identità del Draft, proposta, sorgente,
  snapshot, Node, Git, bundle e runtime, non con il payload del tenant.

La VPN spenta rende impossibile attestare ora la preview live. I test della wave
usano adapter deterministici locali; il gate live resta nominato e separato, non
viene simulato come se fosse superato.

## 7. Preview e refinement

La preview appartiene al Draft corrente. Il receipt include almeno
`draft_ref`, `proposal_ref`, `source_sha256`, endpoint compilato, revisione dello
snapshot, conteggio dei risultati e hash del roster normalizzato. Un
refinement crea una nuova proposta Brain legata alla precedente e invalida
preview e consenso del Draft precedente.

Zero risultati non è un errore tecnico ma impedisce la creazione automatica del
canale. L'operatore può chiedere un refinement o, in una futura policy
esplicita, approvare un fallback. Metis Brain non aggiunge fallback in silenzio.

## 8. Fast channel e roster editoriale V1

`Crea canale` è un'azione distinta e ammessa soltanto dopo una preview non
vuota dello stesso Draft. Nella prima demo il risultato è intenzionalmente un
roster editoriale ordinato, non ancora un palinsesto temporale. Conserva:

- riferimento a Draft e preview;
- nome editoriale scelto dall'operatore;
- lista ordinata dei contenuti normalizzati;
- posizione e `content_ref` di ogni elemento;
- algoritmo/versione `ordered-preview-v1`;
- hash canonico di algoritmo e roster.

Stesso pool ordinato produce lo stesso roster e lo stesso hash. Non vengono
inventati durata, orario di inizio o cadenza. Un palinsesto temporale con
durate e scheduling è una capacità successiva e dovrà avere un contratto
versionato separato. Il canale e il roster muoiono con la sessione.

## 9. Gate di sicurezza e prodotto

La wave è verde soltanto con prove eseguibili per:

1. token upstream non osservabile dal browser;
2. rifiuto di Origin estraneo, token/session mismatch e replay;
3. rifiuto di source/path/target controllati dal browser;
4. tupla proposal/preflight/context esatta e fail-closed;
5. traversal, symlink, file speciale, overflow e CAS stale;
6. cleanup su successo, close, TTL e fallimento parziale;
7. compile failure senza runtime o canale;
8. preview vuota senza pubblicazione;
9. proposal -> clone Git -> manifest -> compile Brain -> build artifact set ->
   preview -> consenso -> roster canale in un
   E2E deterministico;
10. suite, typecheck, build e diff check del repository Metis Fast;
11. E2E HTTP con Brain reale e, separatamente, preview live quando la VPN e le
    autorità necessarie sono volutamente disponibili.

Un E2E deterministico chiude il contratto software, non il gate live. Un Draft
compiler-clean chiude la sintassi, non prova la pertinenza dei contenuti. Questi
claim rimangono separati anche nella UI e nei receipt.

La prova reale del 4 settembre ha attraversato il gateway HTTP Fast e il Brain
locale, con target existing server-owned. Una richiesta a quattro vincoli ha
attivato Model 1, una domanda semantica tipizzata su `film`, grounding completo
e compilazione verde in 39,250 secondi; il refinement proposal-based da 24 a 12
risultati ha riutilizzato tutti i vincoli e completato in 33,847 secondi. In
entrambi i terminali `generation_strategy=model`, `semantic_grounded=true` e
`tenant_modified=false`. La materializzazione è rimasta esclusa perché la VPN
era intenzionalmente spenta.

La chiusura del processo gateway segue lo stesso confine: smette di accettare
connessioni, marca e revoca le sessioni, interrompe i child Git/build/runtime
con escalation `SIGTERM`/`SIGKILL`, attende le operazioni in-flight e rimuove
gli envelope. Materializzazioni diverse nella stessa sessione sono serializzate;
close o TTL durante body, clone, preview o creazione canale marcano la sessione
prima del commit di stato, abortiscono le chiamate upstream, attendono le
operazioni in-flight e impediscono sia clone orfani sia risultati tardivi.
