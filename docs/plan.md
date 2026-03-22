# ProxyMind Development Plan

Initial focus — chat-first digital twin. The plan is built in vertical slices: each phase ends with a working and verifiable result. After phase 2, you can already upload a document and get an answer.

## Testing Strategy

Tests are split into two tracks:

- **Deploy tests (CI)** — deterministic unit and integration tests with no external provider dependencies. Fast, stable, block deployment on failure.
- **Quality tests (evals)** — provider smoke tests + semi-automated eval runs on real models. Run separately, do not block CI.

## Stories

### Phase 1: Bootstrap

Phase outcome: the project starts, all services run, API responds.

- [x] **S1-01: Project bootstrap**
      Monorepo structure (`backend/` + `frontend/` + `persona/` + `config/` + `docs/`), `docker-compose.yml` (PostgreSQL, Qdrant, SeaweedFS, Redis), Dockerfile for backend, Caddyfile, `.editorconfig`, `.gitignore`, separate `.env` files. Backend: `pyproject.toml`, FastAPI app skeleton, structlog, `/health` and `/ready` endpoints. Frontend: Bun + Vite + React + Biome init.
  - **Outcome:** infrastructure starts with a single command, API is accessible
  - **Verification:** `docker-compose up` → all services start; `curl /health` → 200; `cd frontend && bun dev` → dev server starts
  - Tasks: directory structure, Docker, FastAPI app, frontend init, CI lint (Biome + Ruff)

- [x] **S1-02: Database + migrations**
      SQLAlchemy 2.x, Alembic, asyncpg. All base tables: agents, sources, documents, document_versions, chunks (metadata), knowledge_snapshots, sessions, messages, audit_logs, embedding_profiles, batch_jobs, catalog_items. Tenant-ready fields.
  - **Outcome:** DB schema is created automatically on startup
  - **Verification:** `alembic upgrade head` → all tables; basic CRUD agent via tests
  - Tasks: SQLAlchemy models, Alembic config, first migration, seed data for agent

### Phase 2: First E2E Slice

Phase outcome: minimal working product. Upload a Markdown file → get a snapshot → ask a question → see an answer.

- [x] **S2-01: Upload source**
      `POST /api/admin/sources` — accept file (Markdown/TXT) + metadata. File → MinIO, metadata → PostgreSQL, task → Redis queue.
  - **Outcome:** a file can be uploaded via API and is persisted
  - **Verification:** `curl -F file=@doc.md /api/admin/sources` → 202 + task_id; file in MinIO; record in PG
  - Tasks: MinIO client, upload endpoint, task queue (arq), GET /api/admin/tasks/:id

- [x] **S2-02: Parse + chunk + embed**
      Worker picks up the task: Docling parses the file → HybridChunker splits into chunks with anchor metadata → Gemini Embedding 2 generates dense vectors → upsert into Qdrant with payload.
  - **Outcome:** uploaded document is indexed and available for search
  - **Verification:** upload MD file → chunks in PG with metadata; chunks in Qdrant; vector search returns results
  - Tasks: Docling integration, HybridChunker config, Gemini Embedding 2 client, Qdrant client, worker task

- [x] **S2-03: Knowledge snapshot (minimal)**
      Draft → publish → active lifecycle. On source upload, chunks are linked to a draft snapshot. Publish finalizes the snapshot, activate selects it for retrieval, and publish supports `?activate=true` as a convenience path. Retrieval only from active.
  - **Outcome:** knowledge versions can be listed, inspected, published, activated, and search works only against active content
  - **Verification:** create draft → upload source → publish+activate → vector search against active snapshot works; chunks from draft are not visible
  - Tasks: snapshot list/detail API, publish/activate logic, active snapshot invariant, ingestion-side snapshot locking

