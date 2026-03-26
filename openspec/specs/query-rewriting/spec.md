## Purpose

LLM-based query rewriting for multi-turn conversations: reformulates context-dependent queries into self-contained search queries using conversation history, with fail-open semantics, token budget trimming, and configurable timeout. Introduced by S4-04.



### Requirement: QueryRewriteService.rewrite() method contract

`QueryRewriteService` SHALL provide an async `rewrite()` method that accepts a query string, a list of conversation history messages, and an optional `session_id` (for logging context). The method SHALL return a `RewriteResult` containing the `query` to use for retrieval and an `is_rewritten` boolean indicating whether the query was reformulated. When rewriting succeeds, `query` SHALL contain the LLM-reformulated query and `is_rewritten` SHALL be `True`. When rewriting is skipped or fails, `query` SHALL contain the original input query and `is_rewritten` SHALL be `False`.

#### Scenario: Successful rewrite with conversation history

- **WHEN** `rewrite()` is called with query "Tell me more about the second one" and a non-empty history containing prior user/assistant exchanges
- **THEN** the method SHALL return a `RewriteResult` with the LLM-reformulated query
- **AND** `is_rewritten` SHALL be `True`

#### Scenario: RewriteResult contains original query on skip

- **WHEN** `rewrite()` is called with an empty history list
- **THEN** the method SHALL return a `RewriteResult` with `query` equal to the original input
- **AND** `is_rewritten` SHALL be `False`

#### Scenario: session_id is optional

- **WHEN** `rewrite()` is called without providing `session_id`
- **THEN** the method SHALL execute without error
- **AND** structlog events SHALL omit the `session_id` field

---

### Requirement: Skip condition

The `rewrite()` method SHALL skip the LLM call and return the original query when the conversation history is empty (first message in session) or when `rewrite_enabled` is `False`. The LLM SHALL NOT be called in either case.

#### Scenario: Skip on empty history

- **WHEN** `rewrite()` is called with an empty history list and `rewrite_enabled` is `True`
- **THEN** the method SHALL return the original query with `is_rewritten=False`
- **AND** the LLM SHALL NOT be called

#### Scenario: Skip when rewriting is disabled

- **WHEN** `rewrite()` is called with a non-empty history list and `rewrite_enabled` is `False`
- **THEN** the method SHALL return the original query with `is_rewritten=False`
- **AND** the LLM SHALL NOT be called

---

### Requirement: Fail-open semantics

Any exception during the rewrite LLM call — including timeout, LLM provider errors, empty response, and unexpected errors — SHALL result in the original query being returned with `is_rewritten=False`. Query rewriting SHALL NOT be a point of failure on the chat hot path.

#### Scenario: LLM provider error falls back to original query

- **WHEN** the LLM call raises an exception (e.g., `LLMError`, network error)
- **THEN** the method SHALL return the original query with `is_rewritten=False`
- **AND** the exception SHALL NOT propagate to the caller

#### Scenario: Empty LLM response falls back to original query

- **WHEN** the LLM returns an empty string or whitespace-only response
- **THEN** the method SHALL return the original query with `is_rewritten=False`

#### Scenario: Unexpected exception falls back to original query

- **WHEN** the LLM call raises an unexpected `Exception` subclass
- **THEN** the method SHALL catch it, return the original query with `is_rewritten=False`
- **AND** SHALL log a warning via structlog

---

### Requirement: Timeout enforcement

The LLM call within `rewrite()` SHALL be wrapped in `asyncio.wait_for()` with a timeout of `rewrite_timeout_ms` milliseconds (default 3000). When the timeout fires, the method SHALL return the original query with `is_rewritten=False`.

#### Scenario: LLM call completes within timeout

- **WHEN** the LLM call completes in 500ms and `rewrite_timeout_ms` is 3000
- **THEN** the method SHALL return the rewritten query with `is_rewritten=True`

#### Scenario: LLM call exceeds timeout

- **WHEN** the LLM call takes 5000ms and `rewrite_timeout_ms` is 3000
- **THEN** `asyncio.wait_for` SHALL raise `TimeoutError`
- **AND** the method SHALL return the original query with `is_rewritten=False`

#### Scenario: Custom timeout value respected

- **WHEN** `rewrite_timeout_ms` is configured to 5000
- **THEN** `asyncio.wait_for` SHALL use a timeout of 5.0 seconds (5000 / 1000)

