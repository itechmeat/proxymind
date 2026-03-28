## Purpose

Chat session lifecycle, message send/receive, retrieval-augmented response generation, LLM integration, prompt assembly, SSE streaming (S4-02), and query rewriting (S4-04). Introduced by S2-04.

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

The system SHALL provide a `POST /api/chat/messages` endpoint that accepts `session_id` (UUID), `text` (non-empty string), and an optional `idempotency_key` (string, client-generated) in the `SendMessageRequest`. The endpoint SHALL save the user message with `role=user`, `status=received`, and `idempotency_key` (when provided), then perform query rewriting, then build a conversation memory block from session history, then perform retrieval against the session's active snapshot, then assemble a prompt using `ContextAssembler.assemble()` with the retrieval chunks, original user query, source map, and memory block, and stream the assistant's response as SSE (`text/event-stream; charset=utf-8`) with status 200. After the response completes successfully, if the memory block indicates `needs_summary_update=True`, the system SHALL enqueue a `generate_session_summary` arq task.

After the user message is persisted, the system SHALL load conversation history for the session, then call `QueryRewriteService.rewrite()` with the user's query text and the loaded history. The retrieval step SHALL use the rewritten query (or the original query if rewriting was skipped or failed). After query rewriting and before retrieval, the system SHALL build a `MemoryBlock` by calling `ConversationMemoryService.build_memory_block()` with the session and the loaded history (excluding the current user message). The prompt assembly step SHALL call `ContextAssembler.assemble(chunks=retrieved_chunks, query=original_query, source_map=source_map, memory_block=memory_block)` -- using the original user query text, not the rewritten query, and including the memory block. When rewriting produces a different query, the `rewritten_query` column on the user message SHALL be updated with the rewritten text.

The `ChatService` SHALL provide a `stream_answer()` method alongside the existing `answer()` method. The existing `answer()` method SHALL be preserved. Both methods SHALL include the query rewriting step, the conversation memory step, and SHALL call `ContextAssembler.assemble()` for prompt construction instead of `build_chat_prompt()`.

After the LLM response is received and citations are extracted, the system SHALL call `compute_content_type_spans()` with the response text and the `included_promotions` from `AssembledPrompt`. The resulting spans SHALL be persisted in the assistant message's `content_type_spans` JSONB column.

After the assistant message is persisted with `status=complete`, the system SHALL check `memory_block.needs_summary_update`. When `True` and a `summary_enqueuer` is available, the system SHALL enqueue a `generate_session_summary` arq task with `session_id` and `memory_block.window_start_message_id`. `window_start_message_id` MAY be `null` when the memory window is empty and all recent messages should be summarized. Enqueue failure SHALL be logged but SHALL NOT fail the response.

The assistant message SHALL be created with `role=assistant`, `status=streaming`, and `parent_message_id` set to the user message's `id` before the first SSE event is emitted. Upon successful completion, the assistant message SHALL be updated to `status=complete` with `content`, `model_name`, token counts (`token_count_prompt`, `token_count_completion`), deduplicated `source_ids` from retrieved chunks, `content_type_spans` from heuristic classification, and audit hashes (`config_commit_hash`, `config_content_hash` from `context_assembler.persona_context`).

Pre-stream errors (session not found, no active snapshot, concurrent stream conflict, idempotency conflict for STREAMING) SHALL return standard HTTP error codes (404, 409, 422) as JSON responses -- the SSE stream SHALL NOT be opened for these cases.

On every response -- both the LLM-generated response path (`chat.assistant_completed`) and the code-level refusal path (`chat.refusal_returned`) -- `ChatService` SHALL log `config_commit_hash` and `config_content_hash` from `context_assembler.persona_context` via structlog. The response SHALL include a runtime-computed `retrieved_chunks_count` field.

#### Scenario: Successful message with SSE streaming response

- **WHEN** `POST /api/chat/messages` is called with a valid `session_id` and `text`, and the session has an active snapshot with indexed chunks
- **THEN** the response SHALL be 200 with `Content-Type: text/event-stream; charset=utf-8`
- **AND** the SSE stream SHALL emit `meta` (with `message_id`, `session_id`, `snapshot_id`), then one or more `token` events, then `done` (with `token_count_prompt`, `token_count_completion`, `model_name`, `retrieved_chunks_count`)

#### Scenario: ContextAssembler called with memory_block

- **WHEN** `ChatService.stream_answer()` or `ChatService.answer()` assembles the LLM prompt
- **THEN** it SHALL call `ContextAssembler.assemble(chunks=retrieved_chunks, query=original_query, source_map=source_map, memory_block=memory_block)`
- **AND** SHALL pass the resulting `AssembledPrompt.messages` to the LLM service
- **AND** SHALL NOT call `build_chat_prompt()`

#### Scenario: Memory block built from session history

