## Purpose

Chat session lifecycle, message send/receive, retrieval-augmented response generation, LLM integration, and prompt assembly. Introduced by S2-04.

## ADDED Requirements

### Requirement: Session creation via POST /api/chat/sessions

The system SHALL provide a `POST /api/chat/sessions` endpoint that creates a new chat session. The endpoint SHALL accept an optional `channel` field (default `"web"`). The session SHALL be created with `agent_id` set to `DEFAULT_AGENT_ID`. The `snapshot_id` SHALL be set to the currently active snapshot at creation time, or `null` if no active snapshot exists. The endpoint SHALL return 201 Created with the session data. No authentication SHALL be required.

#### Scenario: Create session with active snapshot

- **WHEN** `POST /api/chat/sessions` is called with `{"channel": "web"}` and an active snapshot exists
- **THEN** the response SHALL be 201
- **AND** the response SHALL contain `id` (UUID), `snapshot_id` (UUID of the active snapshot), `channel` ("web"), `status` ("active"), `message_count` (0), and `created_at`

#### Scenario: Create session without active snapshot

- **WHEN** `POST /api/chat/sessions` is called and no active snapshot exists
- **THEN** the response SHALL be 201
- **AND** `snapshot_id` SHALL be `null`

#### Scenario: Create session with default channel

- **WHEN** `POST /api/chat/sessions` is called with an empty body
- **THEN** the response SHALL be 201 with `channel` set to `"web"`

---

### Requirement: Message send via POST /api/chat/messages

The system SHALL provide a `POST /api/chat/messages` endpoint that accepts `session_id` (UUID) and `text` (non-empty string). The endpoint SHALL save the user message with `role=user` and `status=received`, then perform retrieval against the session's active snapshot, assemble a prompt using the retrieval context, call the LLM, and return the assistant's response as JSON with status 200. The assistant message SHALL be saved with `role=assistant`, `status=complete`, `content`, `model_name`, token counts (`token_count_prompt`, `token_count_completion`), and deduplicated `source_ids` from retrieved chunks. The response SHALL include a runtime-computed `retrieved_chunks_count` field representing the actual number of chunks passed to the LLM.

#### Scenario: Successful message with retrieval and LLM response

- **WHEN** `POST /api/chat/messages` is called with a valid `session_id` and `text`, and the session has an active snapshot with indexed chunks
- **THEN** the response SHALL be 200
- **AND** the response SHALL contain `message_id`, `session_id`, `role` ("assistant"), `content`, `status` ("complete"), `model_name`, `retrieved_chunks_count`, `token_count_prompt`, `token_count_completion`, and `created_at`

#### Scenario: User message is persisted before LLM call

- **WHEN** `POST /api/chat/messages` is called with valid data
- **THEN** a user message record SHALL be saved with `role=user` and `status=received` before the retrieval and LLM steps execute

#### Scenario: Session message_count is updated after successful response

- **WHEN** a message exchange completes successfully
- **THEN** the session's `message_count` SHALL be incremented to reflect both the user and assistant messages

---

### Requirement: Lazy snapshot bind on first message

The system SHALL implement lazy snapshot binding. If `session.snapshot_id` is `null` when a message is sent, the system SHALL attempt to bind the current active snapshot to the session. If an active snapshot is found, `session.snapshot_id` SHALL be set and persisted. Once bound, `snapshot_id` SHALL be immutable for the session — lazy bind occurs only on the transition from `null` to a valid snapshot. If no active snapshot exists after the lazy-bind attempt, the endpoint SHALL return 422 Unprocessable Entity.

#### Scenario: Lazy bind succeeds when active snapshot becomes available

- **WHEN** a session was created with `snapshot_id=null` (no active snapshot at creation time)
- **AND** an active snapshot now exists
- **AND** `POST /api/chat/messages` is called for this session
- **THEN** the session's `snapshot_id` SHALL be set to the active snapshot's ID
- **AND** the message processing SHALL proceed normally

#### Scenario: Lazy bind fails when no active snapshot exists

- **WHEN** a session has `snapshot_id=null`
- **AND** no active snapshot exists
- **AND** `POST /api/chat/messages` is called for this session
- **THEN** the response SHALL be 422 with a detail indicating no active snapshot is available

#### Scenario: Snapshot ID is immutable once bound

- **WHEN** a session has a non-null `snapshot_id`
- **AND** a new active snapshot is published after the session was bound
- **AND** `POST /api/chat/messages` is called for this session
- **THEN** the session SHALL continue using the originally bound `snapshot_id`
- **AND** the `snapshot_id` SHALL NOT change to the new active snapshot

