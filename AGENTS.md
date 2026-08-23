# AGENTS.md

Instructions for AI agents working in this repository.

## Read first

- `README.md` for layout and commands.
- `docs/CURATION.md` before touching anything under `data/curated/`.

## Ground rules

- `data/raw/` is generated output. Never hand-edit it; run `fetch-reciters` to refresh it.
- `data/curated/reciters/` is manually maintained. Never regenerate or bulk-edit these files. Propose changes, apply only what was asked, then verify with `audit-reciters --strict`.
- `data/curated/reciters/` is the source of truth. `data/curated/catalog.json` is the generated `reciter -> riwayat -> styles -> providers` view built from those Markdown files. Never hand-edit it; when the two disagree, fix the authoritative Markdown if needed, then run `generate-catalog`.
- Curated file format and workflow are specified in `docs/CURATION.md`. Follow it exactly: `#name` header with `en:`/`ar:` lines, one section per provider tag (`QFS`, `QFA`, `MP3`, `EA`), raw JSON pasted verbatim.
- New providers require every touch point in the `docs/CURATION.md` checklist: a fetcher registered in `PROVIDERS`; a `SectionSpec` in `AUDIT_SECTIONS`; the curated tag in `REQUIRED_SECTIONS`; its public provider key in `_SECTION_PROVIDER`; explicit classification and `build_catalog` dispatch; the tag in `templates/_template.md`; and matching documentation plus parser, audit, and catalog tests.
- Tests are `unittest`. Run the full suite with `python3 -m unittest discover -s tests` after any code change.
- No runtime dependencies; keep it that way.

## Verification

Before finishing any task:

1. `python3 -m unittest discover -s tests`
2. If curated data changed: `audit-reciters --strict` and report the result.
3. If catalog inputs or generation changed: `generate-catalog --check` and report the result.
