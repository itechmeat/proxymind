## 1. Database & Configuration

- [x] 1.1 Create Alembic migration 010: add summary, summary_token_count, summary_up_to_message_id nullable columns to sessions table
- [x] 1.2 Update Session SQLAlchemy model in dialogue.py with 3 new mapped columns
- [x] 1.3 Add 5 conversation memory settings to config.py (conversation_memory_budget, conversation_summary_ratio, conversation_summary_model, conversation_summary_temperature, conversation_summary_timeout_ms)
- [x] 1.4 Add conversation_summary_model to normalize_empty_optional_strings validator
- [x] 1.5 Update docs/spec.md Implementation defaults table with 5 new parameters
- [x] 1.6 Write unit tests for config defaults and validation (budget >= 1, ratio 0.0-1.0, temperature 0.0-2.0, timeout >= 1, empty string normalization for summary model)

## 2. ConversationMemoryService

- [x] 2.1 Create MemoryBlock dataclass and ConversationMemoryService in backend/app/services/conversation_memory.py
- [x] 2.2 Write unit tests for build_memory_block: empty session, short session fits in budget, long session triggers needs_summary, session with existing summary, summary budget deducted at face value, chronological order preserved, boundary message not found falls back to all messages
- [x] 2.3 Run tests and verify all pass

## 3. ContextAssembler Multi-turn + Memory Layer

- [x] 3.1 Add conversation_summary layer between promotions and citation_instructions in ContextAssembler
- [x] 3.2 Add memory_block optional parameter to assemble() method
- [x] 3.3 Implement multi-turn message output: system + history pairs + user
- [x] 3.4 Implement unified conversation_memory token accounting (pop conversation_summary, use memory_block.total_tokens)
- [x] 3.5 Write unit tests: backward compat (memory_block=None produces 2 messages), multi-turn format correct roles and order, summary in system prompt with XML tags, layer ordering (summary before citation_instructions), token counts unified under conversation_memory key, summary-only-no-history edge case tracked correctly, conversation_summary tag absent when no summary, assemble() signature backward compatible
- [x] 3.6 Run all context assembler tests (old + new) and verify pass

## 4. Summary Generation arq Task

- [x] 4.1 Create generate_session_summary task in backend/app/workers/tasks/summarize.py with SUMMARIZE_SYSTEM_PROMPT_TEMPLATE using max_summary_tokens computed from budget * ratio
- [x] 4.2 Register task in workers/tasks/__init__.py
- [x] 4.3 Add summary_llm_service creation in workers/main.py on_startup and register task in WorkerSettings.functions
- [x] 4.4 Write unit tests: summary generated and saved correctly, summary skipped when no messages to summarize, LLM timeout handled gracefully (old summary preserved), LLM error handled gracefully (logged, no update), dedup guard skips when summary_up_to_message_id already updated, incremental summary includes old summary in prompt, max_summary_tokens correctly computed from config
- [x] 4.5 Run tests and verify pass

## 5. ChatService Integration

- [x] 5.1 Add ConversationMemoryService and SummaryEnqueuer to ChatService constructor (optional, backward compat)
- [x] 5.2 Add _build_memory helper and _maybe_enqueue_summary helper methods
- [x] 5.3 Integrate memory into answer() flow: load history, build memory block, pass to assemble(), enqueue summary
- [x] 5.4 Integrate memory into stream_answer() flow: same pattern, enqueue after streaming done
- [x] 5.5 Write unit tests: memory service called during answer, memory_block passed to assemble(), summary enqueued when needs_summary_update is True, summary NOT enqueued when needs_summary_update is False, enqueue failure logged but does not fail the response, backward compat without memory service (conversation_memory_service=None works), constructor accepts new optional params without breaking existing callers, refusal path does not enqueue summary
- [x] 5.6 Run all chat service tests (old + new) and verify pass

## 6. Dependency Injection Wiring

- [x] 6.1 Add get_conversation_memory_service to dependencies.py
- [x] 6.2 Add summary enqueue function with arq job_id=f"summary:{session_id}" deduplication
- [x] 6.3 Update get_chat_service to pass conversation_memory_service and summary_enqueuer
- [x] 6.4 Create ConversationMemoryService in main.py lifespan

## 7. Test Fixtures & Integration Tests

- [x] 7.1 Add mock_memory_service fixture to conftest.py and update chat_app fixtures
- [x] 7.2 Write integration test: memory block from real session with DB messages
- [x] 7.3 Write integration test: summary persisted and used in next build_memory_block
- [x] 7.4 Run full test suite and verify no regressions

## 8. Final Verification

- [x] 8.1 Run linters (ruff check, ruff format)
- [x] 8.2 Verify migration applies on fresh database (docker compose down -v, up, alembic upgrade head)
- [x] 8.3 Run full test suite one final time
