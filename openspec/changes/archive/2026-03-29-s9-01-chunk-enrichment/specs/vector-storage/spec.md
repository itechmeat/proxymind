## MODIFIED Requirements

### Requirement: Point upsert with named vector and payload

The `upsert_chunks()` method SHALL accept a list of point data and upsert them to Qdrant. Each point SHALL have: `id` (chunk UUID from PostgreSQL, string format), vector dict containing `"dense"` (float vector) and `"bm25"` (`models.Document(text=point.bm25_text, model="Qdrant/bm25", options=Bm25Config(language=self.bm25_language))`), and a payload containing: `snapshot_id`, `source_id`, `chunk_id`, `document_version_id`, `agent_id`, `knowledge_base_id`, `text_content`, `chunk_index`, `token_count`, `anchor_page`, `anchor_chapter`, `anchor_section`, `anchor_timecode`, `source_type`, `language`, `status`, `enriched_summary`, `enriched_keywords`, `enriched_questions`, `enriched_text`, `enrichment_model`, `enrichment_pipeline_version`.

**[Modified by S9-01]** The BM25 sparse vector input SHALL use the `bm25_text` property of each point instead of `text_content`. The `bm25_text` property SHALL resolve to `enriched_text` when available (non-None), falling back to `text_content` otherwise. This ensures enriched keywords and questions improve lexical search without requiring changes to the retrieval pipeline. The `text_content` payload field SHALL continue to hold the original chunk text (without enrichment artifacts) for use in LLM context during answer generation and for citation display.

#### Scenario: Points upserted with both dense and BM25 vectors

- **WHEN** `upsert_chunks()` is called with a list of points
- **THEN** each point SHALL have a vector dict with key `"dense"` containing the float vector
- **AND** each point SHALL have a vector dict with key `"bm25"` containing a `Document` with `model="Qdrant/bm25"`, `text=point.bm25_text`, and `options=Bm25Config(language=self.bm25_language)`
- **AND** each point payload SHALL contain all specified fields including the 6 enrichment fields

#### Scenario: BM25 Document uses enriched_text when available

- **WHEN** a chunk has been enriched and `enriched_text` is non-None
- **THEN** the `"bm25"` Document text SHALL be `enriched_text` (the concatenation of original text with summary, keywords, and questions)
- **AND** the `"dense"` embedding SHALL also have been generated from `enriched_text`
- **AND** `text_content` in the payload SHALL remain the original unenriched chunk text

#### Scenario: BM25 Document falls back to text_content when unenriched

- **WHEN** a chunk has not been enriched (enrichment disabled or enrichment failed) and `enriched_text` is None
- **THEN** the `"bm25"` Document text SHALL be `text_content`
- **AND** behavior SHALL be identical to the pre-enrichment pipeline

#### Scenario: text_content dual-write to payload

- **WHEN** a chunk is upserted to Qdrant
- **THEN** the payload SHALL include `text_content` with the original chunk text (not enriched text)
- **AND** the same `text_content` SHALL exist in the PostgreSQL Chunk record (source of truth for audit and reindex; Qdrant copy avoids PG round-trip during chat retrieval)
- **AND** the write ordering SHALL be PostgreSQL Tx 1 (persist `Chunk` rows as PENDING) -> Qdrant upsert -> PostgreSQL Tx 2 (finalize rows as INDEXED)
- **AND** if PostgreSQL Tx 1 succeeds but the Qdrant upsert fails, the task SHALL fail and the persisted PostgreSQL records SHALL be marked FAILED in a recovery transaction
- **AND** if the Qdrant upsert succeeds but PostgreSQL Tx 2 fails, the worker SHALL attempt a compensating delete of the just-upserted Qdrant points by point ID (the chunk UUID used as the Qdrant point ID); if that delete also fails, the task SHALL still fail and operator reconciliation is required

---

## ADDED Requirements

### Requirement: Enrichment payload fields in Qdrant

**[Added by S9-01]** The Qdrant point payload SHALL include 6 enrichment fields in addition to the existing payload fields. These fields store LLM-generated enrichment metadata and audit information for each chunk. All enrichment fields SHALL be nullable — they are None when enrichment is disabled, when the chunk's enrichment call failed, or when the chunk was indexed via Path A (which skips enrichment).

The enrichment payload fields SHALL be:

| Field                         | Type                | Description                                                                               |
| ----------------------------- | ------------------- | ----------------------------------------------------------------------------------------- |
| `enriched_summary`            | `str \| None`       | LLM-generated 1-2 sentence summary of the chunk                                           |
| `enriched_keywords`           | `list[str] \| None` | LLM-generated search keywords including synonyms                                          |
| `enriched_questions`          | `list[str] \| None` | LLM-generated natural questions the chunk answers                                         |
| `enriched_text`               | `str \| None`       | Full concatenated text used for embedding (text_content + summary + keywords + questions) |
| `enrichment_model`            | `str \| None`       | Model identifier used for enrichment (e.g. `"gemini-2.5-flash"`)                          |
| `enrichment_pipeline_version` | `str \| None`       | Pipeline version tag (e.g. `"s9-01-enrichment-v1"`)                                       |

The `enriched_` prefix distinguishes generated fields from original document data. No payload indexes SHALL be created on enrichment fields — they are not used for filtering. The `enriched_text` field is stored for reproducibility, recording exactly what was embedded for the dense vector and BM25 sparse vector.

#### Scenario: Enriched chunk payload contains all 6 enrichment fields

- **WHEN** a chunk with successful enrichment is upserted to Qdrant
- **THEN** the payload SHALL contain `enriched_summary` as a non-empty string
- **AND** the payload SHALL contain `enriched_keywords` as a non-empty list of strings
- **AND** the payload SHALL contain `enriched_questions` as a non-empty list of strings
- **AND** the payload SHALL contain `enriched_text` as a non-empty string containing the original `text_content` plus enrichment metadata
- **AND** the payload SHALL contain `enrichment_model` as a non-empty string (e.g. `"gemini-2.5-flash"`)
- **AND** the payload SHALL contain `enrichment_pipeline_version` as a non-empty string

#### Scenario: Unenriched chunk payload has null enrichment fields

- **WHEN** a chunk without enrichment (enrichment disabled, enrichment failed, or Path A) is upserted to Qdrant
- **THEN** `enriched_summary`, `enriched_keywords`, `enriched_questions`, `enriched_text`, `enrichment_model`, and `enrichment_pipeline_version` SHALL all be None in the payload

#### Scenario: No payload indexes on enrichment fields

- **WHEN** `ensure_collection()` creates or validates the collection
- **THEN** no payload indexes SHALL be created on `enriched_summary`, `enriched_keywords`, `enriched_questions`, `enriched_text`, `enrichment_model`, or `enrichment_pipeline_version`
- **AND** the existing payload indexes on `snapshot_id`, `agent_id`, `knowledge_base_id`, `source_id`, `status`, `source_type`, and `language` SHALL remain unchanged

---
