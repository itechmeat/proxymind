# ProxyMind Development Plan

Initial focus — chat-first digital twin. The plan is built in vertical slices: each phase ends with a working and verifiable result. After phase 2, you can already upload a document and get an answer.

> **Security ordering note:** The Chat API is public from S2-04, and Admin API endpoints are added throughout Phases 2–5, but API security (S7-01: auth + rate limiting) is in Phase 7. This is acceptable for local development but MUST be resolved before any production deployment. Rate limiting and admin auth are baseline security per `docs/development.md` and `docs/architecture.md`, not late hardening. For production readiness, implement S7-01 before exposing the instance to untrusted traffic.

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

- [x] **S2-01: Upload source** (DON'T CHANGE!!!)
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

- [x] **S3-02: BM25 sparse vectors**
      Qdrant BM25 sparse vectors (language from `.env`, Snowball stemmer) indexed alongside dense as named vectors.
  - **Outcome:** keyword search works alongside vector search
  - **Verification:** keyword search via Qdrant returns results; stemmer language matches `.env`
  - Tasks: Bm25Config with language, sparse vector upsert, keyword search endpoint for tests

- [x] **S3-03: Hybrid retrieval + RRF**
      Dense (query-oriented) + sparse (BM25) search, Reciprocal Rank Fusion, `min_dense_similarity` filtering before fusion. Scoped by `snapshot_id` + tenant-ready fields.
  - **Outcome:** retrieval combines semantic and keyword search
  - **Verification:** query → results better than dense-only; filtering by snapshot works
  - Tasks: Qdrant hybrid query, RRF fusion config, payload filtering, retrieval service upgrade

- [x] **S3-04: Path A (Gemini native)**
      For short PDFs/images/audio/video: Gemini LLM → text_content, Gemini Embedding 2 → vector. Thresholds for switching to Path B (`path_a_text_threshold_pdf`, `path_a_text_threshold_media`).
  - **Outcome:** multimodal sources are indexed and searchable
  - **Verification:** upload image → text_content generated → search query finds it
  - Tasks: Gemini GenerateContent for text extraction, Path A/B routing logic, threshold config

- [x] **S3-05: Snapshot lifecycle (full)**
      Rollback to previous published. Draft testing via Admin API (`POST /api/admin/snapshots/:id/test`). Soft delete source considering published snapshots. Snapshot list/detail already delivered in S2-03.
  - **Outcome:** full knowledge version management
  - **Verification:** publish → rollback → twin responds from old snapshot; test draft → only draft chunks visible
  - Tasks: rollback endpoint, draft test endpoint, source soft delete logic

- [x] **S3-06: Gemini Batch API**
      Bulk operations: extend existing `batch_jobs` table (created in S1-02) with Gemini-specific fields, Gemini → internal status mapping, deduplication on retry, polling.
  - **Outcome:** bulk uploads are processed cheaper and in parallel
  - **Verification:** upload 10+ files → batch job → all processed; retry → batch not duplicated
  - Tasks: Batch API client, extend batch_jobs schema, status mapping, retry guard

### Phase 4: Dialog Expansion

Phase outcome: full-featured dialog with persona, citations, memory, promotions.

- [x] **S4-01: Persona loader**
      Read `IDENTITY.md` / `SOUL.md` / `BEHAVIOR.md` from `persona/`. Inject into system prompt. System safety policy (immutable, on top of persona). `config_commit_hash` + `config_content_hash` for audit.
  - **Outcome:** twin responds according to configured persona
  - **Verification:** change SOUL.md → restart → response style changed; system safety policy cannot be bypassed via persona
  - Tasks: file reader, prompt injection, system safety prompt, hash computation

- [x] **S4-02: SSE streaming**
      Switch `POST /api/chat/messages` to SSE streaming. Message state machine: received → streaming → complete/partial/failed. Idempotency key. Persist user + assistant messages in PG.
  - **Outcome:** responses stream in real time
  - **Verification:** send message → SSE token stream → response saved; disconnect → partial; retry → idempotent result
  - Tasks: SSE endpoint, message state machine, idempotency, message persistence

- [x] **S4-03: Citation builder**
      LLM returns `[source:N]`, backend substitutes URL (online) or text citation (offline). Anchor metadata from Qdrant payload. SSE event type=citations.
  - **Outcome:** responses contain verified source references
  - **Verification:** response with citation → correct URL; offline source → "Book, chapter N, p. M"
  - Tasks: citation prompt instructions, source_id extraction, URL/text substitution, SSE citation event

- [x] **S4-04: Query rewriting**
      LLM-based reformulation with history context. Fail-open on timeout. Token budget.
  - **Outcome:** multi-turn dialog yields relevant retrieval
  - **Verification:** "tell me more" → reformulated → better retrieval; timeout → fallback to original
  - Tasks: rewrite prompt, timeout handling, token budget trimming
  - **Parallel pair:** S5-01 (Chat UI) — pure backend vs pure frontend, zero file overlap

- [x] **S4-05: Promotions + context assembly**
      Backend parses `PROMOTIONS.md`: filter expired, inject into prompt by priority rules (high/medium/low). No more than one recommendation per response. Full context assembly of all prompt layers except conversation memory (delivered in S4-07): system safety → IDENTITY → SOUL → BEHAVIOR → PROMOTIONS → retrieval → user query. Token budget management (`retrieval_context_budget`). Content type markup (fact/inference/recommendation). Conversation memory slot is reserved but populated in S4-07.
  - **Outcome:** prompt assembly with all layers including promotions, token budgets, and content type markup; conversation memory slot is a placeholder until S4-07
  - **Verification:** promo with expired date → not in prompt; all layers present; when budget exceeded — retrieval is trimmed; response distinguishes content types
  - Tasks: PROMOTIONS.md parser, expiry filter, priority-based inclusion, prompt builder service, token counting, budget trimming, content type instructions
  - **Parallel pair:** S5-02 (Chat polish) — backend prompt work vs frontend components, zero file overlap

- [x] **S4-06: Lightweight knowledge processing migration**
      Replace the remaining Docling-centric implementation with the lightweight local core and external-heavy processing architecture defined in canonical docs. Keep Qdrant local, preserve the current chunk contract, and introduce routing policy `local-first, external-on-complexity`: lightweight local parsing by default, Google Cloud Document AI as an external fallback for complex documents, Gemini Embedding 2 as the external embedding layer.
  - **Outcome:** the knowledge contour matches the canonical lightweight architecture without local heavy ML dependencies
  - **Verification:** Docling and local ML stacks are absent from runtime dependencies; supported text-centric formats still ingest successfully through the lightweight path; complex documents route through the external fallback; Qdrant payloads and citations remain compatible
  - Tasks: provider-agnostic document processing interface, Document AI adapter, routing rules, normalized chunk contract validation, dependency cleanup, regression coverage for local path and external fallback

- [x] **S4-07: Conversation memory**
  Dialog history + summary for long conversations. Trimming when token budget exceeded. Session management.
  - **Outcome:** long conversations retain context
  - **Verification:** 20+ messages → context preserved; summary generated when limit reached
  - Tasks: history window, summary generation trigger, token budget integration
  - **Parallel pair:** S5-03 (Admin UI — knowledge) — backend dialog vs admin frontend, zero file overlap

### Phase 5: Frontend

Phase outcome: full-featured web interface for visitors and the owner.

- [x] **S5-01: Chat UI**
      React + Vite + Bun. Chat interface: input field, message feed, SSE streaming, twin avatar and name.
  - **Outcome:** visitor can chat with the twin in the browser
  - **Verification:** open → send message → streaming response → history on refresh
  - Tasks: chat layout, SSE client, message rendering, session persistence
  - **Parallel pair:** S4-04 (Query rewriting) — pure frontend vs pure backend, zero file overlap

- [x] **S5-02: Chat polish — citations display + twin profile**
      Inline references in text, collapsible sources block under the message (Perplexity-style). Clickable for online, text-only for offline. Twin avatar (upload → 977SeaweedFS) and name in chat header. Note: "public links" require a backend schema extension — defer to a future story.
  - **Outcome:** sources visible and clickable; twin profile displayed in chat
  - **Verification:** citation → clickable link; collapse/expand block; avatar visible in chat header
  - Tasks: citation parser, collapsible block component, link rendering, avatar upload, profile metadata form, display in chat header
  - **Parallel pair:** S4-05 (Promotions + context assembly) — frontend vs backend, zero file overlap

- [x] **S5-03: Admin UI — knowledge management**
      Source upload (drag & drop), source list with ingestion statuses, soft delete. Snapshot list, create draft, publish, rollback, draft testing.
  - **Outcome:** owner manages sources and knowledge versions through the interface
  - **Verification:** upload file → see processing progress → status done; create snapshot → publish → twin responds; rollback → previous version
  - Tasks: file upload component, source list, status polling, delete confirmation, snapshot list, publish/rollback buttons, draft test view
  - **Parallel pair:** S4-07 (Conversation memory) — admin frontend vs backend dialog, zero file overlap

### Phase 6: Commerce

Phase outcome: full commercial layer — catalog, recommendations, citation integration.

- [ ] **S6-01: Commerce backend — catalog + recommendations**
      Admin API: CRUD catalog_items. Source ↔ catalog_item linking. Citation enrichment with purchase links. PROMOTIONS.md + catalog integration for native delivery. Citation takes priority over commercial link. No more than one recommendation per response.
  - **Outcome:** products linked to sources, appear in citations; twin recommends products naturally in context
  - **Verification:** citation of linked product → store link; conversation about topic → relevant recommendation; not every response has recommendation
  - Tasks: catalog API endpoints, source-catalog linking, citation enrichment, promotion-catalog integration, native recommendation prompt, frequency control
  - **Parallel pair:** S7-01 (API security) — commerce domain vs security middleware, minimal overlap

- [ ] **S6-02: Admin UI — product catalog**
      Product catalog CRUD, source ↔ catalog item linking. Depends on S6-01 backend.
  - **Outcome:** owner manages products through the interface
  - **Verification:** add product → link to source → citation includes purchase link
  - Tasks: catalog form, source-catalog linking UI
  - **Parallel pair:** S7-02 (Observability) — frontend vs infra, zero file overlap

### Phase 7: Operations Layer

Phase outcome: the product is secured, observable, and auditable.

- [ ] **S7-01: API security — auth + rate limiting**
      Admin API: API key (`Authorization: Bearer`), key from `.env`. Chat API: Redis-based rate limiting, configurable limits. Chat API remains public.
  - **Outcome:** admin endpoints protected; chat protected from abuse
  - **Verification:** admin without key → 401; with key → 200; exceed rate limit → 429; after cooldown → ok
  - Tasks: auth middleware, key config, error responses, rate limit middleware, Redis counters, keep admin auth isolated from future visitor identity for channel connectors
  - **Parallel pair:** S6-01 (Commerce backend) — security middleware vs commerce domain, minimal overlap

- [ ] **S7-02: Observability — audit logging + monitoring**
      Audit: every response → audit_logs with `snapshot_id`, `source_ids`, `config_commit_hash`, `config_content_hash`, timestamp, session_id. Monitoring: Prometheus `/metrics`, Grafana dashboard, OpenTelemetry tracing, correlation ids.
  - **Outcome:** every response reproducible; system observable
  - **Verification:** conversation → audit records with full data; dashboard with metrics; end-to-end request trace
  - Tasks: audit service, log schema, config hash injection, metrics middleware, Grafana provisioning, OTel instrumentation
  - **Parallel pair:** S6-02 (Catalog UI) — infra vs frontend, zero file overlap

### Phase 8: Evals and Quality

Phase outcome: measured quality, data-driven decisions on upgrade paths.

- [ ] **S8-01: Eval framework**
      Test harness, dataset format, suite runner, report generation. Separate from CI.
  - **Outcome:** eval suite can be run and produces a report
  - **Verification:** `run-evals` → report with metrics
  - Tasks: dataset format, eval runner, report generator

- [ ] **S8-02: Eval runs + upgrade decision**
      Retrieval evals: Precision@K, Recall@K, MRR baseline. Answer quality: groundedness, citation accuracy, persona fidelity, refusal quality (LLM-as-judge + manual sampling). Upgrade path decision documented based on results: chunk enrichment, parent-child, BGE-M3.
  - **Outcome:** retrieval and answer quality measured; data-backed improvement plan
  - **Verification:** report with retrieval + answer metrics; baseline recorded; decision document supported by data
  - Tasks: retrieval eval scenarios, metric computation, baseline snapshot, eval prompts per metric, scoring rubric, human review process, data analysis, cost/benefit, decision doc

### Phase 9: RAG Upgrades (based on eval results)

Phase outcome: improved retrieval and answer quality driven by data.

- [ ] **S9-01: Chunk enrichment**
      Fresh research (RAGFlow Transformer stage). LLM enrichment (summary, keywords, questions) via Batch API. New payload fields. Reindex.
  - **Outcome:** retrieval metrics improved
  - **Verification:** A/B eval: with enrichment vs without → documented improvement
  - Tasks: research, enrichment pipeline stage, Batch API integration, reindex, A/B eval
  - **Parallel pair:** S9-02 (Parent-child chunking) — both modify ingestion pipeline but touch different stages

- [ ] **S9-02: Parent-child chunking**
      Hierarchical indexing for books. Search by child, context from parent.
  - **Outcome:** long documents provide richer context
  - **Verification:** book → hierarchical chunks → retrieval returns child + parent
  - Tasks: hierarchy extraction from the normalized parsing pipeline, parent-child linking, context expansion
  - **Parallel pair:** S9-01 (Chunk enrichment) — both modify ingestion pipeline but touch different stages

- [ ] **S9-03: BGE-M3 fallback**
      Replace BM25 sparse with BGE-M3 sparse for languages with insufficient BM25 quality. Dense (Gemini) unchanged.
  - **Outcome:** keyword search improves for the target language
  - **Verification:** eval on target language → metrics improved vs BM25
  - Tasks: BGE-M3 integration, sparse vector swap, reindex, language-specific eval
  - **Parallel pair:** S9-01 or S9-02 — separate embedding/vector concern, no overlap with chunking code

### Phase 10: Agent Protocols and Distribution

Phase outcome: twin is available as a distribution-ready agent in the open ecosystem.

- [ ] **S10-01: A2A endpoint**
      Agent Card, task intake via A2A protocol, stateful task lifecycle, streaming.
  - **Outcome:** external agents can interact with the twin
  - **Verification:** Agent Card at URL; external agent → task → response
  - Tasks: A2A spec implementation, Agent Card generation, task handler, streaming transport
  - **Parallel pair:** S10-02 (MCP layer) — both are transport wrappers over existing services, no shared code

- [ ] **S10-02: MCP layer**
      Internal access to tools and data connectors via MCP. `TOOLS.md` configuration.
  - **Outcome:** MCP clients can use the twin's capabilities
  - **Verification:** MCP client → list tools → call tool → result
  - Tasks: MCP server, tool registry, TOOLS.md parser, data connector adapters
  - **Parallel pair:** S10-01 (A2A endpoint) — both are transport wrappers over existing services, no shared code

- [ ] **S10-03: Distribution manifest + session contract**
      Publish a machine-readable distribution contract for external surfaces such as marketplaces, directories, applications, and channels. The manifest exposes identity, capabilities, supported action classes, usage schema, settlement identity, optional public identity fields, and supported transports. Requests from a distribution surface carry normalized context such as `distribution_surface_id`, `distribution_profile_id`, `external_session_id`, and optional limits or allowances.
  - **Outcome:** the same twin can be integrated into multiple external surfaces without a bespoke adapter per surface
  - **Verification:** two simulated external surfaces load the manifest, send requests with different distribution profiles, and receive responses correlated to the correct external session and profile
  - Tasks: manifest schema, discovery endpoint, distribution session context model, correlation persistence, profile resolver, compatibility tests
  - **Parallel pair:** S10-04 (Usage metering + receipts) — contract boundary vs execution accounting, minimal overlap

- [ ] **S10-04: Usage metering + receipts**
      Emit normalized usage events and receipts for performed actions. ProxyMind measures what the twin did and returns machine-readable receipts linked to messages, tasks, and sessions, but retail pricing remains the responsibility of the external distribution surface.
  - **Outcome:** marketplaces and other surfaces can apply their own pricing, free modes, allowances, and settlement rules on top of standardized usage
  - **Verification:** response produces a receipt; retry with the same idempotency key does not duplicate the receipt; audit links the receipt to the message, session, or task
  - Tasks: action class taxonomy, metering hooks, receipt schema, idempotency, audit integration, regression tests
  - **Parallel pair:** S10-03 (Distribution manifest + session contract) — contract boundary vs execution accounting, minimal overlap

- [ ] **S10-05: Owner distribution settings**
      Admin API and UI for owner-managed distribution settings: payout destination, allowed external surfaces, optional public identity fields, free or paid mode permissions, invitation or export policies, and minimum settlement rules. Retail pricing is not stored as a single global twin price and MAY differ per external surface.
  - **Outcome:** the owner can safely expose the same twin through multiple marketplaces, apps, and channels with different business rules
  - **Verification:** configure two surfaces with different policies; inbound requests honor the correct policy and payout destination
  - Tasks: settings schema, admin endpoints, owner UI, payout configuration, allowlist and policy validation, optional public identity fields, tests

### Phase 11: External Channels (v2)

Phase outcome: the twin can operate in external messaging and social channels without a standalone ProxyMind registration flow for end users. This phase is intentionally outside the first distribution-ready scope because external surfaces can already integrate the twin through Phase 10.

- [ ] **S11-01: External channels — identity + connectors**
      Visitor identity model: resolve or create visitors implicitly from platform identity such as `(channel_connector, external_user_id)`. Keep separate from admin auth. Integration layer for external chat platforms (Telegram, Facebook, VK, Instagram, TikTok, and similar channels). Normalize inbound/outbound events into the same internal chat flow as the web UI.
  - **Outcome:** external channels work with implicit visitor identity; system has a defined path for adding channels without changing the core dialogue workflow
  - **Verification:** connector delivers a normalized message into the chat pipeline; external identity maps to a visitor and session without local registration
  - Tasks: visitor identity entity, external identity mapping, connector interface, message normalization, delivery abstraction, connector lifecycle and error handling
