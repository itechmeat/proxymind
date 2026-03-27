## Purpose

Delta spec for S4-07 Conversation Memory: integrates `ConversationMemoryService` into the `ChatService` message send flow, adds `MemoryBlock` to the `ContextAssembler.assemble()` call, enqueues async summary generation after successful responses, and extends the `ChatService` constructor with two new optional dependencies.

## MODIFIED Requirements

### Requirement: Message send via POST /api/chat/messages

The system SHALL provide a `POST /api/chat/messages` endpoint that accepts `session_id` (UUID), `text` (non-empty string), and an optional `idempotency_key` (string, client-generated) in the `SendMessageRequest`. The endpoint SHALL save the user message with `role=user`, `status=received`, and `idempotency_key` (when provided), then perform query rewriting (S4-04), then build a conversation memory block from session history, then perform retrieval against the session's active snapshot, then assemble a prompt using `ContextAssembler.assemble()` with the retrieval chunks, original user query, source map, and memory block, and stream the assistant's response as SSE (`text/event-stream; charset=utf-8`) with status 200. After the response completes successfully, if the memory block indicates `needs_summary_update=True`, the system SHALL enqueue a `generate_session_summary` arq task.

After the user message is persisted, the system SHALL load conversation history for the session, then call `QueryRewriteService.rewrite()` with the user's query text and the loaded history. The retrieval step SHALL use the rewritten query (or the original query if rewriting was skipped or failed). After query rewriting and before retrieval, the system SHALL build a `MemoryBlock` by calling `ConversationMemoryService.build_memory_block()` with the session and the loaded history (excluding the current user message). The prompt assembly step SHALL call `ContextAssembler.assemble(chunks=retrieved_chunks, query=original_query, source_map=source_map, memory_block=memory_block)` -- using the original user query text, not the rewritten query, and including the memory block. When rewriting produces a different query, the `rewritten_query` column on the user message SHALL be updated with the rewritten text.

The `ChatService` SHALL provide a `stream_answer()` method alongside the existing `answer()` method. The existing `answer()` method SHALL be preserved (used by tests and non-streaming internal calls). Both methods SHALL include the query rewriting step. Both methods SHALL include the conversation memory step. Both methods SHALL call `ContextAssembler.assemble()` for prompt construction instead of `build_chat_prompt()`.

After the LLM response is received and citations are extracted, the system SHALL call `compute_content_type_spans()` with the response text and the `included_promotions` from `AssembledPrompt`. The resulting spans SHALL be persisted in the assistant message's `content_type_spans` JSONB column.

After the assistant message is persisted with `status=complete`, the system SHALL check `memory_block.needs_summary_update`. When `True` and a `summary_enqueuer` is available, the system SHALL enqueue a `generate_session_summary` arq task with `session_id` and `memory_block.window_start_message_id`. `window_start_message_id` MAY be `null` when no verbatim memory window fits and all unsummarized messages should be summarized. Enqueue failure SHALL be logged but SHALL NOT fail the response -- the summary is non-critical and will be retried on the next request.

The assistant message SHALL be created with `role=assistant`, `status=streaming`, and `parent_message_id` set to the user message's `id` before the first SSE event is emitted. Upon successful completion, the assistant message SHALL be updated to `status=complete` with `content`, `model_name`, token counts (`token_count_prompt`, `token_count_completion`), deduplicated `source_ids` from retrieved chunks, `content_type_spans` from heuristic classification, and audit hashes (`config_commit_hash`, `config_content_hash` from `context_assembler.persona_context`).

Pre-stream errors (session not found, no active snapshot, concurrent stream conflict, idempotency conflict for STREAMING) SHALL return standard HTTP error codes (404, 409, 422) as JSON responses -- the SSE stream SHALL NOT be opened for these cases.

On every response -- both the LLM-generated response path (`chat.assistant_completed`) and the code-level refusal path (`chat.refusal_returned`) -- `ChatService` SHALL log `config_commit_hash` and `config_content_hash` from `context_assembler.persona_context` via structlog. The response SHALL include a runtime-computed `retrieved_chunks_count` field (delivered in the `done` or `meta` SSE event as appropriate).