- [x] **S2-04: Minimal chat**
      `POST /api/chat/messages` — accept a question, find relevant chunks in Qdrant (dense vector search against active snapshot), assemble prompt (minimal: system + retrieval context + question), call LLM via LiteLLM, return response (JSON, no streaming).
  - **Outcome:** a question can be asked and answered based on uploaded knowledge
  - **Verification:** upload document → publish → `POST /api/chat/messages {"text": "..."}` → response based on document content
  - Tasks: LiteLLM integration, retrieval service (dense only), prompt assembly (minimal), chat endpoint, session creation

- [x] **S2-05: Replace Legacy Object Storage with SeaweedFS**
      Legacy object storage is deprecated and MUST be fully removed. Replace it with SeaweedFS (`weed server -filer`, all-in-one). Rewrite `StorageService` to use `httpx` + SeaweedFS Filer HTTP API (POST/GET/DELETE). Replace the Docker Compose service, migrate configuration (`SEAWEEDFS_*`), and update all documentation.
  - **Outcome:** object storage works on SeaweedFS, zero legacy object-storage references remain in runtime code and canonical docs
  - **Verification:** `docker-compose up` → SeaweedFS healthy; upload source → file in SeaweedFS; existing tests pass; scoped case-insensitive search for the removed provider name returns zero matches in runtime code and canonical docs
  - Tasks: Docker Compose swap, StorageService rewrite (httpx + Filer API), config migration, test updates, documentation updates (spec.md, architecture.md, plan.md, rag.md, CLAUDE.md, AGENTS.md, README.md), remove the obsolete object-storage SDK from `pyproject.toml`

### Phase 3: Knowledge Expansion

Phase outcome: full-featured ingestion pipeline — all formats, hybrid search, batch, snapshots with rollback.

- [x] **S3-01: More formats (PDF, DOCX, HTML)**
      Extend Docling parsing: PDF with tables and structure, DOCX, HTML. Anchor metadata for each format (page, chapter, section).
  - **Outcome:** PDF/DOCX/HTML can be uploaded and parsed correctly
  - **Verification:** upload PDF → chunks with page numbers; upload DOCX → chunks with headings
  - Tasks: Docling format configs, anchor extraction per format, tests for different formats

- [ ] **S3-02: BM25 sparse vectors**
      Qdrant BM25 sparse vectors (language from `.env`, Snowball stemmer) indexed alongside dense as named vectors.
  - **Outcome:** keyword search works alongside vector search
  - **Verification:** keyword search via Qdrant returns results; stemmer language matches `.env`
  - Tasks: Bm25Config with language, sparse vector upsert, keyword search endpoint for tests

- [ ] **S3-03: Hybrid retrieval + RRF**
      Dense (query-oriented) + sparse (BM25) search, Reciprocal Rank Fusion, `min_dense_similarity` filtering before fusion. Scoped by `snapshot_id` + tenant-ready fields.
  - **Outcome:** retrieval combines semantic and keyword search
  - **Verification:** query → results better than dense-only; filtering by snapshot works
  - Tasks: Qdrant hybrid query, RRF fusion config, payload filtering, retrieval service upgrade

- [ ] **S3-04: Path A (Gemini native)**
      For short PDFs/images/audio/video: Gemini LLM → text_content, Gemini Embedding 2 → vector. Thresholds for switching to Path B (`path_a_text_threshold_pdf`, `path_a_text_threshold_media`).
  - **Outcome:** multimodal sources are indexed and searchable
  - **Verification:** upload image → text_content generated → search query finds it
  - Tasks: Gemini GenerateContent for text extraction, Path A/B routing logic, threshold config

- [ ] **S3-05: Snapshot lifecycle (full)**
      Rollback to previous published. Draft testing via Admin API (`POST /api/admin/snapshots/:id/test`). Soft delete source considering published snapshots. Snapshot list/detail already delivered in S2-03.
  - **Outcome:** full knowledge version management
  - **Verification:** publish → rollback → twin responds from old snapshot; test draft → only draft chunks visible
  - Tasks: rollback endpoint, draft test endpoint, source soft delete logic

