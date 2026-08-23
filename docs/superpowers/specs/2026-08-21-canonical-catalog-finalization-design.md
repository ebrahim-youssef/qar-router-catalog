# Canonical Catalog Finalization Design

## Purpose

Finalize the repository's data foundation before any public SDK work. The end state is a reproducible offline pipeline in which provider snapshots are audited against manually resolved per-reciter Markdown files and a deterministic generator derives `data/curated/catalog.json` solely from those Markdown files.

Correctness, preservation of existing curation, and explicit unresolved metadata take precedence over completeness. The migration must not infer reciter identity, riwayah, style, or capability merely to make generation succeed.

## Current repository state

The current implementation already provides:

- a dependency-free Python 3.11 package under `src/reciter_fetcher/`;
- provider-specific fetchers registered in `PROVIDERS`;
- concurrent fetch execution with atomic replacement of successful raw files;
- separate Quran Foundation chapter and ayah provider domains;
- raw snapshots under `data/raw/`;
- 261 manually resolved reciter Markdown files under `data/curated/reciters/`;
- an audit that checks coverage, stale IDs, duplicates, malformed snippets, missing name headers, and strict snippet equality;
- a manually polished `data/curated/catalog.json`.

The current catalog is organized as `reciter -> style -> riwayah -> providers`. The approved target is `reciter -> riwayah -> style -> providers`. This is an intentional schema migration, not a claim that the existing file already uses the target order.

There is no authoritative catalog generator today. Some EveryAyah classification metadata has already been copied into Markdown, while the current strict audit still reports missing name headers and Quran Foundation ayah snippet drift. The existing catalog must remain protected until a generated candidate has been proven to preserve its curated meaning.

## Data ownership

The pipeline has four ownership layers:

1. Provider APIs are external truth.
2. `data/raw/` files are replaceable provider snapshots and remain close to upstream schemas.
3. `data/curated/reciters/*.md` files are the manually maintained canonical identity and mapping source of truth.
4. `data/curated/catalog.json` is deterministic generated output consumed by the future SDK.

Provider-specific names, IDs, fields, and availability metadata remain attached to provider bindings. The canonical layer does not flatten genuinely different provider concepts into one invented common schema.

## Canonical identity model

Each Markdown filename stem is the canonical reciter ID. Its `#name` section supplies the canonical English and Arabic names. Provider sections retain their existing tags:

- `QFA`: Quran Foundation ayah audio;
- `QFS`: Quran Foundation surah/chapter audio;
- `MP3`: MP3Quran;
- `EA`: EveryAyah.

QFA and QFS are independent provider domains even when their numeric IDs overlap. Audit uniqueness and catalog bindings are scoped by provider tag, never by a shared Quran Foundation ID space.

The generated hierarchy is:

```text
reciter
  -> riwayat
    -> styles
      -> providers
```

The leaf identifies one exact recording combination: canonical reciter, riwayah, and style. Provider bindings beneath that leaf remain arrays because one provider can expose multiple bindings, qualities, servers, or representations for the same recording.

Canonical riwayah and style values are open strings validated as non-empty normalized slugs. The generator may contain explicit mappings for terminology present in supported providers, but the schema is not closed to only today's values.

## Provider normalization

Normalization is deterministic and source-based:

- QFS obtains style and riwayah from its structured `style` and `qirat` metadata.
- QFA has style metadata but no upstream riwayah field. Its riwayah must be explicit curated Markdown metadata established during the bootstrap migration; it is not inferred during routine generation.
- Each MP3Quran `moshaf` is a distinct recording binding. Its provider metadata supplies the moshaf name and IDs used by explicit normalization rules. Unknown terminology remains unresolved and fails generation with file, provider, and entry identifiers.
- EA has no sufficient upstream classification metadata. Its existing curated-only `style`, `riwaya`, and optional `dead` fields remain the explicit source. `dead: true` entries remain auditable but are excluded from generated recording leaves.

The one-time migration may copy a classification from the existing catalog back into the exact corresponding Markdown provider entry when the match is unambiguous by canonical reciter, provider domain, and provider identifiers. It may not create classifications that are absent from both sources.

## Provider bindings and capabilities

Generated provider keys use explicit domain names:

- `quranFoundationAyah`;
- `quranFoundationSurah`;
- `mp3Quran`;
- `everyAyah`.

Bindings preserve provider-specific metadata in the catalog's established camelCase representation where compatibility is useful. Normalization must be lossless for fields retained by the existing polished catalog.

Stable capabilities are emitted only when supported by the provider domain and available source data:

- Quran Foundation ayah: granularity `ayah`; representation is recorded only if the source establishes `standalone` or `segment`.
- Quran Foundation surah: granularity `surah`, representation `standalone`.
- MP3Quran: granularity `surah`, representation `standalone`.
- EveryAyah: granularity `ayah`, representation `standalone`.

The generator must not label the legacy Quran Foundation `Streaming` name as a representation without source evidence. Streaming is a transport characteristic, not the inverse of segmentation. Unknown capability details are omitted or reported, never guessed.

Exact URLs, timestamps, and volatile per-resource availability remain provider/runtime concerns. Existing stable MP3Quran `surahList` and `surahTotal` metadata may remain in bindings because they are already supplied cheaply in the provider snapshot; the project will not add a new universal availability schema in this task.

## Bootstrap migration

The existing catalog is protected input during migration. The bootstrap proceeds in four stages:

1. Parse every Markdown file and the existing catalog into comparable recording/binding identities.
2. Produce a structured comparison of catalog-only metadata, Markdown-only metadata, exact matches, and conflicts.
3. Apply only unambiguous catalog-to-Markdown backfills, preserving raw snippets except for explicitly allowed curated metadata fields or the required canonical `#name` block.
4. Generate a candidate catalog from Markdown and compare it semantically with the existing catalog before replacing the generated file.