#### Scenario: Successful message with SSE streaming response

- **WHEN** `POST /api/chat/messages` is called with a valid `session_id` and `text`, and the session has an active snapshot with indexed chunks
- **THEN** the response SHALL be 200 with `Content-Type: text/event-stream; charset=utf-8`
- **AND** the SSE stream SHALL emit `meta` (with `message_id`, `session_id`, `snapshot_id`), then one or more `token` events, then `done` (with `token_count_prompt`, `token_count_completion`, `model_name`)

#### Scenario: ContextAssembler called with memory_block

- **WHEN** `ChatService.stream_answer()` or `ChatService.answer()` assembles the LLM prompt
- **THEN** it SHALL call `ContextAssembler.assemble(chunks=retrieved_chunks, query=original_query, source_map=source_map, memory_block=memory_block)`
- **AND** SHALL pass the resulting `AssembledPrompt.messages` to the LLM service
- **AND** SHALL NOT call `build_chat_prompt()`
- **CI test:** mock assembler, verify memory_block argument

#### Scenario: Memory block built from session history

- **WHEN** a session has prior messages and a new message is sent
- **THEN** `ConversationMemoryService.build_memory_block()` SHALL be called with the session and history (excluding the current user message)
- **AND** the resulting `MemoryBlock` SHALL be passed to `ContextAssembler.assemble()`
- **CI test:** mock memory service, verify call arguments

#### Scenario: Summary task enqueued when needs_summary_update is True

- **WHEN** the assistant message is saved with `status=complete` and `memory_block.needs_summary_update` is `True`
- **THEN** the system SHALL enqueue `generate_session_summary` via `summary_enqueuer`
- **AND** the enqueue call SHALL include `session_id` and `window_start_message_id`
- **CI test:** mock enqueuer, verify called with correct args

#### Scenario: Summary task not enqueued when needs_summary_update is False

- **WHEN** the assistant message is saved with `status=complete` and `memory_block.needs_summary_update` is `False`
- **THEN** the system SHALL NOT enqueue a summary task
- **CI test:** mock enqueuer, verify not called

#### Scenario: Summary enqueue failure does not fail response

- **WHEN** the summary task enqueue raises an exception
- **THEN** the exception SHALL be caught and logged as a warning
- **AND** the assistant response SHALL still be returned successfully to the client
- **CI test:** mock enqueuer to raise, verify response still succeeds

#### Scenario: Config hashes accessed via context_assembler.persona_context

- **WHEN** the assistant message is saved with `status=complete` or a refusal is returned
- **THEN** `config_commit_hash` and `config_content_hash` SHALL be read from `context_assembler.persona_context`
- **AND** these values SHALL be persisted on the assistant message and logged via structlog

#### Scenario: Content type spans computed after LLM response

- **WHEN** the LLM returns a successful response and citations are extracted
- **THEN** `compute_content_type_spans()` SHALL be called with the response text and `assembled_prompt.included_promotions`
- **AND** the resulting spans SHALL be stored in the assistant message's `content_type_spans` column

#### Scenario: Content type spans empty when refusal

- **WHEN** retrieval returns fewer chunks than `min_retrieved_chunks` and a refusal is returned
- **THEN** `content_type_spans` on the assistant message SHALL be `null` or an empty list (no content type classification is needed for refusal text)

#### Scenario: Rewritten query used for retrieval, original for assembler

- **WHEN** a user sends "Tell me more about the second one" in a session with prior history
- **AND** query rewriting reformulates the query to "Tell me more about Sergey's book Deep Learning in Practice"
- **THEN** the retrieval step SHALL search using "Tell me more about Sergey's book Deep Learning in Practice"
- **AND** `ContextAssembler.assemble()` SHALL receive the original query "Tell me more about the second one"

#### Scenario: First message skips rewriting and produces empty memory

