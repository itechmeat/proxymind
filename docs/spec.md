# ProxyMind Specification

## System contours

The system is divided into three independent contours:

- **Dialogue contour** — message intake, session management, context selection, model invocation, streaming response with source references.
- **Knowledge contour** — source loading, parsing, chunking, embeddings, indexing, snapshot publishing.
- **Operations contour** — queues, background tasks, monitoring, audit, rate limits, cache.

This separation ensures resilience: chat does not depend on heavy indexing, and knowledge updates do not break online responses.

## Tools and versions

> All dependencies are installed at or above the specified versions. For tools without a single semver version, the official model identifier, API, or specific artifact is listed.

### Backend

| Tool             | Min. version | Role                                            |
| ---------------- | ------------ | ----------------------------------------------- |
| Python           | 3.14.3+      | Backend runtime                                 |
| FastAPI          | 0.135.1+     | HTTP API, streaming, lifespan hooks             |
| Pydantic         | 2.12.5+      | Model validation, settings (pydantic-settings)  |
| SQLAlchemy       | 2.0.48+      | Async ORM                                       |
| Alembic          | 1.18.4+      | DB schema migrations                            |
| asyncpg          | 0.31.0+      | Async PostgreSQL driver                         |
| HTTPX            | 0.28.1+      | HTTP client for external calls                  |
| tenacity         | 9.1.4+       | Retry/backoff for external call resilience      |
| structlog        | 25.5.0+      | Structured JSON logging                         |
| arq              | 0.27.0+      | Async background jobs on Redis                  |
| LiteLLM          | 1.82.3+      | Unified interface to LLM providers              |
| python-multipart | 0.0.20+      | Multipart/form-data parsing for FastAPI uploads |

### Data stores

| Tool       | Min. version | Role                                                     |
| ---------- | ------------ | -------------------------------------------------------- |
| PostgreSQL | 18.3+        | Source of truth, business entities, built-in OAuth       |
| Qdrant     | 1.17.0+      | Vector retrieval, payload filtering, payload indexes     |
| SeaweedFS  | —            | Object storage: files, pipeline artifacts                |
| Redis      | 8.6.1+       | Cache, locks, rate limits, idempotency keys, task broker |

### AI and data processing

> Local ML runtime policy: the project MUST remain deployable on a cheap VPS without local GPU/ML stacks. Installing local ML frameworks or heavyweight inference runtimes is strictly forbidden in project environments and Docker images. This includes `torch`, `torchvision`, `transformers`, CUDA runtime packages, OCR/vision ML stacks, and similar dependencies. When older documents mention local Docling/ML-based processing, this policy overrides them until those references are cleaned up.

| Tool                     | Min. version                            | Role                                                                       |
| ------------------------ | --------------------------------------- | -------------------------------------------------------------------------- |
| Gemini Embedding 2       | `gemini-embedding-2-preview` (model ID) | Multimodal embeddings (text, PDF, images, audio, video)                    |
| Google Cloud Document AI | API v1                                  | Advanced document parsing, OCR, layout, and tables as an external fallback |
| Lightweight parser stack | internal                                | Local parsing/chunking for Markdown, TXT, HTML, DOCX, and text-based PDFs  |
| Gemini Batch API         | v1                                      | Batch processing: embeddings, text extraction, evals (−50% cost)           |
| Deepgram                 | API v1 + model ID                       | Audio transcription (later stages)                                         |

### Frontend

| Tool       | Min. version | Role                   |
| ---------- | ------------ | ---------------------- |
| Bun        | 1.3.10+      | JS/TS runtime          |
| React      | 19.2.4+      | UI framework           |
| TypeScript | 5.9.3+       | Type checking          |
| Vite       | 8.0.0+       | Build, dev server, HMR |
| Biome      | 2.4.7+       | Linting and formatting |

### Infrastructure

| Tool          | Min. version                     | Role                                 |
| ------------- | -------------------------------- | ------------------------------------ |
| Docker        | 29.3.0+ (Engine)                 | Backend containerization             |
| Caddy         | 2.11.2+                          | Reverse proxy, auto-HTTPS            |
| Prometheus    | 3.10.0+                          | Metrics                              |
| Grafana       | 12.4.1+                          | Dashboards                           |
| Grafana Tempo | 2.10.3+                          | Trace storage (OTLP receiver)        |
| OpenTelemetry | Collector 1.53.0+ / spec 1.55.0+ | Distributed tracing, correlation ids |

## Knowledge architecture

Logical data layers:

**source → document → document_version → chunk → embedding profile → knowledge snapshot**

