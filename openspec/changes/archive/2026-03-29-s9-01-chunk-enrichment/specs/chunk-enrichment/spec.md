## ADDED Requirements

### Requirement: EnrichmentService

The system SHALL provide an `EnrichmentService` at `backend/app/services/enrichment.py` that accepts a list of chunks and returns per-chunk enrichment results containing `summary` (str), `keywords` (list[str]), and `questions` (list[str]). The service SHALL call the Gemini LLM using the `google-genai` SDK with structured output (JSON Schema via `response_schema`) to guarantee syntactically valid JSON responses. The structured output schema SHALL require three fields: `summary` (string), `keywords` (array of strings), and `questions` (array of strings). The service SHALL execute enrichment calls concurrently using `asyncio.gather` with a semaphore limited to `ENRICHMENT_MAX_CONCURRENCY`. The service SHALL use the model specified by `ENRICHMENT_MODEL` with temperature `ENRICHMENT_TEMPERATURE` and max output tokens `ENRICHMENT_MAX_OUTPUT_TOKENS`. The service SHALL skip chunks whose `text_content` is shorter than `ENRICHMENT_MIN_CHUNK_TOKENS` tokens, returning `None` for those chunks. The service SHALL operate fail-open: if an individual chunk enrichment call fails (timeout, API error, or unexpected response), that chunk SHALL proceed through the pipeline with its original `text_content` and all `enriched_*` fields set to `None`. Partial failures SHALL NOT block other chunks in the batch.

#### Scenario: Successful enrichment of multiple chunks

- **WHEN** `EnrichmentService.enrich()` is called with a list of 3 chunks that each exceed `ENRICHMENT_MIN_CHUNK_TOKENS`
- **THEN** the service SHALL make 3 concurrent Gemini API calls with structured output
- **AND** each result SHALL contain `summary` (str), `keywords` (list[str]), and `questions` (list[str])

#### Scenario: Chunk below minimum token threshold is skipped

- **WHEN** `EnrichmentService.enrich()` is called with a chunk whose `text_content` is shorter than `ENRICHMENT_MIN_CHUNK_TOKENS` tokens
- **THEN** the service SHALL return `None` for that chunk without making an API call

#### Scenario: Single chunk failure does not block others

- **WHEN** enrichment of chunk 2 out of 3 fails with a Gemini API timeout
- **THEN** chunks 1 and 3 SHALL have enrichment results
- **AND** chunk 2 SHALL proceed with `enriched_*` fields set to `None`

#### Scenario: Concurrency respects semaphore limit

- **WHEN** `EnrichmentService.enrich()` is called with 20 chunks and `ENRICHMENT_MAX_CONCURRENCY` is 10
- **THEN** at most 10 Gemini API calls SHALL be in flight at any given time

#### Scenario: All chunks fail gracefully

- **WHEN** all enrichment API calls fail (e.g., API outage)
- **THEN** all chunks SHALL proceed through the pipeline with original `text_content`
- **AND** no exception SHALL propagate to the caller

---

### Requirement: Feature flag

The system SHALL support an `ENRICHMENT_ENABLED` environment variable (default: `false`) that controls whether the enrichment stage runs. When `ENRICHMENT_ENABLED` is `false`, the ingestion pipeline SHALL behave identically to the pre-enrichment pipeline with no enrichment calls, no enrichment data written to the database, and no performance impact. When `ENRICHMENT_ENABLED` is `true`, the enrichment stage SHALL run for Path B and Path C chunks before embedding.

#### Scenario: Enrichment disabled by default

- **WHEN** the pipeline processes chunks and `ENRICHMENT_ENABLED` is not set in the environment
- **THEN** the enrichment stage SHALL be skipped entirely
- **AND** chunks SHALL be embedded using `text_content` only

#### Scenario: Enrichment enabled

