# Chiusura semantica dei cataloghi e backlog demo

Stato: **`@video` chiuso nel perimetro semantico; gli altri cataloghi restano
una coda esplicita e il hardening operativo della demo è un gate separato**.

Data di riferimento: 28 agosto 2026.

Questo documento impedisce che la chiusura del verticale `@video` venga
scambiata per la chiusura semantica dell'intero tenant o per la prova generale
della demo. I valori dei cataloghi restano contesto tenant-owned recuperato a
runtime: non entrano nei pesi di Model 1 e non autorizzano retraining.

## 1. Stato misurato di `@video`

La patch semantica è il commit
`play-demo/main@484768ed486281878c9e1bc61ab469ac6bd5e387`, contenuto nel `main`
corrente `f18819fc5fddd3a92dec34ab9ae928db51b621ce`:

- campi: `in=113 out=113 distinct=113 gaps=0`, tutti `reviewed`;
- campi finiti: `49`;
- ValueItem finiti: `in=1792 out=1792 distinct=1792 gaps=0`;
- ValueItem `reviewed=1782`, `draft=10`, `unannotated=0`;
- equivalenze fisiche esplicite: `57` concetti su `132` literal;
- superfici `aka` condivise che dichiarano tali equivalenze: `247`;
- gruppi condivisi che includono un nodo non reviewed: `0`;
- alias di campo discriminativi: `59` superfici su `36` campi, collisioni
  esatte tra campi `0`;
- alias di valore riusati tra campi diversi: `8`, tutti reviewed e mantenuti
  come ambiguità esplicite, mai come equivalenze.

I `10` draft non sono copertura mancante né un invito a indovinare:

- `published_flag`: `CMS`, `RDY`, `WKP`;
- `audio_language`: `afg`, `csk`, `ing`, `yug`;
- `last_live_channel_code`: `FT`, `KN`, `N4`.

Rimangono non eseguibili come superfici naturali finché un dizionario
tenant-owned autorevole non ne conferma il significato. Togliere `draft` solo
per ottenere uno zero cosmetico sarebbe una regressione semantica.

## 2. Contratto di equivalenza dei valori

Un unico concetto editoriale può corrispondere a più literal fisici legacy. Il
tenant lo dichiara ripetendo lo stesso `aka` reviewed su tutti e soli i
ValueItem equivalenti dello stesso catalogo e campo.

Il resolver host-owned accetta il gruppo soltanto se:

1. i membri sono almeno due;
2. appartengono allo stesso catalogo e campo;
3. sono tutti ValueItem `reviewed`;
4. ogni membro contiene esattamente la stessa superficie `aka`;
5. il roster proposto coincide con l'intero roster che porta quell'alias;
6. non esistono membri draft omessi, target extra o altri portatori della
   stessa superficie su un campo differente dello stesso catalogo.

L'esito è un unico vincolo `any_of` con tutti i literal fisici. Il consumer DSL
deve abbassarlo a membership (`in [...]`) per un campo scalare e a intersezione
non vuota (`has any [...]`) per un campo multi, quindi compilarlo e verificarlo.
Un alias ripetuto tra campi diversi resta un'ambiguità e richiede chiarimento.
L'ordine dei literal è deterministico ma non ha significato editoriale.

Questo contratto evita entrambe le scorciatoie scorrette:

- scegliere una sola variante e perdere record reali;
- normalizzare o riscrivere i literal legacy nel catalogo o nell'indice.

La grammatica e il compilatore Metis supportano già entrambi gli abbassamenti.
Model 1 non possiede ancora l'emitter grounding -> `.metis`: è un seam della
wave applicativa Brain/Fast, non un motivo per cambiare grammatica o mettere i
valori nei pesi. Prima della demo end-to-end dovrà emettere la forma coerente
con la cardinalità, compilarla col toolchain pinnato e verificare che il roster
IR coincida esattamente con quello adjudicato.

## 3. Coda degli altri cataloghi nel checkout corrente

Il censimento del checkout corrente contiene cinque cataloghi e chiude il
roster a `in=167 out=167 distinct=167 gaps=0` campi:

