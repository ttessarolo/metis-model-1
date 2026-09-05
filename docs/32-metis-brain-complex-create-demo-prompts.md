# Metis Brain: seconda coorte di prompt complessi per la demo

Status: **FROZEN E MISURATO — COPERTURA DEMO PARZIALE**. Questo documento raccoglie
dieci journey indipendenti per creare da zero endpoint complessi in una chat
Metis Brain. I prompt sono la superficie ispezionabile dall'operatore: non
contengono endpoint di riferimento, blueprint, specifiche attese o dati live.

## Risultato headless del 5 settembre 2026

La prova sul profilo congelato `play-prod-v4` ha completato `10/10` sessioni e
`40/40` messaggi in 6 minuti e 3 secondi. Tutte le `9/9` bozze ammesse
dall'autorità corrente sono risultate esatte e compilate al primo tentativo;
`10/10` prime domande e `20/21` blocchi successivi sono stati gestiti come
domande sicure. Nessun Apply è stato eseguito e tenant e modello sono rimasti
immutati.

| Caso | Esemplare strutturale play-prod | T1 | T2 | T3 | T4 | Stato per la demo |
| --- | --- | --- | --- | --- | --- | --- |
| 11 | `multiple_block_dem_scelti_per_te` | Domanda | Bozza esatta | Domanda | Domanda | Parziale: manca il multiblocco parametrico |
| 12 | `subscription_channel_film` | Domanda | Bozza esatta | Domanda | Domanda | Parziale: mancano pool e attivazioni per subscription |
| 13 | `inf_smart_block_film` | Domanda | Bozza esatta | Domanda | Domanda | Parziale: manca lo smart index con variante/fallback |
| 14 | `search.main` | Domanda | Domanda | Domanda | Domanda | Non pronta: manca il binding verificato del normalizzatore |
| 15 | `new_similar_intrattenimento` | Domanda | Bozza esatta | Bozza esatta | Bozza esatta | **Completa: candidata alla demo** |
| 16 | `enabler_test_film` | Domanda | Bozza esatta | Domanda | Domanda | Parziale: manca il piano esatto di injection/take |
| 17 | `similar_sport` | Domanda | Domanda | Domanda | Domanda | Non pronta: famiglia sport e struttura non sono autorizzate |
| 18 | `similar_documentari` | Domanda | Domanda | Domanda | Errore budget | Non pronta: quarto slot oltre il tetto di tre domande |
| 19 | `fnjwq5_lha2` | Domanda | Bozza esatta | Domanda | Domanda | Parziale: manca il piano dei take delle venti righe |
| 20 | `inf_multiple_block_film` | Domanda | Bozza esatta | Domanda | Domanda | Parziale: mancano istanze parametriche e smart ordering |

Il verdetto complessivo è quindi **RED per copertura**, non per qualità delle
bozze prodotte: soltanto il caso 15 arriva alla quarta richiesta con un endpoint
completo. Gli altri nove casi restano ottimi test manuali di conversazione e
fail-closed, ma non vanno presentati come generazione complessa conclusa finché
le rispettive autorità strutturali non sono implementate. I turni che hanno
prodotto una bozza hanno richiesto in media 21,7 secondi end-to-end.

## Prerequisiti e regole di prova

1. Avvia Metis Brain e apri in VS Code il tenant `play-prod` previsto dalla
   configurazione della demo.
2. Apri una nuova sessione della chat Metis per ciascun caso. Non riusare la
   memoria di un caso nel successivo.
3. Incolla i quattro prompt del caso, nell'ordine, **nella stessa sessione**.
   Attendi la risposta di Brain prima di inviare il prompt successivo.
4. Se Brain pone una domanda, rispondi in chat in modo naturale usando solo le
   informazioni già espresse nel prompt successivo, quindi prosegui con la
   sequenza. Non anticipare dettagli dei turni successivi.
5. Ispeziona la bozza `.metis` e gli eventi di compilazione, ma non selezionare
   **Apply**. Questa è una prova Draft-only e non autorizza modifiche al tenant.

Il file macchina corrispondente è
[`metis-brain-complex-create-prompts.play-prod-v4.json`](../examples/metis-brain-complex-create-prompts.play-prod-v4.json).
I blocchi seguenti sono copiati byte per byte dai 40 messaggi di quel file.

## Caso 11 — Homepage personalizzata multiblocco

Parte da una riga di film simili e la trasforma in una homepage personalizzata
con seed, righe riusabili, blocchi per genere, fallback e ordinamento delle
righe per affinità.

### Prompt 1

<!-- prompt:case_11:1 -->
```text
Voglio una riga di film simili per la sezione cinema.
```

