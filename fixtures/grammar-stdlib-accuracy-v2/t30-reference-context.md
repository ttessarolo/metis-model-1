# Metis 0.43 grammar and standard-library reference — T30 v2

This is the generic retrieval context for the fresh T30-v2 evaluation. It is
derived from the pinned Metis grammar and standard-library registry. It is not
tenant data, a training example, or an answer to any benchmark task. Every
complete source document starts with exactly `metis 0.43`.

## Output discipline

- For a source task, return one complete Metis document and no prose or
  Markdown fence.
- For a JSON task, return one JSON object and no prose or Markdown fence.
- Use every identifier, literal, endpoint-selection target, and requested edit
  stated by the task. Do not substitute generic names.
- Examples below use parser-clean `reference_*` identifiers. They illustrate
  syntax only and must never replace task-supplied identifiers or literals.
- Keywords are not generally legal qualified-name segments. In particular,
  do not use the reserved keyword `feed` as a name segment. Use an ordinary
  identifier such as `reference_clock_endpoint`.

## Canonical top-level vocabulary

The grammar admits exactly these ten top-level alternatives. JSON review and
explanation tasks use the AST label in the second column, never the lowercase
surface keyword.

| Surface form | Canonical AST label | Name used in `declarations` |
| --- | --- | --- |
| `tenant <name> { ... }` | `Tenant` | `<name>` |
| `catalog <name> { ... }` | `Catalog` | `<name>` |
| `property <name> { ... }` | `Property` | `<name>` |
| `endpoint <name> ... { ... }` | `Endpoint` | `<name>` |
| `preset <name> from ...` | `Preset` | `<name>` |
| `list <name> ...` | `List` | `<name>` |
| `transformer <name> { ... }` | `Transformer` | `<name>` |
| `block <name> { ... }` | `NamedBlock` | `<name>` |
| `settings <name> { ... }` | `SettingsDecl` | `<name>` |
| `values <catalog-name> { ... }` | `ValueSet` | `<catalog-name>` |

`top_levels` is the first-use-deduplicated sequence of these AST labels. Walk
the source in declaration order and recursively walk endpoint members in
source order. Every named block is a `NamedBlock`, including a top-level
`block`, a direct endpoint `block`, a block inside `blocks { ... }`, and a block
inside a variant. Nested blocks therefore contribute `NamedBlock` even though
their surface occurrence is not a document-level declaration. The
`declarations` array emits every distinct `{kind,name}` declaration encountered
by that same recursive walk and deduplicates an exact repeated pair at first
use.

## Parser-clean complete skeleton

This one document illustrates all ten top-level alternatives, all three
catalog-domain representations, both compact endpoint-variant forms, ambient
time, and pure standard-library calls. Its identifiers are examples only.

```metis
metis 0.43
tenant reference_world {}

settings reference_world.time {
  timezone "UTC"
}

catalog reference_video {
  driver opensearch
  index "reference_video_index"
  id video_id
  fields {
    video_id keyword
    availability keyword values ["free" "premium"]
    status keyword enum(3)
    title keyword open
  }
}

values reference_video {
  status editorial ["draft" "ready" "published"]
}

property reference_clock_policy {
  needs time
  attributes open_now = time.hour >= 9
}

preset reference_recent from @reference_video include where @status is "ready"

list reference_labels static {
  "first"
  "second"
}

transformer reference_text {
  in request { title text raw text }
  set decoded = std.codec.decode("url", $raw)
  set encoded = std.codec.encode("base64", $raw)
  set slug = std.text.slugify($title)
  set short = std.text.truncate($title, 80)
  set clean = std.text.normalize($title)
  out response { decoded text encoded text slug text short text clean text }
}

block reference_card {
  take 1 from @reference_video include using preset.reference_recent
  take 1 from list.reference_labels
}

endpoint reference_clock_endpoint as "reference_clock_endpoint" {
  needs time
  attributes observed = time.now exists
  block endpoint_card { take 1 from @reference_video }
  variant primary if time.hour >= 0 use block.endpoint_card
  variant empty_state empty
}
```

## Grammar surface

### Settings

The ordinary form is a sequence of key/string pairs:

```metis
settings reference_world.time {
  timezone "Europe/Rome"
}
```

