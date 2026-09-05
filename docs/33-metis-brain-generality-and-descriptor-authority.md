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

Il pin AST corrente espone già identità di catalogo, profili di similarità
nominali e proiezioni di ritorno. Il `Model` root non è però un nuovo
costrutto-dominio `@model` annotabile: Brain non inventa una dichiarazione che
la grammatica non offre. La sidecar G5 realizza la proiezione autorizzata di
quei ruoli tecnici verso Brain, senza introdurre una nuova annotazione fittizia.

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

Le descrizioni editoriali sono conoscenza interrogabile, non decorazione del
file. Il retrieval può usare le loro superfici linguistiche per collegare la richiesta
umana a un identificatore reale; non può trasformare una similarità lessicale
in un valore non presente nello snapshot. `unannotated`, `draft`, catalogo
ambiguo, value-set incompleto, lookup non verificato o revision mismatch sono
stati non autorizzati: Brain chiede chiarimento o si arresta in modo esplicito.

La sidecar tecnica privata di Brain deriva invece dall'AST pinnato e contiene
solo una allowlist catalog-qualified: `id_field`, driver/capabilities, fields,
`similarity_profiles` e projections. È distinta dai descrittori editoriali
reviewed e ha un proprio proof/revision binding. Non serializza mai il
`RuntimeCtx` intero, corpi di endpoint, settings, dati live, servizi, pesi o
altri payload operativi.

Il prompt del modello riceve riferimenti opachi e contesto bounded derivato da
queste proiezioni, mai un elenco di simboli codificato nel programma come
fallback. La risoluzione finale resta vincolata a catalogo, campo, valore e
ruolo tecnico revisionati; il modello non è un'autorità alternativa.

## 3. Confine delle responsabilità

La catena di verità è:

`richiesta -> retrieval semantico del tenant -> riferimenti verificati ->
 modello -> AST/.metis -> compilatore/oracle`.

Il contratto di Brain può esprimere struttura dell'endpoint (blocchi,
parametri, filtri, ordinamento, paginazione, risposta e fallback) secondo
grammatica e standard library; lo stato delle capability G5 attive è dichiarato
nella sezione 6. Non può inventare il catalogo o dedurre il significato
operativo da un nome di campo. Un campo chiamato `mood`, `protagonistaSesso` o
`last_live_channel_code` non acquista semantica perché il nome è familiare:
servono descrittore, dominio/value-set e, per i codici opachi, la mappatura
esplicita al nome leggibile.

In particolare non si inferiscono dai nomi le funzioni implicite di:

- identificatore o chiave di deduplicazione;
- profilo di similarità;
- data di recenza o finestra temporale;
- raggruppamento, ordinamento o priorità;
- relazione fra cataloghi o collegamento di una view.

L'AST pinnato rende già disponibili identità, profili e returns, ma non basta
che esistano nel runtime: devono essere proiettati nella sidecar privata e
attestati per il catalogo esatto. Fino a quando quella prova e il relativo gate
non esistono, Brain deve chiedere una specifica esplicita o rifiutare la
proposta. Non è consentito riempire il vuoto con la conoscenza di `play-prod`.

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
4. proiettare dall'AST pinnato i ruoli già disponibili (identità, profili e
   returns) con prova indipendente; chiedere all'operatore o fermare la
   proposta quando il ruolo richiesto resta assente, senza inventare un
   `@model` annotabile;
5. eseguire i gate su `play-demo`, `play-prod-v2` e tenant rinominati sintetici;
6. eliminare le costanti di dominio solo dopo evidenza equivalente e mantenere
   eventuali profili di qualifica confinati ai test.

La wave può dichiararsi completa solo quando il runtime non usa più
tailoring come autorità. Le lacune di descrittori restano `OPEN`/`STOP` con
una domanda operativa all'utente; non vengono occultate da descrizioni
tautologiche o da roster copiati dalla demo.

## 6. Gate storico della prima tranche e stato G5

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

La generalità completa resta aperta. Le recipe chiuse sono state fisicamente
rimosse dal prodotto e sopravvivono solo in fixture `tests/legacy_*`: non sono
un package runtime, non esiste un flag di compatibilità per riattivarle e i
loro risultati storici non descrivono il nuovo default.

Il core G5 è **VERIFICATO**: gate completo con 4.444 casi distinti, 4.442
passati, due qualifiche opt-in saltate, zero fallimenti/errori e zero omissioni.
Il motore può aggiungere un blocco
filtrato con conteggio totale e può creare una pagina filtrata con
`page_default` soltanto come nuova root variant: il pin reale vieta tale modo
su un `NamedBlock`. Può modificare il conteggio totale di un take esistente,
ordinare per un campo reviewed esplicito, scegliere sul
take un nome di return projection dichiarato dal catalogo, usare un fallback di
blocco nello stesso Draft e applicare `similarity_from_input` con profilo
dichiarato e input seed esplicito. Due tenant rinominati hanno compilato il
percorso di similarità nel pin reale; questi casi sono inclusi nel gate core,
ma non qualificano un client o una demo.

L'operatore può correggere le scelte prima del Draft; roster oltre 64 elementi
sono paginati, round e decisioni bound sono limitati a 32, non a una chat
indefinita. Sono ammessi 64 messaggi, mantenendo invariato il tetto complessivo
di byte. La suite esegue retrieval a ogni risposta: solo messaggi interamente
coperti da decisioni ammesse e adiacenti possono conservare il grounding. Una
conferma con ulteriori requisiti non acquisisce autorità implicitamente.

Una forma pool-only può compilare verde senza emettere risposta. La correzione
implementata emette variant/use nel primo CREATE e nell'add-block; i test
richiedono anche questa struttura nell'IR, non il solo esito del compilatore.
`view-all`, external fallback, grouping e relazioni arbitrarie fra cataloghi
non sono dichiarati pronti. La qualifica del client VSIX e dei prompt complessi
con inferenza resta distinta dal gate core; contratto, limite linguistico e
requisiti UX sono nell'[handover v2](handover-g5-visix-dialogue-v2.md).

Il gate corrente è `make check TEST_WORKERS=2` su copia indipendente
dell'autorità Metis, senza cambiare il pin: exit 0, 1.509,39 secondi. Tutti i
13 nuovi casi di compilatore/proiezione tecnica sono eseguiti, non saltati.
Il journey naturale percorre sette operazioni con retrieval a ogni risposta
su due tenant rinominati. Non è stata eseguita inferenza di Model 1 in questa
wave e nessun peso, tenant, client o repository esterno è stato modificato.

Il gate della prima tranche, **storico e non il gate G5 corrente**, era
`make check TEST_WORKERS=2`:
4.254 test passati, 2 saltati, zero fallimenti/errori, con 4.256 casi distinti
contabilizzati senza omissioni. Include i due tenant sintetici rinominati
attraverso il compilatore reale isolato; non è una nuova qualifica live di
Model 1, della demo complessa o dell'integrazione G5. Evidenze e prossimi passi sono nella
[lavagna della wave](../orchestra/runs/2026-09-05-brain-generality/BLACKBOARD.md).