- **WHEN** a session has prior messages and a new message is sent
- **THEN** `ConversationMemoryService.build_memory_block()` SHALL be called with the session and history (excluding the current user message)
- **AND** the resulting `MemoryBlock` SHALL be passed to `ContextAssembler.assemble()`

#### Scenario: Summary task enqueued when needs_summary_update is True

- **WHEN** the assistant message is saved with `status=complete` and `memory_block.needs_summary_update` is `True`
- **THEN** the system SHALL enqueue `generate_session_summary` via `summary_enqueuer`
- **AND** the enqueue call SHALL include `session_id` and `window_start_message_id`

#### Scenario: Summary task not enqueued when needs_summary_update is False

- **WHEN** the assistant message is saved with `status=complete` and `memory_block.needs_summary_update` is `False`
- **THEN** the system SHALL NOT enqueue a summary task

#### Scenario: Summary enqueue failure does not fail response

- **WHEN** the summary task enqueue raises an exception
- **THEN** the exception SHALL be caught and logged as a warning
- **AND** the assistant response SHALL still be returned successfully to the client

#### Scenario: User message is persisted before streaming begins

- **WHEN** `POST /api/chat/messages` is called with valid data
- **THEN** a user message record SHALL be saved with `role=user`, `status=received`, and `idempotency_key` (when provided) before the retrieval and LLM steps execute

#### Scenario: Assistant message created with STREAMING status before first event

- **WHEN** the system is about to start streaming the LLM response
- **THEN** an assistant message SHALL be created with `status=streaming` and `parent_message_id` set to the user message's `id`
- **AND** the `meta` SSE event SHALL be emitted with this assistant message's `id`

#### Scenario: Session message_count is updated after successful response

- **WHEN** a message exchange completes successfully (assistant message reaches COMPLETE status)
- **THEN** the session's `message_count` SHALL be incremented to reflect both the user and assistant messages

#### Scenario: ContextAssembler used for prompt construction

- **WHEN** `ChatService.stream_answer()` assembles the LLM prompt
- **THEN** it SHALL call `ContextAssembler.assemble(chunks=retrieved_chunks, query=original_query, source_map=source_map, memory_block=memory_block)`
- **AND** SHALL pass the resulting `AssembledPrompt.messages` to the LLM service
- **AND** SHALL NOT call `build_chat_prompt()`

#### Scenario: Config hashes accessed via context_assembler.persona_context

- **WHEN** the assistant message is saved with `status=complete` or a refusal is returned
- **THEN** `config_commit_hash` and `config_content_hash` SHALL be read from `context_assembler.persona_context`
- **AND** these values SHALL be persisted on the assistant message and logged via structlog

#### Scenario: Config hashes logged on successful LLM response

- **WHEN** the LLM returns a successful response and the assistant message is saved with `status=complete`
- **THEN** structlog SHALL emit a `chat.assistant_completed` event
- **AND** the log entry SHALL include `config_commit_hash` and `config_content_hash` from `context_assembler.persona_context`

#### Scenario: Config hashes logged on code-level refusal

- **WHEN** retrieval returns fewer chunks than `min_retrieved_chunks` and the system returns a refusal without calling the LLM
- **THEN** structlog SHALL emit a `chat.refusal_returned` event
- **AND** the log entry SHALL include `config_commit_hash` and `config_content_hash` from `context_assembler.persona_context`

#### Scenario: Content type spans computed after LLM response

- **WHEN** the LLM returns a successful response and citations are extracted
- **THEN** `compute_content_type_spans()` SHALL be called with the response text and `assembled_prompt.included_promotions`
- **AND** the resulting spans SHALL be stored in the assistant message's `content_type_spans` column

#### Scenario: Content type spans empty when refusal

- **WHEN** retrieval returns fewer chunks than `min_retrieved_chunks` and a refusal is returned
- **THEN** `content_type_spans` on the assistant message SHALL be `null` or an empty list (no content type classification is needed for refusal text)

#### Scenario: SendMessageRequest accepts optional idempotency_key

- **WHEN** `POST /api/chat/messages` is called with `{"session_id": "...", "text": "...", "idempotency_key": "client-key-123"}`
- **THEN** the request SHALL be accepted and the `idempotency_key` SHALL be stored on the user message

#### Scenario: Existing answer() method preserved

- **WHEN** `ChatService` is used after S4-02 implementation
- **THEN** the `answer()` method SHALL remain available and functional with the same signature and behavior

#### Scenario: Rewritten query used for retrieval, original for assembler

- **WHEN** a user sends "Tell me more about the second one" in a session with prior history
- **AND** query rewriting reformulates the query to "Tell me more about Sergey's book Deep Learning in Practice"
- **THEN** the retrieval step SHALL search using "Tell me more about Sergey's book Deep Learning in Practice"
- **AND** `ContextAssembler.assemble()` SHALL receive the original query "Tell me more about the second one"

