# Canonical Catalog Finalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make curated per-reciter Markdown the complete source of truth and generate the canonical catalog deterministically and offline without losing accepted curated information.

**Architecture:** A shared curated-Markdown parser feeds both the raw-data audit and a new catalog builder. Provider-specific normalizers create explicit QFA, QFS, MP3Quran, and EveryAyah bindings beneath `reciter -> riwayah -> style -> providers`; a guarded bootstrap migrates catalog-only facts into Markdown before an atomic generator replaces the old catalog.

**Tech Stack:** Python 3.11+, standard library only, `unittest`, JSON, Markdown fragments, setuptools console scripts.

**Spec:** `docs/superpowers/specs/2026-08-21-canonical-catalog-finalization-design.md`

## Global Constraints

- Keep Python runtime dependencies empty.
- Preserve Unicode Arabic with `ensure_ascii=False`.
- Never merge reciters by fuzzy matching.
- Never infer missing reciter identity, Arabic names, English names, riwayah, style, or representation.
- QFA and QFS are separate provider domains and separate ID spaces.
- Preserve raw provider fields; only documented curated-only fields may differ in strict audit comparisons.
- Do not hand-edit `data/raw/`; it is generated output.
- Curated Markdown is authoritative after the bootstrap; `catalog.json` is generated output.
- Generated hierarchy is `reciter -> riwayat -> styles -> providers`.
- Provider keys are exactly `quranFoundationAyah`, `quranFoundationSurah`, `mp3Quran`, and `everyAyah`.
- Capability vocabulary uses granularities `ayah` and `surah`, and representations `standalone` and `segment`; omit unsupported or unproven representation claims.
- Generation and comparison are offline, deterministic, fail loudly, and preserve the previous catalog on any failure.
- Use `unittest`; every production behavior is introduced by a failing test first.
- No public SDK, discovery API, resolver, playback, caching, or frontend state is implemented.
- This checkout has no accessible Git repository. Agents must not claim commits; each task report lists changed files and exact test output, and the controller creates before/after review packages from filesystem snapshots.

---

### Task 1: Shared curated-Markdown parser

**Files:**
- Create: `src/reciter_fetcher/curated.py`
- Create: `tests/test_curated.py`
- Modify: `src/reciter_fetcher/audit.py`
- Modify: `tests/test_audit.py`

**Interfaces:**
- Produces `CuratedIssue(code: str, file: str, section: str | None, entry_id: int | None, message: str)`.
- Produces `CuratedEntry(section: str, identifier: int, payload: dict[str, Any])`.
- Produces `CuratedReciter(slug: str, file: str, name_en: str | None, name_ar: str | None, sections: dict[str, list[CuratedEntry]])`.
- Produces `parse_curated_text(text: str, *, file_name: str) -> tuple[CuratedReciter, list[CuratedIssue]]`.
- Produces `load_curated_reciters(root: Path) -> tuple[list[CuratedReciter], list[CuratedIssue]]`.
- Existing audit APIs `extract_entries`, `split_sections`, `parse_name_header`, `audit`, `format_report`, and `report_to_json` remain compatible while delegating parsing to `curated.py`.

- [ ] **Step 1: Write failing parser tests**

Add literal fixtures to `tests/test_curated.py` that prove:

```python
class CuratedParserTests(unittest.TestCase):
    def test_parses_name_and_all_provider_sections(self):
        reciter, issues = parse_curated_text(FULL_MARKDOWN, file_name="example.md")
        self.assertEqual([], issues)
        self.assertEqual("example", reciter.slug)
        self.assertEqual("Example Reciter", reciter.name_en)
        self.assertEqual("قارئ", reciter.name_ar)
        self.assertEqual([7, 173], [entry.identifier for entry in reciter.sections["QFS"]])
        self.assertEqual([28], [entry.identifier for entry in reciter.sections["EA"]])

    def test_reports_missing_section_headers(self):
        _, issues = parse_curated_text("#name\nen:X\nar:س\n\n# QFS\n", file_name="x.md")
        self.assertEqual(
            ["missing_section", "missing_section", "missing_section"],
            [issue.code for issue in issues],
        )

    def test_reports_missing_identifier_and_malformed_json(self):
        _, issues = parse_curated_text(BROKEN_MARKDOWN, file_name="broken.md")
        self.assertEqual(["missing_id", "invalid_json"], [issue.code for issue in issues])
```

