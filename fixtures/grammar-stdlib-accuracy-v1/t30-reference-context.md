# Metis 0.43 grammar and standard-library reference

This compact reference is retrieved at inference time. It is public synthetic
toolchain context, not tenant data and not a training example. Every document
starts with `metis 0.43`.

## Top-level skeletons

The grammar admits these ten top-level alternatives:

```metis
tenant sample.world {}

catalog sample.video {
  id id
  fields {
    id keyword
    status keyword enum(3)
    title keyword open
  }
}

property sample.policy {
  needs time
  attributes open_now = time.hour >= 9
}

endpoint sample.feed as "sample_feed" {
  needs time
  attributes open_now = time.hour >= 9
}

preset sample.recent from @video include where @id is "1"

list sample.labels static { "first" "second" }

transformer sample.slug {
  in request { title text }
  set slug = std.text.slugify($title)
  out response { slug text }
}

block sample_card {
  take 1 from @video
}

settings sample.time {
  timezone "UTC"
}

values sample.video {
  status editorial ["draft" "ready" "published"]
}
```

`catalog` holds the field skeleton and similarity/search metadata. A tiny,
stable enum may remain inline. A bounded external domain is marked
`keyword enum(N)` and its values live in a same-catalog `values` declaration;
an open or enormous domain is marked `keyword open` and is retrieved from the
live index. Tenant settings own the thresholds; do not invent fixed cut-offs.

## Standard-library registry

`time` is ambient. An endpoint or property that uses it must declare
`needs time`; ambient members are referenced without `std.`:

- `time.now` -> string;
- `time.month`, `time.day`, `time.hour`, `time.hhmm`, and
  `time.fractional_second` -> number;
- `time.weekday` -> string.

`settings <namespace>.time { timezone "<IANA name>" }` configures derived
calendar values. The registry default is `UTC`; `time.now` remains the absolute
instant. The registered setting identity is `time.timezone`.

`codec` and `text` are deterministic pure modules. They are always available,
must not appear in `needs`, and are called under `std.` as the right-hand side
of a transformer `set`:

```metis
set decoded = std.codec.decode("url", $raw)
set encoded = std.codec.encode("base64", $raw)
set slug = std.text.slugify($title)
set short = std.text.truncate($title, 80)
set clean = std.text.normalize($title)
```

Known modules and members are closed by the pinned registry. Do not invent a
module or member, do not call ambient `time` under `std.`, and do not add
`needs codec` or `needs text`.

## Output discipline

When asked for source, return one complete `metis 0.43` document and no prose.
When asked for JSON, return exactly one JSON object and no Markdown.

## Generic repair cues

For endpoint variants, use the exact endpoint syntax `variant <variant> use block.<block>`; the form `<variant> block...` is forbidden.

When a diagnostic marker is supplied, copy it literally, including backticks and punctuation.
