# S4-07: Conversation Memory — Design

## Overview

Add conversation memory to the dialogue circuit so the digital twin retains context across long conversations. The LLM currently sees only persona + retrieval + the current query. This story fills **layer 6 (Conversation memory)** in the context assembly stack: recent messages verbatim plus an LLM-generated summary of older messages when the token budget is exceeded.

**Important scope boundary:** Conversation memory provides conversational context to the LLM *after* retrieval succeeds. It does not bypass the retrieval requirement. The existing `min_retrieved_chunks` refusal policy remains unchanged — if retrieval returns fewer chunks than the threshold, the twin still refuses rather than answering from conversation history alone. This is deliberate: the twin must ground its answers in the knowledge base, not in prior conversation turns. Query rewriting (S4-04) is the mechanism that makes follow-up queries like "tell me more" retrievable by reformulating them into self-contained queries. If an installation wants to allow responses without retrieval context (e.g., for pure chat scenarios), it can set `min_retrieved_chunks=0`.

## Decisions Log

| # | Question | Decision | Rationale |
|---|----------|----------|-----------|
| 1 | Memory strategy | Sliding window + LLM summary | Matches canonical docs ("recent messages + brief summary"). Balances complexity and quality. Summary is lazy — zero overhead for short sessions. Pure sliding window loses early context; hierarchical summary is overengineering at this stage. |
| 2 | Summary trigger | Token-budget based | No wasted LLM calls while history fits in budget. ~80% of sessions are short — zero overhead. Consistent with existing budget patterns (retrieval, rewrite). Count-based triggers may fire too early or too late. |
| 3 | Summary storage | 3 fields in `sessions` table | Summary is working state of a session, not a business entity. `summary_up_to_message_id` tracks which messages are already summarized. Separate table would be overengineering — old summary is not needed after update. |
| 4 | Summary in prompt | Part of system message (layer 6) | Fits current `ContextAssembler` architecture where all layers are in the system message. No need to change message format for summary specifically. |
| 5 | Summary model | Separate `conversation_summary_model`, defaults to `llm_model` | Flexibility to use a cheaper model. Works out of the box without extra config. Summary is a simple task that does not require a powerful model. |
| 6 | Fail-safe strategy | Async generation (C) + fallback to old summary (B) | Async via arq task removes LLM call from hot path entirely. Old summary as fallback guarantees graceful degradation. If no summary exists yet — pure sliding window. Consistent with fail-open pattern in query rewriting. |
| 7 | History format in prompt | Native multi-turn messages | All modern LLMs are optimized for multi-turn format. LiteLLM already supports message arrays. Current `AssembledPrompt.messages` is `list[dict]` — ready for extension. Serializing history as text in system prompt loses native format advantages. |
| 8 | Assistant message truncation | Full messages, no truncation | Budget is controlled by number of pairs fitting in the window. Truncation loses context that may be important for digital twin conversations. Simpler implementation. |
| 9 | Interaction with query rewriting | Independent flows | Different budgets, different tasks. Current rewriting is tested and stable — no changes needed. One extra SELECT is not critical. Less coupling between services. |
| 10 | Summary timing | Post-response async (arq task) | Zero added latency on hot path. arq infrastructure already exists. Summary is ready by next user message. Fallback covers the gap if it is not. |

## Architecture

### Approach: Inline Memory Layer

Conversation memory is implemented as a new service (`ConversationMemoryService`) integrated into the existing `ContextAssembler`. Summary is generated asynchronously via an arq task. This is the minimal approach that fits the current architecture without introducing unnecessary abstractions.

### Data Flow

```
User sends message
    |
    v
ChatService.stream_answer()
    |
    +--> QueryRewriteService.rewrite()          (unchanged)
    +--> RetrievalService.search()              (unchanged)
    +--> ConversationMemoryService.build_memory_block()   [NEW]
    +--> ContextAssembler.assemble(..., memory_block)     [MODIFIED]
    +--> LLMService.stream()                    (unchanged)
    +--> Persist assistant message               (unchanged)
    +--> if needs_summary_update:               [NEW]
            enqueue arq task generate_session_summary
```

## Data Model

### Sessions table extension (Alembic migration)

Three new nullable columns:

| Column | Type | Description |
|--------|------|-------------|
| `summary` | `Text \| NULL` | LLM-generated summary of earlier messages |
| `summary_token_count` | `Integer \| NULL` | Token count of summary (for fast budget calculation) |
| `summary_up_to_message_id` | `UUID FK -> messages.id \| NULL` | Last message included in the summary |

All fields are updated atomically when a new summary is generated.

## ConversationMemoryService

**File:** `backend/app/services/conversation_memory.py`

**Primary method:**