- **Source** — where data came from (book, blog, channel, podcast). Can optionally reference a product card in the catalog. An optional public URL is specified at upload time — only for publicly accessible materials. Sources without a public URL are part of the non-linked knowledge base.
- **Document** — a specific content unit.
- **Document version** — a version of the document after an update.
- **Chunk** — an indexable fragment, produced by the normalized parsing and chunking pipeline.
- **Embedding profile** — model, dimensions, task type, pass date, pipeline version.
- **Knowledge snapshot** — a published set of versions that the twin responds from.

The twin responds only from the active published snapshot. Drafts can be tested before publishing. Rollback to a previous snapshot is supported. Full audit trail of changes.

## Ingestion pipeline

Routing policy: **local-first, external-on-complexity**.

The system keeps storage, retrieval, and business state local, while offloading only heavy processing to external services.

**Path A — Gemini native path** for supported multimodal inputs within model limits when the router explicitly prefers native Gemini handling:

- Images (PNG, JPEG) — up to 6 files per request
- Audio (MP3, WAV) — up to 80 sec
- Video (MP4) — up to 120 sec
- Short PDFs only when native multimodal handling is preferred over lightweight text extraction

**Path B — lightweight local parsing path** by default for text-centric documents:

- Markdown, TXT
- HTML
- DOCX
- Text-based PDFs of any length when lightweight extraction is sufficient, including short PDFs

**Path C — external document intelligence fallback** for complex cases:

- Scanned PDFs
- PDFs with complex layout, tables, or poor reading order

Google Cloud Document AI is the preferred external fallback for Path C. It is used as a compute service only; parsed output is normalized into the local chunk contract before persistence and indexing.

Implementation knobs for Path C:

- `DOCUMENT_AI_PROJECT_ID` + `DOCUMENT_AI_PROCESSOR_ID` enable the fallback path
- `DOCUMENT_AI_LOCATION` defaults to `us`
- `PATH_C_MIN_CHARS_PER_PAGE` controls scan auto-detection for low-text PDFs

Long audio/video are currently rejected outside Path A limits. Any future fallback for these formats MUST remain external and MUST NOT introduce local ML runtimes.

**Chunking:** structure-aware, lightweight, and non-ML in the base installation. Local chunking MUST preserve headings and metadata where available. External parsing results MUST be normalized into the same chunk model (`text_content`, token count, chunk index, anchors) before persistence. Configurable chunk size targets the 8192-token window of Gemini Embedding 2.

Heavy operations (parsing, chunking, embeddings, reindex) run in background workers via arq + Redis. FastAPI does not perform ingestion in the request cycle.

**Gemini Batch API** is used for bulk operations: embedding generation when loading large knowledge bases, text_content generation for multimodal sources (Path A), full reindexing during reindex. Cost is −50% compared to the interactive API. SLO up to 24 hours, but usually significantly faster. Not used for real-time chat — only for asynchronous knowledge contour tasks and evals.

## Retrieval

Hybrid scoped retrieval — the twin searches only within the allowed knowledge scope, combining vector and keyword search:

1. Determine the active published snapshot.
2. Prepare the search query considering recent messages (query rewriting).
3. Obtain a dense embedding via Gemini Embedding 2 (query-oriented task type).
4. Obtain a sparse representation via the active sparse backend: Qdrant BM25 (`language` configurable per installation) or external BGE-M3 sparse output.
5. Hybrid search in Qdrant: dense + sparse vectors, Reciprocal Rank Fusion (RRF).
6. Apply payload filters: `agent_id`, `knowledge_base_id`, `snapshot_id`, `language`, `status`, `source_type`.
7. Select a limited set of chunks.
8. Pass only those to the LLM.

Indexing: retrieval-oriented task type (dense) + sparse representation from the active sparse backend. Search: query-oriented task type (dense) + sparse query from the same backend.

`SPARSE_BACKEND` is installation-level and supports `bm25` and `bge_m3`. The dense component (Gemini Embedding 2) remains unchanged. Switching the sparse backend requires explicit reindex because indexed child payloads persist `sparse_backend`, `sparse_model`, and `sparse_contract_version`, and startup validation rejects incompatible sparse contracts.

Qdrant payload indexes are required on frequently filtered fields.

## Agent memory

Three types of memory, never mixed in a single prompt:

- **Dialogue** — recent messages + brief conversation summary.
- **Operational** — language, channel, response format settings, active knowledge scope.
- **Knowledge** — retrieval context from Qdrant based on the published snapshot.

This separation prevents cost growth, loss of controllability, and emergence of "false memory."

## Response policy

