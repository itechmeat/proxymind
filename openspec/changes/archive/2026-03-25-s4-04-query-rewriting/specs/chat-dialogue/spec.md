## Purpose

Delta spec for S4-04 Query Rewriting: inserts query rewrite step into the message send flow, adds `rewritten_query` column to the messages table, adds conversation history loading, and extends `ChatService` constructor with `QueryRewriteService` dependency.

## CHANGED Requirements

### Requirement: Message send via POST /api/chat/messages

The message send flow SHALL insert a query rewrite step between user message persistence and retrieval. After the user message is persisted with `status=received`, the system SHALL load conversation history for the session, then call `QueryRewriteService.rewrite()` with the user's query text and the loaded history. The retrieval step SHALL use the rewritten query (or the original query if rewriting was skipped or failed). The main LLM prompt assembly SHALL use the original user query text — not the rewritten query. When rewriting produces a different query, the `rewritten_query` column on the user message SHALL be updated with the rewritten text.

#### Scenario: Rewritten query used for retrieval, original for prompt

- **WHEN** a user sends "Tell me more about the second one" in a session with prior history
- **AND** query rewriting reformulates the query to "Tell me more about Sergey's book Deep Learning in Practice"
- **THEN** the retrieval step SHALL search using "Tell me more about Sergey's book Deep Learning in Practice"
- **AND** the main LLM prompt SHALL contain the original query "Tell me more about the second one"

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

The `ChatService` constructor SHALL accept a `query_rewrite_service` parameter of type `QueryRewriteService`. This dependency SHALL be injected via the existing dependency injection mechanism in `api/dependencies.py`. The `QueryRewriteService` SHALL be initialized during application lifespan startup.

#### Scenario: ChatService requires QueryRewriteService

- **WHEN** `ChatService` is instantiated
- **THEN** it SHALL require a `query_rewrite_service` parameter
- **AND** SHALL store it for use during message processing

#### Scenario: QueryRewriteService wired via dependency injection

- **WHEN** the `get_chat_service()` dependency is resolved
- **THEN** it SHALL provide a `QueryRewriteService` instance to the `ChatService` constructor

---

## ADDED Requirements

### Requirement: rewritten_query column on messages table

The `messages` table SHALL have a `rewritten_query` column of type nullable TEXT. This column SHALL be populated only for user messages (`role=user`) when query rewriting occurs and produces a different query. The column SHALL be `NULL` when: the message is the first in a session (no history), rewriting is disabled, rewriting fails or times out, or the message is an assistant message. An Alembic migration SHALL add this column.

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

The `ChatService` SHALL provide a `_load_history()` method (or equivalent) that loads session messages for the rewrite context. The method SHALL load all messages in the session excluding the current user message, ordered by `created_at` ascending. Only messages with status RECEIVED (user messages) or COMPLETE (assistant messages) SHALL be included. Messages with status STREAMING, PARTIAL, or FAILED SHALL be excluded.

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