---

### Requirement: Token budget trimming

Conversation history SHALL be trimmed to fit within `rewrite_token_budget` (default 2048 tokens) before being sent to the LLM. Token estimation SHALL use a character-based approximation of `CHARS_PER_TOKEN = 3` (conservative for multilingual safety). Trimming SHALL start from the most recent messages and work backwards, keeping as many recent messages as fit within the budget. The number of messages SHALL also be capped by `rewrite_history_messages` (default 10) — whichever limit is reached first.

#### Scenario: History within budget included in full

- **WHEN** history contains 4 messages totaling 3000 characters (~1000 tokens) and `rewrite_token_budget` is 2048
- **THEN** all 4 messages SHALL be included in the rewrite prompt

#### Scenario: History exceeding budget trimmed to most recent

- **WHEN** history contains 20 messages totaling 30000 characters (~10000 tokens) and `rewrite_token_budget` is 2048
- **THEN** only the most recent messages fitting within the token budget SHALL be included
- **AND** older messages SHALL be dropped

#### Scenario: History capped by message count limit

- **WHEN** history contains 15 messages all within token budget and `rewrite_history_messages` is 10
- **THEN** only the 10 most recent messages SHALL be included

#### Scenario: Trimmed history preserves chronological order

- **WHEN** history is trimmed to the last 5 messages
- **THEN** the messages in the rewrite prompt SHALL appear in chronological order (oldest first of the retained set)

---

### Requirement: History content filtering

The conversation history provided to the rewrite service SHALL include full user and assistant message pairs. Only messages with status RECEIVED (user messages) or COMPLETE (assistant messages) SHALL be included. Messages with status STREAMING, PARTIAL, or FAILED SHALL be excluded from the rewrite context.

#### Scenario: COMPLETE assistant messages included

- **WHEN** a session has a user message (RECEIVED) and an assistant message (COMPLETE)
- **THEN** both messages SHALL appear in the rewrite history

#### Scenario: FAILED assistant messages excluded

- **WHEN** a session has a user message (RECEIVED) and an assistant message (FAILED)
- **THEN** only the user message SHALL appear in the rewrite history
- **AND** the FAILED assistant message SHALL be excluded

#### Scenario: STREAMING messages excluded

- **WHEN** a session has an assistant message with status STREAMING
- **THEN** that message SHALL be excluded from the rewrite history

---

### Requirement: Rewrite prompt structure

The rewrite prompt SHALL consist of a system message instructing the LLM to reformulate the query, followed by a user message containing the trimmed conversation history and the current query. The system message SHALL instruct the LLM to output only the rewritten query with no additional text. The prompt SHALL instruct the LLM to preserve the language of the original query.

#### Scenario: Prompt preserves original language

- **WHEN** the user query is in Russian and history is in Russian
- **THEN** the rewrite prompt SHALL instruct the LLM to preserve the language of the original query
- **AND** the rewritten query SHOULD be in Russian

#### Scenario: Self-contained query returned as-is

- **WHEN** the user query is already self-contained (e.g., "What is machine learning?") with no ambiguous references
- **THEN** the LLM SHOULD return the query unchanged or with minimal reformulation

#### Scenario: Context-dependent query reformulated

- **WHEN** the user query is "Tell me more about the second one" and the history mentions three specific books
- **THEN** the rewritten query SHALL incorporate the specific book name from the history to form a self-contained search query

---

### Requirement: Configuration settings

The `Settings` class SHALL include the following 8 settings for query rewriting:

- `rewrite_enabled` (bool, default `True`) — global toggle for query rewriting
- `rewrite_llm_model` (str or None, default `None`) — LLM model for rewriting; `None` falls back to `llm_model`
- `rewrite_llm_api_key` (str or None, default `None`) — API key for the rewrite model; `None` falls back to `llm_api_key`
- `rewrite_llm_api_base` (str or None, default `None`) — base URL for the rewrite model; `None` falls back to `llm_api_base`
- `rewrite_temperature` (float, default `0.1`) — low temperature for deterministic reformulation
- `rewrite_timeout_ms` (int, default `3000`) — timeout in milliseconds for the rewrite LLM call
- `rewrite_token_budget` (int, default `2048`) — maximum token budget for history in the rewrite prompt
- `rewrite_history_messages` (int, default `10`) — maximum number of history messages to include