```python
def build_memory_block(session: SessionLike, messages: list[MessageLike]) -> MemoryBlock
```

The method is **synchronous** — it performs no I/O. The caller (`ChatService`) is responsible for loading the session and message history from the database before calling this method. The `messages` list must **exclude the current user message** to avoid duplication (the current query is appended separately by `ContextAssembler` as the final user message). `ChatService` already has `_load_history(session_id, exclude_message_id)` which provides exactly this filtered list.

**Algorithm:**

1. Read from `session` object: `summary`, `summary_token_count`, `summary_up_to_message_id`
2. The `messages` parameter contains session messages (status `RECEIVED` or `COMPLETE`, excluding current turn), ordered by `created_at`
3. Split messages into:
   - **summarized:** up to and including `summary_up_to_message_id` (already in summary)
   - **recent:** after `summary_up_to_message_id` (candidates for sliding window)
4. If `summary is NULL` then `recent = all messages`
5. Build sliding window from recent (newest first, to guarantee most recent messages are always included):
   - Available budget = `conversation_memory_budget` - `summary_token_count` (or full budget if no summary)
   - Iterate from the newest message toward the oldest, accumulate user/assistant pairs while total tokens remain within budget
   - Once budget is exhausted, stop — older messages are excluded from the window
   - Reverse the collected pairs back to chronological order for the prompt
6. Return `MemoryBlock`:
   - `summary_text`: the summary or `None`
   - `messages`: list of `{role, content}` dicts (multi-turn pairs)
   - `total_tokens`: tokens consumed by summary + window
   - `needs_summary_update`: `True` if messages exist between summary boundary and window start
   - `window_start_message_id`: ID of the first message in the window

### MemoryBlock dataclass

```python
@dataclass
class MemoryBlock:
    summary_text: str | None
    messages: list[dict[str, str]]
    total_tokens: int
    needs_summary_update: bool
    window_start_message_id: UUID | None
```

## Summary Generation (arq task)

**Task:** `generate_session_summary`

**Trigger:** enqueued by `ChatService` after streaming completes, when `memory_block.needs_summary_update is True`.

**Algorithm:**

1. Load session (`summary`, `summary_up_to_message_id`)
2. Load messages to summarize: from the beginning of the session (or messages with `created_at` after the `summary_up_to_message_id` boundary message) up to `window_start_message_id` (exclusive, by `created_at`)
3. Build summarization prompt:
   - If old summary exists: "Previous summary: {old_summary}\n\nNew messages to incorporate: ..."
   - If no summary: "Summarize this conversation: ..."
4. Call LLM (`conversation_summary_model`, `conversation_summary_temperature`)
5. Atomically update `sessions`: `summary`, `summary_token_count`, `summary_up_to_message_id`

**Summarization prompt:**

```
Summarize the following conversation between a user and an AI assistant.
Preserve: key topics discussed, user's questions and intent, important facts mentioned,
any decisions or conclusions reached.
Keep summary under {max_summary_tokens} tokens.
Be concise but complete. Write in the same language as the conversation.
```

**Fail-safe:**
- Timeout: `conversation_summary_timeout_ms` (default 10000ms)
- On failure: log error, do not update summary. Old summary remains valid.
- Natural retry: `needs_summary_update` will be `True` again on next request
- Deduplication: arq `job_id = f"summary:{session_id}"` — one task per session at a time. Before generating, verify `summary_up_to_message_id` has not been updated by another task.

## ContextAssembler Changes

### New prompt format (multi-turn)

```
messages = [
    {"role": "system", "content": "<system prompt with all layers>"},
    {"role": "user", "content": "<message from history>"},
    {"role": "assistant", "content": "<response from history>"},
    ... more history pairs ...
    {"role": "user", "content": "<current query>"}
]
```

### Prompt layer placement

**System message** (assembled from layers in this order):

```
1. System safety policy          (unchanged)
2. IDENTITY.md                   (unchanged)
3. SOUL.md                       (unchanged)
4. BEHAVIOR.md                   (unchanged)
5. PROMOTIONS.md (active only)   (unchanged)
6. Conversation summary          [NEW — "Earlier in this conversation: {summary}"]
7. Citation instructions         (unchanged)
8. Content type guidelines       (unchanged)
```

**Multi-turn history** (between system message and final user message):

```
[user] historical message
[assistant] historical response
... more pairs ...
```

**Final user message** (contains retrieval context + current query):

```
9. Retrieval context (chunks)    (unchanged — lives in user message, NOT system prompt)
10. Current user query           (unchanged)
```

Note: retrieval context is placed in the user message (wrapped in `<knowledge_context>` tags), not in the system prompt. This matches the existing `ContextAssembler` implementation and is unchanged by this story.

### Method signature change