| Priorità | Catalogo | Campi | Stato semantico corrente | Prossima consegna |
|---|---|---:|---|---|
| chiusura corrente | `video` | 113 | 113 reviewed; valori come §1 | mantenere receipt e regressioni |
| P0 | `users` | 9 | 9 senza semantica | significato, privacy, domini e alias per richieste utente |
| P1 | `video_pg` | 40 | 40 senza semantica | descrivere il mirror PostgreSQL e riferire il vocabolario `@video` |
| P1 | `smart_index` | 3 | 3 senza semantica | pagine smart e similarità editoriale |
| P2 | `user_session` | 2 | 2 senza semantica | fingerprint e sessione runtime |

`video_pg` non deve copiare i `1792` valori di `@video`: duplicare il
vocabolario creerebbe due fonti di verità. Serve un collegamento semantico
esplicito al catalogo proprietario e un gate che ne provi la compatibilità.

I cataloghi nominati dal piano superiore ma assenti dal checkout corrente non
vengono inventati né contati come completati. Entrano nel roster soltanto
quando una revisione tenant pinnata li materializza.

Per ciascun catalogo la pipeline è sempre:

```text
census tecnico completo
  -> disposizione dei domini (finito | open | none motivato)
  -> means/aka con review frontier
  -> controllo collisioni ed equivalenze
  -> indice retrieval derivato
  -> grounding reale + compiler/oracle
  -> receipt e promozione separata
```

## 4. Hardening della demo: coda distinta

La proposta esterna contiene tre verifiche operative utili, ma non sono prove
di qualità semantica e non vengono dichiarate eseguite da questa wave:

1. riesecuzione reale del momento diagnostico M6 e aggiornamento del runbook;
2. diagnosi e warm-up controllato dell'endpoint PostgreSQL a freddo;
3. click-through Grafana log -> trace -> log in prova generale.

Prima di M6 va risolta una contraddizione nella proposta ricevuta: il testo
indica sia `search:play-demo:video` sia
`metis_breaker_state{target="search:play-demo:users"}` come target atteso. Il
run non deve essere costruito su un'attesa incoerente. Questi tre punti
richiedono il repository/runtime Metis, i servizi locali e l'autorità sui
secret della demo; restano quindi una wave autonoma con receipt osservata.

## 5. Elementi della proposta non adottati alla cieca

- I denominatori `1628`, `sette draft` e `un solo aka` fotografano uno stato
  precedente e non sono più utilizzabili.
- `finito = zero draft` non vale quando manca l'autorità sul significato: il
  criterio corretto è zero nodi non disposti, draft tutti quarantinati e zero
  draft utilizzati per una risoluzione naturale.
- La versione VSIX `0.23.94` non diventa un prerequisito finché pacchetto,
  digest e compatibilità non sono pubblicati e verificati. La baseline minima
  già verificata per `means`/`aka` resta `0.23.93`.
- Le quattro ratifiche di grammatica (soft keyword `label`, doppio span del
  ValueItem, preservazione byte dei superstiti del sync e `means` al posto dei
  commenti) vanno controllate nel piano upstream consegnato dal team
  proprietario; questa repository non duplica né modifica quell'autorità.

## 6. Gate di chiusura

`VIDEO_SEMANTIC_EQUIVALENCE_READY` richiede insieme:

- roster e stati del §1 ricomputati dal parser;
- `57` concetti equivalenti / `132` literal, zero gruppi unsafe;
- `59` alias discriminativi di campo senza collisioni e gli `8` riusi di alias
  fra valori di campi diversi ancora fail-closed;
- test resolver v1 e adjudicator v2 su roster completo, incompleto, draft,
  extra e cross-field;
- replay sul tenant reale di una richiesta multi-concetto;
- parser, validator, R8, sync e compiler invariance verdi;
- diff tecnico dei literal/tipi/modificatori/domìni invariato;
- `make check` Model 1 verde oppure failure dichiarata e attribuita senza
  alterare il gate.

Il gate chiude `@video`, non `SEMANTIC_CATALOG_READY` globale. Quest'ultimo
resta aperto finché la coda del §3 non è materializzata e verificata.