#### Scenario: First message skips rewriting

- **WHEN** the first message in a session is sent
- **THEN** query rewriting SHALL be skipped (no history available)
- **AND** the retrieval step SHALL use the original query text
- **AND** `rewritten_query` on the user message SHALL remain `NULL`

#### Scenario: Rewrite failure does not block the chat flow

- **WHEN** the query rewrite LLM call times out or raises an error
- **THEN** the retrieval step SHALL proceed with the original query text
- **AND** the assistant response SHALL be generated normally
- **AND** `rewritten_query` on the user message SHALL remain `NULL`

#### Scenario: Rewritten query persisted on user message

- **WHEN** query rewriting succeeds and produces a different query
- **THEN** the `rewritten_query` column on the user message record SHALL be updated with the rewritten text
- **AND** the update SHALL occur before the retrieval step

---

### Requirement: ChatService constructor

**[Modified by S7-02]** The `ChatService` constructor SHALL accept a `context_assembler` parameter of type `ContextAssembler` instead of a direct `persona_context` parameter. The `context_assembler` SHALL encapsulate `persona_context` and make it accessible as a public attribute (`context_assembler.persona_context`) for config hash access. The `ChatService` constructor SHALL also accept a `query_rewrite_service` parameter of type `QueryRewriteService`. The `ChatService` constructor SHALL also accept an optional `conversation_memory_service` parameter of type `ConversationMemoryService | None` and an optional `summary_enqueuer` parameter of type `SummaryEnqueuer | None`. The `ChatService` constructor SHALL also accept a required `audit_service` parameter of type `AuditService`. All dependencies SHALL be injected via the existing dependency injection mechanism in `api/dependencies.py`. When `conversation_memory_service` is `None`, the memory step SHALL be skipped and `memory_block` SHALL be `None`. When `summary_enqueuer` is `None`, summary task enqueue SHALL be skipped.

#### Scenario: ChatService accepts context_assembler instead of persona_context

- **WHEN** `ChatService` is instantiated
- **THEN** it SHALL require a `context_assembler` parameter of type `ContextAssembler`
- **AND** SHALL NOT accept a direct `persona_context` parameter
- **AND** SHALL store `context_assembler` for use during prompt construction

#### Scenario: persona_context accessible via context_assembler

- **WHEN** `ChatService` needs `config_commit_hash` or `config_content_hash` for audit logging
- **THEN** it SHALL access them via `self.context_assembler.persona_context.config_commit_hash` and `self.context_assembler.persona_context.config_content_hash`

#### Scenario: ChatService requires QueryRewriteService

- **WHEN** `ChatService` is instantiated
- **THEN** it SHALL require a `query_rewrite_service` parameter
- **AND** SHALL store it for use during message processing

#### Scenario: ContextAssembler wired via dependency injection

- **WHEN** the `get_chat_service()` dependency is resolved
- **THEN** it SHALL provide a `ContextAssembler` instance (wrapping `persona_context` and `promotions_service`) to the `ChatService` constructor
- **AND** SHALL NOT pass `persona_context` directly

#### Scenario: QueryRewriteService wired via dependency injection

- **WHEN** the `get_chat_service()` dependency is resolved
- **THEN** it SHALL provide a `QueryRewriteService` instance to the `ChatService` constructor

#### Scenario: ChatService accepts optional conversation_memory_service

- **WHEN** `ChatService` is instantiated with `conversation_memory_service=ConversationMemoryService(...)`
- **THEN** it SHALL store the service for use during message processing

#### Scenario: ChatService accepts optional summary_enqueuer

- **WHEN** `ChatService` is instantiated with `summary_enqueuer=<async callable>`
- **THEN** it SHALL store the enqueuer for use after successful response completion

#### Scenario: ChatService without conversation_memory_service skips memory

- **WHEN** `ChatService` is instantiated with `conversation_memory_service=None`
- **THEN** the memory step SHALL be skipped during message processing
- **AND** `ContextAssembler.assemble()` SHALL be called with `memory_block=None`

#### Scenario: ConversationMemoryService wired via dependency injection

- **WHEN** the `get_chat_service()` dependency is resolved
- **THEN** it SHALL provide a `ConversationMemoryService` instance to the `ChatService` constructor

#### Scenario: ChatService requires audit_service

- **WHEN** `ChatService` is instantiated with `audit_service=AuditService()`
- **THEN** it SHALL store the audit service as `self._audit_service` for use after message finalization

#### Scenario: AuditService wired via dependency injection

- **WHEN** the `get_chat_service()` dependency is resolved
- **THEN** it SHALL provide an `AuditService` instance to the `ChatService` constructor

---

### Requirement: Audit logging at all terminal message states