The fixture contains two QFS objects, one QFA object, one MP3 object with nested `moshaf`, and one EA keyed fragment so the tests exercise the real parser.

- [ ] **Step 2: Run the new tests and verify RED**

Run:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_curated.py' -v
```

Expected: import failure for `reciter_fetcher.curated`.

- [ ] **Step 3: Implement the shared parser**

Implement `curated.py` with the existing brace-aware `_read_string` and `_read_block` behavior moved from `audit.py`. Parse headings line-by-line, require `NAME`, `QFS`, `QFA`, `MP3`, and `EA`, and parse EA keyed fragments using the numeric key immediately preceding an object. Use stable issue codes:

```python
MISSING_NAME = "missing_name"
MISSING_SECTION = "missing_section"
INVALID_JSON = "invalid_json"
UNBALANCED_JSON = "unbalanced_json"
MISSING_ID = "missing_id"
DUPLICATE_ID = "duplicate_id"
```

`name_en` and `name_ar` remain `None` when the header line is absent or empty; the parser never fabricates values.

- [ ] **Step 4: Refactor audit to consume the parser**

Keep thin compatibility wrappers for currently imported helpers. Convert `CuratedIssue` values into existing `FileIssue` values so the current report format and tests remain stable. Ensure strict comparison ignores only `SectionSpec.curated_keys`.

- [ ] **Step 5: Run focused and full tests and verify GREEN**

Run:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_curated.py' -v
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_audit.py' -v
PYTHONPATH=src python3 -m unittest discover -s tests
```

Expected: all parser, audit, and existing tests pass.

- [ ] **Step 6: Write the task report**

Record changed files, the production mutation each test catches, both commands, full pass counts, and any parser compatibility concerns in the assigned task report.

---

### Task 2: Provider normalization and canonical tree builder

**Files:**
- Create: `src/reciter_fetcher/catalog.py`
- Create: `tests/test_catalog.py`

**Interfaces:**
- Consumes `CuratedReciter`, `CuratedEntry`, and `CuratedIssue` from Task 1.
- Produces `CatalogIssue(code: str, file: str, section: str, entry_id: int | None, message: str)`.
- Produces `build_catalog(reciters: Iterable[CuratedReciter]) -> tuple[dict[str, Any], list[CatalogIssue]]`.
- Produces `serialize_catalog(catalog: dict[str, Any]) -> str`.
- Produces `semantic_catalog(catalog: dict[str, Any], *, legacy: bool = False) -> dict[str, Any]` for preservation comparison.

- [ ] **Step 1: Write failing normalization tests**

Create hand-written `CuratedReciter` fixtures and assert literal target structures:

```python
def test_qfa_and_qfs_with_same_id_remain_separate_bindings(self):
    catalog, issues = build_catalog([RECITER_WITH_QFA_AND_QFS_ID_7])
    self.assertEqual([], issues)
    providers = catalog["example"]["riwayat"]["hafs"]["styles"]["murattal"]["providers"]
    self.assertEqual([{"id": 7, "reciterName": "Ayah Name", "style": None}], providers["quranFoundationAyah"])
    self.assertEqual(7, providers["quranFoundationSurah"][0]["id"])

def test_dead_everyayah_entry_is_not_generated(self):
    catalog, issues = build_catalog([RECITER_WITH_DEAD_EA])
    self.assertEqual({}, catalog)
    self.assertEqual([], issues)

def test_unknown_mp3_rewaya_id_is_reported_not_guessed(self):
    catalog, issues = build_catalog([RECITER_WITH_MP3_REWAYA_999])
    self.assertEqual({}, catalog)
    self.assertEqual(["unknown_riwayah"], [issue.code for issue in issues])
```

Add cases for QFS structured style/qirat, QFA curated classification, MP3 multi-moshaf splitting, EA translation with `riwaya: none`, deterministic provider-array order, Arabic serialization, and an unproven QFS `Streaming` entry that is included without a representation label.