The name is an identifier followed by zero or more settings-group segments.
Settings keys may be kebab-case. Settings also admit preview-input declarations
and editor links:

```metis
settings reference_world.preview {
  input content_id values ["Example" group "Editorial" id "content-1"]
  input session_id random
  "Observability" group "Tools" at "http://localhost.invalid"
}
```

The registered standard-library setting is exactly `time.timezone`; its source
form is `settings <namespace>.time { timezone "<IANA name>" }`. Under the pinned
toolchain an unknown key in a `.time` group can be parser-valid and reported as
a warning rather than a parser error. A task in the
`timezone-setting-invalid-key` interaction class repairs that warning to the
warning-free canonical key `timezone`; it must not describe the input as
parser-invalid.

### Tenant

```metis
tenant reference_world {
  input locale text default "it"
  params timeout standard
  boost { subtle 2 default subtle }
  providers reference_provider from fixture "reference"
  personas { editor default { locale "it" } }
  in -> transformer.reference_text
}
```

A tenant body may contain request inputs, params, scales, services, providers,
personas, and `in`/`out` pipelines. A plural input block is
`inputs { name type ... }`; a single input is `input name type`.

### Catalog, fields, and value domains

```metis
catalog reference_video {
  driver opensearch
  index "reference_video_index"
  id video_id
  similarity title
  similarity editorial_profile from { @title @summary }
  fields {
    video_id keyword
    owner ref @reference_people
    metadata object { code keyword enum(4), label text }
    tags keyword multi enum(12)
    title keyword open
  }
  returns default { video_id title }
}
```

A catalog may declare `driver`, either `index` or `keyspace`, `id`, a scalar
similarity field, named similarity profiles, fields, and return projections.
Fields use `name type`, followed by modifiers, one optional domain, optional
logical-field aliases, and optional field members. Types are a simple type,
`ref @catalog`, or `object { ... }`. Modifiers include `multi`, `ordered`,
`sort <mode>`, and `indexed as "<wire-name>"`.

There are three canonical domain classes:

- Tiny stable inline domain: `status keyword values ["draft" "ready"]`.
  The historical bracket-only spelling is parseable, but emit the explicit
  `values` keyword when authoring canonical source.
- Bounded external domain: `status keyword enum(37)`. Values are absent from
  the catalog skeleton and live in the same-catalog external value-set.
- Open or enormous live-index domain: `title keyword open`. It has no
  materialized value list.

An external value-set always states the nature of every field entry:

```metis
values reference_video {
  status editorial ["draft" "ready"]
  genre reflected ["drama" "news"]
}
```

`editorial` means the redaction owns the list. `reflected` means the sync tool
regenerates it from the index. Do not emit `values reference_video { status
[... ] }`: omitting `editorial` or `reflected` is invalid. Domain thresholds are
tenant settings and are never hard-coded by the model.

### Property and endpoint family members

```metis
property reference_clock_policy {
  input locale text
  needs time
  context recent = take 4 from @reference_video
  attributes { morning = time.hour < 12 weekday = time.weekday is "monday" }
  out -> transformer.reference_text
}

endpoint reference_clock_endpoint as "reference_clock_endpoint" {
  input locale text
  needs time
  attributes instant_available = time.now exists
  take 4 from @reference_video
  return response
}
```

Properties and endpoints share `params`, input declarations, `context`,
`attributes`, pipelines, and `needs`. Endpoints additionally admit pipeline
opt-outs, blocks, variants, takes, metadata, and `return response...`. Ambient
time is valid only when the containing property or endpoint declares
`needs time`.

### Blocks and variants

Top-level and endpoint blocks use the same explicit form:

```metis
block reference_card {
  take 1 from @reference_video
}
```

An endpoint can declare blocks directly or in a group. Variants can likewise be
direct or grouped. The two compact variant forms are exact:

```metis
endpoint reference_cards_endpoint as "reference_cards_endpoint" {
  input show_cards bool
  block card { take 1 from @reference_video }
  variant primary if $show_cards is true use block.card
  variant empty_state empty
}
```

Inside `variants { ... }`, the `variant` keyword is optional, but canonical
authoring keeps it. The block-selection form always contains `use` and the dot:
`variant <name> use block.<name>`. Empty output is exactly
`variant <name> empty`; do not wrap it in `variants { <name> use ... }` unless
the task asks for the grouped representation.