**[Added by S7-02]** `ChatService` SHALL call `_log_audit()` at every terminal assistant message state: complete, partial (disconnect), and failed. A `start_time = time.perf_counter()` SHALL be recorded at the start of both `answer()` and `stream_answer()`. The latency in milliseconds SHALL be computed as `int((time.perf_counter() - start_time) * 1000)` and passed to `_log_audit()`. In this requirement, `snapshot_id` means the UUID of the retrieval / conversation snapshot bound to the session at the time the assistant response is produced.

#### Scenario: Audit logged on complete response (streaming path)

- **WHEN** the assistant message reaches `status=complete` in `stream_answer()`
- **THEN** `_log_audit()` SHALL be called with `chat_session`, `message`, `snapshot_id`, `retrieved_chunks_count`, and `latency_ms`
- **AND** the call SHALL happen after `await self._session.commit()` and before the citations event is yielded

#### Scenario: Audit logged on complete response (sync answer path)

- **WHEN** the assistant message reaches `status=complete` in `answer()`
- **THEN** `_log_audit()` SHALL be called before `return ChatAnswerResult(...)`
- **AND** this SHALL apply to both the successful LLM response path and the refusal path

#### Scenario: Audit logged on failed response (streaming path)

- **WHEN** the assistant message reaches `status=failed` in the `stream_answer()` exception handler
- **THEN** `_log_audit()` SHALL be called after `await self._session.commit()`
- **AND** `latency_ms` SHALL reflect the time from `start_time` to the failure point

#### Scenario: Audit logged on partial disconnect

- **WHEN** `save_partial_on_disconnect()` saves a message with `status=partial`
- **THEN** the method SHALL load the chat session from DB via `self._session.get(Session, message.session_id)`
- **AND** `_log_audit()` SHALL be called with `latency_ms` derived from `message.created_at` when that timestamp is available
- **AND** `latency_ms` MAY be `null` only when the message timestamp is unavailable
- **AND** `retrieved_chunks_count` SHALL be derived from `len(message.source_ids or [])`

#### Scenario: Audit logged on failed timeout

- **WHEN** `save_failed_on_timeout()` saves a message with `status=failed`
- **THEN** the method SHALL load the chat session from DB via `self._session.get(Session, message.session_id)`
- **AND** `_log_audit()` SHALL be called with `latency_ms` derived from `message.created_at` when that timestamp is available

#### Scenario: save_partial_on_disconnect method signature unchanged

- **WHEN** `save_partial_on_disconnect()` is called
- **THEN** it SHALL accept the same parameters as before: `assistant_message_id` (UUID) and `accumulated_content` (str)
- **AND** no API route code SHALL need to change

#### Scenario: save_failed_on_timeout method signature unchanged

- **WHEN** `save_failed_on_timeout()` is called
- **THEN** it SHALL accept the same parameters as before
- **AND** no API route code SHALL need to change

---

### Requirement: CHAT_RESPONSES_TOTAL metric increment

**[Added by S7-02]** `ChatService` SHALL increment the Prometheus metric `chat_responses_total` via the code constant `CHAT_RESPONSES_TOTAL` whenever an assistant message reaches a terminal state. The counter SHALL use the `status` label with the message status value (`complete`, `partial`, or `failed`). The increment SHALL happen at the same code points where `_log_audit()` is called.

#### Scenario: Counter incremented on complete

- **WHEN** an assistant message reaches `status=complete`
- **THEN** `CHAT_RESPONSES_TOTAL.labels(status="complete").inc()` SHALL be called

#### Scenario: Counter incremented on partial

- **WHEN** an assistant message reaches `status=partial` (client disconnect)
- **THEN** `CHAT_RESPONSES_TOTAL.labels(status="partial").inc()` SHALL be called

#### Scenario: Counter incremented on failed

- **WHEN** an assistant message reaches `status=failed` (LLM error or timeout)
- **THEN** `CHAT_RESPONSES_TOTAL.labels(status="failed").inc()` SHALL be called

---

### Requirement: CHAT_RESPONSE_LATENCY_SECONDS histogram observation

**[Added by S7-02]** `ChatService` SHALL observe the `CHAT_RESPONSE_LATENCY_SECONDS` histogram with the measured latency converted to seconds (`latency_ms / 1000`) at the same code points where `CHAT_RESPONSES_TOTAL` is incremented. This ensures every terminal assistant message state records both the count and the latency distribution.

#### Scenario: Latency histogram observed on complete response

- **WHEN** an assistant message reaches `status=complete`
- **THEN** `CHAT_RESPONSE_LATENCY_SECONDS.observe(latency_ms / 1000)` SHALL be called
- **AND** the observation SHALL happen at the same code point where `CHAT_RESPONSES_TOTAL.labels(status="complete").inc()` is called

#### Scenario: Latency histogram observed on failed response