```python
def assemble(
    self,
    chunks: list[RetrievedChunk],
    query: str,
    source_map: dict[UUID, Source],
    memory_block: MemoryBlock | None = None,  # NEW
) -> AssembledPrompt
```

### Token accounting

- When `memory_block` is not `None`, a single key `"conversation_memory"` is added to `layer_token_counts` with value `memory_block.total_tokens` (sum of summary + history message tokens). The `conversation_summary` layer is still added to the system prompt for content, but its tokens are tracked under `conversation_memory` to avoid double-counting.
- `token_estimate` includes all message pairs
- Backward compatible: `memory_block=None` produces identical output to current behavior

## ChatService Integration

### Updated flow in `stream_answer()`

```
1. Load session, check idempotency                       (unchanged)
2. Persist user message                                   (unchanged)
3. Query rewrite                                          (unchanged)
4. Retrieval search                                       (unchanged)
5. Build memory block (ConversationMemoryService)         [NEW]
6. Context assembly (persona + memory + retrieval)        [MODIFIED]
7. Stream LLM response                                    (unchanged)
8. Persist assistant message                              (unchanged)
9. Check needs_summary_update -> enqueue arq task         [NEW]
```

`ConversationMemoryService` is added to `dependencies.py` following the same pattern as `QueryRewriteService` and `PromotionsService`.

## Configuration

New parameters in `backend/app/core/config.py` and `docs/spec.md` (Implementation defaults table):

| Parameter | Default | Description |
|-----------|---------|-------------|
| `conversation_memory_budget` | 4096 tokens | Max tokens for conversation memory (summary + sliding window) in prompt |
| `conversation_summary_ratio` | 0.3 | Soft target for summary generation length as a fraction of `conversation_memory_budget`. Used to set `max_summary_tokens` in the summarization prompt. Not a hard partition — actual summary tokens are deducted from budget at face value, and the window shrinks accordingly |
| `conversation_summary_model` | `None` (falls back to `llm_model`) | Model for summarization. If unset, uses the main model |
| `conversation_summary_temperature` | 0.1 | Temperature for summarization LLM calls |
| `conversation_summary_timeout_ms` | 10000 | Timeout for summary LLM call in arq task |

## Error Handling & Edge Cases

**First message in session:** `memory_block.messages = []`, `summary = None`. `ContextAssembler` produces output identical to current behavior.

**Rapid sequential messages (race condition):** arq deduplication via `job_id = f"summary:{session_id}"` ensures one task per session. Task verifies `summary_up_to_message_id` before writing to prevent stale overwrites.

**Session without active snapshot:** Conversation memory is independent of snapshots — loads history regardless. `NoActiveSnapshotError` is raised before retrieval, memory is not affected.

**Very long sessions (100+ messages):** Summary accumulates incrementally: "old summary + new messages -> new summary". The summarization prompt requests the LLM to keep the summary under `conversation_memory_budget * conversation_summary_ratio` tokens (~1228 at defaults), but this is a soft target — the LLM may produce a slightly longer summary. The actual `summary_token_count` is deducted from the budget at face value, shrinking the sliding window accordingly. This ensures the total memory block never exceeds `conversation_memory_budget`.

## Testing Strategy

### Unit tests (CI, deterministic)

- `ConversationMemoryService.build_memory_block()`:
  - Empty session (first message)
  - Short session (all messages fit in budget, no summary needed)
  - Long session (summary exists, sliding window built correctly)
  - Budget edge case (messages fit exactly)
  - `needs_summary_update` flag correctness
- `ContextAssembler` with `memory_block`:
  - Multi-turn message format is correct
  - Layer order in system prompt
  - Backward compatibility (`memory_block=None`)
  - Token accounting includes memory
- Token budget enforcement: window does not exceed budget

### Integration tests (CI, in Docker)

- arq task `generate_session_summary`: mock LLM, verify write to sessions
- Full flow: create session -> 20+ messages -> verify summary is generated and used in next response
- arq task deduplication under rapid messages

### Evals (separate, Phase 8)

- Summary quality: are key facts preserved?
- Impact of conversation memory on answer quality in long dialogues
- Optimal `conversation_memory_budget` value

## Scope

### In scope

- `ConversationMemoryService` + `MemoryBlock` dataclass
- `sessions` table extension (3 fields, Alembic migration)
- `ContextAssembler` refactor for multi-turn + memory layer
- arq task `generate_session_summary`
- `ChatService` integration (steps 5 and 9)
- Configuration (5 new parameters in config + spec.md)
- Unit + integration tests

### Out of scope

- Cross-session persistent memory
- User preferences / facts extraction
- Semantic memory (embedding conversation history)
- Frontend changes (S4-07 is purely backend)
- Changes to query rewriting (remains independent)