- **WHEN** the first message in a session is sent
- **THEN** query rewriting SHALL be skipped (no history available)
- **AND** `ConversationMemoryService.build_memory_block()` SHALL be called with an empty messages list
- **AND** the resulting `MemoryBlock` SHALL have `summary_text=None`, `messages=[]`, `needs_summary_update=False`
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

The `ChatService` constructor SHALL accept a `context_assembler` parameter of type `ContextAssembler` instead of a direct `persona_context` parameter. The `context_assembler` SHALL encapsulate `persona_context` and make it accessible as a public attribute (`context_assembler.persona_context`) for config hash access. The `ChatService` constructor SHALL also accept a `query_rewrite_service` parameter of type `QueryRewriteService`. The `ChatService` constructor SHALL also accept an optional `conversation_memory_service` parameter of type `ConversationMemoryService | None` (default `None`) and an optional `summary_enqueuer` parameter of type `SummaryEnqueuer | None` (default `None`). All dependencies SHALL be injected via the existing dependency injection mechanism in `api/dependencies.py`. When `conversation_memory_service` is `None`, the memory step SHALL be skipped and `memory_block` SHALL be `None` (backward compatible). When `summary_enqueuer` is `None`, summary task enqueue SHALL be skipped.

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

#### Scenario: ChatService accepts optional conversation_memory_service

- **WHEN** `ChatService` is instantiated with `conversation_memory_service=ConversationMemoryService(...)`
- **THEN** it SHALL store the service for use during message processing
- **AND** SHALL call `build_memory_block()` during the message send flow
- **CI test:** verify constructor accepts the parameter

#### Scenario: ChatService accepts optional summary_enqueuer

- **WHEN** `ChatService` is instantiated with `summary_enqueuer=<async callable>`
- **THEN** it SHALL store the enqueuer for use after successful response completion
- **CI test:** verify constructor accepts the parameter

#### Scenario: ChatService without conversation_memory_service skips memory

- **WHEN** `ChatService` is instantiated with `conversation_memory_service=None`
- **THEN** the memory step SHALL be skipped during message processing
- **AND** `ContextAssembler.assemble()` SHALL be called with `memory_block=None`
- **CI test:** verify backward compatibility

#### Scenario: ContextAssembler wired via dependency injection

- **WHEN** the `get_chat_service()` dependency is resolved
- **THEN** it SHALL provide a `ContextAssembler` instance (wrapping `persona_context` and `promotions_service`) to the `ChatService` constructor
- **AND** SHALL NOT pass `persona_context` directly

#### Scenario: QueryRewriteService wired via dependency injection

- **WHEN** the `get_chat_service()` dependency is resolved
- **THEN** it SHALL provide a `QueryRewriteService` instance to the `ChatService` constructor

#### Scenario: ConversationMemoryService wired via dependency injection

- **WHEN** the `get_chat_service()` dependency is resolved
- **THEN** it SHALL provide a `ConversationMemoryService` instance to the `ChatService` constructor
- **AND** the service SHALL be initialized with `budget=conversation_memory_budget` and `summary_ratio=conversation_summary_ratio`

---

## ADDED Requirements

### Requirement: Conversation memory integration in chat flow

`ChatService` SHALL integrate conversation memory into both `answer()` and `stream_answer()` methods. After loading conversation history via `_load_history()` and performing query rewriting, the service SHALL call `ConversationMemoryService.build_memory_block(session=session, messages=history)` to build a `MemoryBlock`. The `history` list SHALL exclude the current user message (same list used for query rewriting). The resulting `MemoryBlock` SHALL be passed to `ContextAssembler.assemble()` as the `memory_block` parameter. After the assistant message is successfully persisted with `status=complete`, if `memory_block.needs_summary_update` is `True` and `summary_enqueuer` is not `None`, the service SHALL enqueue a summary generation task. The complete updated flow SHALL be:

1. Load session, check idempotency (unchanged)
2. Persist user message (unchanged)
3. Load conversation history via `_load_history()` (unchanged)
4. Query rewrite using history (unchanged)
5. Build memory block via `ConversationMemoryService.build_memory_block()` (NEW)
6. Retrieval search (unchanged)
7. Context assembly via `ContextAssembler.assemble(..., memory_block=memory_block)` (MODIFIED)
8. Stream/complete LLM response (unchanged)
9. Persist assistant message (unchanged)
10. Enqueue summary task if `needs_summary_update=True` (NEW)

#### Scenario: Full flow with conversation memory

- **WHEN** a user sends a message in a session with 10 prior messages
- **THEN** `_load_history()` SHALL return the 10 prior messages
- **AND** `ConversationMemoryService.build_memory_block()` SHALL be called with those 10 messages
- **AND** `ContextAssembler.assemble()` SHALL receive the resulting `MemoryBlock`
- **AND** the LLM SHALL receive the assembled prompt including conversation history
- **CI test:** mock all services, verify call chain

#### Scenario: Memory step skipped when no memory service

- **WHEN** `conversation_memory_service` is `None`
- **THEN** the memory build step SHALL be skipped
- **AND** `ContextAssembler.assemble()` SHALL receive `memory_block=None`
- **CI test:** verify backward compatibility

#### Scenario: Refusal skips memory assembly for LLM but still builds block

- **WHEN** retrieval returns fewer chunks than `min_retrieved_chunks`
- **THEN** the system SHALL return a refusal without calling `ContextAssembler` or the LLM
- **AND** the summary enqueue step SHALL be skipped (no successful response)
- **CI test:** verify assembler not called on refusal

---

### Requirement: Summary enqueue protocol

`SummaryEnqueuer` SHALL be defined as a protocol: an async callable accepting `session_id` (`str`) and `window_start_message_id` (`str | null`). The implementation SHALL enqueue a `generate_session_summary` arq task with `job_id=f"summary:{session_id}"` for deduplication. The enqueue SHALL be performed after the assistant message is successfully persisted. Enqueue failure (any exception) SHALL be caught by `ChatService`, logged as a warning via structlog, and SHALL NOT propagate to the caller -- the response MUST complete successfully regardless of enqueue outcome.

#### Scenario: Enqueue called with correct parameters

- **WHEN** `summary_enqueuer` is called after a successful response with `needs_summary_update=True`
- **THEN** it SHALL receive `session_id` as a string and `window_start_message_id` as either a string or `null`
- **CI test:** mock enqueuer, verify argument types and values

#### Scenario: arq job_id ensures deduplication

- **WHEN** the `SummaryEnqueuer` implementation enqueues a task
- **THEN** the arq `job_id` SHALL be `f"summary:{session_id}"`
- **AND** concurrent enqueue for the same session SHALL be deduplicated by arq
- **CI test:** verify job_id format

#### Scenario: Enqueue failure gracefully handled

- **WHEN** the `summary_enqueuer` raises `ConnectionError` or any other exception
- **THEN** `ChatService` SHALL catch the exception
- **AND** SHALL log a warning including the `session_id` and error details
- **AND** the HTTP response to the client SHALL NOT be affected
- **CI test:** mock enqueuer to raise, verify log and response

---

## Stable Behavior for Test Coverage

The following stable behavior MUST be covered by tests before this change is archived:

1. **Memory block passed to assembler** -- `assemble()` called with `memory_block` from `build_memory_block()` (CI unit test)
2. **First message produces empty memory** -- `build_memory_block()` called with empty history (CI unit test)
3. **Summary enqueue on needs_summary_update=True** -- enqueuer called with correct args (CI unit test)
4. **Summary enqueue skipped on needs_summary_update=False** -- enqueuer not called (CI unit test)
5. **Summary enqueue failure does not fail response** -- response completes even if enqueue raises (CI unit test)
6. **Backward compatibility without memory service** -- memory_block=None when service is None (CI unit test)
7. **Constructor accepts new optional parameters** -- both `conversation_memory_service` and `summary_enqueuer` (CI unit test)