- **WHEN** an assistant message reaches `status=failed` (LLM error or timeout)
- **THEN** `CHAT_RESPONSE_LATENCY_SECONDS.observe(latency_ms / 1000)` SHALL be called
- **AND** the observation SHALL happen at the same code point where `CHAT_RESPONSES_TOTAL.labels(status="failed").inc()` is called

#### Scenario: Latency histogram observed on partial response (disconnect)

- **WHEN** an assistant message reaches `status=partial` (client disconnect)
- **THEN** `CHAT_RESPONSE_LATENCY_SECONDS.observe(latency_ms / 1000)` SHALL be called when `latency_ms` is available
- **AND** the histogram observation MAY be skipped when `latency_ms` is `null`
- **AND** the observation SHALL happen at the same code point where `CHAT_RESPONSES_TOTAL.labels(status="partial").inc()` is called

#### Scenario: \_log_audit suppresses audit persistence failures

- **WHEN** `AuditService.log_response()` raises inside `_log_audit()`
- **THEN** `_log_audit()` SHALL catch the exception, log it with response context, and suppress propagation so response delivery is not affected

---

### Requirement: Conversation memory integration in chat flow

`ChatService` SHALL integrate conversation memory into both `answer()` and `stream_answer()` methods. After loading conversation history via `_load_history()` and performing query rewriting, the service SHALL call `ConversationMemoryService.build_memory_block(session=session, messages=history)` to build a `MemoryBlock`. The history list SHALL exclude the current user message. The resulting `MemoryBlock` SHALL be passed to `ContextAssembler.assemble()` as the `memory_block` parameter. After the assistant message is successfully persisted with `status=complete`, if `memory_block.needs_summary_update` is `True` and `summary_enqueuer` is not `None`, the service SHALL enqueue a summary generation task.

#### Scenario: Full flow with conversation memory

- **WHEN** a user sends a message in a session with 10 prior messages
- **THEN** `_load_history()` SHALL return the 10 prior messages
- **AND** `ConversationMemoryService.build_memory_block()` SHALL be called with those 10 messages
- **AND** `ContextAssembler.assemble()` SHALL receive the resulting `MemoryBlock`
- **AND** the LLM SHALL receive the assembled prompt including conversation history

#### Scenario: Memory step skipped when no memory service

- **WHEN** `conversation_memory_service` is `None`
- **THEN** the memory build step SHALL be skipped
- **AND** `ContextAssembler.assemble()` SHALL receive `memory_block=None`

#### Scenario: Refusal skips memory assembly for LLM but still builds block

- **WHEN** retrieval returns fewer chunks than `min_retrieved_chunks`
- **THEN** the system SHALL return a refusal without calling `ContextAssembler` or the LLM
- **AND** the summary enqueue step SHALL be skipped

---

### Requirement: Summary enqueue protocol

`SummaryEnqueuer` SHALL be defined as a protocol: an async callable accepting `session_id` (`str`) and `window_start_message_id` (`str | null`). The implementation SHALL enqueue a `generate_session_summary` arq task with `job_id=f"summary:{session_id}"` for deduplication. The enqueue SHALL be performed after the assistant message is successfully persisted. Enqueue failure SHALL be caught by `ChatService`, logged as a warning, and SHALL NOT propagate to the caller.

#### Scenario: Enqueue called with correct parameters

- **WHEN** `summary_enqueuer` is called after a successful response with `needs_summary_update=True`
- **THEN** it SHALL receive `session_id` as a string and `window_start_message_id` as either a string or `null`

#### Scenario: arq job_id ensures deduplication

- **WHEN** the `SummaryEnqueuer` implementation enqueues a task
- **THEN** the arq `job_id` SHALL be `f"summary:{session_id}"`

#### Scenario: Enqueue failure gracefully handled

- **WHEN** the `summary_enqueuer` raises `ConnectionError` or any other exception
- **THEN** `ChatService` SHALL catch the exception
- **AND** SHALL log a warning including the `session_id` and error details
- **AND** the HTTP response to the client SHALL NOT be affected

---

### Requirement: rewritten_query column on messages table

The `messages` table SHALL have a `rewritten_query` column of type nullable TEXT. This column SHALL be populated only for user messages (`role=user`) when query rewriting occurs and produces a different query. The column SHALL be `NULL` when: the message is the first in a session (no history), rewriting is disabled, rewriting fails or times out, or the message is an assistant message. Introduced by S4-04.

#### Scenario: Rewritten query stored for user message

- **WHEN** a user message triggers successful query rewriting
- **THEN** the `rewritten_query` column SHALL contain the LLM-reformulated query text

#### Scenario: NULL for first message in session

- **WHEN** the first message is sent in a new session (no prior history)
- **THEN** the `rewritten_query` column SHALL be `NULL`

#### Scenario: NULL for assistant messages

- **WHEN** an assistant message is persisted
- **THEN** the `rewritten_query` column SHALL be `NULL`

