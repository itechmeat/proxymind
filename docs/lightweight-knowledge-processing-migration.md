# Lightweight Knowledge Processing Migration

## Goal

Move ProxyMind from a Docling-centric ingestion design to a **lightweight local core with external-heavy processing**.

The target state is:

- data and retrieval remain local
- heavy document intelligence moves to external services
- the base installation stays deployable on a cheap VPS
- Qdrant remains the canonical retrieval store

## Architectural decision

ProxyMind keeps **knowledge ownership, storage, retrieval, and business state** inside the product. External providers are used only as compute services.

This means:

- PostgreSQL remains the source of truth
- SeaweedFS remains the file store
- Qdrant remains the vector retrieval store
- snapshots, citations, audit, and chunk metadata remain product-owned
- Google services are adapters, not system-of-record components

## Processing policy

Routing policy: **local-first, external-on-complexity**.

### Path A: Gemini native

Use Gemini-native processing only where the model directly supports the input within documented limits:

- short PDF
- images
- short audio
- short video

Gemini-native processing is used for multimodal embeddings and content extraction when that is the most direct path.

### Path B: lightweight local

Use local lightweight parsing and chunking by default for text-centric documents:

- Markdown
- TXT
- HTML
- DOCX
- text-based PDF

The local path MUST avoid local ML runtimes, OCR stacks, CUDA packages, and heavyweight inference dependencies.

### Path C: external document intelligence fallback

Use Google Cloud Document AI only when lightweight extraction is insufficient:

- scanned PDF
- complex tables
- complex reading order
- layout-heavy documents
- other cases where the local path materially degrades document quality

Document AI output MUST be normalized into the same internal chunk contract used by the local path.

## Boundary rules

### Local responsibilities

The following concerns remain local and product-owned:

- ingestion orchestration
- routing decisions
- normalized chunk model
- citation metadata
- snapshot lifecycle
- indexing into Qdrant
- retrieval rules
- audit trail

### External responsibilities

The following concerns are allowed to be externalized:

- multimodal embeddings
- OCR
- layout analysis
- table understanding
- complex document parsing

## Non-goals

This migration does **not** move ProxyMind to a Google-managed retrieval stack.

Specifically, the migration does not make these systems canonical by default:

- Vertex AI Search as the primary retrieval layer
- Vertex AI RAG Engine as the primary knowledge store

These may be evaluated later, but they are not part of the target architecture for this migration.

## Internal contract requirement

All ingestion paths MUST converge to the same normalized internal contract before persistence and indexing.

Minimum normalized chunk contract:

- `text_content`
- `token_count`
- `chunk_index`
- `anchor_page`
- `anchor_chapter`
- `anchor_section`

Provider-specific response shapes MUST NOT leak into domain models or retrieval logic.

## Why this migration exists

The previous Docling-centric design solved parsing and chunking, but it conflicted with the product's operating constraint:

- the base system must remain lightweight
- local heavy ML dependencies are unacceptable
- heavy processing volume is expected to be low enough to justify external services

The migration aligns the implementation with the product direction instead of preserving a heavier architecture that is no longer desired.

## Expected outcome

After the migration:

- the base installation remains cheap-VPS friendly
- local containers do not pull heavy ML/OCR runtimes
- text-centric documents continue to ingest through the lightweight local path
- complex documents are handled by external fallback processing
- Qdrant remains local and unchanged as the retrieval backbone
- the product retains control of storage, snapshots, citations, and indexing semantics

## Implementation checklist for the next story

- define a provider-agnostic document processing interface
- keep the lightweight local parser path as the default baseline
- add a Document AI adapter for complex-document fallback
- preserve the current chunk contract across all paths
- verify citation compatibility after normalization
- remove remaining runtime assumptions that require Docling-specific metadata
- keep dependency policy aligned with the cheap-VPS constraint
