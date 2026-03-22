## Story

**S2-04: Minimal chat** — the fourth story in Phase 2 (First E2E Slice).

**Outcome:** a question can be asked and answered based on uploaded knowledge.

**Verification:** upload document → publish → `POST /api/chat/messages {"text": "..."}` → response based on document content.

**Test coverage:** all new services (ChatService, RetrievalService, LLMService, prompt builder) and API endpoints MUST be covered by unit and integration tests before archive.

## Why

Phase 2 delivers the first end-to-end slice: upload → index → ask → answer. S2-01 through S2-03 handle upload, ingestion, and snapshot lifecycle. S2-04 closes the loop by adding the dialogue circuit — the user can now ask a question and receive an answer grounded in published knowledge. Without this story, the system ingests data but cannot surface it.

## What Changes

- New Chat API: three public endpoints (`POST /sessions`, `POST /messages`, `GET /sessions/:id`)
- New RetrievalService: dense vector search in Qdrant scoped by active snapshot
- New LLMService: async LiteLLM wrapper for provider-agnostic LLM calls
- New prompt builder: assembles system instruction + retrieval context + user query
- New ChatService: thin orchestrator coordinating retrieval, LLM, and message persistence
- LLM configuration via three new `.env` variables (`LLM_MODEL`, `LLM_API_KEY`, `LLM_API_BASE`)
- QdrantService gains a `search()` method (dense vector query with payload filtering)
- SnapshotService gains a `get_active_snapshot()` method
- Lazy-bind snapshot to session on first message (session created before publish still works)

## Capabilities

### New Capabilities

- `chat-dialogue`: Chat session lifecycle, message send/receive, LLM integration, prompt assembly, and retrieval-augmented response generation (JSON, no streaming)

### Modified Capabilities

- `vector-storage`: QdrantService gains a `search()` method for dense vector retrieval with payload filtering and optional score threshold
- `snapshot-lifecycle`: SnapshotService gains a `get_active_snapshot()` query method

## Impact

- **Code:** new files in `backend/app/services/` (chat, retrieval, llm, prompt), `backend/app/api/` (chat router, schemas); modifications to qdrant.py, snapshot.py, config.py, dependencies.py, main.py
- **APIs:** three new public Chat API endpoints under `/api/chat/`
- **Dependencies:** LiteLLM (already in pyproject.toml, v1.82.3+) — first actual usage
- **Configuration:** three new env vars for LLM provider
- **Data:** Session and Message models already exist — no migration needed