#### Scenario: NULL when rewrite fails

- **WHEN** query rewriting times out or raises an error
- **THEN** the `rewritten_query` column on the user message SHALL remain `NULL`

---

### Requirement: Conversation history loading

The `ChatService` SHALL provide a `_load_history()` method (or equivalent) that loads session messages for the rewrite context. The method SHALL load all messages in the session excluding the current user message, ordered by `created_at` ascending. Only messages with status RECEIVED (user messages) or COMPLETE (assistant messages) SHALL be included. Messages with status STREAMING, PARTIAL, or FAILED SHALL be excluded. Introduced by S4-04.

#### Scenario: History loaded excluding current message

- **WHEN** a session has 4 prior messages and the user sends a 5th message
- **THEN** `_load_history()` SHALL return the 4 prior messages
- **AND** the current (5th) user message SHALL NOT be included

#### Scenario: Only RECEIVED and COMPLETE messages included

- **WHEN** a session has 3 messages: user (RECEIVED), assistant (COMPLETE), and assistant (FAILED)
- **THEN** `_load_history()` SHALL return 2 messages (the RECEIVED user message and the COMPLETE assistant message)
- **AND** the FAILED assistant message SHALL be excluded

#### Scenario: Empty history for first message

- **WHEN** the first message is sent in a new session
- **THEN** `_load_history()` SHALL return an empty list

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

When retrieval returns fewer chunks than `min_retrieved_chunks` (configurable, default 1), `ChatService` SHALL save an assistant message with a hardcoded refusal text and `status=complete`, and return it without calling the LLM or the `ContextAssembler`. This check SHALL happen before the assembler is invoked. `ChatService` is the single owner of the refusal decision — the `ContextAssembler` does budget trimming but never decides to refuse.

#### Scenario: Refusal when zero chunks retrieved

- **WHEN** `POST /api/chat/messages` is called and retrieval returns 0 chunks
- **THEN** the response SHALL be 200 with an assistant message containing a refusal text
- **AND** the assistant message `status` SHALL be `"complete"`
- **AND** the LLM SHALL NOT be called
- **AND** the `ContextAssembler` SHALL NOT be called
- **AND** `retrieved_chunks_count` SHALL be 0

#### Scenario: Refusal when chunks below min_retrieved_chunks threshold

- **WHEN** `min_retrieved_chunks` is configured to 3 and retrieval returns 2 chunks
- **THEN** the system SHALL return a refusal without calling the LLM or the assembler

#### Scenario: Normal flow when chunks meet threshold

- **WHEN** `min_retrieved_chunks` is 1 and retrieval returns 3 chunks
- **THEN** the system SHALL proceed to `ContextAssembler.assemble()` and then to the LLM call

---

### Requirement: Session history via GET /api/chat/sessions/:id

The system SHALL provide a `GET /api/chat/sessions/{session_id}` endpoint that returns the session with its ordered message history. Messages SHALL be ordered by `created_at` ascending. The response SHALL include `id`, `status`, `channel`, `snapshot_id`, `message_count`, `created_at`, and a `messages` array. Each message in the array SHALL be represented by the `MessageInHistory` schema and SHALL include `id`, `role`, `content`, `status`, `model_name` (for assistant messages), `created_at`, and a `citations` field (`list[CitationResponse] | None`).

`CitationResponse` SHALL contain the following fields:

- `index` — integer, the citation's position number in the response text
- `source_id` — UUID, the knowledge source this citation references
- `source_title` — string, the human-readable title of the source document
- `source_type` — string, the type of the source (e.g., `"pdf"`, `"webpage"`, `"markdown"`)
- `url` — nullable string, the public URL of the source (null when no public URL exists)
- `anchor` — `AnchorResponse`, the location within the source
- `text_citation` — string, human-readable bibliographic reference (e.g., `"Clean Architecture", Chapter 5, p. 42`). Always present regardless of whether `url` is set. Assembled from source title and anchor metadata by the citation service.

`AnchorResponse` SHALL contain the following fields:

- `page` — nullable integer, the page number within the source document
- `chapter` — nullable string, the chapter title or identifier
- `section` — nullable string, the section title or identifier
- `timecode` — nullable string, the timecode for audio/video sources

For user messages, the `citations` field SHALL be `null` (citations are not applicable). For assistant messages with COMPLETE status, the `citations` field SHALL be an empty list `[]` when no citations were produced (never `null`). For assistant messages with FAILED or PARTIAL status, the `citations` field SHALL be `null` (citations were not computed). If the session does not exist, the endpoint SHALL return 404.

#### Scenario: Get session with messages including citations

