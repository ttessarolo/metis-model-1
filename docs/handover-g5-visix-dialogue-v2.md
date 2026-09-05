# Handover G5: integrazione operazioni e dialogo VSIX v2

**Stato: CORE G5 VERIFICATO / CLIENT DA INTEGRARE.** Il gate completo
`make check TEST_WORKERS=2` è concluso con exit 0: 4.442 test passati,
due qualifiche opt-in saltate, zero fallimenti/errori; 4.444 casi distinti
senza omissioni. Receipt e hash sono nella
[lavagna](../orchestra/runs/2026-09-05-brain-generality/BLACKBOARD.md).
Questo handover non attesta un client live, una demo completa o qualità del modello.

## Contratto Brain disponibile

- `similarity_from_input` è un'operazione tipizzata
  in `brain_create_descriptor_operations.py`: `_similarity_mutations` richiede
  il profilo dichiarato e produce mutazioni sigillate. Due
  tenant rinominati (`north`, `south`) hanno compilato nel pin reale
  (`test_similarity_seed_producer_compiles_with_the_real_pin_on_renamed_tenants`). È evidenza
  limitata al compilatore, inclusa nel gate core, non una chiusura VSIX.
- Una return projection non è un enum universale `default`/`expanded`: Brain
  accetta solo il nome presente nelle `projections` del catalogo tecnico del
  take (`prepare_descriptor_operation` e `build_descriptor_operation`).
- `page_default` non è valido su un `NamedBlock`: il probe al pin reale lo
  verifica come `invalid` (`test_named_block_page_default_is_explicitly_rejected_by_the_real_pin`).
  La sola forma generica ammessa è `add_filtered_page`, che crea una nuova root
  variant con pagina default (`build_descriptor_operation`).

## Blocco prima del claim di Draft generico

Una forma pool-only può compilare con esito verde senza emettere una risposta.
Il percorso primo CREATE + add-block è stato corretto affinché emetta una
variant/use, con asserzioni sul normalized IR. Il gate completo resta quello
della lavagna: le sole receipt del compilatore non provano né un client live
né il risultato di una ricerca effettiva nell'indice.

## Mismatch VSIX esterno: parser v1 contro dialogo v2

L'integrazione VSIX è **read-only da questa wave**. La sua attuale superficie
non può consumare il payload di chiarimento v2 di Brain, che può portare fino a
32 decisioni (`MAX_DECISIONS`, `PendingClarificationV2` e
`ClarificationStore.create_pending_v2`). Sono stati
verificati senza modifica i seguenti punti del repository Metis esterno:

- `/Users/tommasotessarolo/Developer/ares-matioska/metis/tooling/src/extension/metis-brain-clarifications.ts:68`
  fissa `MAX_ROUNDS = 3`; `:202-216` rifiuta `max_rounds > 3`.
- Lo stesso file `:260-265` ammette solo la shape v1
  `clarification_id/kind/question/options/answer_schema` con tre metadati
  opzionali: campi v2 come `schema_version` e `questions` sono rifiutati.
- `metis-brain-client.ts:259-260` invoca quel parser per ogni
  `needs_clarification`; `:352-358` invia sempre una risposta
  `schema_version: 1`.
- Anche il summary client è limitato a tre round/decisioni in
  `metis-brain-client.ts:110, 132-154`.
- `metis-chat.ts:323-330` usa `schema_version: 2` per il turno iniziale, non
  per il payload di risposta a un chiarimento: non risolve il mismatch.

Il team VSIX deve quindi progettare e validare un consumer esplicito di
`metis-brain-dialogue/v2`, incluse domande bounded, riferimenti opachi,
risposte tipizzate e il budget 32. Non introdurre downgrade silenziosi a v1,
troncamenti di decisioni o conversioni di scelta in testo libero.

## Non dichiarato disponibile

Restano fuori dal claim: `view-all`, external fallback, grouping e relazioni
arbitrarie fra cataloghi; inoltre mancano la qualifica HTTP/VSIX di questa
superficie e la nuova prova della coorte complessa con inferenza.
Nessun catalogo, modello, inferenza, tenant o repository esterno viene
modificato da questo handover.

## Wire da implementare nel client

L'health annuncia `turn_schema_versions=[1,2]` e
`clarification_answer_schema_versions=[1,2]`. Il client deve verificare entrambe
le capability e mantenere la versione della conversazione, non dedurla dalla
sola forma del turno iniziale. Lo schema normativo è
[`metis-brain-dialogue-v2.schema.json`](../schemas/metis-brain-dialogue-v2.schema.json).

Un pending v2 contiene `clarification_id`, `questions[]`, `round`, `max_rounds`
ed eventualmente `expires_in_seconds`. Ogni domanda contiene `question_ref`,
`kind`, `question`, `answer_schema` e `options[]`: label e descrizione sono testo
da mostrare, gli `option_ref` sono riferimenti opachi da preservare. Non
ricostruire cataloghi, campi o valori dalle label nel client.

La route universale rimane
`POST /v1/sessions/{session_id}/turns/{parent_turn_id}/answer`.
Per la normale risposta nella chat, inviare l'envelope v2 con `message` e
`answers: []`; per una scelta guidata usare gli exact `question_ref` e i valori
tipizzati (`option_ref`, `option_refs`, `integer`) e `message: null`. Il messaggio
e le risposte possono coesistere, ma il client non decide se il testo introduce
nuovi requisiti: lo decide Brain. Serve sempre un nuovo `request_id` UUID;
sessione, parent turn e clarification devono restare quelli correnti.

Gestire esplicitamente risposte parziali, replay, revoca, snapshot cambiato,
scadenza e budget esaurito. Massimi: cinque domande per pending, 64 opzioni per
domanda, 32 round e 32 decisioni ammesse. I roster più lunghi sono paginati da
Brain. La cronologia privata ammette 64 messaggi ma conserva il precedente
tetto complessivo di 1.310.720 byte; TTL e memoria restano di sessione.

Il journey avversariale di sette operazioni usa 25 round, 28 decisioni e 32
messaggi/retrieval: dimostra continuità e limiti, non una UX ottimale. Il tetto
32 non è un obiettivo di conversazione. La riduzione delle domande quando i
requisiti sono già univoci va qualificata senza saltare il binding all'input
o la conferma delle operazioni non ancora autorizzate.

Gate client richiesto: chat naturale completa con retrieval a ogni risposta,
correzione prima del Draft, annullamento senza proposta, due refinement con
parent aggiornato, scadenza, budget e conflitto. Draft, Apply e ricompilazione
restano verifiche separate. L'implementazione di questo consumer è fuori dal
repository Model1 e non è stata eseguita in questa wave.

## Limite linguistico osservato

Nella fixture sintetica la richiesta lunga «Crea una collezione di storia
artica con 17 risultati totali» lascia residui non risolti (`collezione`,
`totali`), mentre «storia artica, 17 risultati» risolve. Il journey usa la
seconda formulazione per isolare il contratto di dialogo: non prova robustezza
del primo prompt in linguaggio libero, Flash o inferenza di Model 1. Questo
rimane un caso negativo da qualificare prima della demo, non una ragione per
aggiungere alias artificiali ai descrittori o scartare silenziosamente parole.