- [ ] **S3-06: Gemini Batch API**
      Bulk operations: batch_jobs in PG, Gemini → internal status mapping, deduplication on retry, polling.
  - **Outcome:** bulk uploads are processed cheaper and in parallel
  - **Verification:** upload 10+ files → batch job → all processed; retry → batch not duplicated
  - Tasks: Batch API client, batch_jobs table, status mapping, retry guard

### Phase 4: Dialog Expansion

Phase outcome: full-featured dialog with persona, citations, memory, promotions.

- [ ] **S4-01: Persona loader**
      Read `IDENTITY.md` / `SOUL.md` / `BEHAVIOR.md` from `persona/`. Inject into system prompt. System safety policy (immutable, on top of persona). `config_commit_hash` + `config_content_hash` for audit.
  - **Outcome:** twin responds according to configured persona
  - **Verification:** change SOUL.md → restart → response style changed; system safety policy cannot be bypassed via persona
  - Tasks: file reader, prompt injection, system safety prompt, hash computation

- [ ] **S4-02: SSE streaming**
      Switch `POST /api/chat/messages` to SSE streaming. Message state machine: received → streaming → complete/partial/failed. Idempotency key. Persist user + assistant messages in PG.
  - **Outcome:** responses stream in real time
  - **Verification:** send message → SSE token stream → response saved; disconnect → partial; retry → idempotent result
  - Tasks: SSE endpoint, message state machine, idempotency, message persistence

- [ ] **S4-03: Citation builder**
      LLM returns `[source_id:N]`, backend substitutes URL (online) or text citation (offline). Anchor metadata from Qdrant payload. SSE event type=citations.
  - **Outcome:** responses contain verified source references
  - **Verification:** response with citation → correct URL; offline source → "Book, chapter N, p. M"
  - Tasks: citation prompt instructions, source_id extraction, URL/text substitution, SSE citation event

- [ ] **S4-04: Query rewriting**
      LLM-based reformulation with history context. Fail-open on timeout. Token budget.
  - **Outcome:** multi-turn dialog yields relevant retrieval
  - **Verification:** "tell me more" → reformulated → better retrieval; timeout → fallback to original
  - Tasks: rewrite prompt, timeout handling, token budget trimming

- [ ] **S4-05: PROMOTIONS.md integration**
      Backend parses `PROMOTIONS.md`: filter expired, inject into prompt by priority rules (high/medium/low). No more than one recommendation per response.
  - **Outcome:** twin natively recommends relevant current products in context
  - **Verification:** promo with expired date → not in prompt; high priority → appears in relevant context
  - Tasks: PROMOTIONS.md parser, expiry filter, priority-based inclusion, prompt layer

- [ ] **S4-06: Context assembly (full)**
      All 8 prompt layers: system safety → IDENTITY → SOUL → BEHAVIOR → PROMOTIONS → dialog memory → retrieval → user query. Token budget management (`retrieval_context_budget`). Content type markup (fact/inference/recommendation).
  - **Outcome:** full prompt assembly with all layers and content types
  - **Verification:** all layers present; when budget exceeded — retrieval is trimmed; response distinguishes content types
  - Tasks: prompt builder service, token counting, budget trimming, content type instructions

- [ ] **S4-07: Conversation memory**
      Dialog history + summary for long conversations. Trimming when token budget exceeded. Session management.
  - **Outcome:** long conversations retain context
  - **Verification:** 20+ messages → context preserved; summary generated when limit reached
  - Tasks: history window, summary generation trigger, token budget integration

### Phase 5: Frontend

Phase outcome: full-featured web interface for visitors and the owner.

- [ ] **S5-01: Chat UI**
      React + Vite + Bun. Chat interface: input field, message feed, SSE streaming, twin avatar and name.
  - **Outcome:** visitor can chat with the twin in the browser
  - **Verification:** open → send message → streaming response → history on refresh
  - Tasks: chat layout, SSE client, message rendering, session persistence

- [ ] **S5-02: Citations display**
      Inline references in text, collapsible sources block under the message (Perplexity-style). Clickable for online, text-only for offline.
  - **Outcome:** sources are visible and clickable
  - **Verification:** citation → clickable link; collapse/expand block
  - Tasks: citation parser, collapsible block component, link rendering

