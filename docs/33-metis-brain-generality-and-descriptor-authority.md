# Generalità di Metis Brain e autorità dei descrittori

**Stato: D-017 ratificata; prima tranche verificata, generalità completa ancora aperta.**

## 1. Principio costituzionale

Metis Brain è un sistema generale per il DSL Metis, non un generatore costruito
attorno ai tenant o agli endpoint usati nella demo. La generalità è un
invariante di prodotto: nessuna scorciatoia specifica di `play-prod`,
`play-demo`, di un endpoint noto, di una chiave, di un valore, di un catalogo o
di una frase italiana può diventare autorità del runtime soltanto perché rende
verde un benchmark o soddisfa un operatore.

Il codice di Brain possiede esclusivamente il comportamento strutturale:
grammatica, standard library, compilatore, diagnostica, sicurezza, limiti,
orchestrazione e forme canoniche del DSL. La conoscenza del dominio appartiene
al tenant attivo e viene fornita dal suo snapshot Schema2 verificato.

Il principio riguarda tutti i descrittori dichiarati dal tenant, inclusi i
`@model` annotati: devono essere letti attraverso le proiezioni del toolchain
disponibili per il rispettivo costrutto. La prima implementazione qui descritta
copre cataloghi, campi e valori; non afferma che Schema2 esponga già tutti i
contratti operativi di ogni `@model`.

Di conseguenza un risultato è accettabile soltanto se la stessa architettura
funziona anche quando un tenant isomorfo rinomina cataloghi, campi, valori e
lessico. Un profilo di qualifica può fissare una configurazione di prova, ma
non può conferire autorità di prodotto né introdurre conoscenza nel modello.

## 2. Sorgente di conoscenza semantica

Per ogni sessione, Brain usa esclusivamente una proiezione immutabile e
versionata del tenant autorizzato. La proiezione deve provenire da un catalogo
Schema2 compilabile e includere, quando presenti e nello stesso revision
binding:

- `label`, `means` e `aka` del catalogo;
- `means` e `aka` di campi e valori;
- natura e cardinalità del dominio (`inline`, `enum(N)`, `open` o value-set
  esterno);
- valori effettivamente risolti dal retrieval e la loro evidenza;
- il costrutto `semantics from @catalog`, quando dichiarato dalla grammatica;
- tipo, modificatori e metadati tecnici necessari al compilatore.

Le descrizioni sono conoscenza interrogabile, non decorazione del file. Il
retrieval può usare le loro superfici linguistiche per collegare la richiesta
umana a un identificatore reale; non può trasformare una similarità lessicale
in un valore non presente nello snapshot. `unannotated`, `draft`, catalogo
ambiguo, value-set incompleto, lookup non verificato o revision mismatch sono
stati non autorizzati: Brain chiede chiarimento o si arresta in modo esplicito.

Il prompt del modello riceve riferimenti opachi e il contesto bounded della
proiezione, mai un elenco di simboli codificato nel programma come fallback.
La risoluzione finale deve restare vincolata a catalogo, campo e valore
revisionati; il modello non è un'autorità alternativa.

## 3. Confine delle responsabilità

La catena di verità è:

`richiesta -> retrieval semantico del tenant -> riferimenti verificati ->
 modello -> AST/.metis -> compilatore/oracle`.

Brain può decidere la struttura dell'endpoint (blocchi, parametri, filtri,
ordinamento, paginazione, risposta e fallback) secondo grammatica e standard
library. Non può inventare il catalogo o dedurre il significato operativo da
un nome di campo. Un campo chiamato `mood`, `protagonistaSesso` o
`last_live_channel_code` non acquista semantica perché il nome è familiare:
servono descrittore, dominio/value-set e, per i codici opachi, la mappatura
esplicita al nome leggibile.

In particolare non si inferiscono dai nomi le funzioni implicite di:

- identificatore o chiave di deduplicazione;
- profilo di similarità;
- data di recenza o finestra temporale;
- raggruppamento, ordinamento o priorità;
- relazione fra cataloghi o collegamento di una view.

L'attuale superficie Schema2 descrive bene cataloghi, campi, domini e valori,
ma non garantisce ancora una dichiarazione canonica per tutti questi ruoli
strutturali impliciti. Fino a quando la grammatica/standard library non li
esporrà (o il retrieval non potrà dimostrarli con un oracle), Brain deve
chiedere una specifica esplicita o rifiutare la proposta. Non è consentito
riempire il vuoto con la conoscenza di `play-prod`.