- [ ] **Step 2: Run catalog tests and verify RED**

Run:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_catalog.py' -v
```

Expected: import failure for `reciter_fetcher.catalog`.

- [ ] **Step 3: Implement explicit provider mappings**

Use these exact MP3Quran riwayah mappings derived from the accepted catalog:

```python
MP3_RIWAYAH_BY_ID = {
    1: "hafs", 2: "warsh_an_nafi", 3: "khalaf_an_hamzah",
    4: "albazzi_an_ibnkatheer", 5: "qalun_an_nafi",
    6: "qunbul_an_ibnkatheer", 7: "alsusi_an_abiamr",
    8: "qalun_an_nafi_tariq_abinasheet",
    9: "ruways_and_rawh_an_yaqoub_alhadrami",
    10: "warsh_an_nafi_tariq_abibakr_alasbahani",
    11: "albazzi_and_qunbul_an_ibnkatheer",
    12: "aldouri_an_alkisai", 13: "aldouri_an_abiamr",
    15: "shubah_an_asim", 16: "ibndhakwan_an_ibnamer",
    18: "warsh_an_nafi_tariq_alazraq", 19: "hisham_an_ibnamer",
    20: "ibnjammaz_an_abijaafar", 21: "hafs", 22: "hafs",
}
```

Use `moshaf_type == 213` for `muallim`, `moshaf_type == 222` for `mujawwad`, and the currently accepted remaining listed types `{11, 14, 21, 31, 41, 51, 61, 71, 81, 91, 101, 111, 120, 121, 131, 151, 161, 181, 191, 201}` for `murattal`. Any unlisted type produces `unknown_style`.

QFA requires curated fields `riwaya` and, when raw `style` is null, `catalog_style`. Normalize its non-null raw styles with exactly `{"Mujawwad": "mujawwad", "Muallim": "muallim"}`. QFS uses its structured `qirat.name` and `style.name`, with exactly `QFS_RIWAYAH_BY_NAME = {"Hafs": "hafs"}` and `QFS_STYLE_BY_NAME = {"Murattal": "murattal", "Muallim": "muallim", "Kids Repeat": "kids_repeat"}` for the current corpus; other values produce structured unknown-classification issues. EA requires `style`; it requires `riwaya` except when `style == "translation"`, for which the explicit value is `none`.

- [ ] **Step 4: Implement binding conversion and tree insertion**

Convert raw snake_case fields to the existing catalog's camelCase bindings:

```python
MP3_BINDING_FIELDS = {
    "reciterId", "reciterName", "letter", "date", "moshafId",
    "moshafName", "rewayaId", "moshafType", "server",
    "surahTotal", "surahList",
}
```

Preserve QFA fields `id`, `reciterName`, and `style`; QFS fields `id`, `name`, `style`, `qirat`, and `translatedName`; EA fields `everyAyahId`, `subfolder`, `name`, and `bitrate`. Do not copy curated classification helper keys into bindings.

Insert with `catalog[slug]["riwayat"][riwaya]["styles"][style]["providers"][provider]`. Sort reciters, riwayat, styles, provider keys, and binding arrays by stable provider identity (`id`, `moshafId`, or `everyAyahId`).

- [ ] **Step 5: Implement semantic comparison projection**

`semantic_catalog(..., legacy=True)` reads the old `styles -> riwayat` layout and projects both layouts to records keyed by `(slug, riwayah, style, provider, binding_identity)`. Ignore only object/key ordering and these intentional transformations: hierarchy reorder, omission of `dead: true` EA bindings, and addition of curated bindings absent from the legacy catalog. Any field missing from a matching legacy live binding remains a loss.

- [ ] **Step 6: Run focused and full tests and verify GREEN**

Run:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_catalog.py' -v
PYTHONPATH=src python3 -m unittest discover -s tests
```

Expected: all tests pass and serialization contains literal Arabic rather than `\u` escapes.

- [ ] **Step 7: Write the task report**

Record mapping tables implemented, changed files, exact test commands and counts, unresolved terminology encountered in fixtures, and self-review results.

---

### Task 3: Guarded bootstrap and deterministic generator CLI