---

### Requirement: Retrieval-grounded refusal without LLM call

When retrieval returns fewer chunks than `min_retrieved_chunks` (configurable, default 1), the system SHALL save an assistant message with a hardcoded refusal text and `status=complete`, and return it without calling the LLM. This prevents wasted LLM calls and eliminates hallucination risk when no grounding context is available. The refusal message content SHALL indicate that no answer was found in the knowledge base.

#### Scenario: Refusal when zero chunks retrieved

- **WHEN** `POST /api/chat/messages` is called and retrieval returns 0 chunks
- **THEN** the response SHALL be 200 with an assistant message containing a refusal text
- **AND** the assistant message `status` SHALL be `"complete"`
- **AND** the LLM SHALL NOT be called
- **AND** `retrieved_chunks_count` SHALL be 0

#### Scenario: Refusal when chunks below min_retrieved_chunks threshold

- **WHEN** `min_retrieved_chunks` is configured to 3 and retrieval returns 2 chunks
- **THEN** the system SHALL return a refusal without calling the LLM

#### Scenario: Normal flow when chunks meet threshold

- **WHEN** `min_retrieved_chunks` is 1 and retrieval returns 3 chunks
- **THEN** the system SHALL proceed to prompt assembly and LLM call

---

### Requirement: Session history via GET /api/chat/sessions/:id

The system SHALL provide a `GET /api/chat/sessions/{session_id}` endpoint that returns the session with its ordered message history. Messages SHALL be ordered by `created_at` ascending. The response SHALL include `id`, `status`, `channel`, `snapshot_id`, `message_count`, `created_at`, and a `messages` array. Each message in the array SHALL include `id`, `role`, `content`, `status`, `model_name` (for assistant messages), and `created_at`. If the session does not exist, the endpoint SHALL return 404.

#### Scenario: Get session with messages

- **WHEN** `GET /api/chat/sessions/{session_id}` is called for a session that has 2 messages (1 user, 1 assistant)
- **THEN** the response SHALL be 200
- **AND** `messages` SHALL contain 2 entries ordered by `created_at` ascending
- **AND** the first message SHALL have `role=user` and the second SHALL have `role=assistant`

#### Scenario: Get session with no messages

- **WHEN** `GET /api/chat/sessions/{session_id}` is called for a session with no messages
- **THEN** the response SHALL be 200 with `messages` as an empty array and `message_count` of 0

#### Scenario: Get non-existent session returns 404

- **WHEN** `GET /api/chat/sessions/{session_id}` is called with a UUID that does not match any session
- **THEN** the response SHALL be 404 with detail "Session not found"

---

### Requirement: LLM configuration via environment variables

The system SHALL be configurable via three environment variables for LLM provider integration: `LLM_MODEL` (LiteLLM model string, e.g., `"openai/gpt-4o"`), `LLM_API_KEY` (provider API key), and `LLM_API_BASE` (custom endpoint URL for proxy or self-hosted setups). These SHALL be exposed in the Settings class. Additional settings SHALL include `llm_temperature` (float, default 0.7), `retrieval_top_n` (int, default 5), `min_retrieved_chunks` (int, default 1), and `min_dense_similarity` (float or None, default None — disabled until calibrated via evals).

#### Scenario: LLM call uses configured model and credentials

- **WHEN** `LLM_MODEL=openai/gpt-4o`, `LLM_API_KEY=sk-test`, and `LLM_API_BASE=https://api.example.com` are set
- **THEN** the LLMService SHALL pass these values to LiteLLM's `acompletion` call

#### Scenario: LLM settings have sensible defaults

- **WHEN** no LLM environment variables are set
- **THEN** `llm_model` SHALL default to `"openai/gpt-4o"`
- **AND** `llm_api_key` SHALL default to `None`
- **AND** `llm_api_base` SHALL default to `None`
- **AND** `llm_temperature` SHALL default to `0.7`

#### Scenario: Retrieval settings have sensible defaults

- **WHEN** no retrieval environment variables are set
- **THEN** `retrieval_top_n` SHALL default to 5
- **AND** `min_retrieved_chunks` SHALL default to 1
- **AND** `min_dense_similarity` SHALL default to `None`

---

### Requirement: Error handling for chat endpoints

The chat endpoints SHALL handle errors as follows:

- Session not found: `ChatService` SHALL raise `SessionNotFoundError`, router SHALL return 404.
- No active snapshot after lazy-bind attempt: `ChatService` SHALL raise `NoActiveSnapshotError`, router SHALL return 422.
- Empty or missing `text` in message request: Pydantic validation SHALL return 422 automatically.
- LLM call failure: `LLMService` SHALL raise `LLMError`; `ChatService` SHALL save an assistant message with `status=failed` before re-raising; router SHALL return 500.
- Qdrant or embedding failure: exceptions SHALL propagate through `ChatService`, which SHALL save an assistant message with `status=failed`; router SHALL return 500.

After a user message is saved, any subsequent error MUST result in a persisted assistant message with `status=failed` for observability.

#### Scenario: Session not found returns 404

- **WHEN** `POST /api/chat/messages` is called with a `session_id` that does not exist
- **THEN** the response SHALL be 404 with detail "Session not found"

#### Scenario: No active snapshot returns 422

- **WHEN** `POST /api/chat/messages` is called for a session with `snapshot_id=null` and no active snapshot exists
- **THEN** the response SHALL be 422

#### Scenario: Empty text returns 422

- **WHEN** `POST /api/chat/messages` is called with `text` as an empty string or missing
- **THEN** the response SHALL be 422 (Pydantic validation error)

#### Scenario: LLM failure returns 500 with failed message persisted

- **WHEN** the LLM call fails during message processing
- **THEN** an assistant message SHALL be saved with `status=failed`
- **AND** the response SHALL be 500

#### Scenario: Qdrant failure returns 500 with failed message persisted

- **WHEN** the Qdrant search fails during message processing
- **THEN** an assistant message SHALL be saved with `status=failed`
- **AND** the response SHALL be 500

---

### Requirement: Source IDs tracking on assistant messages

The assistant message SHALL store deduplicated `source_ids` (UUID array) extracted from the retrieved chunks. Multiple chunks may originate from the same source document; `source_ids` SHALL contain each unique `source_id` exactly once. The `source_ids` field already exists in the Message model — no migration is needed. This field supports future citation building and audit logging.

#### Scenario: Source IDs are deduplicated from retrieved chunks

- **WHEN** retrieval returns 5 chunks from 2 unique source documents
- **THEN** the assistant message `source_ids` SHALL contain exactly 2 UUIDs

#### Scenario: Source IDs are empty when refusal is triggered

- **WHEN** retrieval returns 0 chunks and a refusal message is generated
- **THEN** the assistant message `source_ids` SHALL be an empty array

#### Scenario: Source IDs are persisted on the assistant message record

- **WHEN** a successful assistant message is saved
- **THEN** the `source_ids` column in the database SHALL contain the deduplicated UUIDs from the retrieval result

---

### Requirement: Prompt assembly as pure functions

The system SHALL provide prompt assembly via stateless pure functions in `services/prompt.py`. The `build_chat_prompt` function SHALL accept a user query and a list of retrieved chunks, and SHALL return a messages list in OpenAI chat API format (accepted by LiteLLM). The system message SHALL contain behavioral instructions directing the LLM to answer only from the provided context. The user message SHALL contain the formatted retrieval context followed by the user question. Each chunk in the context SHALL include its source_id for traceability.

#### Scenario: Prompt structure with retrieved chunks

- **WHEN** `build_chat_prompt` is called with a query and 3 retrieved chunks
- **THEN** the result SHALL be a list of 2 messages: one with `role=system` and one with `role=user`
- **AND** the system message SHALL instruct the LLM to answer only from provided context
- **AND** the user message SHALL contain all 3 chunk texts with source identifiers, followed by the user question

#### Scenario: Prompt with empty chunks list

- **WHEN** `build_chat_prompt` is called with an empty chunks list
- **THEN** the result SHALL still contain a system message and a user message
- **AND** the user message SHALL contain only the question (no context section)

---

### Requirement: LLMService as async LiteLLM wrapper

The system SHALL provide an `LLMService` at `services/llm.py` that wraps LiteLLM's `acompletion` call. The `complete` method SHALL accept a messages list and an optional temperature parameter (default from settings). It SHALL return an `LLMResponse` containing `content`, `model_name`, `token_count_prompt`, and `token_count_completion`. On LiteLLM errors, the service SHALL log via structlog and raise `LLMError`. The service SHALL NOT implement retry logic (LiteLLM has built-in retry). The service SHALL NOT implement streaming (deferred to S4-02).

#### Scenario: Successful LLM completion

- **WHEN** `complete` is called with a valid messages list
- **THEN** it SHALL return an `LLMResponse` with non-empty content, model name, and token counts