A block may contain metadata, params, block-parameter bindings, schedules,
takes, named take assignments, return flow, `use block.<name>`, or
`use blocks { ... }`. A parameterized block declares named parameters in its
head, for example `block cards(limit! number) { ... }`.

### Preset and list

```metis
preset reference_recent from @reference_video include where @status is "ready"

list reference_labels static {
  "first"
  "second"
}
```

A preset names a catalog and uses `exclude`, `include`, or `promote` followed by
`where` and one condition or a condition block. A list can be `static` or
`dynamic`, may declare `type <type>`, and contains quoted string items.

### Transformer

```metis
transformer reference_text {
  in request { title text raw text }
  set decoded = std.codec.decode("url", $raw)
  set slug = std.text.slugify($title)
  out response { decoded text slug text }
}
```

A transformer body admits `in`, `out`, `using`, `source`, `set`, `expires`,
take assignment, service call, merge, and drop members. Standard-library calls
are right-hand sides of `set` and use `std.<pure-module>.<member>(...)`.

### Takes, conditions, guards, and values

A take begins `take [count] from <source>`. Sources are a catalog (`@name`), a
catalog field, a list, or a context path. Its body can include include/exclude/
promote filters, ordering, grouping, limits, skip, metadata, return flow, and
block parameters. A one-clause body may omit braces; multiple clauses use
braces.

Conditions combine with `and`/`or`; guards additionally admit `not` and
parentheses. Field references start with `@`, request inputs with `$`,
attributes with `#`, context values with `context.`, block arguments with
`arg.`, ambient clock members with `time.`, and pure calls with `std.`. Values
include strings, numbers, durations, booleans, `empty`, string lists, list
references, and those operands.

## Complete pinned standard library

The registry is closed: three modules, twelve members, and one setting.

### Ambient module `time`

An endpoint or property using an ambient clock member must declare
`needs time`. A transformer can use a bare `time.<member>` operand, while the
endpoint/property call site owns the ambient capability declaration; transformer
grammar has no `needs` member. Ambient references never use the `std.` prefix.

| Source spelling | Canonical registry ID | Type |
| --- | --- | --- |
| `time.now` | `time.now` | string |
| `time.month` | `time.month` | number |
| `time.day` | `time.day` | number |
| `time.hour` | `time.hour` | number |
| `time.hhmm` | `time.hhmm` | number |
| `time.weekday` | `time.weekday` | string |
| `time.fractional_second` | `time.fractional_second` | number |

`time.month`, `time.day`, `time.hour`, `time.hhmm`, `time.weekday`, and
`time.fractional_second` are derived in the tenant timezone. `time.now` remains
the absolute request instant. The registry default timezone is `UTC`.

### Pure module `codec`

Pure modules are deterministic and always available. They must not appear in
`needs`.

| Source spelling | Canonical registry ID | Result |
| --- | --- | --- |
| `std.codec.decode("url", $raw)` | `codec.decode` | string |
| `std.codec.encode("base64", $raw)` | `codec.encode` | string |

The supported codec names are `url` and `base64`.

### Pure module `text`

| Source spelling | Canonical registry ID | Result |
| --- | --- | --- |
| `std.text.slugify($title)` | `text.slugify` | string |
| `std.text.truncate($title, 80)` | `text.truncate` | string |
| `std.text.normalize($title)` | `text.normalize` | string |

### Standard-library normalization and nature rules

For JSON arrays, normalize a pure source call by dropping only its legal source
prefix: `std.codec.decode` becomes `codec.decode`, and `std.text.slugify`
becomes `text.slugify`. Ambient `time.hour` remains `time.hour`. Deduplicate
each array by first source use.

These are distinct failure classes:

- `std.time.now` is a known ambient member used through the wrong namespace;
  it is a standard-library nature mismatch, not an invented symbol.
- `needs codec` or `needs text` names known pure modules in the wrong place;
  this is a nature mismatch, not an invented symbol.
- `time.hour` in an endpoint/property without its required `needs time` is a
  missing ambient capability, not an invented symbol. A transformer still uses
  bare `time.hour`; do not invent a transformer `needs` member.
