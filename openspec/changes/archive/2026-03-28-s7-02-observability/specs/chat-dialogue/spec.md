## MODIFIED Requirements

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
- **AND** `_log_audit()` SHALL be called with `latency_ms=0` (unknown at disconnect time)
- **AND** `latency_ms=0` SHALL be treated as a sentinel for "latency unknown because the stream terminated before a measurable completion point"
- **AND** `retrieved_chunks_count` SHALL be derived from `len(message.source_ids or [])`

#### Scenario: Audit logged on failed timeout

- **WHEN** `save_failed_on_timeout()` saves a message with `status=failed`
- **THEN** the method SHALL load the chat session from DB via `self._session.get(Session, message.session_id)`
- **AND** `_log_audit()` SHALL be called with `latency_ms=0`

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
- **THEN** `CHAT_RESPONSE_LATENCY_SECONDS.observe(0.0)` SHALL be called (latency unknown at disconnect time)
- **AND** the observation SHALL happen at the same code point where `CHAT_RESPONSES_TOTAL.labels(status="partial").inc()` is called

#### Scenario: \_log_audit suppresses audit persistence failures

- **WHEN** `AuditService.log_response()` raises inside `_log_audit()`
- **THEN** `_log_audit()` SHALL catch the exception, log it with response context, and suppress propagation so response delivery is not affected

---

## Test Coverage

### CI tests (deterministic)

- **ChatService constructor test**: verify `ChatService` accepts `audit_service` parameter and stores it as `_audit_service`.
- **\_log_audit delegation test**: mock `AuditService`, construct `ChatService` with it, call `_log_audit()`, verify `log_response()` is called with correct field mapping.
- **\_log_audit no-op test**: construct `ChatService` with `audit_service=None`, call `_log_audit()`, verify no error.
- **\_log_audit exception isolation test**: mock `AuditService.log_response()` to raise, verify `_log_audit()` catches exception and logs error.
- **CHAT_RESPONSES_TOTAL increment test**: verify counter is incremented with correct status label after message finalization.
- **Existing ChatService tests pass**: verify all pre-existing `test_chat_service.py` and `test_chat_streaming.py` tests pass with an injected AuditService test double.