- **WHEN** the pipeline processes Path B/C chunks and `ENRICHMENT_ENABLED` is `true`
- **THEN** the `EnrichmentService` SHALL be invoked before embedding

#### Scenario: Path A skips enrichment regardless of flag

- **WHEN** the pipeline processes a Path A chunk (LLM-generated `text_content`) and `ENRICHMENT_ENABLED` is `true`
- **THEN** the enrichment stage SHALL be skipped for that chunk

---

### Requirement: Configuration

The system SHALL add the following settings to the `Settings` class in `backend/app/core/config.py` via Pydantic Settings, each configurable through environment variables:

| Setting                        | Env Variable                   | Type    | Default              | Description                                    |
| ------------------------------ | ------------------------------ | ------- | -------------------- | ---------------------------------------------- |
| `enrichment_enabled`           | `ENRICHMENT_ENABLED`           | `bool`  | `False`              | Feature flag controlling enrichment activation |
| `enrichment_model`             | `ENRICHMENT_MODEL`             | `str`   | `"gemini-2.5-flash"` | Gemini model used for enrichment               |
| `enrichment_max_concurrency`   | `ENRICHMENT_MAX_CONCURRENCY`   | `int`   | `10`                 | Maximum concurrent enrichment API calls        |
| `enrichment_temperature`       | `ENRICHMENT_TEMPERATURE`       | `float` | `0.1`                | Low temperature for factual extraction         |
| `enrichment_max_output_tokens` | `ENRICHMENT_MAX_OUTPUT_TOKENS` | `int`   | `512`                | Per-chunk output token budget                  |
| `enrichment_min_chunk_tokens`  | `ENRICHMENT_MIN_CHUNK_TOKENS`  | `int`   | `10`                 | Minimum chunk size to attempt enrichment       |

#### Scenario: Default configuration values

- **WHEN** a `Settings` instance is created without enrichment-related environment variables
- **THEN** `enrichment_enabled` SHALL be `False`
- **AND** `enrichment_model` SHALL be `"gemini-2.5-flash"`
- **AND** `enrichment_max_concurrency` SHALL be `10`
- **AND** `enrichment_temperature` SHALL be `0.1`
- **AND** `enrichment_max_output_tokens` SHALL be `512`
- **AND** `enrichment_min_chunk_tokens` SHALL be `10`

#### Scenario: Custom configuration via environment variables

- **WHEN** `ENRICHMENT_MODEL` is set to `"gemini-2.5-pro"` and `ENRICHMENT_MAX_CONCURRENCY` is set to `5`
- **THEN** `settings.enrichment_model` SHALL be `"gemini-2.5-pro"`
- **AND** `settings.enrichment_max_concurrency` SHALL be `5`

---

### Requirement: Text concatenation and token budget enforcement

When enrichment succeeds for a chunk, the system SHALL build an `enriched_text` field by concatenating the original `text_content` with enrichment metadata in the following format:

```
{text_content}

Summary: {summary}
Keywords: {', '.join(keywords)}
Questions:
- {question_1}
- {question_2}
```

The `enriched_text` SHALL be used as the source for both dense embedding (Gemini Embedding 2) and BM25 sparse vector generation. The original `text_content` SHALL always be preserved separately and used for LLM context during answer generation and for citation display.

The system SHALL enforce a maximum token budget of 8192 tokens for `enriched_text`. When the concatenated text exceeds this budget, the system SHALL truncate enrichment metadata in the following priority order (least important removed first):

1. Remove `questions` section first
2. Remove `keywords` section second
3. Truncate `summary` last (preserving as much as possible)

If `text_content` alone exceeds 8192 tokens, the system SHALL use `text_content` without any enrichment concatenation.

#### Scenario: Enriched text format

- **WHEN** a chunk with `text_content` "The company reported strong revenue growth." is enriched with `summary` "Financial performance summary", `keywords` ["revenue", "earnings", "financial results"], and `questions` ["What were the company earnings?"]
- **THEN** `enriched_text` SHALL contain the original text followed by a blank line, then "Summary: Financial performance summary", "Keywords: revenue, earnings, financial results", and a `Questions:` section with one bullet per question

