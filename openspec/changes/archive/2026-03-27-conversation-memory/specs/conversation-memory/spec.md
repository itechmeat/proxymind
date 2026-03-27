## Purpose

Sliding window + LLM summary conversation memory for multi-turn dialogue sessions. Provides a `ConversationMemoryService` that builds a `MemoryBlock` from session history (recent messages verbatim plus an LLM-generated summary of older messages when the token budget is exceeded), an async arq task for summary generation, session-level summary storage, and configuration parameters. Conversation memory fills layer 6 in the context assembly stack. Introduced by S4-07.

## ADDED Requirements

### Requirement: MemoryBlock dataclass

The system SHALL provide a frozen `MemoryBlock` dataclass with the following fields: `summary_text` (`str | None`), `messages` (`list[dict[str, str]]`), `total_tokens` (`int`), `needs_summary_update` (`bool`), `window_start_message_id` (`UUID | None`). The dataclass SHALL use `frozen=True` and `slots=True` for immutability and performance. `summary_text` SHALL contain the LLM-generated summary of earlier messages or `None` when no summary exists. `messages` SHALL contain user/assistant message dicts in chronological order for the sliding window. `total_tokens` SHALL be the sum of summary tokens plus window message tokens. `needs_summary_update` SHALL be `True` when messages exist between the summary boundary and the window start that are not yet summarized. `window_start_message_id` SHALL be the ID of the first message in the sliding window or `None` when the window is empty.

#### Scenario: MemoryBlock is immutable

- **WHEN** a `MemoryBlock` instance is created
- **THEN** attempting to reassign any field SHALL raise `FrozenInstanceError`

#### Scenario: MemoryBlock fields have correct types

- **WHEN** a `MemoryBlock` is constructed with `summary_text="test"`, `messages=[{"role": "user", "content": "hi"}]`, `total_tokens=5`, `needs_summary_update=False`, `window_start_message_id=UUID(...)`
- **THEN** all fields SHALL be accessible with the provided values

---

### Requirement: ConversationMemoryService.build_memory_block

`ConversationMemoryService` SHALL provide a synchronous `build_memory_block()` method accepting `session` (conforming to a `SessionLike` protocol with `id`, `summary`, `summary_token_count`, `summary_up_to_message_id` attributes) and `messages` (a list conforming to `MessageLike` protocol, excluding the current user turn). The method SHALL perform no I/O -- the caller MUST load session and messages beforehand. The method SHALL split messages into summarized (up to and including `summary_up_to_message_id`) and recent (after the boundary). When `summary_up_to_message_id` is `None` or not found in the messages list, all messages SHALL be treated as recent and any existing summary SHALL be discarded. The method SHALL build a sliding window from the recent messages by iterating from newest to oldest, accumulating messages while total tokens remain within the available window budget. The window SHALL then be reversed to chronological order. When no messages are provided, the method SHALL return an empty `MemoryBlock` with `summary_text=None`, `messages=[]`, `total_tokens=0`, `needs_summary_update=False`, `window_start_message_id=None`.

#### Scenario: Empty session returns empty block

- **WHEN** `build_memory_block()` is called with an empty messages list
- **THEN** the returned `MemoryBlock` SHALL have `summary_text=None`, `messages=[]`, `total_tokens=0`, `needs_summary_update=False`, `window_start_message_id=None`
- **CI test:** deterministic, no I/O

#### Scenario: Short session fits entirely in budget

- **WHEN** `build_memory_block()` is called with 4 messages totaling fewer tokens than `conversation_memory_budget` and no existing summary
- **THEN** the returned `MemoryBlock.messages` SHALL contain all 4 messages in chronological order
- **AND** `needs_summary_update` SHALL be `False`
- **AND** `summary_text` SHALL be `None`
- **CI test:** deterministic, no I/O

#### Scenario: Long session triggers needs_summary_update

- **WHEN** `build_memory_block()` is called with 6 messages that exceed the budget and no existing summary
- **THEN** the returned `MemoryBlock.messages` SHALL contain fewer than 6 messages (the newest that fit in the budget)
- **AND** `needs_summary_update` SHALL be `True` (messages excluded from window are not yet summarized)
- **CI test:** deterministic, no I/O

