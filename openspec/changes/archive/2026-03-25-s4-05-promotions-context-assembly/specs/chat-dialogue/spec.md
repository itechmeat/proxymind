## Purpose

Delta spec for S4-05 Promotions + Context Assembly: ChatService uses `ContextAssembler` instead of `build_chat_prompt()`, config hashes accessed via `context_assembler.persona_context`, content type spans computed and persisted after LLM response, and ChatService is the single owner of the refusal decision (before the assembler is called).

## MODIFIED Requirements

### Requirement: Message send via POST /api/chat/messages

The system SHALL provide a `POST /api/chat/messages` endpoint that accepts `session_id` (UUID), `text` (non-empty string), and an optional `idempotency_key` (string, client-generated) in the `SendMessageRequest`. The endpoint SHALL save the user message with `role=user`, `status=received`, and `idempotency_key` (when provided), then perform query rewriting (S4-04), then perform retrieval against the session's active snapshot, then assemble a prompt using `ContextAssembler.assemble()` with the retrieval chunks, original user query, and source map, and stream the assistant's response as SSE (`text/event-stream; charset=utf-8`) with status 200.

After the user message is persisted, the system SHALL load conversation history for the session, then call `QueryRewriteService.rewrite()` with the user's query text and the loaded history. The retrieval step SHALL use the rewritten query (or the original query if rewriting was skipped or failed). The prompt assembly step SHALL call `ContextAssembler.assemble(chunks=retrieved_chunks, query=original_query, source_map=source_map)` — using the original user query text, not the rewritten query. When rewriting produces a different query, the `rewritten_query` column on the user message SHALL be updated with the rewritten text.

The `ChatService` SHALL provide a `stream_answer()` method alongside the existing `answer()` method. The existing `answer()` method SHALL be preserved (used by tests and non-streaming internal calls). Both methods SHALL include the query rewriting step. Both methods SHALL call `ContextAssembler.assemble()` for prompt construction instead of `build_chat_prompt()`.

After the LLM response is received and citations are extracted, the system SHALL call `compute_content_type_spans()` with the response text and the `included_promotions` from `AssembledPrompt`. The resulting spans SHALL be persisted in the assistant message's `content_type_spans` JSONB column.

The assistant message SHALL be created with `role=assistant`, `status=streaming`, and `parent_message_id` set to the user message's `id` before the first SSE event is emitted. Upon successful completion, the assistant message SHALL be updated to `status=complete` with `content`, `model_name`, token counts (`token_count_prompt`, `token_count_completion`), deduplicated `source_ids` from retrieved chunks, `content_type_spans` from heuristic classification, and audit hashes (`config_commit_hash`, `config_content_hash` from `context_assembler.persona_context`).

Pre-stream errors (session not found, no active snapshot, concurrent stream conflict, idempotency conflict for STREAMING) SHALL return standard HTTP error codes (404, 409, 422) as JSON responses — the SSE stream SHALL NOT be opened for these cases.

On every response — both the LLM-generated response path (`chat.assistant_completed`) and the code-level refusal path (`chat.refusal_returned`) — `ChatService` SHALL log `config_commit_hash` and `config_content_hash` from `context_assembler.persona_context` via structlog. The response SHALL include a runtime-computed `retrieved_chunks_count` field (delivered in the `done` or `meta` SSE event as appropriate).

#### Scenario: Successful message with SSE streaming response

- **WHEN** `POST /api/chat/messages` is called with a valid `session_id` and `text`, and the session has an active snapshot with indexed chunks
- **THEN** the response SHALL be 200 with `Content-Type: text/event-stream; charset=utf-8`
- **AND** the SSE stream SHALL emit `meta` (with `message_id`, `session_id`, `snapshot_id`), then one or more `token` events, then `done` (with `token_count_prompt`, `token_count_completion`, `model_name`)

#### Scenario: ContextAssembler used for prompt construction

- **WHEN** `ChatService.stream_answer()` or `ChatService.answer()` assembles the LLM prompt
- **THEN** it SHALL call `ContextAssembler.assemble(chunks=retrieved_chunks, query=original_query, source_map=source_map)`
- **AND** SHALL pass the resulting `AssembledPrompt.messages` to the LLM service
- **AND** SHALL NOT call `build_chat_prompt()`

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

The `ChatService` constructor SHALL accept a `context_assembler` parameter of type `ContextAssembler` instead of a direct `persona_context` parameter. The `context_assembler` SHALL encapsulate `persona_context` and make it accessible as a public attribute (`context_assembler.persona_context`) for config hash access. The `ChatService` constructor SHALL also accept a `query_rewrite_service` parameter of type `QueryRewriteService`. Both dependencies SHALL be injected via the existing dependency injection mechanism in `api/dependencies.py`.

#### Scenario: ChatService accepts context_assembler instead of persona_context

- **WHEN** `ChatService` is instantiated
- **THEN** it SHALL require a `context_assembler` parameter of type `ContextAssembler`
- **AND** SHALL NOT accept a direct `persona_context` parameter
- **AND** SHALL store `context_assembler` for use during prompt construction

#### Scenario: persona_context accessible via context_assembler

- **WHEN** `ChatService` needs `config_commit_hash` or `config_content_hash` for audit logging
- **THEN** it SHALL access them via `self.context_assembler.persona_context.config_commit_hash` and `self.context_assembler.persona_context.config_content_hash`

#### Scenario: ContextAssembler wired via dependency injection

- **WHEN** the `get_chat_service()` dependency is resolved
- **THEN** it SHALL provide a `ContextAssembler` instance (wrapping `persona_context` and `promotions_service`) to the `ChatService` constructor
- **AND** SHALL NOT pass `persona_context` directly

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
