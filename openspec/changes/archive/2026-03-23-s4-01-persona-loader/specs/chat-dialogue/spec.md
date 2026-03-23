## MODIFIED Requirements

### Requirement: Message send via POST /api/chat/messages

The system SHALL provide a `POST /api/chat/messages` endpoint that accepts `session_id` (UUID) and `text` (non-empty string). The endpoint SHALL save the user message with `role=user` and `status=received`, then perform retrieval against the session's active snapshot, assemble a prompt using the retrieval context and the loaded `PersonaContext`, call the LLM, and return the assistant's response as JSON with status 200. The `ChatService` SHALL receive `PersonaContext` and pass it to `build_chat_prompt(query, chunks, persona)` for system message assembly that includes the safety policy and persona layers. The assistant message SHALL be saved with `role=assistant`, `status=complete`, `content`, `model_name`, token counts (`token_count_prompt`, `token_count_completion`), and deduplicated `source_ids` from retrieved chunks. The response SHALL include a runtime-computed `retrieved_chunks_count` field representing the actual number of chunks passed to the LLM. On every response — both the LLM-generated response path (`chat.assistant_completed`) and the code-level refusal path (`chat.refusal_returned`) — `ChatService` SHALL log `config_commit_hash` and `config_content_hash` from the `PersonaContext` via structlog. The old hardcoded `SYSTEM_PROMPT` SHALL be removed and replaced by `SYSTEM_SAFETY_POLICY` plus persona layers.

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

#### Scenario: PersonaContext is injected into prompt assembly

- **WHEN** `ChatService.answer()` assembles the LLM prompt
- **THEN** it SHALL call `build_chat_prompt(query, chunks, persona)` with the `PersonaContext` from `app.state`
- **AND** the system message SHALL contain the safety policy followed by persona layers (identity, soul, behavior) with empty sections skipped

#### Scenario: Config hashes logged on successful LLM response

- **WHEN** the LLM returns a successful response and the assistant message is saved with `status=complete`
- **THEN** structlog SHALL emit a `chat.assistant_completed` event
- **AND** the log entry SHALL include `config_commit_hash` and `config_content_hash` from the `PersonaContext`

#### Scenario: Config hashes logged on code-level refusal

- **WHEN** retrieval returns fewer chunks than `min_retrieved_chunks` and the system returns a refusal without calling the LLM
- **THEN** structlog SHALL emit a `chat.refusal_returned` event
- **AND** the log entry SHALL include `config_commit_hash` and `config_content_hash` from the `PersonaContext`

#### Scenario: Old SYSTEM_PROMPT no longer used

- **WHEN** the chat message flow assembles a prompt
- **THEN** the old hardcoded `SYSTEM_PROMPT` constant SHALL NOT be referenced
- **AND** the system message SHALL be assembled from `SYSTEM_SAFETY_POLICY` plus persona layers via `build_chat_prompt`
