# Direzione prodotto: Metis Brain e integrazione VS Code

Stato: **DIREZIONE RATIFICATA; CORE SESSIONI/COMPILER V1 IMPLEMENTATO;
INFERENZA, APP E INTEGRAZIONE VSIX ANCORA APERTE; WINDOWS FUORI PERIMETRO**.

Questo documento fissa la destinazione del prodotto affinché le wave correnti
non ottimizzino il modello per un'interfaccia diversa da quella prevista. Il
core sessioni/compilatore realizzato non autorizza distribuzione, inferenza
remota o scritture sui repository reali.

## 1. Risultato di prodotto

Metis Model 1 sarà consumato nella fase di sviluppo e demo attraverso
un'applicazione installabile su macOS denominata **Metis Brain**.
L'applicazione ospiterà un servizio locale e gestirà il ciclo di vita del
modello:

- acquisizione separata del base model e dell'adapter Metis;
- verifica di manifest, hash, compatibilità e licenze prima dell'attivazione;
- inferenza locale, health check, aggiornamento e rollback;
- API locale unica e versionata per i client autorizzati;
- conservazione della versione precedente fino alla verifica della nuova.

L'archivio S3 creato per `INITIAL_LOCAL_QLORA_V1` è un backup sigillato, non il
canale di distribuzione dei client. Il release channel di Metis Brain richiederà
un contratto separato, firmato e verificabile.

## 2. Ruolo dell'estensione Metis per VS Code

L'estensione VS Code è un client editoriale di Metis Brain. Deve permettere a
Giulia e alla redazione di creare, modificare, correggere, migrare e revisionare
endpoint Metis reali usando il workspace corrente e l'inferenza locale.

Il flusso di riferimento è:

```text
richiesta editoriale + workspace attendibile
  -> estensione Metis VS Code
  -> API locale versionata di Metis Brain
  -> retrieval del contesto corrente
  -> base Qwen3.8 + adapter Metis
  -> parse/link/validate/compile/oracle e repair limitato
  -> patch + diagnostici + evidenza
  -> preview/diff e conferma umana
  -> applicazione nel workspace
```

Il modello propone; il toolchain verifica; l'utente decide se applicare. Nessuna
scrittura autonoma su endpoint reali è abilitata per default. Compile-clean non
sostituisce la correttezza semantica.

## 3. Local-first e fallback

La policy predefinita è `local-first` con fallback remoto disabilitato. Un
fallimento locale non può inviare automaticamente codice, contesto o dati a un
servizio esterno.

Un futuro fallback può usare inferenza remota oppure tool/modelli già presenti o
installabili in VS Code soltanto se una policy esplicita stabilisce, per ogni
richiesta:

- provider, modello o tool consentito;
- motivo del fallback e dati che possono lasciare la macchina;
- consenso dell'utente o policy organizzativa applicabile;
- redazione, limiti, timeout e audit/receipt;
- indicazione visibile del percorso locale, remoto o tool-based effettivamente
  usato.

I fallback non diventano autorità semantica: parser, linker, validator, compiler,
IR e oracle Metis restano il gate del risultato.

## 4. Confini fra pesi, retrieval e toolchain

La direzione prodotto conferma la separazione fondativa:

- i pesi apprendono grammatica stabile, authoring, editing, repair, review e
  migrazione;
- checkout, endpoint, simboli, cataloghi, valori e configurazioni correnti
  appartengono a retrieval e contesto;
- il toolchain Metis stabilisce validità ed equivalenza applicabili.

I valori tenant, gli endpoint reali e lo stato operativo non devono essere
memorizzati nell'adapter. Questa scelta mantiene il modello aggiornabile con
interventi piccoli e consente a Metis Brain di lavorare su workspace differenti.

## 5. Vincoli imposti alle wave di accuracy

Le decisioni delle wave successive di Metis Brain devono preservare:

1. adapter separato dal base model, versionato e disattivabile;
2. uso del runtime MLX/MLX-VLM già qualificato come percorso della demo Mac,
   senza introdurre ora astrazioni per backend non richiesti;
3. confronto B/D con retrieval e compiler loop identici;
4. valutazione su authoring, patch minimale, repair, review, migrazione e
   spiegazione strutturale, cioè le operazioni esposte dal plugin;
5. output strutturato come patch, diagnostici ed evidenza, non sola completion;
6. rollback e rifiuto fail-closed delle combinazioni incompatibili fra base,
   adapter, runtime, versione Metis e toolchain;
7. fallback remoto escluso dai benchmark che misurano l'uplift dell'adapter.

## 6. Piattaforma della demo

Il checkpoint corrente è qualificato con MLX/MLX-VLM su Apple Silicon: questo è
il solo percorso richiesto per la fase di sviluppo e per la demo.

Windows non è un requisito corrente e non blocca accuracy, Metis Brain, plugin o
demo. Soltanto dopo l'approvazione del progetto si deciderà se aprire una wave
separata per backend, packaging e parità Windows. Nessuna astrazione Windows va
implementata preventivamente.

## 7. Sicurezza del servizio locale

Anche un servizio limitato alla macchina locale tratta estensione e processi
chiamanti come non attendibili. Il core v1 implementa già:

- bind HTTP su `127.0.0.1`, bootstrap ruotato, token di sessione, capability e
  protocollo versionato;
- associazione di ogni sessione a client autorizzato, alias tenant, snapshot e
  revisione immutabile;
- nessun path, comando, argomento o variabile d'ambiente arbitrario;
- limiti di concorrenza, sessioni, compiler, tempo e dimensione richiesta;
- scadenza dopo 20 minuti esatti di inattività semantica, close esplicito,
  revoca dei risultati tardivi e cleanup confinato;
- log redatti senza credenziali, `.env` o payload tenant non autorizzati.

Preview, diff, conferma umana, applicazione CAS e rollback prima di modificare
file reali restano responsabilità dei client futuri.

## 8. Decisioni ancora aperte

La direzione e il core session/compiler v1 sono ratificati; restano
deliberatamente aperti fino alle wave di prodotto W7-W8:

- protocollo di inferenza condivisa, retrieval progressivo e streaming degli
  eventi di lavoro;
- pairing dell'app con VSIX/Metis Fast, workflow editoriale e superfici chat;
- packaging, firma/notarizzazione, updater e release channel;
- provider remoti ammessi e classificazione dei dati trasmissibili;
- uno o più adapter per le diverse famiglie di task;
- licenze e autorizzazioni per distribuire base e adapter oltre il perimetro
  locale corrente.

L'eventuale supporto Windows è una decisione post-approvazione e non appartiene
agli open gate della demo Mac.

Questi dettagli non bloccano la prossima accuracy wave, ma la candidate finale
deve conservarne la fattibilità.