#### Scenario: Token budget exceeded — questions removed first

- **WHEN** `text_content` + all enrichment metadata exceeds 8192 tokens
- **THEN** the `questions` section SHALL be removed first
- **AND** if still over budget, the `keywords` section SHALL be removed
- **AND** if still over budget, the `summary` SHALL be truncated

#### Scenario: Text content alone exceeds token budget

- **WHEN** `text_content` alone exceeds 8192 tokens
- **THEN** `enriched_text` SHALL equal `text_content` with no enrichment metadata appended

#### Scenario: Unenriched chunk uses text_content

- **WHEN** enrichment is disabled or fails for a chunk
- **THEN** the system SHALL use `text_content` as the source for dense embedding and BM25 sparse vector generation

---

### Requirement: Database schema extension

The system SHALL add 6 new nullable columns to the `chunks` table via an Alembic migration. The columns SHALL be added to the `Chunk` SQLAlchemy model in `backend/app/db/models/knowledge.py`:

| Column                        | SQL Type            | SQLAlchemy Type              | Description                                        |
| ----------------------------- | ------------------- | ---------------------------- | -------------------------------------------------- |
| `enriched_summary`            | `TEXT NULL`         | `Text, nullable=True`        | LLM-generated summary                              |
| `enriched_keywords`           | `JSONB NULL`        | `JSONB, nullable=True`       | LLM-generated keywords array                       |
| `enriched_questions`          | `JSONB NULL`        | `JSONB, nullable=True`       | LLM-generated questions array                      |
| `enriched_text`               | `TEXT NULL`         | `Text, nullable=True`        | Full concatenated text used for embedding          |
| `enrichment_model`            | `VARCHAR(100) NULL` | `String(100), nullable=True` | Model identifier used for enrichment               |
| `enrichment_pipeline_version` | `VARCHAR(50) NULL`  | `String(50), nullable=True`  | Pipeline version tag (e.g., "s9-01-enrichment-v1") |

All columns MUST be nullable to maintain backward compatibility with existing unenriched chunks. The migration SHALL be a single `ALTER TABLE` operation adding all 6 columns. These columns serve as the persistence contract between the enrichment stage and the batch embedding completion handler (`batch_orchestrator._apply_results`).

#### Scenario: Migration adds columns to existing table

- **WHEN** the Alembic migration runs against a database with the existing `chunks` table
- **THEN** 6 new nullable columns SHALL be added: `enriched_summary`, `enriched_keywords`, `enriched_questions`, `enriched_text`, `enrichment_model`, `enrichment_pipeline_version`
- **AND** existing rows SHALL have `NULL` for all new columns

#### Scenario: Enriched chunk persists all fields

- **WHEN** a chunk is enriched successfully and saved to the database
- **THEN** `enriched_summary` SHALL contain the LLM-generated summary
- **AND** `enriched_keywords` SHALL contain the keywords as a JSON array
- **AND** `enriched_questions` SHALL contain the questions as a JSON array
- **AND** `enriched_text` SHALL contain the full concatenated text
- **AND** `enrichment_model` SHALL contain the model identifier (e.g., "gemini-2.5-flash")
- **AND** `enrichment_pipeline_version` SHALL contain the pipeline version tag

#### Scenario: Unenriched chunk has null enrichment fields

- **WHEN** a chunk is processed without enrichment (flag disabled or enrichment failed)
- **THEN** all 6 enrichment columns SHALL be `NULL`

---

### Requirement: Qdrant payload extension

The system SHALL add the same 6 enrichment fields to the Qdrant chunk payload in `backend/app/services/qdrant.py`. The `QdrantChunkPoint` model and `_build_payload()` method SHALL include:

| Payload Field                 | Type                | Description                               |
| ----------------------------- | ------------------- | ----------------------------------------- |
| `enriched_summary`            | `str \| None`       | LLM-generated summary                     |
| `enriched_keywords`           | `list[str] \| None` | LLM-generated keywords                    |
| `enriched_questions`          | `list[str] \| None` | LLM-generated questions                   |
| `enriched_text`               | `str \| None`       | Full concatenated text used for embedding |
| `enrichment_model`            | `str \| None`       | Model identifier                          |
| `enrichment_pipeline_version` | `str \| None`       | Pipeline version tag                      |

The `bm25_text` property (used as the BM25 document source) SHALL return `enriched_text` when it is not `None`, falling back to `text_content` otherwise. No new payload indexes SHALL be created for enrichment fields.

#### Scenario: Enriched chunk payload contains enrichment fields

- **WHEN** an enriched chunk is upserted to Qdrant
- **THEN** the payload SHALL include `enriched_summary`, `enriched_keywords`, `enriched_questions`, `enriched_text`, `enrichment_model`, and `enrichment_pipeline_version` with their values

#### Scenario: BM25 source uses enriched_text when available

- **WHEN** a chunk has a non-null `enriched_text`
- **THEN** the BM25 document source (`bm25_text`) SHALL be `enriched_text`

#### Scenario: BM25 source falls back to text_content

- **WHEN** a chunk has `enriched_text` set to `None`
- **THEN** the BM25 document source (`bm25_text`) SHALL be `text_content`

#### Scenario: Unenriched chunk payload has null enrichment fields

- **WHEN** an unenriched chunk is upserted to Qdrant
- **THEN** all 6 enrichment payload fields SHALL be `None`

---

### Requirement: Pipeline integration

The enrichment stage SHALL run in `backend/app/workers/tasks/pipeline.py` within `embed_and_index_chunks()`, **before** the branch into batch and inline embedding paths. The integration SHALL follow this sequence:

1. If `ENRICHMENT_ENABLED` is `true` and the chunk is Path B or Path C:
   a. Call `EnrichmentService.enrich(chunks)` with concurrent `asyncio.gather`
   b. For each chunk with successful enrichment: build `enriched_text`, store enrichment data in the `Chunk` DB rows (new columns)
   c. For failed chunks: proceed with original `text_content`
2. Build `texts_for_embedding` list using `enriched_text` when available, `text_content` otherwise
3. Branch into inline or batch embedding path — both paths receive the enriched text
4. For the batch path: `batch_orchestrator._apply_results` SHALL read enrichment data from the `Chunk` DB columns when building the Qdrant payload

Path A chunks SHALL skip enrichment regardless of the feature flag, since their `text_content` is already LLM-generated.

#### Scenario: Enrichment runs before embedding branch

- **WHEN** `ENRICHMENT_ENABLED` is `true` and Path B/C chunks are processed
- **THEN** `EnrichmentService.enrich()` SHALL be called before both the inline and batch embedding paths
- **AND** the resulting `enriched_text` SHALL be used as input for embedding

#### Scenario: Inline path receives enriched text

- **WHEN** the inline embedding path processes an enriched chunk
- **THEN** `EmbeddingService.embed_texts()` SHALL receive `enriched_text` for that chunk

#### Scenario: Batch path reads enrichment from DB

- **WHEN** the batch embedding path completes and `batch_orchestrator._apply_results` builds the Qdrant payload
- **THEN** it SHALL read `enriched_summary`, `enriched_keywords`, `enriched_questions`, `enriched_text`, `enrichment_model`, and `enrichment_pipeline_version` from the `Chunk` DB rows

#### Scenario: Enrichment disabled — pipeline unchanged

- **WHEN** `ENRICHMENT_ENABLED` is `false`
- **THEN** the pipeline SHALL skip the enrichment stage entirely
- **AND** `texts_for_embedding` SHALL use `text_content` for all chunks