#### Scenario: Session with existing summary uses summary and recent window

- **WHEN** `build_memory_block()` is called with a session that has `summary="User discussed topics."`, `summary_token_count=10`, and `summary_up_to_message_id` pointing to the 2nd message, and messages after the boundary fit in the remaining budget
- **THEN** `summary_text` SHALL be `"User discussed topics."`
- **AND** `messages` SHALL contain only messages after the boundary
- **AND** `needs_summary_update` SHALL be `False`
- **CI test:** deterministic, no I/O

#### Scenario: Sliding window preserves chronological order

- **WHEN** the window is built from newest to oldest and then reversed
- **THEN** the `messages` list SHALL be in chronological order (oldest first within the window)
- **CI test:** deterministic, no I/O

#### Scenario: window_start_message_id tracks first message in window

- **WHEN** `build_memory_block()` returns a non-empty window
- **THEN** `window_start_message_id` SHALL equal the `id` of the first (oldest) message in the `messages` list
- **CI test:** deterministic, no I/O

---

### Requirement: Token budget management

The `ConversationMemoryService` SHALL be initialized with `budget` (corresponding to `conversation_memory_budget`, default 4096) and `summary_ratio` (corresponding to `conversation_summary_ratio`, default 0.3). The `budget` parameter SHALL control the total maximum tokens for conversation memory (summary + sliding window). When a summary exists, its actual `summary_token_count` SHALL be deducted from the budget at face value to determine the remaining window budget (`budget - summary_token_count`). The `summary_ratio` is a soft target for summary generation length (used by the summary task to set `max_summary_tokens` in the LLM prompt) -- it is NOT a hard partition of the budget. If the actual summary is longer than `budget * summary_ratio`, the window budget shrinks accordingly. The sliding window SHALL be filled from the newest messages backwards until the window budget is exhausted. The total `MemoryBlock.total_tokens` SHALL never exceed `budget` (summary tokens + window tokens).

#### Scenario: Summary takes large share, window shrinks

- **WHEN** `summary_token_count` is 80 and `budget` is 100
- **THEN** the window budget SHALL be 20 tokens
- **AND** only messages fitting within 20 tokens SHALL be included in the window
- **AND** `total_tokens` SHALL not exceed 100
- **CI test:** deterministic, no I/O

#### Scenario: No summary gives full budget to window

- **WHEN** no summary exists (`summary_token_count` is `None` or 0)
- **THEN** the full `budget` SHALL be available for the sliding window
- **CI test:** deterministic, no I/O

#### Scenario: Zero or negative window budget includes no messages

- **WHEN** `summary_token_count` equals or exceeds `budget`
- **THEN** the window budget SHALL be clamped to 0
- **AND** the `messages` list SHALL be empty
- **AND** `summary_text` SHALL still be included
- **CI test:** deterministic, no I/O

---

### Requirement: Async summary generation

The system SHALL provide an arq task `generate_session_summary` that generates an LLM summary of conversation messages. The task SHALL be triggered post-response by `ChatService` when `MemoryBlock.needs_summary_update` is `True`. The task SHALL accept `session_id` (str) and `window_start_message_id` (str) as parameters. The task SHALL load the session and messages between the summary boundary and the window start (exclusive). When an old summary exists, the summarization prompt SHALL include `"Previous summary: {old_summary}"` followed by `"New messages to incorporate:"` and the new messages. When no summary exists, the prompt SHALL contain the messages to summarize directly. The task SHALL call the LLM with `SUMMARIZE_SYSTEM_PROMPT_TEMPLATE` including `max_summary_tokens` (computed as `conversation_memory_budget * conversation_summary_ratio`). Upon success, the task SHALL atomically update the session's `summary`, `summary_token_count`, and `summary_up_to_message_id` fields. On any failure (timeout, LLM error, unexpected exception), the task SHALL log a warning and return without updating the session -- the old summary remains valid. The `needs_summary_update` flag will naturally be `True` again on the next request, providing a retry mechanism. Deduplication SHALL be enforced via arq `job_id = f"summary:{session_id}"` to ensure at most one summary task per session at a time.