**Files:**
- Create: `src/reciter_fetcher/catalog_cli.py`
- Create: `src/reciter_fetcher/bootstrap.py`
- Create: `src/reciter_fetcher/bootstrap_cli.py`
- Create: `tests/test_catalog_cli.py`
- Create: `tests/test_bootstrap.py`
- Modify: `src/reciter_fetcher/storage.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes `load_curated_reciters`, `build_catalog`, `serialize_catalog`, and `semantic_catalog`.
- Produces `atomic_write_text(path: Path, content: str) -> None` alongside existing `atomic_write_json`.
- Produces `CatalogComparison(lost: list[dict[str, Any]], changed: list[dict[str, Any]], added: list[dict[str, Any]], allowed_removed: list[dict[str, Any]])`.
- Produces `MigrationEdit(file: str, section: str, entry_id: int | None, field: str, old_value: Any, new_value: Any, source_path: str)`.
- Produces `MigrationConflict(file: str, section: str, entry_id: int | None, field: str, catalog_value: Any, markdown_value: Any, catalog_path: str)`.
- Produces `MigrationPlan(backfills: list[MigrationEdit], conflicts: list[MigrationConflict], comparison: CatalogComparison)`.
- Produces `compare_catalogs(legacy: dict[str, Any], candidate: dict[str, Any]) -> CatalogComparison`.
- Produces `build_migration(root: Path) -> MigrationPlan` and `apply_migration(root: Path, plan: MigrationPlan) -> None`.
- Adds console scripts `generate-catalog = reciter_fetcher.catalog_cli:main` and `bootstrap-catalog = reciter_fetcher.bootstrap_cli:main`.

- [ ] **Step 1: Write failing CLI and bootstrap tests**

Use real temporary repositories. Tests prove:

```python
def test_generate_writes_catalog_atomically_from_markdown(self):
    result = catalog_main(["--root", str(self.root)])
    self.assertEqual(0, result)
    self.assertEqual(EXPECTED_CATALOG, json.loads(self.catalog_path.read_text()))

def test_check_fails_when_checked_in_catalog_differs(self):
    self.catalog_path.write_text("{}\n", encoding="utf-8")
    self.assertEqual(1, catalog_main(["--root", str(self.root), "--check"]))

def test_generation_error_preserves_previous_catalog(self):
    before = self.catalog_path.read_bytes()
    self.assertEqual(1, catalog_main(["--root", str(self.root)]))
    self.assertEqual(before, self.catalog_path.read_bytes())

def test_bootstrap_report_never_changes_markdown_without_apply(self):
    before = self.markdown_path.read_bytes()
    self.assertEqual(0, bootstrap_main(["--root", str(self.root), "--json"]))
    self.assertEqual(before, self.markdown_path.read_bytes())
```

Add tests that `--apply` backfills a QFA `riwaya`/`catalog_style` only when provider ID and canonical reciter match, copies a missing name only when the legacy name is explicit, and leaves conflicts unchanged with exit code 1.

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_catalog_cli.py' -v
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_bootstrap.py' -v
```

Expected: import failures for the new CLI and bootstrap modules.

- [ ] **Step 3: Add atomic text writing and generator CLI**

Implement `atomic_write_text` with `tempfile.mkstemp`, UTF-8, `os.replace`, and cleanup on `BaseException`. `catalog_cli.main(argv)` loads Markdown, prints every issue deterministically, returns 1 without writing on any issue, writes in normal mode, and in `--check` compares exact serialized bytes without writing.

- [ ] **Step 4: Add preservation comparison and bootstrap CLI**

The bootstrap report contains stable JSON arrays:

```json
{
  "backfills": [],
  "conflicts": [],
  "legacyLosses": [],
  "additions": []
}
```

Default is report-only. `--apply` edits only name lines and documented curated-only fields, using exact provider identifiers. After applying, rebuild the candidate and refuse catalog replacement while `legacyLosses` or `conflicts` is non-empty. Print each conflict with slug, Markdown file, provider tag, provider ID, field, legacy value, and Markdown value.

- [ ] **Step 5: Register scripts**

Add exactly:

```toml
generate-catalog = "reciter_fetcher.catalog_cli:main"
bootstrap-catalog = "reciter_fetcher.bootstrap_cli:main"
```