- **WHEN** `GET /api/chat/sessions/{session_id}` is called for a session that has 2 messages (1 user, 1 assistant with 2 citations)
- **THEN** the response SHALL be 200
- **AND** `messages` SHALL contain 2 entries ordered by `created_at` ascending
- **AND** the user message SHALL have `citations` as `null`
- **AND** the assistant message SHALL have `citations` as a list of 2 `CitationResponse` objects
- **AND** each `CitationResponse` SHALL include `index`, `source_id`, `source_title`, `source_type`, `url`, `anchor`, and `text_citation`

#### Scenario: COMPLETE assistant message without citations returns empty list

- **WHEN** `GET /api/chat/sessions/{session_id}` is called for a session with a COMPLETE assistant message that produced no citations
- **THEN** the assistant message SHALL have `citations` as `[]` (empty list, not `null`)

#### Scenario: User message citations is null

- **WHEN** `GET /api/chat/sessions/{session_id}` is called for a session with a user message
- **THEN** the user message SHALL have `citations` as `null`

#### Scenario: CitationResponse anchor structure

- **WHEN** an assistant message has a citation referencing page 42, section "Introduction"
- **THEN** the `CitationResponse.anchor` SHALL be an `AnchorResponse` with `page=42`, `section="Introduction"`, and `chapter` and `timecode` as `null`

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
- Concurrent stream in session: the system SHALL detect an existing STREAMING assistant message in the session and return 409 Conflict. This check runs after the idempotency check.
- Idempotency conflict (STREAMING in flight): when the idempotency key matches a user message whose paired assistant message has status STREAMING, the endpoint SHALL return 409 Conflict.
- LLM call failure during stream: the system SHALL emit an `error` SSE event, save the assistant message with `status=failed` (including any accumulated content), and close the stream.
- Qdrant or embedding failure (retrieval error): `ChatService` SHALL persist an assistant message with `status=failed` before re-raising; router SHALL return 500. This occurs pre-stream, so standard HTTP error codes are used.

After a user message is saved, any subsequent error MUST result in a persisted assistant message with `status=failed` (for pre-stream errors) or appropriate terminal status (FAILED for mid-stream errors, PARTIAL for disconnect) for observability.

#### Scenario: Session not found returns 404

- **WHEN** `POST /api/chat/messages` is called with a `session_id` that does not exist
- **THEN** the response SHALL be 404 with detail "Session not found"

#### Scenario: No active snapshot returns 422

- **WHEN** `POST /api/chat/messages` is called for a session with `snapshot_id=null` and no active snapshot exists
- **THEN** the response SHALL be 422

#### Scenario: Empty text returns 422

- **WHEN** `POST /api/chat/messages` is called with `text` as an empty string or missing
- **THEN** the response SHALL be 422 (Pydantic validation error)

#### Scenario: Concurrent stream returns 409

- **WHEN** `POST /api/chat/messages` is called for a session that already has an assistant message with status STREAMING
- **THEN** the response SHALL be 409 Conflict

#### Scenario: Idempotency conflict for STREAMING returns 409

- **WHEN** `POST /api/chat/messages` is called with an `idempotency_key` whose paired assistant message has status STREAMING
- **THEN** the response SHALL be 409 Conflict

#### Scenario: LLM failure during stream emits error event and saves FAILED

- **WHEN** the LLM call fails during SSE streaming
- **THEN** an `error` SSE event SHALL be emitted with a detail describing the failure
- **AND** the assistant message SHALL be saved with `status=failed` and any accumulated content
- **AND** the stream SHALL be closed

#### Scenario: Qdrant failure returns 500 with failed message persisted

- **WHEN** the Qdrant search fails during message processing (pre-stream)
- **THEN** an assistant message SHALL be saved with `status=failed`
- **AND** the response SHALL be 500

#### Scenario: Retrieval error persists FAILED then raises

- **WHEN** the embedding or Qdrant call fails during retrieval
- **THEN** the system SHALL persist an assistant message with `status=failed`
- **AND** SHALL re-raise the exception so the router returns HTTP 500

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

The `services/prompt.py` module SHALL retain utility functions (`format_chunk_header()` and `NO_CONTEXT_REFUSAL` constant) used by other services. The `build_chat_prompt()` function SHALL be removed — its responsibility is now handled by `ContextAssembler`. Layer assembly logic, XML tag wrapping, and budget management SHALL live exclusively in `ContextAssembler`.

#### Scenario: build_chat_prompt no longer exists

- **WHEN** the `services/prompt.py` module is inspected after S4-05
- **THEN** it SHALL NOT contain a `build_chat_prompt()` function

#### Scenario: format_chunk_header retained

- **WHEN** `ContextAssembler` formats retrieval chunks
- **THEN** it SHALL use `format_chunk_header()` from `services/prompt.py`
- **AND** the function SHALL remain available for other consumers

#### Scenario: NO_CONTEXT_REFUSAL retained

- **WHEN** `ChatService` returns a refusal due to insufficient chunks
- **THEN** it SHALL use the `NO_CONTEXT_REFUSAL` constant from `services/prompt.py`

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

