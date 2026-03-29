## Story

**S9-02: Parent-child chunking** — Phase 9: RAG Upgrades (based on eval results).

Verification criteria from plan: book → hierarchical chunks → retrieval returns child + parent.

Stable behavior requiring test coverage: long-form qualification, parent-section persistence, child-only retrieval payloads with parent metadata, child + parent context assembly, immediate/batch embedding parity, and fallback observability.

## Why

Flat chunking works for short documents, but long-form sources such as books often need more surrounding context than a single retrieved fragment can provide. This change adds hierarchical indexing so retrieval remains precise at the child level while answer generation receives the richer parent-section context required for grounded long-form responses.

## What Changes

- Add structure-first parent-child chunking for qualifying long-form Path B and Path C documents
- Persist parent sections and child-to-parent links in PostgreSQL as the canonical hierarchy model
- Keep retrieval ranking child-only while extending Qdrant child payloads with parent metadata for fast context expansion
- Update prompt assembly so the LLM receives child evidence plus deduplicated parent context
- Apply the same fixed parent-aware payload contract to both immediate embedding and Gemini Batch embedding flows
- Add structured observability for qualification decisions, fallback usage, and parent counts during ingestion
- Keep short documents and non-qualifying sources on the existing flat chunking path
- Fail the ingestion run for qualifying documents if hierarchy construction or parent persistence cannot complete consistently

### Long-form qualification

For this change, a "qualifying long-form document" means a Path B or Path C source that meets both hierarchy thresholds after initial flat chunking:

- Total parsed token count is greater than or equal to `PARENT_CHILD_MIN_DOCUMENT_TOKENS`.
- Parsed flat child chunk count is greater than or equal to `PARENT_CHILD_MIN_FLAT_CHUNKS`.

The current defaults are `1500` tokens and `6` child chunks. Structure markers such as headings, chapter labels, section labels, or document-semantic anchors improve the grouping strategy but are not mandatory for qualification.

Qualification maps to runtime behavior as follows:

- If `qualifies=true`, ingestion enables parent-section persistence in PostgreSQL, child-only retrieval payloads with parent metadata in Qdrant, child + parent context assembly, and immediate/batch embedding parity.
- If `qualifies=false`, the source stays on flat chunking, no `chunk_parents` rows are created, `chunks.parent_id` stays null, and Qdrant parent metadata fields remain null.

Examples:

- A Path B markdown book chapter with `2200` parsed tokens and `9` flat child chunks qualifies.
- A Path C OCR PDF with `1800` parsed tokens and `7` child chunks qualifies even if heading anchors are sparse.
- A short Path B note with `700` parsed tokens or only `3` flat child chunks does not qualify.
- A Path A source never enters this hierarchy flow.

Downstream code should treat the hierarchy decision as the authoritative signal. The observable runtime fields are the structured decision log (`qualifies`, `reason`, `has_structure`, `total_tokens`, `chunk_count`, `parent_count`) plus persisted `chunk_parents` rows and non-null `chunks.parent_id` values for qualifying documents.

### Structure-first chunking strategy

In this proposal, "structure-first parent-child chunking" means the algorithm prefers document structural boundaries such as headings, sections, and semantic blocks before falling back to size-only grouping.

- Parent chunks represent whole structural units whenever those units fit within configured parent size bounds.
- Child chunks remain the retrieval-ranked unit and are linked to exactly one parent chunk.
- If a structural unit exceeds the parent token bound, the system subdivides that unit deterministically into bounded parent groups without reordering children.
- If reliable structure is missing, the system falls back to deterministic adjacent-child grouping using the same configured token bounds.

Examples:

- Path B: for a markdown/manual document with `H1/H2` anchors, parent chunks align to those section boundaries first; if a single section is too large, subdivision happens inside that section rather than across sections.
- Path C: for an OCR/Document AI PDF, detected chapter/section anchors become parent boundaries when reliable; otherwise adjacent OCR-derived child chunks are grouped by bounded fallback inside the same reading order.

### Failure policy for qualifying documents

This change uses fail-closed behavior, not silent fallback to flat chunking, for qualifying long-form documents.

- State transitions are `BackgroundTaskStatus.PENDING -> PROCESSING -> FAILED` for the ingestion task and `SourceStatus.PENDING/PROCESSING -> FAILED` for the source when hierarchy construction or parent persistence fails.
- If document, document version, or chunk rows were already created, they are marked failed through the existing persistence failure path (`DocumentStatus.FAILED`, `DocumentVersionStatus.FAILED`, `ChunkStatus.FAILED`).
- There is no automatic retry, exponential backoff, or manual-review queue in this change.
- Recorded metadata/telemetry includes the task `error_message`, `completed_at`, the structured hierarchy decision log (`worker.ingestion.parent_child_decision`), and the terminal ingestion failure log (`worker.ingestion.failed`).
- Implementers should treat any broken hierarchy contract or parent persistence inconsistency as terminal for that ingestion run.

## Capabilities

### New Capabilities

- `hierarchical-chunking`: structure-first parent-child chunking, bounded fallback grouping, PostgreSQL parent persistence, and child-to-parent linking for qualifying long-form documents

### Modified Capabilities

- `ingestion-pipeline`: qualifying Path B/Path C documents now derive parent sections, persist parent links, and emit hierarchy decision logs during ingestion
- `vector-storage`: child Qdrant payloads now carry parent metadata while retrieval remains child-ranked
- `context-assembly`: retrieval context now supports child + parent prompt units with shared-parent deduplication
- `batch-embedding`: Gemini Batch submission/completion must preserve the same parent-aware payload contract as immediate embedding

## Impact

- **Backend code:** document processing, ingestion handlers, pipeline orchestration, Qdrant service, batch orchestrator, prompt assembly, and new hierarchy service
- **Database:** additive migration for `chunk_parents` and `chunks.parent_id`
- **APIs:** no public API changes
- **Systems affected:** knowledge contour primarily; dialogue contour receives context assembly changes; operational contour gains structured logs for hierarchy rollout visibility
- **Dependencies:** no new external libraries required
