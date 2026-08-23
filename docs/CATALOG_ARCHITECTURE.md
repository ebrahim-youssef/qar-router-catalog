# Catalog architecture

## Scope

This repository provides a reproducible data foundation: provider snapshots, a manual canonical mapping layer, a strict audit, and an offline generator. It deliberately does **not** provide a public SDK, discovery API, default-selection policy, URL resolver, playback system, cache, availability service, or frontend state.

## Ownership model

| Layer | Owner and role |
|---|---|
| Provider API | External source of provider-specific IDs, labels, and transport metadata. |
| `data/raw/` | Generated replaceable provider snapshot; close to upstream shape. |
| `data/curated/reciters/*.md` | Reviewed canonical identity and mapping source of truth. |
| `data/curated/catalog.json` | Generated projection of curated Markdown; replaceable and never hand-edited. |

The generator reads curated Markdown only. It does not use the former catalog as routine input, make network requests, or apply fuzzy identity matching.

## Generated shape

The generated hierarchy is ordered and serialized deterministically as:

```text
reciter slug
  name: { ar, en }
  riwayat
    riwayah slug
      styles
        style slug
          providers
            provider-domain key: [binding, ...]
```

The provider keys are `quranFoundationAyah`, `quranFoundationSurah`, `mp3Quran`, and `everyAyah`. Binding values stay arrays because a provider can expose more than one concrete source for the same canonical reciter/riwayah/style combination: for example, multiple Quran Foundation records or multiple MP3Quran `moshaf` records.

Quran Foundation ayah (`QFA`) and surah (`QFS`) are separate domains and separate ID spaces. A shared integer or a similar label is not evidence that two provider records are the same binding.

## Normalization and explicit curation

The generator uses provider-local, deterministic rules where the source supports them:

- QFS uses structured raw `qirat` and `style` data.
- QFA requires curated `riwaya`; a raw null `style` additionally requires curated `catalog_style`.
- MP3Quran creates one binding per raw `moshaf`, using explicit provider IDs/types for riwayah and style mapping.
- EveryAyah requires curated `style` and, except for translations, curated `riwaya`; `dead: true` remains auditable but is omitted from generated output.

Unsupported terminology, malformed Markdown, missing names, or missing classifications are explicit failures. The generator does not silently coerce data into `hafs`, `murattal`, or `unknown`. A literal `unknown` appears only when a curator has intentionally written that normalized value.

## Provider domains are not capabilities

The four provider keys say where a binding came from; they are not a universal media-capability schema. Granularity and representation vocabulary is kept distinct:

- Granularity: `ayah` or `surah`.
- Representation: `standalone` or `segment`.

`standalone` means a provider exposes a self-contained resource at the stated granularity. `segment` means a resource is a portion of a larger asset; it is not the opposite of streaming. In particular, a source name containing “Streaming” does not prove a representation and the generator must not invent a `representation` field from it.

The current generated catalog keeps provider-specific binding metadata rather than asserting unproven universal capability fields. Capability claims should be added only when source evidence supports the relevant granularity and representation.

## Hybrid availability

Availability is intentionally hybrid rather than flattened into one universal boolean or URL. Stable availability hints already exposed by a provider remain on that provider binding (for example MP3Quran `surahList` and `surahTotal`); volatile URL resolution, transport status, timestamps, and per-resource reachability are runtime/provider concerns outside this catalog.

Consequently, catalog membership is not a promise that every individual media request will resolve at a later time. Known unavailable EveryAyah records are retained with curated `dead: true` for audit provenance and excluded from generated leaves.

## Deterministic generation and safety

`generate-catalog` parses all curated files, builds and sorts the complete catalog in memory, and writes UTF-8 JSON with unescaped Arabic, two-space indentation, and one final newline. It atomically replaces `data/curated/catalog.json` only after a complete successful build. `generate-catalog --check` writes nothing and fails unless the checked-in bytes exactly equal the regenerated serialization.

The workflow is:

```bash
fetch-reciters
audit-reciters --strict
generate-catalog
generate-catalog --check
```

After an initial bootstrap, deleting and regenerating `catalog.json` is lossless for accepted canonical names, normalized recording combinations, retained provider bindings, and retained binding metadata because the Markdown corpus is authoritative. It is not a replacement for raw snapshots: refreshes still require `fetch-reciters`, followed by strict audit and deliberate curation.

## Bootstrap history

`bootstrap-catalog` exists only to migrate safely from the former manually polished catalog. Its default/report-first mode compares that legacy catalog with Markdown and reports conflicts or exact candidate backfills. `--apply` is deliberately explicit and limited to reviewed, unambiguous legacy-derived fields. It is not part of ordinary refresh or generation, and it cannot justify invented metadata or fuzzy reciter merges.

The accepted migration completed the Markdown authority transition. Routine generation and checking now depend on curated Markdown alone.