---

### Requirement: Parent message ID for user-assistant pairing

The `messages` table SHALL have a `parent_message_id` column (nullable UUID, foreign key to `messages.id`). This column SHALL be set on assistant messages to link back to the user message they respond to. The column SHALL be added via an Alembic migration. User messages SHALL have `parent_message_id` set to `null`. This explicit pairing supports reliable idempotency lookup (finding the assistant response for a given user message) and is more robust than implicit pairing via timestamps or ordering.

#### Scenario: Assistant message linked to user message

- **WHEN** a user sends a message and the system generates an assistant response
- **THEN** the assistant message SHALL have `parent_message_id` set to the user message's `id`

#### Scenario: User message has no parent

- **WHEN** a user message is saved
- **THEN** `parent_message_id` SHALL be `null`

#### Scenario: Idempotency lookup uses parent_message_id

- **WHEN** an idempotency key matches a user message
- **THEN** the system SHALL find the paired assistant message by querying `parent_message_id` equal to the user message's `id`

---

### Requirement: Save partial content on disconnect

The `ChatService` SHALL provide a `save_partial_on_disconnect` method (or equivalent logic) that is invoked when a client disconnects during an active SSE stream. This method SHALL save the accumulated content buffer to the assistant message, update the assistant message status to PARTIAL, and persist the change to the database. This ensures no generated content is lost on client disconnect.

#### Scenario: Partial content saved on disconnect

- **WHEN** the client disconnects after the LLM has emitted some tokens
- **THEN** the assistant message SHALL be updated with status PARTIAL and the accumulated content

#### Scenario: Empty partial saved on early disconnect

- **WHEN** the client disconnects before any LLM tokens are received (but after the assistant message is created)
- **THEN** the assistant message SHALL be updated with status PARTIAL and empty content

---

### Requirement: Save failed content on timeout

The `ChatService` SHALL provide a `save_failed_on_timeout` method (or equivalent logic) that is invoked when the inter-token timeout fires during an active SSE stream. This method SHALL save any accumulated content buffer to the assistant message, update the assistant message status to FAILED, and persist the change to the database.

#### Scenario: Failed content saved on timeout

- **WHEN** the inter-token timeout fires after some tokens have been received
- **THEN** the assistant message SHALL be updated with status FAILED and the accumulated content

#### Scenario: Failed with no content on early timeout

- **WHEN** the inter-token timeout fires before any LLM tokens are received
- **THEN** the assistant message SHALL be updated with status FAILED and empty content

---

### Requirement: Source metadata batch loading in chat flow

After retrieval and before prompt assembly, the chat service SHALL batch-load source metadata from PostgreSQL for all unique `source_id` values present in the retrieved chunks. The batch query SHALL load `title`, `public_url`, and `source_type` for each source in a single database query. The resulting source map (`dict[UUID, SourceInfo]`) SHALL be passed to both the prompt builder (for context enrichment) and the citation service (for building citation objects with source titles and URLs).

`SourceInfo` SHALL contain the following fields:

- `id` — UUID, the source identifier
- `title` — string, the human-readable title of the source document
- `public_url` — nullable string, the public URL of the source (null when no public URL exists)
- `source_type` — string, the type of the source (e.g., `"pdf"`, `"markdown"`, `"audio"`)

Sources that are soft-deleted (`deleted_at IS NOT NULL`) SHALL be excluded from the source map. If a retrieved chunk references a `source_id` that is missing from the source map (deleted or otherwise absent), the citation service SHALL silently skip that source — no fallback entry, no error.

#### Scenario: Batch load source metadata for retrieved chunks

- **WHEN** retrieval returns 5 chunks from 3 unique source documents
- **THEN** the chat service SHALL execute a single batch query to load metadata for those 3 source IDs
- **AND** the resulting source map SHALL contain entries for all 3 sources

#### Scenario: Source map passed to citation service

- **WHEN** the source map is constructed after retrieval
- **THEN** the chat service SHALL pass the source map to the citation service alongside the LLM response and retrieved chunks

#### Scenario: Source map passed to prompt builder

- **WHEN** the source map is constructed after retrieval
- **THEN** the chat service SHALL pass the source map to the prompt builder for context enrichment

#### Scenario: Missing source silently skipped

- **WHEN** a retrieved chunk references a `source_id` that no longer exists in the database (soft-deleted or absent)
- **THEN** the source map SHALL NOT contain an entry for that `source_id`
- **AND** the citation service SHALL silently skip that source (no citation produced for it)
- **AND** the chat flow SHALL NOT raise an error

#### Scenario: No retrieval skips batch loading

- **WHEN** retrieval returns 0 chunks (triggering a refusal)
- **THEN** the source metadata batch loading step SHALL be skipped
- **AND** an empty source map SHALL be used