Comparison accounts for the intentional hierarchy reorder and deterministic ordering. A changed traversal order is not data loss. Missing recordings, provider bindings, provider identifiers, names, or provider metadata are data loss and block replacement.

Conflicts are reported with canonical reciter ID, provider domain, provider entry ID, old catalog path, Markdown file, and differing values. The migration never resolves those conflicts with fuzzy matching.

## Markdown parsing

Parsing builds on the audit's brace-aware JSON extraction rather than using regular expressions to parse nested JSON. The shared parser must:

- require a valid canonical `#name` section after the migration;
- require every known provider section header, allowing empty sections;
- accept the existing object snippets and EA keyed fragments;
- preserve multiple entries within a provider section;
- report malformed JSON, unbalanced braces, missing IDs, duplicate IDs, and unknown section classifications with file context;
- distinguish raw provider fields from the small documented set of curated-only fields.

The template is updated to include the required `#name`, `en:`, and `ar:` lines so newly curated files conform to the parser contract.

## Catalog generator

A new `reciter_fetcher.catalog` module owns parsing, normalization, catalog construction, semantic comparison, and deterministic serialization. A thin `catalog_cli` module exposes generation without network access.

The CLI supports:

```text
generate-catalog --root <repository>
generate-catalog --root <repository> --check
```

Normal mode validates all sources, builds the catalog in memory, performs the configured preservation guard, and atomically writes `data/curated/catalog.json`. Check mode regenerates in memory and exits nonzero if the checked-in file is not byte-for-byte deterministic output or if any source error exists.

Dictionary keys and provider arrays use stable ordering. JSON is UTF-8, Arabic remains unescaped, indentation is two spaces, and the file ends with one newline.

The normal generator must not depend indefinitely on the old catalog. The existing catalog is used only by a separate bootstrap/compare workflow. Once semantic equivalence is proven and Markdown is complete, routine generation and `--check` read only Markdown.

## Audit changes

The existing `audit-reciters` command remains the raw-to-curated coverage gate. It is extended to share Markdown parsing primitives with the generator and to report:

- raw provider entries absent from curated Markdown;
- curated provider IDs absent from current raw snapshots;
- duplicate provider IDs within or across canonical reciters;
- malformed snippets and missing required provider identifiers;
- missing canonical names or provider section headers;
- strict raw-snippet drift after ignoring only documented curated-only fields;
- classification metadata missing for an entry that must enter the catalog;
- unsupported or conflicting normalization terminology.

Audit output remains actionable and deterministic. JSON output contains stable structured issue codes in addition to human-readable messages. No fuzzy merging or automatic identity resolution is added.

## Error handling and safety

All write paths are atomic. Source parsing and catalog construction complete successfully before any generated file is replaced. A failed provider refresh preserves the old raw snapshot, and a failed catalog build preserves the old catalog.

Errors identify the precise Markdown file, section, provider ID, and field where possible. Unknown riwayah/style values are retained as explicit unresolved issues rather than coerced to `hafs`, `murattal`, or `unknown` recording branches unless `unknown` already represents an intentional curated value.

The bootstrap command defaults to report-only behavior. Applying Markdown changes requires an explicit flag and writes only changes proven to come from the existing catalog. This makes the one-time migration reviewable before the generator becomes authoritative.

## Testing strategy

Implementation follows red-green-refactor cycles with standard-library `unittest`:

- parser tests for headers, multiple snippets, EA fragments, malformed JSON, and missing identifiers;
- normalization tests for all four provider domains and unresolved terminology;
- generator tests for hierarchy, separate QFA/QFS bindings, deterministic ordering, Unicode, dead EA exclusion, and atomic failure behavior;
- comparison tests proving hierarchy reordering is semantically neutral and missing metadata blocks replacement;
- bootstrap tests proving only unambiguous catalog metadata is backfilled and conflicts remain unchanged;
- audit regression tests for existing coverage/drift behavior plus new classification and section requirements;
- CLI tests for successful generation, `--check`, nonzero validation failures, and preservation of the old catalog on failure.

Repository-level validation includes the full unit suite, strict audit, two consecutive generation checks, and a semantic before/after report. A curated-data change is not accepted without a recorded strict-audit result, including any genuinely unresolved issues.

## Documentation and developer workflow

`README.md` and `docs/CURATION.md` are updated rather than creating competing workflow documents. A focused `docs/CATALOG_ARCHITECTURE.md` records ownership, schema, capability terminology, bootstrap history, and future-SDK boundaries.

The documented workflow is:

```text
fetch-reciters
  -> audit-reciters --strict
  -> manually curate reported differences
  -> generate-catalog
  -> generate-catalog --check
```

The documentation explicitly states that the public SDK, discovery API, defaults, audio resolver, media playback, caching, and frontend state are outside this task.

## Acceptance criteria

The task is complete when:

1. Every provider domain is explicit and QFA/QFS remain separate.
2. Markdown contains all curated information required to reproduce the accepted catalog, or every unresolved exception is reported without guessing.
3. The generator deterministically builds `reciter -> riwayah -> style -> providers` from Markdown alone.
4. Deleting and regenerating `catalog.json` loses no accepted canonical names, recording combinations, bindings, identifiers, or retained provider metadata.
5. Generation is offline and failed generation cannot damage the prior catalog.
6. Audit output covers mapping, staleness, duplication, malformed input, identifiers, drift, and missing classifications.
7. The full unit suite passes.
8. Strict audit results and any remaining ambiguities are documented accurately.
9. The repository documents fetch, audit, curate, generate, and check commands.
10. No public SDK implementation is introduced.