#### Scenario: Summary generated and saved

- **WHEN** `generate_session_summary` is called for a session with unsummarized messages between the boundary and window start
- **THEN** the LLM SHALL be called with the summarization prompt
- **AND** the session's `summary` SHALL be updated with the LLM response
- **AND** `summary_token_count` SHALL be updated with the token estimate of the new summary
- **AND** `summary_up_to_message_id` SHALL be updated to the last summarized message's ID
- **CI test:** mock LLM, verify DB writes

#### Scenario: Incremental summary incorporates old summary

- **WHEN** `generate_session_summary` is called for a session that already has a summary
- **THEN** the summarization prompt SHALL include `"Previous summary: {old_summary}"` and the new messages
- **CI test:** mock LLM, verify prompt content

#### Scenario: No messages to summarize skips LLM call

- **WHEN** `generate_session_summary` is called but no messages exist between the boundary and window start
- **THEN** the LLM SHALL NOT be called
- **AND** the session SHALL NOT be updated
- **CI test:** mock LLM, verify not called

#### Scenario: LLM failure preserves old summary

- **WHEN** the LLM call fails with a timeout or exception during summary generation
- **THEN** the session's `summary`, `summary_token_count`, and `summary_up_to_message_id` SHALL remain unchanged
- **AND** a warning SHALL be logged
- **CI test:** mock LLM to raise, verify no DB update

#### Scenario: Timeout enforced on LLM call

- **WHEN** `conversation_summary_timeout_ms` is 10000
- **THEN** the LLM call SHALL be wrapped in `asyncio.wait_for()` with a timeout of 10.0 seconds
- **CI test:** mock LLM with delay, verify TimeoutError handling

#### Scenario: Deduplication via arq job_id

- **WHEN** `ChatService` enqueues a summary task for session X
- **THEN** the arq `job_id` SHALL be `"summary:{session_id}"` to prevent duplicate concurrent tasks for the same session
- **CI test:** verify job_id format in enqueue call

---

### Requirement: Session summary fields

The `sessions` table SHALL have 3 new nullable columns: `summary` (`Text`, nullable), `summary_token_count` (`Integer`, nullable), and `summary_up_to_message_id` (`UUID`, nullable, foreign key to `messages.id` with `ondelete=SET NULL`). These fields SHALL be added via an Alembic migration. All three fields SHALL be updated atomically by the summary generation task. `summary` stores the LLM-generated summary text. `summary_token_count` stores the estimated token count of the summary for fast budget calculation without re-counting. `summary_up_to_message_id` tracks the last message included in the summary, serving as the boundary between summarized and recent messages. The corresponding SQLAlchemy `Session` model SHALL be updated with matching mapped columns.

#### Scenario: New columns exist after migration

- **WHEN** the Alembic migration is applied
- **THEN** the `sessions` table SHALL have `summary`, `summary_token_count`, and `summary_up_to_message_id` columns
- **AND** all three SHALL be nullable
- **CI test:** run migration in Docker, verify column existence

#### Scenario: Foreign key constraint on summary_up_to_message_id

- **WHEN** `summary_up_to_message_id` references a message that is deleted
- **THEN** the foreign key `ondelete=SET NULL` SHALL set `summary_up_to_message_id` to `NULL`
- **CI test:** verify FK constraint behavior in Docker

#### Scenario: Existing sessions unaffected

- **WHEN** the migration is applied to a database with existing sessions
- **THEN** all existing sessions SHALL have `summary=NULL`, `summary_token_count=NULL`, `summary_up_to_message_id=NULL`
- **CI test:** verify existing data preserved after migration in Docker

---

### Requirement: Configuration parameters

The `Settings` class SHALL include 5 new configuration parameters for conversation memory:

- `conversation_memory_budget` (`int`, default `4096`, `ge=1`) -- maximum tokens for conversation memory (summary + sliding window) in the prompt
- `conversation_summary_ratio` (`float`, default `0.3`, `ge=0.0`, `le=1.0`) -- soft target for summary generation length as a fraction of `conversation_memory_budget`, used to compute `max_summary_tokens` in the summarization prompt
- `conversation_summary_model` (`str | None`, default `None`) -- model for conversation summarization; when `None`, falls back to `llm_model`
- `conversation_summary_temperature` (`float`, default `0.1`, `ge=0.0`, `le=2.0`) -- temperature for summarization LLM calls
- `conversation_summary_timeout_ms` (`int`, default `10000`, `ge=1`) -- timeout in milliseconds for the summary LLM call in the arq task

`conversation_summary_model` SHALL be included in the `normalize_empty_optional_strings` validator to normalize empty strings to `None`.

#### Scenario: Default configuration values

- **WHEN** no conversation memory environment variables are set
- **THEN** `conversation_memory_budget` SHALL be `4096`
- **AND** `conversation_summary_ratio` SHALL be `0.3`
- **AND** `conversation_summary_model` SHALL be `None`
- **AND** `conversation_summary_temperature` SHALL be `0.1`
- **AND** `conversation_summary_timeout_ms` SHALL be `10000`
- **CI test:** deterministic, verify defaults

#### Scenario: Custom configuration via environment variables

- **WHEN** `CONVERSATION_MEMORY_BUDGET=8192` and `CONVERSATION_SUMMARY_MODEL=gemini/gemini-2.0-flash` are set
- **THEN** `conversation_memory_budget` SHALL be `8192`
- **AND** `conversation_summary_model` SHALL be `"gemini/gemini-2.0-flash"`
- **CI test:** deterministic, verify env override

#### Scenario: Budget validation rejects non-positive values

- **WHEN** `conversation_memory_budget` is set to `0`
- **THEN** the Settings validation SHALL reject the value
- **CI test:** deterministic, verify validation error

#### Scenario: Summary ratio validation enforces bounds

- **WHEN** `conversation_summary_ratio` is set to `1.5`
- **THEN** the Settings validation SHALL reject the value (exceeds `le=1.0`)
- **CI test:** deterministic, verify validation error

---

### Requirement: Retrieval refusal independence

Conversation memory SHALL NOT bypass the `min_retrieved_chunks` refusal policy. The `ChatService` refusal check (`min_retrieved_chunks`) SHALL continue to execute before `ContextAssembler` is invoked, regardless of whether conversation memory is available. Conversation memory provides conversational context to the LLM after retrieval succeeds -- it does not substitute for retrieval. Query rewriting (S4-04) is the mechanism that makes follow-up queries retrievable by reformulating them into self-contained queries. If an installation wants to allow responses without retrieval context (e.g., for pure chat scenarios), it can set `min_retrieved_chunks=0`.

#### Scenario: Refusal still triggered with conversation memory present

- **WHEN** a session has 10 prior messages (conversation memory available) but retrieval returns 0 chunks and `min_retrieved_chunks=1`
- **THEN** the system SHALL return a refusal without calling the LLM
- **AND** conversation memory SHALL NOT be used to bypass the refusal
- **CI test:** mock retrieval to return 0 chunks, verify refusal

#### Scenario: Memory used after retrieval succeeds

- **WHEN** retrieval returns sufficient chunks and conversation memory is available
- **THEN** the memory block SHALL be passed to `ContextAssembler.assemble()` alongside retrieval chunks
- **AND** the LLM SHALL receive both retrieval context and conversation history
- **CI test:** verify assemble() called with memory_block

---

## Stable Behavior for Test Coverage

The following stable behavior MUST be covered by tests before this change is archived:

1. **MemoryBlock construction** -- empty session, short session, long session, existing summary (CI unit tests)
2. **Token budget enforcement** -- window respects budget, summary deducted at face value (CI unit tests)
3. **needs_summary_update flag** -- correctly set when messages fall between boundary and window (CI unit tests)
4. **Sliding window order** -- messages in chronological order after reversal (CI unit tests)
5. **Summary generation task** -- LLM called with correct prompt, session updated atomically, failure preserves old summary (CI unit tests with mocked LLM)
6. **Deduplication** -- arq job_id format for summary tasks (CI unit tests)
7. **Configuration defaults and validation** -- all 5 parameters (CI unit tests)