### Prompt 2

<!-- prompt:case_11:2 -->
```text
Usa il catalogo video e dammi 30 risultati totali, usando il contenuto visto come seed.
```

### Prompt 3

<!-- prompt:case_11:3 -->
```text
Aggiungi una riga Perché hai visto con titolo dinamico, una riga Film che ti potrebbero piacere e una riga Serie TV del momento. Prepara inoltre un blocco parametrico obbligatorio per genere, con Vedi tutto, e istanzialo per Azione, Commedia/Comico, Drammatico, Animazione, Fantascienza, Thriller, Sentimentale, Horror, Avventura e Guerra; ogni riga di genere deve unire un take da 20 sul genere primario e un take da 130 sul genere generale, poi deduplicare e limitare a 150.
```

### Prompt 4

<!-- prompt:case_11:4 -->
```text
Usa il fingerprint storico sia per promuovere gli elementi sia per riordinare tutte le righe della pagina per affinità, quindi limita la pagina a quattro righe. Se la riga Film che ti potrebbero piacere è vuota, usa un blocco di fallback che unisce quattro take da 10, 5, 10 e 10 film, quindi deduplica, mescola e limita a 30; mostra la riga Perché hai visto solo quando esiste il seed e la riga personalizzata solo quando il fingerprint esiste e ci sono più di tre visioni.
```

## Caso 12 — Sezioni guidate dalla subscription

Costruisce una pagina di film e serie usando pool separati per canale,
alternative pesate, due blocchi e ordine delle sezioni dipendente dal ruolo.

### Prompt 1

<!-- prompt:case_12:1 -->
```text
Voglio una riga di film simili per la sezione cinema.
```

### Prompt 2

<!-- prompt:case_12:2 -->
```text
Usa il catalogo video e dammi 50 risultati totali, usando il contenuto visto come seed.
```

### Prompt 3

<!-- prompt:case_12:3 -->
```text
Costruisci pool candidati separati per i film MediasetPlay, Infinity, MGM, MidnightFactory, InfAutore, InfComico, InfLight e InfNero e per le serie MediasetPlay, Infinity, MGM, HistoryPlayIt, BlazePlayIt e CiPlayIt. Mantieni per ciascuna famiglia i pool per le prime posizioni distinti dai pool principali.
```

### Prompt 4

<!-- prompt:case_12:4 -->
```text
Crea i blocchi Film del momento e Serie TV del momento, entrambi con Vedi tutto e due take: il primo da 15 combina i pool per le prime posizioni e il secondo da 50 combina i pool principali con alternative best-plus-near-full, poi deduplica e limita a 50. Nella variante mostra prima il blocco film e poi quello serie; attiva i pool opzionali solo quando la subscription include il canale, evita sovrapposizioni fra canali concorrenti e conserva il ranking a sette o ventiquattro ore appropriato a ciascun pool.
```

## Caso 13 — Smart index con fallback editoriale

Introduce un indice editoriale per identità e titolo della riga, con una
variante personalizzata e un percorso di fallback deterministico.

### Prompt 1

<!-- prompt:case_13:1 -->
```text
Voglio una riga di film simili per la sezione cinema.
```

### Prompt 2

<!-- prompt:case_13:2 -->
```text
Usa il catalogo video e dammi 30 risultati totali, usando il contenuto visto come seed.
```

### Prompt 3

<!-- prompt:case_13:3 -->
```text
Aggiungi una riga Film del momento il cui titolo arriva dallo smart_index: prendi una sola riga dallo smart index, ordinala per similarità al fingerprint storico dell'utente e limita la risposta a 30. Se lo smart index non produce elementi, sostituisci la riga con Da non perdere.
```

### Prompt 4

<!-- prompt:case_13:4 -->
```text
Usa anche il catalogo users e definisci due varianti alternative: smart_page usa Film del momento solo se l'utente ha un fingerprint storico e più di tre contenuti visti, mentre fallback_page usa Da non perdere negli altri casi. Nel fallback unisci un take da 30 film recenti e un take da 10 film più visti, poi deduplica, mescola e limita a 30.
```

## Caso 14 — Ricerca multivariante

Espande una ricerca testuale in blocchi riusabili, navigazione per canale,
gestione della capacità 4K, Vedi tutto e percorsi predefiniti di recupero.

### Prompt 1

<!-- prompt:case_14:1 -->
```text
Mi serve una ricerca dei contenuti del servizio.
```

### Prompt 2

<!-- prompt:case_14:2 -->
```text
Catalogo video, 20 risultati per pagina, con ricerca su testo e canale; normalizza il testo di ricerca prima di eseguire le query.
```