#### Scenario: LLM error raises LLMError

- **WHEN** the LiteLLM `acompletion` call raises an exception
- **THEN** the service SHALL log the error via structlog
- **AND** SHALL raise `LLMError`

---

### Requirement: RetrievalService for dense vector search

The system SHALL provide a `RetrievalService` at `services/retrieval.py` that coordinates query embedding and Qdrant search. The `search` method SHALL accept a query string, a snapshot_id, and an optional `top_n` parameter (default from `retrieval_top_n` setting). It SHALL embed the query using `EmbeddingService.embed_texts` with `task_type=RETRIEVAL_QUERY`, then call `QdrantService.search` with the resulting vector, snapshot_id filter, and optional `score_threshold` from `min_dense_similarity` setting. It SHALL return a list of `RetrievedChunk` objects containing `chunk_id`, `source_id`, `text_content`, `score`, and `anchor_metadata`.

#### Scenario: Successful retrieval returns chunks

- **WHEN** `search` is called with a query and a snapshot_id that has indexed chunks
- **THEN** it SHALL return a list of `RetrievedChunk` objects ordered by relevance score

#### Scenario: Empty retrieval returns empty list

- **WHEN** `search` is called and no chunks match the query or snapshot
- **THEN** it SHALL return an empty list

#### Scenario: Score threshold filters weak chunks

- **WHEN** `min_dense_similarity` is set to 0.5 and retrieval returns chunks with scores [0.8, 0.6, 0.3]
- **THEN** only chunks with scores above 0.5 SHALL be returned (the chunk with score 0.3 is excluded)

---

### Requirement: ChatService as thin orchestrator

The system SHALL provide a `ChatService` at `services/chat.py` that orchestrates session creation, message processing, and history retrieval. Dependencies SHALL be `AsyncSession`, `SnapshotService`, `RetrievalService`, and `LLMService`. `ChatService` SHALL be instantiated per request (because it depends on `AsyncSession`), while `LLMService` and `RetrievalService` SHALL be initialized in the application lifespan and stored in `app.state`.

#### Scenario: ChatService coordinates the full answer flow

- **WHEN** `answer(session_id, text)` is called with a valid session
- **THEN** it SHALL load the session, save the user message, call retrieval, build the prompt, call the LLM, save the assistant message, update session message count, and return the assistant message

#### Scenario: ChatService is per-request with shared stateless services

- **WHEN** the DI system creates a `ChatService` for a request
- **THEN** it SHALL receive a fresh `AsyncSession` and shared `LLMService`/`RetrievalService` instances from `app.state`

---

## Test Coverage

### CI tests (deterministic, mocked external services)

The following stable behavior MUST be covered by CI tests before archive:

- **Prompt builder unit tests**: verify `build_chat_prompt` returns correct message structure (system + user), context formatting includes chunk text and source_id, empty chunks list produces question-only user message.
- **LLMService unit tests**: mock `litellm.acompletion`. Verify `complete` returns `LLMResponse` with correct fields. Verify LiteLLM error raises `LLMError` with structlog logging.
- **RetrievalService unit tests**: mock `EmbeddingService` and `QdrantService`. Verify `search` calls embedding with `RETRIEVAL_QUERY` task type, calls Qdrant search with correct parameters, returns `RetrievedChunk` list. Verify empty result handling. Verify `min_dense_similarity` filtering: chunks below threshold are excluded; with threshold=None all chunks pass; threshold filtering can trigger min_retrieved_chunks refusal.
- **ChatService unit tests**: mock `RetrievalService`, `LLMService`, `SnapshotService`, and DB session. Verify session creation with and without active snapshot. Verify full answer flow (retrieval -> prompt -> LLM -> save). Verify refusal when chunks below threshold. Verify lazy bind (session with snapshot_id=None binds when active snapshot appears). Verify lazy bind still returns 422 when no active snapshot exists. Verify LLM error saves failed assistant message. Verify source_ids deduplication.
- **Chat API integration tests**: with TestClient + testcontainers (PG) + mocked LLM + mocked Qdrant. Verify create session (201), send message (200), get history (200 with ordered messages). Verify 404 for non-existent session. Verify 422 for no active snapshot. Verify 422 for empty text. Verify lazy bind E2E (create session before publish -> publish snapshot -> send message succeeds). Verify LLM failure returns 500 with failed message persisted.

### Evals (non-CI)

- Real LLM response quality with actual provider calls is evaluated manually, not in CI.
- Real vector search quality with actual Gemini embeddings is evaluated manually, not in CI.