- Relies on the published knowledge base. Can discuss adjacent topics but does not stray far beyond boundaries.
- If data is unavailable — honest refusal without fabrication.
- Never mix old and draft knowledge versions.

## Response format: content types

Each fragment of the twin's response belongs to one of three types:

- **Knowledge-based fact** — a statement backed by a specific chunk from the published snapshot. May include a reference or citation.
- **Inference** — reasoning or conclusion based on its knowledge, but without verbatim support from a specific source. The twin can discuss adjacent topics but must not present inference as fact.
- **Commercial recommendation** — a native product or service suggestion from the prototype, woven into the conversation context. Does not look like advertising — the twin recommends naturally, like a real person. Source is the product catalog, not the knowledge base.

Ideally the user understands which type each part of the response belongs to. The specific implementation (visual markup, tooltips, blocks) is a frontend concern.

## Source references

Three formats:

- **Direct quote** — a verbatim fragment with source attribution (book/chapter/page, video, post). Used when a quote strengthens the response.
- **Inline reference** — a fragment of response text wrapped in a link to the original. The text is not a quote but leads to the source.
- **Collapsed sources block** — below the message, similar to Perplexity. All relevant sources used in forming the response.

Not every message contains references — only where appropriate. Light small talk or clarifying questions from the twin have no references.

### Citation protocol

The LLM **never generates URLs on its own**. Core principle:

1. The LLM prompt receives chunks with metadata: `source_id`, `chunk_id`, and chunk anchor metadata (source title, chapter, page, section, timecode — whatever is available from the normalized parsing pipeline).
2. The LLM returns a response in Markdown format, referencing retrieved sources via ordinal markers (e.g., `[source:1]`).
3. The backend constructs the citation based on source and chunk metadata:
   - **Source with a public URL** — a clickable link with anchor details (e.g., _"Book Title, Chapter 3"_ → link to store).
   - **Source without a public URL** — a text citation without a link (e.g., _"Book Title, Chapter 3, p. 42"_). Not clickable but informative.
4. Anchor metadata (page, chapter, section, timecode) is stored in the Qdrant payload during chunk indexing. The backend extracts it when constructing citations.

This eliminates link hallucination: the LLM operates only with identifiers, while citation construction (URL + anchor or text reference) happens on the backend.

## Commercial links and product catalog

In addition to knowledge source references, the twin can reference the prototype's products and services:

- Links to stores (books, courses, merch).
- Links to events (concerts, lectures, conferences).
- Native recommendations woven into the dialogue context.

The product catalog is a separate entity outside the knowledge base.

**Source ↔ catalog item relationship.** A single entity can be both a knowledge source and a product. A book = source in the knowledge base + product in the catalog. A source optionally references a product card, allowing automatic purchase link suggestions when citing.

### PROMOTIONS.md — current promotions file

A configuration file for current sales priorities:

- List of current products/services with priority.
- Contextual hints — when it is appropriate to suggest them.
- Validity dates — automatic removal of expired items.

Not part of the knowledge base. An operational config, similar to persona files.

**Management in v1:** files managed manually (git / filesystem). In the future — possible migration to an admin panel and database.

## Persona files

Minimum set for v1:

- **IDENTITY.md** — who this twin is, role, background, public biography.
- **SOUL.md** — speech style, tone, values, worldview.
- **BEHAVIOR.md** — reactions to topics, discussion boundaries, dialogue manner, off-limits topics.

Extended set (future versions): TOOLS.md, HEARTBEAT.md, BOOTSTRAP.md, etc. Discussed in agent.md.

**Management in v1:** files managed manually. Versioned together with the rest of the configuration.

## Embedding

Gemini Embedding 2:

- Dimensions: 128–3072 (default 3072). Matryoshka Representation Learning for flexible truncation.
- Max input: 8192 tokens.
- Multimodal: text, images, audio, video, PDF.
- All modalities in a single vector space.

Qdrant collection organization (one shared or separate per modality) is an architectural decision to be made after initial evals. Requirement: a unified retrieval API regardless of internal collection structure.

Task types:

- **retrieval-oriented** — for document indexing.
- **query-oriented** — for user queries.

Embedding pass metadata is stored in PostgreSQL: model, dimensions, task type, date, pipeline version.

Optimal dimensions (1024 / 1536 / 3072) to be determined empirically during evals.

### Multilingual support

The product defaults to English, but all language-dependent components are configurable:

