## ADDED Requirements

### Requirement: Installation-level sparse backend selection drives chunk indexing

The ingestion pipeline SHALL continue producing chunk rows, enrichment data, and dense embeddings exactly as before, but sparse indexing SHALL be driven by the installation's active sparse backend.

The sparse input text SHALL remain `enriched_text` when available and `text_content` otherwise. The pipeline SHALL NOT introduce a second text-selection rule for BGE-M3. The indexed sparse backend metadata SHALL be preserved with the chunk's Qdrant payload via the vector storage layer.

#### Scenario: BM25 backend indexes chunks using existing sparse text selection

- **WHEN** a Path B or Path C chunk is indexed with `sparse_backend=bm25`
- **THEN** the sparse input text SHALL be `enriched_text` when available and `text_content` otherwise
- **AND** the indexed sparse representation SHALL be produced by the BM25 sparse provider

#### Scenario: BGE-M3 backend indexes chunks using the same sparse text selection

- **WHEN** a Path B or Path C chunk is indexed with `sparse_backend=bge_m3`
- **THEN** the sparse input text SHALL be `enriched_text` when available and `text_content` otherwise
- **AND** the indexed sparse representation SHALL be produced by the external BGE-M3 sparse provider

#### Scenario: Dense embedding behavior remains unchanged

- **WHEN** the sparse backend is switched from `bm25` to `bge_m3`
- **THEN** Gemini dense embedding generation SHALL remain unchanged
- **AND** the pipeline SHALL continue using the existing dense text input rules

---

### Requirement: Sparse backend switch is an explicit reindex-triggering change

Changing `sparse_backend` SHALL be treated as an explicit reindex-triggering change for the knowledge index. The system SHALL NOT treat an existing BM25-built sparse index as compatible with BGE-M3, and vice versa.

This requirement applies to operational workflow as well as implementation logic. A provider switch SHALL require reindexing before retrieval quality claims are made for the new backend.

The incompatibility check is performed by comparing indexed payload metadata (`sparse_backend`, `sparse_model`, `sparse_contract_version`) against the current sparse backend configuration during startup collection validation. S9-03 v1 refuses to serve retrieval traffic on a mismatched index rather than attempting a runtime fallback.

#### Scenario: BM25 to BGE-M3 switch requires reindex

- **WHEN** the installation changes `sparse_backend` from `bm25` to `bge_m3`
- **THEN** the existing sparse index state SHALL be treated as incompatible
- **AND** retrieval under the new sparse backend SHALL require explicit reindexing first
- **AND** incompatibility SHALL be detected from the stored `sparse_backend`, `sparse_model`, and `sparse_contract_version` payload metadata

#### Scenario: BGE-M3 to BM25 rollback requires reindex

- **WHEN** the installation changes `sparse_backend` from `bge_m3` back to `bm25`
- **THEN** the BGE-M3-built sparse index SHALL be treated as incompatible with BM25 reuse
- **AND** rollback SHALL require explicit reindexing
- **AND** incompatibility SHALL be detected from the stored `sparse_backend`, `sparse_model`, and `sparse_contract_version` payload metadata

#### Scenario: Startup blocks retrieval until reindex completes

- **WHEN** startup validation finds a sparse backend contract mismatch or missing sparse contract metadata
- **THEN** `QdrantService.ensure_collection()` SHALL raise `CollectionSchemaMismatchError`
- **AND** the API/worker SHALL fail readiness rather than serving retrievals against the incompatible index
- **AND** operator-visible logs SHALL state that explicit reindexing is required before retrieval can resume

---

## Test Coverage

### CI tests (deterministic, mocked external services)

The following stable behavior MUST be covered by CI tests before archive:

- pipeline tests proving sparse text selection remains `enriched_text`-first regardless of active sparse backend
- pipeline tests proving dense embedding behavior remains unchanged when sparse backend switches
- CI tests proving sparse backend metadata is preserved in Qdrant payloads together with the existing enriched-text storage semantics
- tests simulating backend switches and asserting incompatible sparse indexes are detected and blocked before retrieval starts
- unit tests for explicit reindex requirement helpers or metadata comparison logic, specifically `sparse_backend_change_requires_reindex()` and startup-time payload metadata validation