## 4. Invarianti e gate

Ogni implementazione che modifica l'autorità semantica deve dimostrare:

1. nessun identificatore, valore, frase o fallback di tenant è richiesto dal
   codice di produzione per costruire una proposta;
2. ogni selezione emessa contiene catalogo, campo/valore, revisioni e prova
   Schema2, ed è rifiutata se la prova non è `reviewed`;
3. il modello riceve soltanto riferimenti e contesto bounded, mai credenziali,
   payload live o autorità di scrittura;
4. una modifica di descrittore, value-set, stato editoriale o snapshot
   invalida cache e proposta precedente;
5. due tenant sintetici isomorfi con nomi e valori disgiunti producono la
   stessa forma strutturale normalizzata, sostituendo soltanto i riferimenti
   autorizzati;
6. rimuovere o rinominare il descrittore fa fallire il gate in modo visibile,
   non attiva un fallback hardcoded;
7. compilazione, correttezza semantica e sicurezza restano gate distinti.

Un benchmark derivato da un solo tenant può misurare regressioni, ma non può
dimostrare generalità. Nessun `DONE` della wave è valido senza il test
metamorfico e l'ispezione del diff tecnico che provano l'assenza di nuove
scorciatoie.

## 5. Piano di migrazione

La migrazione avviene per incrementi verificabili:

1. censire ogni costante di dominio nel runtime e classificare ciò che è
   davvero grammatica/stdlib da ciò che è conoscenza di tenant;
2. introdurre un'autorità semantica tipizzata che consumi la proiezione
   Schema2, con revision binding, cache invalidation e fail-closed;
3. migrare prima le selezioni dichiarate dall'utente (catalogo, campo e valori)
   e poi i ruoli strutturali, senza alterare la superficie tecnica degli AST;
4. estendere grammatica/standard library con descrittori espliciti per
   identificatore, similarità, recenza, grouping e relazioni, oppure rendere
   obbligatoria la domanda all'operatore quando mancano;
5. eseguire i gate su `play-demo`, `play-prod-v2` e tenant rinominati sintetici;
6. eliminare le costanti di dominio solo dopo evidenza equivalente e mantenere
   eventuali profili di qualifica confinati ai test.

La wave può dichiararsi completa solo quando il runtime non usa più
tailoring come autorità. Le lacune di descrittori restano `OPEN`/`STOP` con
una domanda operativa all'utente; non vengono occultate da descrizioni
tautologiche o da roster copiati dalla demo.

## 6. Prima tranche implementata e limiti misurabili

Il provider di prodotto propone una collezione a catalogo singolo con filtri
di inclusione su campi keyword finiti revisionati e un conteggio totale
esplicito. Chiede prima il conteggio se manca, poi mostra catalogo, valori,
logica dei filtri e quantità per la conferma. Le alternative di uno stesso
campo richiedono `value_mode=any_of`; i campi distinti sono in AND. Selezioni
separate dello stesso campo restano non autorizzate finché manca un contratto
esplicito per il loro operatore logico.

La conferma è vincolata al proof semantico, al conteggio e alla revisione
dell'inventario. Una successiva richiesta sostanziale richiede una nuova
conferma. Il validatore riceve separatamente l'indice originale e il conteggio
autorizzato: non può ricostruire la propria autorità dalla proposta da validare.
Il compilatore resta un gate separato prima di pubblicare il Draft.

La generalità completa resta aperta. Le vecchie recipe chiuse sono disabilitate
nel provider creato dal server e restano raggiungibili soltanto mediante
un'opzione interna esplicita di compatibilità; sono ancora presenti nel
pacchetto e la loro estrazione/migrazione è G5. I risultati storici sui percorsi
complessi non attestano il comportamento del nuovo default. Similarità,
paginazione, fallback e multi-block richiedono le successive capability
generali; questa tranche non li dichiara pronti per la demo.

Il gate di repository della prima tranche è `make check TEST_WORKERS=2`:
4.254 test passati, 2 saltati, zero fallimenti/errori, con 4.256 casi distinti
contabilizzati senza omissioni. Include i due tenant sintetici rinominati
attraverso il compilatore reale isolato; non è una nuova qualifica live di
Model 1 o della demo complessa. Evidenze e prossimi passi sono nella
[lavagna della wave](../orchestra/runs/2026-09-05-brain-generality/BLACKBOARD.md).