### Prompt 3

<!-- prompt:case_14:3 -->
```text
Deriva gli attributi has_search, has_channel e wants_infinity. Dichiara blocchi riusabili separati per programmi e serie, film, clip, episodi, video predefiniti e stagioni predefinite; nei blocchi con query usa alternative tra titolo, persone e genere, mentre nei blocchi predefiniti ordina per visualizzazioni nelle ultime 24 ore e deduplica prima del limite.
```

### Prompt 4

<!-- prompt:case_14:4 -->
```text
Instrada sei varianti mutuamente esclusive: ricerca senza canale, default Infinity, ricerca Infinity, ricerca su un altro canale, default di un altro canale e default generale. Applica i filtri HDR o SDR in base alla capacità 4K, abilita Vedi tutto sulle sezioni e usa le sezioni predefinite come fallback sostitutivo quando una ricerca non restituisce risultati.
```

## Caso 15 — Similarità per intrattenimento

Costruisce pool distinti per episodi e clip, quindi li combina con alternative,
finestre temporali, promozione dei contenuti recenti e fallback in coda.

### Prompt 1

<!-- prompt:case_15:1 -->
```text
Vorrei una riga di intrattenimento simile al contenuto visto.
```

### Prompt 2

<!-- prompt:case_15:2 -->
```text
Catalogo video, una riga da 24 risultati totali usando il contenuto visto come seed.
```

### Prompt 3

<!-- prompt:case_15:3 -->
```text
Costruisci quattro pool candidati da 50 elementi ciascuno: episodi dello stesso programma, clip/extra, episodi di intrattenimento e clip di intrattenimento; usa una finestra di 18 mesi per gli episodi, 14 giorni per i contenuti recenti e raggruppa per programma.
```

### Prompt 4

<!-- prompt:case_15:4 -->
```text
Nel consumer usa un primo take da 4 e uno finale da 24, combina i pool con alternative best-plus-near-full, promuovi contenuti recenti, deduplica e limita a 24; se gli elementi piatti sono meno di uno aggiungi in coda il fallback intrat_recent.
```

## Caso 16 — Injection posizionale e contenuto casuale

Parte da una pagina di film recenti e inserisce contenuti puntuali, una finestra
di un blocco e un elemento casuale in posizioni determinate.

### Prompt 1

<!-- prompt:case_16:1 -->
```text
Crea una pagina con i titoli del momento.
```

### Prompt 2

<!-- prompt:case_16:2 -->
```text
Catalogo video, 20 risultati totali per la pagina, con film e serie TV recenti.
```

### Prompt 3

<!-- prompt:case_16:3 -->
```text
Prima della riga prepara due contenuti puntuali con identificativi Y311040301000901 e F310293901000501, un contenuto casuale preso dall'intero catalogo e un blocco Sport recenti da 30 elementi. Nella risposta inserisci il primo contenuto alla posizione 2, il secondo alla 3, un solo elemento del blocco Sport alla 4 e il contenuto casuale alla 5.
```

### Prompt 4

<!-- prompt:case_16:4 -->
```text
La selezione principale deve usare take page default 20, mentre dopo le quattro injection la risposta va limitata a page default 19. Il contenuto casuale deve essere scelto con ordinamento random, i tre producer di contenuti devono poter leggere tutto il catalogo e il blocco Sport deve restare lazy fino all'injection.
```

## Caso 17 — Sport con fallback a due livelli

Seleziona contenuti sportivi simili con un percorso per canali esterni e uno
principale, poi distingue il recupero per risposta vuota dal recupero su errore.

### Prompt 1

<!-- prompt:case_17:1 -->
```text
Crea un nuovo endpoint con una riga di contenuti sportivi del catalogo video simili al contenuto visto.
```

### Prompt 2

<!-- prompt:case_17:2 -->
```text
Usa contentId come seed e restituisci 24 risultati; ricevi anche i canali della subscription e promuovi i contenuti pubblicati negli ultimi due giorni.
```

### Prompt 3

<!-- prompt:case_17:3 -->
```text
Aggiungi un percorso per seed provenienti da canali diversi da MediasetPlay, Infinity e UCL, mantenendo i canali del seed, e un percorso principale MediasetPlay. Nel percorso principale anteponi un take da 11 per la serie SE000000001535 quando il seed appartiene a quella serie, poi usa un take da 24 per clip e puntate complete simili, escludendo il seed e il prodotto padre.
```

### Prompt 4