- [ ] **S5-03: Admin UI — source upload**
      File upload (drag & drop), source list with ingestion statuses, soft delete.
  - **Outcome:** owner uploads and views sources through the interface
  - **Verification:** upload file → see processing progress → status done
  - Tasks: file upload component, source list, status polling, delete confirmation

- [ ] **S5-04: Admin UI — snapshot management**
      Snapshot list, create draft, publish, rollback, draft testing.
  - **Outcome:** owner manages knowledge versions through the interface
  - **Verification:** create snapshot → publish → twin responds from it; rollback → previous version
  - Tasks: snapshot list, publish/rollback buttons, draft test view

- [ ] **S5-05: Admin UI — product catalog**
      Product catalog CRUD, source ↔ catalog item linking.
  - **Outcome:** owner manages products through the interface
  - **Verification:** add product → link to source → citation includes purchase link
  - Tasks: catalog form, source-catalog linking UI

- [ ] **S5-06: Admin UI — twin profile**
      Avatar (upload → SeaweedFS), name, public links.
  - **Outcome:** twin profile is configured and displayed in the chat
  - **Verification:** upload avatar → visible in chat interface
  - Tasks: avatar upload, profile metadata form, display in chat header

### Phase 6: Commerce

Phase outcome: full commercial layer — catalog, recommendations, citation integration.

- [ ] **S6-01: Product catalog (backend)**
      Admin API: CRUD catalog_items. Source ↔ catalog_item linking. When citing a source linked to a product, automatically suggest a purchase link.
  - **Outcome:** products are linked to sources and appear in citations
  - **Verification:** citation of a book linked to a product → store link nearby
  - Tasks: catalog API endpoints, source-catalog linking, citation enrichment

- [ ] **S6-02: Native recommendations (end-to-end)**
      Catalog + PROMOTIONS.md + citation builder. Native delivery. Citation takes priority over commercial link.
  - **Outcome:** twin recommends products naturally in context
  - **Verification:** conversation about music → twin mentions a concert; not every response contains a recommendation
  - Tasks: promotion-catalog integration, native recommendation prompt, frequency control

### Phase 7: Operations Layer

Phase outcome: the product is secured, observable, and auditable.

- [ ] **S7-01: Admin API auth**
      API key (`Authorization: Bearer`). Key from `.env`. Chat API is public.
  - **Outcome:** admin endpoints are protected
  - **Verification:** without key → 401; with key → 200
  - Tasks: auth middleware, key config, error responses, keep admin auth isolated from future visitor identity for channel connectors

- [ ] **S7-02: Rate limiting**
      Redis-based for Chat API. Configurable limits.
  - **Outcome:** chat is protected from abuse
  - **Verification:** exceed limit → 429; after cooldown → ok
  - Tasks: rate limit middleware, Redis counters, config

- [ ] **S7-03: Audit logging**
      Every response → audit_logs: `snapshot_id`, `source_ids`, `config_commit_hash`, `config_content_hash`, timestamp, session_id.
  - **Outcome:** every response is reproducible
  - **Verification:** conversation → audit records with full data
  - Tasks: audit service, log schema, config hash injection

- [ ] **S7-04: Monitoring and tracing**
      Prometheus `/metrics`, Grafana dashboard, OpenTelemetry tracing, correlation ids.
  - **Outcome:** system is observable
  - **Verification:** dashboard with metrics; end-to-end request trace
  - Tasks: metrics middleware, Grafana provisioning, OTel instrumentation

### Phase 8: Evals and Quality

Phase outcome: measured quality, data-driven decisions on upgrade paths.

- [ ] **S8-01: Eval framework**
      Test harness, dataset format, suite runner, report generation. Separate from CI.
  - **Outcome:** eval suite can be run and produces a report
  - **Verification:** `run-evals` → report with metrics
  - Tasks: dataset format, eval runner, report generator

