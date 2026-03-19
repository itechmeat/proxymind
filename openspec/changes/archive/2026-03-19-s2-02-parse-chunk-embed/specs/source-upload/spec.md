## MODIFIED Requirements

### Requirement: Upload metadata validation

The `metadata` field SHALL be validated as JSON conforming to a Pydantic schema with the following fields: `title` (string, required, 1-255 characters), `description` (string, optional, max 2000 characters), `public_url` (string, optional, valid HTTP/HTTPS URL, max 2048 characters), `catalog_item_id` (UUID, optional), `language` (string, optional, max 32 characters). The `source_type` SHALL be determined automatically from the file extension (`.md` -> MARKDOWN, `.txt` -> TXT) and SHALL NOT be part of the metadata input.

**Delta (S2-02):** The `language` field from `SourceUploadMetadata` SHALL be persisted on the `Source` record. S2-01 accepted `language` in the metadata schema but silently dropped it during source creation. The `source.py` service `create_source_and_task()` method MUST pass `language=metadata.language` to the Source constructor. Empty or whitespace-only `language` values SHALL be normalized to NULL before persistence. A new nullable `language` column (VARCHAR(32)) SHALL be added to the `sources` table via Alembic migration. Existing sources receive NULL, which means "use system default."

#### Scenario: Language field is persisted on Source record

- **WHEN** a POST request is sent with metadata containing `"language": "russian"`
- **THEN** the created Source record in PostgreSQL SHALL have `language` set to `"russian"`

#### Scenario: Missing language field results in NULL

- **WHEN** a POST request is sent with metadata that does not include `language`
- **THEN** the created Source record in PostgreSQL SHALL have `language` set to NULL

#### Scenario: Blank language is normalized to NULL

- **WHEN** a POST request is sent with metadata containing `"language": "   "`
- **THEN** the created Source record in PostgreSQL SHALL have `language` set to NULL

#### Scenario: Existing sources retain NULL language after migration

- **WHEN** the Alembic migration adding the `language` column is applied
- **THEN** all pre-existing Source records SHALL have `language` set to NULL

#### Scenario: source_type derived from extension (unchanged)

- **WHEN** a `.md` file is uploaded
- **THEN** the created Source record SHALL have `source_type` set to MARKDOWN

- **WHEN** a `.txt` file is uploaded
- **THEN** the created Source record SHALL have `source_type` set to TXT

---

## Test Coverage

### CI tests (deterministic)

The following stable behavior MUST be covered by CI tests before archive:

- **Integration test**: upload with `language` in metadata, verify the Source record in PG has the correct `language` value.
- **Integration test**: upload with `language` length 32, verify the Source record persists it successfully.
- **Integration test**: upload with blank `language`, verify the Source record has `language=NULL`.
- **Validation test**: upload with `language` length > 32, verify the request is rejected with HTTP 422.
- **Integration test**: upload without `language` in metadata, verify the Source record has `language=NULL`.
