## MODIFIED Requirements

### Requirement: QdrantService for collection management, point upsert, and dense search

The system SHALL provide a `QdrantService` at `app/services/qdrant.py` that wraps the async Qdrant client. The service SHALL receive the `AsyncQdrantClient` instance and collection configuration via constructor injection. The service SHALL provide three methods: `ensure_collection()` for idempotent collection creation, `upsert_chunks()` for point upsert, and `search()` for dense vector retrieval with payload filtering.

**[ADDED by S2-04]** The `search()` method SHALL accept the following parameters:

- `vector` (list of floats) — the query embedding vector
- `snapshot_id` (UUID) — mandatory payload filter
- `agent_id` (UUID) — mandatory payload filter
- `knowledge_base_id` (UUID) — mandatory payload filter
- `limit` (int) — maximum number of results to return (maps to `retrieval_top_n` from Settings)
- `score_threshold` (float or None) — optional minimum cosine similarity score. When set, Qdrant SHALL filter out points with similarity below the threshold before returning results. When `None`, no score filtering SHALL be applied.

The `search()` method SHALL perform a dense vector search using the named vector `"dense"`. The method SHALL construct a payload filter combining `snapshot_id`, `agent_id`, and `knowledge_base_id` conditions. The method SHALL return a list of `RetrievedChunk` objects (or equivalent data structure) containing: `chunk_id` (UUID), `source_id` (UUID), `text_content` (str), `score` (float), and `anchor_metadata` (dict with keys: `anchor_page`, `anchor_chapter`, `anchor_section`, `anchor_timecode`).

#### Scenario: QdrantService is instantiable with injected client

- **WHEN** a `QdrantService` is created with an `AsyncQdrantClient` and settings
- **THEN** the instance SHALL be ready to call `ensure_collection()`, `upsert_chunks()`, and `search()`

#### Scenario: Dense search returns matching chunks filtered by snapshot

- **WHEN** `search()` is called with a query vector, snapshot_id, agent_id, knowledge_base_id, and limit=5
- **THEN** the method SHALL query Qdrant using the `"dense"` named vector
- **AND** the payload filter SHALL include conditions for `snapshot_id`, `agent_id`, and `knowledge_base_id`
- **AND** the method SHALL return up to 5 `RetrievedChunk` results ordered by similarity score descending

#### Scenario: Search with score_threshold filters low-scoring results

- **WHEN** `search()` is called with `score_threshold=0.5`
- **THEN** only points with cosine similarity >= 0.5 SHALL be returned
- **AND** points with similarity below 0.5 SHALL be excluded by Qdrant before returning

#### Scenario: Search with score_threshold=None returns all top-N results

- **WHEN** `search()` is called with `score_threshold=None`
- **THEN** all top-N results SHALL be returned regardless of their similarity score

#### Scenario: Search returns empty list when no chunks match

- **WHEN** `search()` is called with a snapshot_id that has no indexed chunks in Qdrant
- **THEN** the method SHALL return an empty list

#### Scenario: Search result contains correct payload fields

- **WHEN** `search()` returns results
- **THEN** each `RetrievedChunk` SHALL contain `chunk_id`, `source_id`, `text_content`, `score`, and `anchor_metadata`
- **AND** `anchor_metadata` SHALL include `anchor_page`, `anchor_chapter`, `anchor_section`, and `anchor_timecode` fields from the point payload

---

## Test Coverage

### CI tests (deterministic, mocked external services)

The following stable behavior MUST be covered by CI tests before archive (in addition to existing QdrantService tests):

- **QdrantService.search unit tests**: mock `AsyncQdrantClient`. Verify search constructs correct named vector query (`"dense"`). Verify payload filter includes all three fields (snapshot_id, agent_id, knowledge_base_id). Verify score_threshold is passed to Qdrant when set. Verify score_threshold=None omits score filtering. Verify results are mapped to `RetrievedChunk` with correct fields. Verify empty result returns empty list.
- **Qdrant round-trip integration test (extended)**: with a real Qdrant container, upsert points with realistic payload, search by vector with snapshot_id filter, verify expected chunks returned with correct payload and score ordering. Uses fake (random) vectors to avoid Gemini dependency.
