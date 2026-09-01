# Architettura di Model 1

## 1. Architettura logica

Model 1 è intenzionalmente un sistema a tre strati:

| Strato | Contiene | Non deve contenere |
|---|---|---|
| Pesi: Qwen3.8 + adapter | Grammatica stabile, idiomi canonici, task behavior, repair/review patterns | Fotografie tenant, decisioni effimere, segreti |
| Contesto corrente | Simboli disponibili, file coinvolti, schema/versione, decisioni correnti | Esempi casuali non provenanced, interi repository senza selezione |
| Oracle eseguibile | Parser, linker, validator, formatter, compiler, IR e controlli di parità | Giudizi semantici non codificati presentati come certi |

Flusso di riferimento:

```text
requisito + checkout corrente
          |
          v
selezione contesto/provenance
          |
          v
Qwen3.8-27B + adapter Metis
          |
          v
patch o sorgente candidato
          |
          v
parse -> link -> validate -> compile -> semantic oracle
          |                         |
          +-- diagnostici ----------+
                       |
                       v
              massimo 1-2 repair loop
                       |
                       v
         output + evidence + limiti dichiarati
```

### Percorso Brain locale corrente

Metis Brain aggiunge un compilatore di intenti Flash prima del retrieval retry:

```text
richiesta -> output parser -> retrieval schema-2
                               |
                               +-- unsupported -> Gemma 4 E4B Flash
                                                    |
                                              Intent IR vincolato
                                                    |
                                         span esatti -> retrieval retry
                                                    |
                                      Model 1 -> grounding -> compiler -> Draft
```

Flash è un worker MLX separato, persistente e caldo, non un quarto livello di
autorità. Non emette Metis e non può scegliere tenant, catalogo, campo o valore.
Il suo `query` è advisory e non viene eseguito; solo testo esatto già scritto
dall'operatore può riattivare il retrieval. Il percorso è specificato in
[`28-metis-brain-flash-intent-compiler.md`](28-metis-brain-flash-intent-compiler.md).

## 2. Base model e checkpoint

**DECISO —** il modello logico è `Qwen/Qwen3.8-27B`.

**VERIFICATO al 20 agosto 2026 —** il checkpoint MLX candidato è
`mlx-community/Qwen3.8-27B-4bit`. È descritto come conversione MLX-VLM; pertanto
il percorso di training candidato è `mlx-vlm`, non `mlx-lm` e non il bundle
Ollama `qwen3.8:27b-mlx`. La compatibilità del checkpoint specifico non è
considerata acquisita: deve superare la qualification W4.

Il bundle Ollama resta utile solo per una prova d'inferenza informale. Non è la
base riproducibile del training perché nasconde parte della catena di conversione,
configurazione e identità dei file necessaria alla provenance.

Nel serving Brain corrente né Model 1 né Flash passano da Ollama: entrambi sono
worker JSONL locali supervisionati che usano MLX/MLX-VLM direttamente.

## 3. Adapter Metis

L'adapter è l'unità versionata e promuovibile. Deve restare separato dal base
model almeno fino alla conclusione delle ablation A/B/C/D.

Identità minima:

```text
adapter_id = hash(
  upstream_model_revision,
  mlx_checkpoint_revision,
  mlx_vlm_version,
  mlx_version,
  dataset_manifest_sha256,
  split_manifest_sha256,
  metis_source_commit,
  metis_language_version,
  training_config_sha256,
  random_seed
)
```

Non basta chiamarlo `metis-v1`. Un adapter privo di uno dei campi precedenti è
un esperimento locale non riproducibile e non può essere promosso.

## 4. Modalità di utilizzo

### Author

Input: intento strutturato, file rilevanti, simboli disponibili e vincoli.

Output: file completo solo per creazione; patch minimale per modifica. Il runner
verifica tutte le fasi applicabili e restituisce il diff semantico.

### Repair

Input: sorgente candidato, diagnostici strutturati e contesto minimo necessario.

Output: patch locale. Il numero di cicli è misurato; dopo il budget massimo il
sistema fallisce in modo trasparente invece di dichiarare successo.