- [ ] **S8-02: Retrieval evals**
      Precision@K, Recall@K, MRR. Baseline for hybrid search.
  - **Outcome:** retrieval quality is measured
  - **Verification:** report with retrieval metrics; baseline recorded
  - Tasks: retrieval eval scenarios, metric computation, baseline snapshot

- [ ] **S8-03: Answer quality evals**
      Groundedness, citation accuracy, persona fidelity, refusal quality. LLM-as-judge + manual sampling.
  - **Outcome:** answer quality is measured across all criteria
  - **Verification:** report with answer metrics
  - Tasks: eval prompts per metric, scoring rubric, human review process

- [ ] **S8-04: Upgrade path decision**
      Documented decision based on S8-02/S8-03: chunk enrichment, parent-child, BGE-M3.
  - **Outcome:** data-backed plan for next improvements
  - **Verification:** decision document supported by data
  - Tasks: data analysis, cost/benefit, decision doc

### Phase 9: RAG Upgrades (based on eval results)

Phase outcome: improved retrieval and answer quality driven by data.

- [ ] **S9-01: Chunk enrichment**
      Fresh research (RAGFlow Transformer stage). LLM enrichment (summary, keywords, questions) via Batch API. New payload fields. Reindex.
  - **Outcome:** retrieval metrics improved
  - **Verification:** A/B eval: with enrichment vs without → documented improvement
  - Tasks: research, enrichment pipeline stage, Batch API integration, reindex, A/B eval

- [ ] **S9-02: Parent-child chunking**
      Hierarchical indexing for books. Search by child, context from parent.
  - **Outcome:** long documents provide richer context
  - **Verification:** book → hierarchical chunks → retrieval returns child + parent
  - Tasks: hierarchy extraction from Docling, parent-child linking, context expansion

- [ ] **S9-03: BGE-M3 fallback**
      Replace BM25 sparse with BGE-M3 sparse for languages with insufficient BM25 quality. Dense (Gemini) unchanged.
  - **Outcome:** keyword search improves for the target language
  - **Verification:** eval on target language → metrics improved vs BM25
  - Tasks: BGE-M3 integration, sparse vector swap, reindex, language-specific eval

### Phase 10: Agent Protocols (TOOLS.md)

Phase outcome: twin is available as an agent in the open ecosystem.

- [ ] **S10-01: A2A endpoint**
      Agent Card, task intake via A2A protocol, stateful task lifecycle, streaming.
  - **Outcome:** external agents can interact with the twin
  - **Verification:** Agent Card at URL; external agent → task → response
  - Tasks: A2A spec implementation, Agent Card generation, task handler, streaming transport

- [ ] **S10-02: MCP layer**
      Internal access to tools and data connectors via MCP. `TOOLS.md` configuration.
  - **Outcome:** MCP clients can use the twin's capabilities
  - **Verification:** MCP client → list tools → call tool → result
  - Tasks: MCP server, tool registry, TOOLS.md parser, data connector adapters

### Phase 11: External Channels

Phase outcome: the twin can operate in external messaging and social channels without a standalone ProxyMind registration flow for end users.

- [ ] **S11-01: External visitor identity model**
      Introduce a visitor identity model for future channel connectors. Resolve or create visitors implicitly from platform identity such as `(channel_connector, external_user_id)`. Keep this separate from admin auth.
  - **Outcome:** the auth model is ready for external channel users without rewriting admin authentication
  - **Verification:** architecture and schema support mapping an external identity to a visitor and session without local registration
  - Tasks: visitor identity entity, external identity mapping, channel metadata on sessions/messages, audit considerations

- [ ] **S11-02: Channel connectors foundation**
      Add the integration layer for external chat platforms (Telegram, Facebook, VK, Instagram, TikTok, and similar channels). Normalize inbound/outbound events into the same internal chat flow as the web UI.
  - **Outcome:** the system has a defined path for adding external channels without changing the core dialogue workflow
  - **Verification:** connector contract documented; one connector can deliver a normalized message into the chat pipeline
  - Tasks: connector interface, message normalization, delivery abstraction, connector lifecycle and error handling