#### Scenario: Mixed enrichment results in a batch

- **WHEN** enrichment succeeds for 8 out of 10 chunks in a batch
- **THEN** the 8 enriched chunks SHALL use `enriched_text` for embedding
- **AND** the 2 failed chunks SHALL use `text_content` for embedding
- **AND** all 10 chunks SHALL be upserted to Qdrant

---

### Requirement: A/B eval dataset

The system SHALL include a vocabulary-gap eval dataset at `backend/evals/datasets/retrieval_enrichment.yaml` containing eval cases that target the specific retrieval failures enrichment is designed to fix. The dataset SHALL include cases for:

- **Synonym queries:** user query uses a synonym not present in the chunk text (e.g., "company earnings" targeting a chunk about "revenue growth")
- **Question-form queries:** user asks a question that the chunk answers in declarative form (e.g., "How to deploy the application?" targeting a chunk with deployment steps)
- **Abstract queries:** user asks at a higher abstraction level than the chunk content (e.g., "what about the costs?" targeting a chunk with specific pricing details)
- **Terminology mismatch:** user uses a layman's term for a domain-specific concept

The eval dataset SHALL be used in A/B comparison: one eval run against a snapshot without enrichment (baseline), one against a snapshot with enrichment enabled. The comparison SHALL produce metric deltas for retrieval scorers (Precision@K, Recall@K, MRR) and answer quality scorers (groundedness, citation_accuracy).

#### Scenario: Eval dataset covers vocabulary gap categories

- **WHEN** the `retrieval_enrichment.yaml` dataset is loaded
- **THEN** it SHALL contain at least one case for each category: synonym mismatch, question-form query, abstract query, and terminology mismatch

#### Scenario: A/B eval comparison produces metric deltas

- **WHEN** the eval is run against both a baseline snapshot (no enrichment) and an enriched snapshot
- **THEN** the comparison report SHALL include per-metric deltas with GREEN/YELLOW/RED zone classification

---

## Test Coverage

### CI tests (deterministic, mocked external services)

- **EnrichmentService unit tests** (`backend/tests/unit/test_enrichment_service.py`): mock Gemini API; verify structured output parsing returns correct `summary`, `keywords`, `questions`; verify chunks below `ENRICHMENT_MIN_CHUNK_TOKENS` are skipped; verify fail-open on API error (returns `None`, no exception); verify concurrency semaphore limits in-flight calls.
- **Configuration tests** (`backend/tests/unit/test_enrichment_service.py`): verify all 6 enrichment settings have correct defaults; verify custom values via environment override.
- **Token budget tests** (`backend/tests/unit/test_enrichment_service.py`): verify `enriched_text` concatenation format; verify truncation order (questions first, then keywords, then summary); verify text_content exceeding 8192 tokens produces no enrichment concatenation.
- **Pipeline integration tests** (`backend/tests/unit/test_pipeline_enrichment.py`): verify enrichment stage is skipped when `ENRICHMENT_ENABLED=false`; verify enrichment is called when enabled for Path B/C; verify Path A skips enrichment regardless of flag; verify mixed success/failure in a batch (enriched chunks use `enriched_text`, failed chunks use `text_content`).
- **Qdrant payload tests** (`backend/tests/unit/test_pipeline_enrichment.py`): verify `bm25_text` returns `enriched_text` when available; verify `bm25_text` falls back to `text_content` when `enriched_text` is `None`; verify all 6 enrichment fields present in payload.

### Evals (real models, not CI)

- **A/B comparison**: run retrieval eval against baseline snapshot (no enrichment) and enriched snapshot; compare Precision@K, Recall@K, MRR, groundedness, citation_accuracy deltas.
- **Vocabulary-gap eval cases** (`retrieval_enrichment.yaml`): synonym, question-form, abstract, and terminology mismatch queries evaluated against both snapshots.