### Review

Input: sorgente e obiettivo atteso.

Output: finding concreto, valore/simbolo coinvolto, prova eseguibile o limite
della prova, correzione suggerita. Un messaggio vago senza grounding non conta
come review corretta.

### Migrate

Input: sorgente, versione di partenza e versione target.

Output: trasformazione canonica verificata dal toolchain target e, quando
disponibile, equivalenza del comportamento compilato. Gli esempi di migrazione
devono essere marcati esplicitamente per non insegnare la sintassi obsoleta come
authoring corrente.

## 5. Contratto del compiler loop

Il loop non è un trucco per migliorare artificialmente il punteggio del modello;
è parte del prodotto e deve essere identico nelle baseline confrontate.

Per ogni tentativo si registrano:

- prompt/context hash e dimensione in token;
- output grezzo del modello;
- exit status di parser/linker/validator/compiler;
- diagnostici strutturati, senza credenziali o payload sensibili;
- patch successiva e numero del ciclo;
- risultato dell'oracle semantico;
- latenza, memoria di picco e token generati.

Il benchmark riporta separatamente first-shot e risultato entro il budget di
repair. Non è ammesso presentare il secondo come se fosse il primo.

## 6. Autorità del contesto

Il retrieval deve essere deterministico e osservabile:

1. identifica versione/commit Metis;
2. risolve i simboli necessari attraverso indici costruiti dal checkout;
3. seleziona solo file e decisioni pertinenti;
4. produce un manifest del contesto effettivamente fornito;
5. evita di includere target, derivati del target o benchmark siblings.

La stessa policy di contesto viene usata in A e B, e la stessa in C e D. Per il
confronto B contro D, il contesto deve essere identico byte per byte quando il
task lo consente.

## 7. Integrazione locale

Il primo runner deve poter:

- attivare/disattivare l'adapter con un flag;
- scegliere thinking/non-thinking in modo esplicito e registrarlo;
- imporre limiti di token e cicli;
- lanciare il toolchain Metis su un workspace temporaneo isolato;
- produrre un report machine-readable e uno leggibile;
- non scrivere nel checkout sorgente salvo un'azione umana separata;
- fallire closed quando compiler, manifest o versione non coincidono.

## 8. Direzione di prodotto ratificata

Model 1 sarà servito nella fase di sviluppo e demo da un'applicazione
installabile su macOS che ospita un servizio locale, acquisisce e verifica
separatamente base model e adapter e offre un'API locale versionata.
L'estensione Metis per VS Code sarà il client editoriale per authoring, editing,
repair, review e migrazione di endpoint reali; ogni modifica passa da toolchain,
preview/diff e conferma umana.

Il core Metis Brain v1 fissa già HTTP numerico loopback, autenticazione
bootstrap/sessione, capability, snapshot tenant immutabili, TTL idle di 20
minuti e compilazione pinnata. Non include ancora inferenza o integrazione
client.

L'inferenza è local-first. Fallback remoti o verso tool/modelli disponibili in
VS Code sono policy-controlled, visibili e auditabili, mai automatici o
silenziosi. Il contratto completo è in
[`19-local-companion-and-vscode-direction.md`](19-local-companion-and-vscode-direction.md).

## 9. Scelte deliberatamente rimandate

- protocollo di inferenza/streaming, pairing e workflow fra Metis Brain,
  estensione e Metis Fast;
- packaging, firma, updater e canale di distribuzione;
- provider e policy del fallback remoto;
- formato dell'artifact store per adapter e dataset;
- eventuale fusione per distribuzione;
- supporto di context window oltre 2.048 token durante il training;
- adapter distinti per author/repair o adapter unico multi-task;
- uso di DPO su preference pairs dopo la SFT.

Queste scelte dipendono dagli esiti di accuracy e dalle qualification di
prodotto; non devono essere anticipate dalla prossima wave del modello.

Il supporto Windows è esplicitamente fuori dal perimetro della demo. Sarà
valutato in una wave separata soltanto se il progetto verrà approvato.