<!-- prompt:case_17:4 -->
```text
Deduplica e limita la risposta a 24. Se gli elementi piatti uniti sono meno di uno, accoda un fallback sportivo materializzato; se invece l'esecuzione produce un errore, sostituisci l'intera pagina con un fallback di errore materializzato.
```

## Caso 18 — Documentari con ranking semantico

Costruisce pool raggruppati di documentari simili, applica promozioni su più
tassonomie e separa fallback annidato e pagina sostitutiva su errore.

### Prompt 1

<!-- prompt:case_18:1 -->
```text
Crea un nuovo endpoint con una riga di documentari del catalogo video simili al contenuto visto.
```

### Prompt 2

<!-- prompt:case_18:2 -->
```text
Usa contentId come seed e restituisci 24 risultati; ricevi anche i canali della subscription e conserva i canali disponibili sul seed.
```

### Prompt 3

<!-- prompt:case_18:3 -->
```text
Costruisci due pool da 150 documentari simili al fingerprint del seed, escludendo clip, stagioni, serie, il contenuto corrente e la stessa serie; raggruppa per serie, tieni un elemento per gruppo e ordina per conteggio. Usa un percorso per canali diversi da Infinity e MediasetPlay e un percorso generale, promuovendo corrispondenze su temi, sottotemi, epoca, ambientazione, genere e tematismi.
```

### Prompt 4

<!-- prompt:case_18:4 -->
```text
Nel percorso generale deduplica la riga e, se gli elementi piatti annidati sono meno di uno, accoda un fallback documentari materializzato. Se l'esecuzione della variante produce un errore, sostituisci l'intera risposta con una pagina di errore materializzata.
```

## Caso 19 — Library editoriale a venti righe

Amplia una riga di fiction e serie in venti percorsi tematici, ciascuno con
Vedi tutto e filtri editoriali specifici.

### Prompt 1

<!-- prompt:case_19:1 -->
```text
Crea una pagina con i titoli del momento.
```

### Prompt 2

<!-- prompt:case_19:2 -->
```text
Catalogo video, 100 risultati totali per la pagina, con film e serie TV recenti.
```

### Prompt 3

<!-- prompt:case_19:3 -->
```text
Trasforma la pagina in venti righe tematiche: Famiglia, Cult anni 80 e 90, Misteri, Amori, Alto rischio, Divano e risate, Intrighi e inganni, Talenti, Amori tormentati, Detective, Attrazione, Medical, Storie commoventi, Rivali in amore, Altra epoca, Ricerche e scomparsi, Mafia, Storia vera, Religione e Famiglia in pericolo. Ogni riga deve mantenere il proprio take da 100, Vedi tutto e template POSTER.
```

### Prompt 4

<!-- prompt:case_19:4 -->
```text
Per ogni riga usa i metadati editoriali pertinenti fra basicplot, mood, generepatemico, generetematico, generediegetico, epoca e tematismi; quando una riga ammette due significati usa only best of. Escludi blacklist, formati 4K e contenuti non ammessi per geolocalizzazione; nelle righe familiari o comiche escludi anche soap opera e rating rossi quando appropriato.
```

## Caso 20 — Ventisei istanze parametriche e smart ordering

Genera due famiglie parallele di righe per genere, una personalizzata e una
anonima, e applica l'ordinamento intelligente solo al livello dei blocchi.

### Prompt 1

<!-- prompt:case_20:1 -->
```text
Voglio una riga di film simili per la sezione cinema.
```

### Prompt 2

<!-- prompt:case_20:2 -->
```text
Usa il catalogo video e dammi 30 risultati totali, usando il contenuto visto come seed.
```

### Prompt 3

<!-- prompt:case_20:3 -->
```text
Dichiara due blocchi parametrici: quello personalizzato riceve genere obbligatorio e scelta del Vedi tutto, applica il fingerprint storico quando esiste e usa POSTER; quello anonimo riceve il genere obbligatorio, usa il Vedi tutto standard e ordina per data. Crea 26 istanze complessive, tredici per blocco, per Azione, Commedia/Comico, Drammatico, Animazione, Fantascienza, Cinema italiano, Guerra, Thriller, Sentimentale, Family, Horror, Avventura e Musical/Musicale: sono 39 argomenti espliciti contando genere e scelta Vedi tutto nel percorso personalizzato.
```

### Prompt 4

<!-- prompt:case_20:4 -->
```text
Usa anche il catalogo users. La variante personalizzata deve attivarsi solo con fingerprint storico e più di tre visioni e deve riordinare le tredici righe per affinità al fingerprint; la variante anonima usa le altre tredici righe in ordine fisso. Mantieni distinti i due percorsi e non trasformare lo smart ordering delle righe in un ordinamento degli elementi interni.
```
