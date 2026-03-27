## Story

**S4-07: Conversation memory**
Dialog history + summary for long conversations. Trimming when token budget exceeded. Session management.

**Verification criteria:**
- 20+ messages in a session preserve context
- Summary generated when token limit reached
- Stable behavior to cover with tests before archive:
  - ConversationMemoryService: empty session, short session, long session with summary, budget enforcement, chronological ordering
  - ContextAssembler: backward compat (memory_block=None), multi-turn format, summary layer placement, unified token accounting, summary-only edge case
  - Summary arq task: generation and persistence, skip when no messages, LLM timeout/error handling, dedup guard, incremental summary with old summary, max_summary_tokens from config
  - ChatService: memory integration in answer/stream flows, summary enqueue when needed, enqueue skipped when not needed, enqueue failure does not fail response, backward compat without memory service, refusal path does not enqueue summary
  - Configuration: defaults, validation ranges, empty string normalization

## Why

The LLM currently sees only persona + retrieval context + the current query. In multi-turn conversations, it has no memory of what was discussed earlier in the session. This means the twin cannot maintain coherent long conversations, reference prior answers, or build on earlier context. Query rewriting (S4-04) reformulates queries for retrieval, but the LLM itself remains stateless across turns. Conversation memory fills layer 6 in the context assembly stack, enabling context-aware responses in long dialogues.

## What Changes

- Add a `ConversationMemoryService` that builds a memory block from session history: recent messages verbatim (sliding window) + LLM-generated summary of older messages when token budget is exceeded
- Refactor `ContextAssembler` from 2-message output (system + user) to N-message multi-turn format (system + history pairs + user), with conversation summary injected into the system prompt
- Add async summary generation via arq task (`generate_session_summary`), triggered post-response when the memory budget is exceeded
- Extend `sessions` table with 3 new fields: `summary`, `summary_token_count`, `summary_up_to_message_id`
- Add 5 new configuration parameters for conversation memory budgets and summary behavior
- Integrate memory into both `ChatService.answer()` and `ChatService.stream_answer()` flows

## Capabilities

### New Capabilities
- `conversation-memory`: Sliding window + LLM summary conversation memory service, including memory block assembly, token budget management, and async summary generation

### Modified Capabilities
- `context-assembly`: Refactor from 2-message to multi-turn prompt format; add conversation summary layer (layer 6) and memory block integration; unified token accounting under `conversation_memory` key
- `chat-dialogue`: Integrate conversation memory service into answer/stream_answer flows; add summary enqueue after response completion; wire new dependencies

## Impact

- **Backend services:** New `conversation_memory.py`, modified `context_assembler.py`, `chat.py`, `dependencies.py`, `main.py`
- **Worker:** New `summarize.py` task, modified `workers/main.py` and `tasks/__init__.py` (adds LLM service to worker context)
- **Database:** Alembic migration 010 adding 3 nullable columns to `sessions`
- **Configuration:** 5 new settings in `config.py` + `docs/spec.md` Implementation defaults table
- **API contract:** No external API changes. Internal prompt format changes from 2 messages to N messages (transparent to callers)
- **Dependencies:** No new packages. Uses existing LiteLLM, arq, SQLAlchemy