- `std.unknown.member`, `std.codec.unknown`, and `needs unknown` assert a module,
  member, or capability absent from the closed registry; these are genuinely
  invented symbols.
- A legal surface alias in JSON, such as `endpoint` instead of `Endpoint`, or
  `std.codec.decode` instead of `codec.decode`, is a serialization-contract
  mismatch. The symbol exists and must not be reported as invented.

## F-4 exact JSON contract

Object key order is part of the output contract. The root keys are exactly:
`contract`, `status`, `top_levels`, `stdlib_members`, `stdlib_settings`,
`endpoint`. The endpoint keys are always exactly `count`, `mode`, `requested`,
`selected`, `variants`, in that order. `variants` is always an array, including
when it is empty.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "additionalProperties": false,
  "required": ["contract", "status", "top_levels", "stdlib_members", "stdlib_settings", "endpoint"],
  "properties": {
    "contract": {"const": "metis-source-review/v1"},
    "status": {"enum": ["ok", "invalid"]},
    "top_levels": {
      "type": "array",
      "uniqueItems": true,
      "items": {"enum": ["Tenant", "Catalog", "Property", "Endpoint", "Preset", "List", "Transformer", "NamedBlock", "SettingsDecl", "ValueSet"]}
    },
    "stdlib_members": {
      "type": "array",
      "uniqueItems": true,
      "items": {"enum": ["time.now", "time.month", "time.day", "time.hour", "time.hhmm", "time.weekday", "time.fractional_second", "codec.decode", "codec.encode", "text.slugify", "text.truncate", "text.normalize"]}
    },
    "stdlib_settings": {
      "type": "array",
      "uniqueItems": true,
      "items": {"enum": ["time.timezone"]}
    },
    "endpoint": {
      "type": "object",
      "additionalProperties": false,
      "required": ["count", "mode", "requested", "selected", "variants"],
      "properties": {
        "count": {"type": "integer", "minimum": 0},
        "mode": {"enum": ["source", "endpoint"]},
        "requested": {"type": ["string", "null"]},
        "selected": {"type": ["string", "null"]},
        "variants": {
          "type": "array",
          "uniqueItems": true,
          "items": {"type": "string", "minLength": 1}
        }
      }
    }
  }
}
```

`mode` is the oracle request mode. `requested` is the endpoint target supplied
by that request; it is not inferred from the source. In `source` mode it is
`null`. In `endpoint` mode it is the exact target stated by the task. `selected`
is the endpoint actually selected by the compiler: for a successful
endpoint-mode request it equals `requested`; in source mode it is `null`.
`count` is the total number of endpoint declarations in the source. `variants`
contains every variant name in recursive source preorder, deduplicated at first
use; use `[]` when there is no variant.

All three arrays use recursive source first-use order and contain each canonical
value at most once. A valid surface alias serialized instead of the canonical
label or registry ID is `contract_mismatch`, not `invented_symbol`.

## F-6 exact JSON contract

Object key order is part of the output contract. Root keys are always exactly
`contract`, `top_levels`, `declarations`, `catalog_fields`, `stdlib_members`,
`stdlib_settings`, `relationships`, in that order. `catalog_fields` is always
present and is `[]` when the source has no catalog field.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "additionalProperties": false,
  "required": ["contract", "top_levels", "declarations", "catalog_fields", "stdlib_members", "stdlib_settings", "relationships"],
  "properties": {
    "contract": {"const": "metis-structural-explanation/v2"},
    "top_levels": {
      "type": "array",
      "uniqueItems": true,
      "items": {"enum": ["Tenant", "Catalog", "Property", "Endpoint", "Preset", "List", "Transformer", "NamedBlock", "SettingsDecl", "ValueSet"]}
    },
    "declarations": {
      "type": "array",
      "uniqueItems": true,
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["kind", "name"],
        "properties": {
          "kind": {"enum": ["Tenant", "Catalog", "Property", "Endpoint", "Preset", "List", "Transformer", "NamedBlock", "SettingsDecl", "ValueSet"]},
          "name": {"type": "string", "minLength": 1}
        }
      }
    },
    "catalog_fields": {
      "type": "array",
      "uniqueItems": true,
      "items": {
        "oneOf": [
          {
            "type": "object",
            "additionalProperties": false,
            "required": ["name", "domain"],
            "properties": {
              "name": {"type": "string", "minLength": 1},
              "domain": {"enum": ["implicit", "open"]}
            }
          },
          {
            "type": "object",
            "additionalProperties": false,
            "required": ["name", "domain", "size"],
            "properties": {
              "name": {"type": "string", "minLength": 1},
              "domain": {"enum": ["inline", "external-enum"]},
              "size": {"type": "integer", "minimum": 0}
            }
          }
        ]
      }
    },
    "stdlib_members": {
      "type": "array",
      "uniqueItems": true,
      "items": {"enum": ["time.now", "time.month", "time.day", "time.hour", "time.hhmm", "time.weekday", "time.fractional_second", "codec.decode", "codec.encode", "text.slugify", "text.truncate", "text.normalize"]}
    },
    "stdlib_settings": {
      "type": "array",
      "uniqueItems": true,
      "items": {"enum": ["time.timezone"]}
    },
    "relationships": {
      "type": "array",
      "uniqueItems": true,
      "items": {"enum": ["settings-configures-timezone", "endpoint-declares-needs-time", "property-declares-needs-time", "pure-stdlib-call", "no-ambient-needs", "valueset-belongs-to-catalog", "endpoint-owns-block", "variant-selects-block", "external-enum-domain"]}
    }
  }
}
```