- **Gemini Embedding 2** — natively supports 100+ languages.
- **Qdrant BM25** — `language` parameter in `Bm25Config` (Snowball stemmer, stop lists). Supports English, German, French, Spanish, Italian, Portuguese, Dutch, Swedish, Norwegian, Danish, Finnish, Hungarian, Romanian, Turkish, and others.
- **External BGE-M3 sparse backend** — multilingual model (100+ languages). Used only for sparse output while the dense component remains on Gemini Embedding 2.

Language and sparse backend are set at deploy time via `.env` and applied to all language-dependent components. Backend selection must be validated through two-run eval comparison before rollout to an installation.

## Provider independence

- **Reasoning model (LLM)** — any provider (OpenAI, Anthropic, Google, open-source). Abstracted via LiteLLM.
- **Embeddings** — tied to Gemini Embedding 2 at launch. Switching providers requires full reindexing.
- **Document processing** — lightweight local parsing by default, with external heavy processing through Google Cloud Document AI as a fallback for complex documents.
- **Transcription** — Deepgram (later stages). At launch — upload of pre-made transcripts.

## Tenant-ready model

An architectural precaution, not a product feature. Even with a single agent per instance — preserve in data structures:

- `owner_id`
- `agent_id`
- `knowledge_base_id`
- `published_version_id`

Does not introduce tenants as an entity but does not close the path to scaling.

## User authentication, visitor identity, and channel connectors

V1 web/app chat MUST require authenticated end-user access. The standard user flow is email-based authentication: registration, sign-in, and password recovery/reset via email. Website/app guests MUST NOT be allowed to create chat sessions, send chat messages, read chat history, or access twin-interaction endpoints that expose dialogue state.

Guest access should be limited to:

- end-user authentication endpoints (for example `/api/auth/*`)
- narrow operational endpoints such as `/health` and `/ready`
- any future explicitly public surface that is separated from chat/session endpoints

Admin access remains a separate authentication surface. In v1 it uses an admin token/API key flow and MUST NOT be merged with the end-user email flow.

Frontend requirements for authentication surfaces:

- the frontend MUST provide user-facing pages for sign-in, registration, and password recovery/reset
- the frontend MUST provide a separate admin authentication page for token-based admin access
- user and admin frontend components MAY reuse the same low-level UI primitives, forms, and validation helpers, or MAY be implemented as separate components, but the route boundaries, state, and security semantics MUST remain distinct

In later stages, ProxyMind may add **channel connectors** for social and messaging platforms such as Telegram, Facebook, VK, Instagram, TikTok, and similar channels. The preferred term is **channel connector**, not plain "connector", to avoid confusion with MCP data connectors and other integration types.

Channel connectors must not require a separate local registration flow for end users. Instead, the system should support implicit visitor provisioning and lookup based on platform-provided identity, using a stable pair such as `(channel_connector, external_user_id)`.

Architectural requirement: **admin authentication and visitor identity must remain decoupled**. Changes to admin auth must not assume that external chat users have local credentials, passwords, or an interactive registration flow inside ProxyMind.

Session, audit, and messaging models should remain ready to carry optional channel metadata so that future connector support can be added without rewriting the core auth model.

## Active response configuration

Each twin response is formed based on three artifacts:

- **Knowledge snapshot** — the published version of the knowledge base.
- **Persona files** — IDENTITY.md, SOUL.md, BEHAVIOR.md.
- **PROMOTIONS.md** — current sales priorities.

For audit and evals: when logging a response, `snapshot_id`, `config_commit_hash` (full git commit), and `config_content_hash` (SHA256 of `persona/` + `config/` contents) are recorded. The content hash distinguishes configuration changes from code/documentation changes.

## Implementation defaults

| Parameter                          | Default             | Description                                                                                                                     |
| ---------------------------------- | ------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| `conversation_memory_budget`       | 4096 tokens         | Maximum tokens for conversation memory in the prompt, including summary and verbatim sliding window.                            |
| `conversation_summary_ratio`       | 0.3                 | Soft target for summary generation length as a fraction of the memory budget. Actual summary tokens are deducted at face value. |
| `conversation_summary_model`       | same as `llm_model` | Optional separate model for conversation summarization. Falls back to the main LLM model when unset.                            |
| `conversation_summary_temperature` | 0.1                 | Temperature for summary generation calls in the background worker.                                                              |
| `conversation_summary_timeout_ms`  | 10000               | Timeout in milliseconds for the summary LLM call executed by the arq worker.                                                    |

## Testing strategy

Two contours:

- **Deployment tests (CI)** — deterministic unit and integration tests independent of external providers. Fast, stable, block deployment on failure.
- **Quality tests (evals)** — provider smoke tests + semi-automated eval runs on real models. Run separately, do not block CI.