Do not add dependencies.

- [ ] **Step 6: Run focused and full tests and verify GREEN**

Run:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_catalog_cli.py' -v
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_bootstrap.py' -v
PYTHONPATH=src python3 -m unittest discover -s tests
```

Expected: all tests pass; the atomic-preservation test proves the old catalog survives a failed build.

- [ ] **Step 7: Write the task report**

Record interfaces, changed files, exact commands and test counts, CLI stdout examples, and any preservation-rule concerns.

---

### Task 4: Audit classification and actionable issue codes

**Files:**
- Modify: `src/reciter_fetcher/audit.py`
- Modify: `src/reciter_fetcher/audit_cli.py`
- Modify: `tests/test_audit.py`

**Interfaces:**
- Consumes shared parser and catalog normalization validation.
- Extends `FileIssue` with stable `code`, `section`, and `entry_id` fields while retaining `file` and human-readable `issue`.
- `report_to_json` emits those fields for every issue.
- Human output format remains one deterministic line per issue.

- [ ] **Step 1: Write failing audit regression tests**

Add cases proving that audit reports `missing_section`, `missing_id`, `missing_classification`, `unknown_riwayah`, and `unknown_style`; QFA and QFS duplicate checks remain scoped separately; and JSON output contains literal stable codes.

```python
def test_qfa_requires_curated_riwayah_and_null_style_classification(self):
    report = audit(self.root)
    issues = [(issue.code, issue.section, issue.entry_id) for issue in report.file_issues]
    self.assertIn(("missing_classification", "QFA", 2), issues)
```

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_audit.py' -v
```

Expected: failure because `FileIssue` has no `code` and classification is not audited.

- [ ] **Step 3: Implement structured issues and classification validation**

Reuse catalog validation without building a second normalization table. Strict raw comparison ignores QFA curated keys `riwaya` and `catalog_style`, and EA curated keys `style`, `riwaya`, and `dead`. It ignores no other edits.

- [ ] **Step 4: Run focused and full tests and verify GREEN**

