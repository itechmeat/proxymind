## 1. Configuration

- [x] 1.1 Add LLM settings to Settings (llm_model, llm_api_key, llm_api_base, llm_temperature)
- [x] 1.2 Add retrieval settings to Settings (retrieval_top_n, min_retrieved_chunks, min_dense_similarity)
- [x] 1.3 Add LLM_MODEL, LLM_API_KEY, LLM_API_BASE to .env.example

## 2. QdrantService — search method

- [x] 2.1 Write unit tests for QdrantService.search() (filtered search, score threshold, empty results)
- [x] 2.2 Add RetrievedChunk dataclass to qdrant.py
- [x] 2.3 Implement search() method with dense vector query, payload filtering, and optional score_threshold
- [x] 2.4 Add _search_points() retry wrapper
- [x] 2.5 Export RetrievedChunk from services/__init__.py
- [x] 2.6 Verify all search unit tests pass

## 3. SnapshotService — get_active_snapshot

- [x] 3.1 Write unit tests for get_active_snapshot() (returns active, returns None)
- [x] 3.2 Implement get_active_snapshot(agent_id, knowledge_base_id) method
- [x] 3.3 Verify tests pass

## 4. Prompt builder

- [x] 4.1 Write unit tests for build_chat_prompt() (structure, content, multiple chunks, source_id inclusion, empty chunks list produces no context block)
- [x] 4.2 Implement prompt.py with SYSTEM_PROMPT, NO_CONTEXT_REFUSAL, and build_chat_prompt()
- [x] 4.3 Verify tests pass

## 5. LLMService

- [x] 5.1 Write unit tests for LLMService.complete() (success, parameter passing, error handling, empty content)
- [x] 5.2 Implement llm.py with LLMError, LLMResponse, and LLMService
- [x] 5.3 Export LLMError, LLMResponse, LLMService from services/__init__.py
- [x] 5.4 Verify tests pass

## 6. RetrievalService

- [x] 6.1 Write unit tests for RetrievalService.search() (embedding + qdrant, score threshold, empty results)
- [x] 6.2 Implement retrieval.py with RetrievalError and RetrievalService
- [x] 6.3 Export RetrievalError, RetrievalService from services/__init__.py
- [x] 6.4 Verify tests pass

## 7. ChatService

- [x] 7.1 Write unit tests for create_session (with/without active snapshot)
- [x] 7.2 Write unit tests for answer (with chunks, no chunks refusal, no snapshot error, LLM error, lazy bind success)
- [x] 7.3 Write unit test: snapshot_id immutability after bind (session already bound, new active snapshot appears, session keeps original snapshot_id)
- [x] 7.4 Write unit test: source_ids deduplication (multiple chunks from same source → single entry in source_ids)
- [x] 7.5 Write unit test for get_session (found, not found)
- [x] 7.6 Implement chat.py with SessionNotFoundError, NoActiveSnapshotError, ChatService
- [x] 7.7 Export ChatService exceptions from services/__init__.py
- [x] 7.8 Verify all ChatService tests pass

## 8. Chat API schemas and router

- [x] 8.1 Create chat_schemas.py (CreateSessionRequest, SessionResponse, SendMessageRequest, MessageResponse, MessageInHistory, SessionWithMessagesResponse)
- [x] 8.2 Add DI functions to dependencies.py (get_llm_service, get_retrieval_service, get_chat_service)
- [x] 8.3 Create chat.py router with three endpoints (POST /sessions, POST /messages, GET /sessions/:id)
- [x] 8.4 Initialize LLMService, RetrievalService, QdrantService, EmbeddingService in main.py lifespan
- [x] 8.5 Register chat router in main.py

## 9. Integration tests

- [x] 9.1 Add chat_app and chat_client fixtures to conftest.py
- [x] 9.2 Write integration test: create session returns 201 (with explicit channel and with empty body → default channel="web")
- [x] 9.3 Write integration test: send message returns assistant response
- [x] 9.4 Write integration test: send message returns 422 without snapshot
- [x] 9.5 Write integration test: send message returns 404 for unknown session
- [x] 9.6 Write integration test: get session returns history
- [x] 9.7 Write integration test: lazy bind E2E (create before publish, send after)
- [x] 9.8 Verify all integration tests pass

## 10. Final verification

- [x] 10.1 Run full test suite (unit + integration)
- [x] 10.2 Run ruff linter on app/ and tests/
- [x] 10.3 Self-review against docs/development.md checklist