For `catalog_fields`, use recursive source field preorder and deduplicate an
exact repeated field record at first use. `implicit` and `open` omit `size`;
`inline` and `external-enum` include the exact integer `size`. Do not serialize
inline literal values in this compact structural contract.

Declarations use recursive source preorder with exact-object first-use
deduplication. For `ValueSet`, `name` is its catalog name. For every
`NamedBlock`, `name` is its block name. Standard-library arrays use canonical
registry IDs and first-use deduplication.

Relationships are a set rendered in deterministic first-evidence order. Emit
each applicable label exactly once:

1. Walk top-level declarations in source order.
2. For a `.time` settings declaration containing `timezone`, emit
   `settings-configures-timezone`.
3. For a catalog containing at least one `enum(N)` marker, emit
   `external-enum-domain`.
4. For a value-set, emit `valueset-belongs-to-catalog`.
5. For a property declaring `needs time`, emit
   `property-declares-needs-time`.
6. For a transformer containing at least one pure standard-library call, emit
   `pure-stdlib-call`; if it contains neither an ambient time reference nor an
   ambient `needs` declaration, then emit `no-ambient-needs` immediately after
   it.
7. For an endpoint, emit applicable labels in this tie order:
   `endpoint-declares-needs-time`, `endpoint-owns-block`,
   `variant-selects-block`. A compact `variant <name> empty` does not select a
   block.
8. If a label was already emitted, do not emit it again.

Wrong key order, extra keys, duplicate set-like array entries, a lowercase
surface kind, or an unnormalized legal `std.` name is a contract mismatch.
Only an asserted grammar label, module, member, setting, or capability absent
from the pinned vocabularies is an invented symbol.

## Required standard-library interaction boundaries

The evaluation distinguishes these ten interaction classes:

- `ambient-valid-needs-time`: `time.<member>` with `needs time`;
- `ambient-invalid-std-namespace`: known ambient `time` incorrectly called as
  `std.time.<member>`;
- `ambient-missing-needs`: an endpoint/property uses `time.<member>` without
  `needs time`;
- `pure-valid-no-needs`: `std.codec.*` or `std.text.*` without `needs`;
- `pure-invalid-needs`: known pure `codec` or `text` incorrectly placed in
  `needs`;
- `unknown-stdlib-module`: an unregistered module under `std.`;
- `unknown-stdlib-member`: an unregistered member of a registered module;
- `unknown-needs-capability`: an unregistered name in `needs`;
- `timezone-setting-valid`: canonical `time.timezone` configuration;
- `timezone-setting-invalid-key`: a parser-valid unknown key in a `.time`
  settings group, repaired to warning-free `timezone`.

Known-symbol nature errors and missing capability declarations are semantic
contract failures, but they are not invented-symbol failures. Unknown registry
identities are genuinely invented symbols. Successful repair/review of these
boundaries receives coverage credit only when the final task result is correct.