Run:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_audit.py' -v
PYTHONPATH=src python3 -m unittest discover -s tests
```

Expected: all tests pass with legacy human messages preserved where their behavior is unchanged.

- [ ] **Step 5: Write the task report**

Record issue codes, changed files, commands and counts, and compatibility notes.

---

### Task 5: Apply the one-time corpus migration and regenerate the catalog

**Files:**
- Modify only as proven necessary: `data/curated/reciters/*.md`
- Regenerate: `data/curated/catalog.json`
- Create: `tests/test_repository_catalog.py`
- Modify: `templates/_template.md`

**Interfaces:**
- Consumes `bootstrap-catalog`, `audit-reciters`, and `generate-catalog` from Tasks 1-4.
- Produces a corpus for which Markdown-only generation is authoritative.

- [ ] **Step 1: Capture preservation baselines**

Record SHA-256 for `data/curated/catalog.json` and a sorted SHA-256 manifest for every Markdown file in the task report before modification. Run report-only bootstrap JSON and save the exact output in the task report.

- [ ] **Step 2: Write the failing repository integration test**

Create `tests/test_repository_catalog.py`:

```python
class RepositoryCatalogTests(unittest.TestCase):
    def test_repository_markdown_builds_without_issues(self):
        reciters, parse_issues = load_curated_reciters(ROOT)
        catalog, catalog_issues = build_catalog(reciters)
        self.assertEqual([], parse_issues)
        self.assertEqual([], catalog_issues)
        self.assertEqual(261, len(catalog))

    def test_checked_in_catalog_is_deterministic_markdown_output(self):
        reciters, _ = load_curated_reciters(ROOT)
        catalog, _ = build_catalog(reciters)
        self.assertEqual(
            (ROOT / "data/curated/catalog.json").read_text(encoding="utf-8"),
            serialize_catalog(catalog),
        )
```

- [ ] **Step 3: Run the repository integration test and verify RED**

Run:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_repository_catalog.py' -v
```

Expected: failures listing the current missing headers/classifications and catalog mismatch.

- [ ] **Step 4: Apply only proven Markdown backfills**

Run report-only bootstrap first, inspect every proposed edit, then run `bootstrap-catalog --apply`. For the twelve QFA entries, preserve the refreshed raw snippet including `translated_name` and add curated `riwaya: hafs`; add `catalog_style: murattal` only where raw `style` is null. This is an existing human decision, not a new inference.

For the ten missing headers, use the existing catalog/curated name registry only when a value is explicit. Preserve unresolved names as the literal curated value `unknown`; do not transliterate or fabricate Arabic. Translation EA entries use `style: translation` and `riwaya: none`. Preserve `dead: true` entries in Markdown.

- [ ] **Step 5: Update the template contract**

Make `templates/_template.md` exactly start with:

```markdown
#name
en:
ar:

# QFS
```

and retain empty QFA, MP3, and EA sections.

- [ ] **Step 6: Compare and regenerate safely**

Run the bootstrap comparison. Review all allowed additions: the eight QFS entries and four QFA entries absent from the legacy catalog may be added because they are explicitly curated provider mappings. Dead EA removal and hierarchy reorder are allowed transformations. Any other `legacyLosses` or `conflicts` blocks replacement.

Run:

```bash
PYTHONPATH=src python3 -m reciter_fetcher.catalog_cli --root .
PYTHONPATH=src python3 -m reciter_fetcher.catalog_cli --root . --check
```

- [ ] **Step 7: Verify corpus and strict audit**

Run:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_repository_catalog.py' -v
PYTHONPATH=src python3 -m reciter_fetcher.audit_cli --root . --strict
PYTHONPATH=src python3 -m unittest discover -s tests
```

Expected: integration tests pass. Strict audit passes unless a genuinely unresolved provider conflict remains; any remaining failure is recorded verbatim and must not be guessed away.

- [ ] **Step 8: Verify change scope**

Compare the before/after Markdown SHA-256 manifests. Every changed Markdown path must correspond to a reviewed bootstrap backfill or raw-snippet refresh. Report unchanged file count, changed file count, catalog semantic additions, allowed removals, and zero unexpected changes.

- [ ] **Step 9: Write the task report**

Include the complete migration report, exact changed Markdown list, preservation comparison, all commands and exit codes, and every unresolved ambiguity.

---

### Task 6: Documentation and complete workflow verification

**Files:**
- Modify: `README.md`
- Modify: `docs/CURATION.md`
- Create: `docs/CATALOG_ARCHITECTURE.md`

**Interfaces:**
- Documents the implemented CLIs and exact ownership model.
- Does not introduce new runtime behavior.

- [ ] **Step 1: Update README commands and ownership**

Document the exact workflow:

```bash
fetch-reciters
audit-reciters --strict
bootstrap-catalog --json
generate-catalog
generate-catalog --check
```

Mark bootstrap as one-time/report-first and `catalog.json` as generated output.

- [ ] **Step 2: Update curation rules**

Document QFA curated keys `riwaya` and `catalog_style`, EA keys `style`, `riwaya`, and `dead`, explicit `unknown`, provider-domain separation, generator failure behavior, and the rule that raw snippets remain verbatim aside from documented curated-only keys.

- [ ] **Step 3: Write architecture documentation**

`docs/CATALOG_ARCHITECTURE.md` covers ownership, target hierarchy, binding arrays, provider-domain/capability distinction, `standalone` versus `segment`, hybrid availability, deterministic generation, bootstrap history, and explicit future-SDK exclusions.

- [ ] **Step 4: Run fresh final verification**

Run exactly:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
PYTHONPATH=src python3 -m reciter_fetcher.audit_cli --root . --strict
PYTHONPATH=src python3 -m reciter_fetcher.catalog_cli --root . --check
PYTHONPATH=src python3 -m reciter_fetcher.catalog_cli --root . --check
```

Record full outputs and exit codes. Two consecutive check runs must succeed without changing catalog bytes.

- [ ] **Step 5: Produce the final implementation report**

List actual existing structure, every changed/created file, deviations and rulings, remaining unmapped/stale/ambiguous entries, fetch/audit/generate commands, whether deletion/regeneration is lossless, and every field still dependent on explicit Markdown curation.