`rewrite_timeout_ms` SHALL reject non-positive values. `rewrite_token_budget` SHALL reject non-positive values.

#### Scenario: Default configuration values

- **WHEN** no rewrite environment variables are set
- **THEN** `rewrite_enabled` SHALL be `True`
- **AND** `rewrite_llm_model` SHALL be `None`
- **AND** `rewrite_llm_api_key` SHALL be `None`
- **AND** `rewrite_llm_api_base` SHALL be `None`
- **AND** `rewrite_temperature` SHALL be `0.1`
- **AND** `rewrite_timeout_ms` SHALL be `3000`
- **AND** `rewrite_token_budget` SHALL be `2048`
- **AND** `rewrite_history_messages` SHALL be `10`

#### Scenario: Custom configuration via environment variables

- **WHEN** `REWRITE_ENABLED=false` and `REWRITE_LLM_MODEL=gemini/gemini-2.0-flash` and `REWRITE_TIMEOUT_MS=5000` are set
- **THEN** `rewrite_enabled` SHALL be `False`
- **AND** `rewrite_llm_model` SHALL be `"gemini/gemini-2.0-flash"`
- **AND** `rewrite_timeout_ms` SHALL be `5000`

#### Scenario: Non-positive timeout rejected

- **WHEN** `rewrite_timeout_ms` is set to `0`
- **THEN** the Settings validation SHALL reject the value

---

### Requirement: Observability

`QueryRewriteService` SHALL emit structured log events via structlog. The following events SHALL be emitted:

- `query_rewrite.skip` at DEBUG level with `reason` ("empty_history" or "disabled") and `session_id`
- `query_rewrite.success` at INFO level with `history_messages` (count), `latency_ms`, and `session_id`
- `query_rewrite.timeout` at WARN level with `timeout_ms` and `session_id`
- `query_rewrite.error` at WARN level with `error` (exception class name) and `session_id`

Log events SHALL NOT include raw query text (original or rewritten) to protect user privacy. The rewritten query is persisted in the database for debugging and eval — logs SHALL NOT duplicate it.

#### Scenario: Skip event logged on empty history

- **WHEN** `rewrite()` is called with empty history
- **THEN** structlog SHALL emit a `query_rewrite.skip` event at DEBUG level
- **AND** the event SHALL include `reason="empty_history"` and `session_id`
- **AND** the event SHALL NOT include the query text

#### Scenario: Success event logged with latency

- **WHEN** `rewrite()` completes successfully in 250ms
- **THEN** structlog SHALL emit a `query_rewrite.success` event at INFO level
- **AND** the event SHALL include `latency_ms` (approximately 250) and `history_messages` (count of messages sent to LLM)

#### Scenario: Timeout event logged

- **WHEN** the LLM call times out
- **THEN** structlog SHALL emit a `query_rewrite.timeout` event at WARN level
- **AND** the event SHALL include `timeout_ms` matching the configured `rewrite_timeout_ms`

#### Scenario: Error event logged without query text

- **WHEN** the LLM call raises an exception
- **THEN** structlog SHALL emit a `query_rewrite.error` event at WARN level
- **AND** the event SHALL include `error` (exception class name)
- **AND** the event SHALL NOT include the original or rewritten query text

---

### Requirement: Dedicated LLM instance

When `rewrite_llm_model` is set (non-null), the system SHALL create a separate `LLMService` instance configured with `rewrite_llm_model`, `rewrite_llm_api_key`, and `rewrite_llm_api_base` for the `QueryRewriteService`. When `rewrite_llm_model` is `None`, the `QueryRewriteService` SHALL reuse the main `LLMService` instance.

#### Scenario: Dedicated LLM instance created

- **WHEN** `rewrite_llm_model` is set to `"gemini/gemini-2.0-flash"`
- **THEN** a separate `LLMService` instance SHALL be created with the rewrite model, key, and base URL
- **AND** the `QueryRewriteService` SHALL use this dedicated instance

#### Scenario: Main LLM instance reused

- **WHEN** `rewrite_llm_model` is `None`
- **THEN** the `QueryRewriteService` SHALL use the same `LLMService` instance as the main chat pipeline
- **AND** no additional `LLMService` instance SHALL be created
