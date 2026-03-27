# S4-07: Conversation Memory — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add conversation memory to the dialogue circuit so the digital twin retains context across long conversations via sliding window + LLM-generated summary.

**Architecture:** New `ConversationMemoryService` builds a `MemoryBlock` (summary + recent messages) that `ContextAssembler` injects into the prompt as multi-turn messages. Summary is generated asynchronously via arq task after response streaming completes. Fallback to old summary or pure sliding window if async summary is not yet ready.

**Tech Stack:** Python, FastAPI, SQLAlchemy, Alembic, arq, LiteLLM, structlog, pytest

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `backend/app/services/conversation_memory.py` | `MemoryBlock` dataclass + `ConversationMemoryService` |
| Create | `backend/app/workers/tasks/summarize.py` | arq task `generate_session_summary` |
| Create | `backend/migrations/versions/010_add_session_summary_fields.py` | Alembic migration: 3 new columns on `sessions` |
| Create | `backend/tests/unit/test_conversation_memory.py` | Unit tests for `ConversationMemoryService` |
| Create | `backend/tests/unit/test_summary_task.py` | Unit tests for summary arq task |
| Modify | `backend/app/db/models/dialogue.py` | Add `summary`, `summary_token_count`, `summary_up_to_message_id` to `Session` |
| Modify | `backend/app/core/config.py` | Add 5 new settings |
| Modify | `backend/app/services/context_assembler.py` | Accept `MemoryBlock`, build multi-turn messages |
| Modify | `backend/app/services/chat.py` | Integrate memory into `answer()` and `stream_answer()` |
| Modify | `backend/app/api/dependencies.py` | Wire `ConversationMemoryService` + arq enqueue |
| Modify | `backend/app/workers/main.py` | Register `generate_session_summary` task + add LLM service to worker |
| Modify | `backend/app/workers/tasks/__init__.py` | Export new task |
| Modify | `backend/tests/unit/test_context_assembler.py` | Add tests for multi-turn + memory |
| Modify | `backend/tests/unit/test_chat_service.py` | Add tests for memory integration in chat flow |
| Modify | `docs/spec.md` | Add 5 new parameters to Implementation defaults table |

---

### Task 1: Alembic Migration — Session Summary Fields

**Files:**
- Create: `backend/migrations/versions/010_add_session_summary_fields.py`

- [ ] **Step 1: Create migration file**

```python
"""add_session_summary_fields

Revision ID: 010
Revises: 009
Create Date: 2026-03-26 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "010"
down_revision: str | Sequence[str] | None = "009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("summary", sa.Text(), nullable=True))
    op.add_column("sessions", sa.Column("summary_token_count", sa.Integer(), nullable=True))
    op.add_column(
        "sessions",
        sa.Column(
            "summary_up_to_message_id",
            sa.Uuid(),
            sa.ForeignKey("messages.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("sessions", "summary_up_to_message_id")
    op.drop_column("sessions", "summary_token_count")
    op.drop_column("sessions", "summary")
```

- [ ] **Step 2: Run migration inside Docker**

```bash
docker compose exec api alembic upgrade head
```

Expected: migration applies cleanly, 3 new nullable columns on `sessions`.

- [ ] **Step 3: Commit**

```bash
git add backend/migrations/versions/010_add_session_summary_fields.py
git commit -m "feat(db): add session summary fields for conversation memory"
```

---

### Task 2: Session Model — Add Summary Fields

**Files:**
- Modify: `backend/app/db/models/dialogue.py`

- [ ] **Step 1: Add fields to Session model**

Add three new fields after `channel_connector` in `Session`:

```python
    summary: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    summary_token_count: Mapped[int | None] = mapped_column(nullable=True)
    summary_up_to_message_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("messages.id", ondelete="SET NULL"), nullable=True
    )
```

- [ ] **Step 2: Verify model loads**

```bash
docker compose exec api python -c "from app.db.models.dialogue import Session; print([c.key for c in Session.__table__.columns])"
```

Expected: output includes `summary`, `summary_token_count`, `summary_up_to_message_id`.

- [ ] **Step 3: Commit**

```bash
git add backend/app/db/models/dialogue.py
git commit -m "feat(models): add summary fields to Session model"
```

---

### Task 3: Configuration — Add Conversation Memory Settings

**Files:**
- Modify: `backend/app/core/config.py`
- Modify: `docs/spec.md`

- [ ] **Step 1: Add settings to config.py**

Add after the `rewrite_history_messages` field (line 70):

```python
    conversation_memory_budget: int = Field(default=4096, ge=1)
    conversation_summary_ratio: float = Field(default=0.3, ge=0.0, le=1.0)
    conversation_summary_model: str | None = Field(default=None)
    conversation_summary_temperature: float = Field(default=0.1, ge=0.0, le=2.0)
    conversation_summary_timeout_ms: int = Field(default=10000, ge=1)
```

Add `"conversation_summary_model"` to the `normalize_empty_optional_strings` field list.

- [ ] **Step 2: Update docs/spec.md Implementation defaults table**

Add these rows to the Implementation defaults table in `docs/spec.md` (the table with `retrieval_top_n`, `rewrite_timeout_ms`, etc.):

```markdown
| `conversation_memory_budget`    | 4096 tokens                | Maximum tokens for conversation memory (summary + sliding window) in prompt                                                   |
| `conversation_summary_ratio`    | 0.3                        | Soft target for summary generation length as a fraction of budget. Not a hard partition — actual summary tokens deducted at face value |
| `conversation_summary_model`    | same as `llm_model`        | Model for conversation summarization. If unset, falls back to the main llm_model                                              |
| `conversation_summary_temperature` | 0.1                     | Temperature for summarization LLM calls                                                                                       |
| `conversation_summary_timeout_ms`  | 10000                   | Timeout (ms) for summary LLM call in the background arq task                                                                  |
```

- [ ] **Step 3: Run config test**

```bash
docker compose exec api python -m pytest tests/unit/test_config.py -v
```

Expected: PASS (existing tests still pass with new defaults).

- [ ] **Step 4: Commit**

```bash
git add backend/app/core/config.py docs/spec.md
git commit -m "feat(config): add conversation memory settings"
```

---

### Task 4: MemoryBlock + ConversationMemoryService

**Files:**
- Create: `backend/app/services/conversation_memory.py`
- Create: `backend/tests/unit/test_conversation_memory.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/unit/test_conversation_memory.py`:

```python
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.conversation_memory import ConversationMemoryService, MemoryBlock


def _msg(role: str, content: str, msg_id: uuid.UUID | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=msg_id or uuid.uuid4(),
        role=SimpleNamespace(value=role),
        content=content,
        status=SimpleNamespace(value="received" if role == "user" else "complete"),
        created_at=None,
    )


def _session(
    summary: str | None = None,
    summary_token_count: int | None = None,
    summary_up_to_message_id: uuid.UUID | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        summary=summary,
        summary_token_count=summary_token_count,
        summary_up_to_message_id=summary_up_to_message_id,
    )


class TestBuildMemoryBlock:
    def test_empty_session_returns_empty_block(self) -> None:
        service = ConversationMemoryService(budget=4096, summary_ratio=0.3)
        block = service.build_memory_block(
            session=_session(),
            messages=[],
        )
        assert block.summary_text is None
        assert block.messages == []
        assert block.total_tokens == 0
        assert block.needs_summary_update is False
        assert block.window_start_message_id is None

    def test_short_session_fits_in_budget(self) -> None:
        msgs = [
            _msg("user", "Hello"),
            _msg("assistant", "Hi there!"),
            _msg("user", "How are you?"),
            _msg("assistant", "I am fine."),
        ]
        service = ConversationMemoryService(budget=4096, summary_ratio=0.3)
        block = service.build_memory_block(
            session=_session(),
            messages=msgs,
        )
        assert block.summary_text is None
        assert len(block.messages) == 4
        assert block.messages[0]["role"] == "user"
        assert block.messages[0]["content"] == "Hello"
        assert block.messages[1]["role"] == "assistant"
        assert block.messages[1]["content"] == "Hi there!"
        assert block.needs_summary_update is False

    def test_long_session_triggers_needs_summary(self) -> None:
        # Create messages that exceed budget (budget=30 tokens, ~90 chars)
        msgs = [
            _msg("user", "A" * 30),
            _msg("assistant", "B" * 30),
            _msg("user", "C" * 30),
            _msg("assistant", "D" * 30),
            _msg("user", "E" * 30),
            _msg("assistant", "F" * 30),
        ]
        service = ConversationMemoryService(budget=30, summary_ratio=0.3)
        block = service.build_memory_block(
            session=_session(),
            messages=msgs,
        )
        # Not all messages fit in budget, oldest dropped
        assert len(block.messages) < 6
        # Messages that don't fit in window AND aren't summarized → needs_summary_update
        assert block.needs_summary_update is True

    def test_session_with_existing_summary(self) -> None:
        boundary_id = uuid.uuid4()
        msgs = [
            _msg("user", "old msg 1", msg_id=uuid.uuid4()),
            _msg("assistant", "old reply 1", msg_id=boundary_id),
            _msg("user", "recent msg"),
            _msg("assistant", "recent reply"),
        ]
        service = ConversationMemoryService(budget=4096, summary_ratio=0.3)
        block = service.build_memory_block(
            session=_session(
                summary="User discussed old topics.",
                summary_token_count=10,
                summary_up_to_message_id=boundary_id,
            ),
            messages=msgs,
        )
        assert block.summary_text == "User discussed old topics."
        # Only messages after boundary are in window
        assert len(block.messages) == 2
        assert block.messages[0]["content"] == "recent msg"
        assert block.needs_summary_update is False

    def test_summary_budget_respected(self) -> None:
        boundary_id = uuid.uuid4()
        # Summary takes 80 tokens of a 100 budget.
        # Ratio is a soft target for generation, not a hard partition.
        # Actual summary tokens are deducted at face value: window budget = 100 - 80 = 20.
        msgs = [
            _msg("user", "old", msg_id=uuid.uuid4()),
            _msg("assistant", "old reply", msg_id=boundary_id),
            _msg("user", "A" * 150),
            _msg("assistant", "B" * 150),
            _msg("user", "C" * 30),
            _msg("assistant", "D" * 30),
        ]
        service = ConversationMemoryService(budget=100, summary_ratio=0.3)
        block = service.build_memory_block(
            session=_session(
                summary="Long summary " * 20,
                summary_token_count=80,
                summary_up_to_message_id=boundary_id,
            ),
            messages=msgs,
        )
        # Window budget = 100 - 80 = 20 tokens, so only the last pair (or fewer) fits
        assert block.total_tokens <= 100

    def test_messages_in_chronological_order(self) -> None:
        msgs = [
            _msg("user", "first"),
            _msg("assistant", "reply first"),
            _msg("user", "second"),
            _msg("assistant", "reply second"),
        ]
        service = ConversationMemoryService(budget=4096, summary_ratio=0.3)
        block = service.build_memory_block(
            session=_session(),
            messages=msgs,
        )
        contents = [m["content"] for m in block.messages]
        assert contents == ["first", "reply first", "second", "reply second"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
docker compose exec api python -m pytest tests/unit/test_conversation_memory.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.conversation_memory'`

- [ ] **Step 3: Implement ConversationMemoryService**

Create `backend/app/services/conversation_memory.py`:

```python
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

import structlog

from app.services.token_counter import estimate_tokens

logger = structlog.get_logger(__name__)


class SessionLike(Protocol):
    id: uuid.UUID
    summary: str | None
    summary_token_count: int | None
    summary_up_to_message_id: uuid.UUID | None


class MessageLike(Protocol):
    id: uuid.UUID
    role: Any  # Has .value attribute
    content: str


@dataclass(slots=True, frozen=True)
class MemoryBlock:
    summary_text: str | None
    messages: list[dict[str, str]]
    total_tokens: int
    needs_summary_update: bool
    window_start_message_id: uuid.UUID | None


class ConversationMemoryService:
    def __init__(
        self,
        *,
        budget: int,
        summary_ratio: float,
    ) -> None:
        self._budget = budget
        self._summary_ratio = summary_ratio

    def build_memory_block(
        self,
        *,
        session: SessionLike,
        messages: list[MessageLike],
    ) -> MemoryBlock:
        if not messages:
            return MemoryBlock(
                summary_text=None,
                messages=[],
                total_tokens=0,
                needs_summary_update=False,
                window_start_message_id=None,
            )

        summary_text = session.summary
        summary_tokens = session.summary_token_count or 0
        boundary_id = session.summary_up_to_message_id

        # Split messages into summarized vs recent
        if boundary_id is not None:
            boundary_index = None
            for i, msg in enumerate(messages):
                if msg.id == boundary_id:
                    boundary_index = i
                    break
            if boundary_index is not None:
                recent = messages[boundary_index + 1 :]
            else:
                recent = messages
                summary_text = None
                summary_tokens = 0
        else:
            recent = messages
            summary_text = None
            summary_tokens = 0

        # Build sliding window from newest to oldest
        window_budget = self._budget - summary_tokens
        if window_budget < 0:
            window_budget = 0

        selected: list[MessageLike] = []
        used_tokens = 0
        for msg in reversed(recent):
            msg_tokens = estimate_tokens(msg.content)
            if used_tokens + msg_tokens > window_budget and selected:
                break
            selected.append(msg)
            used_tokens += msg_tokens

        # Reverse to chronological order
        selected.reverse()

        # Determine window_start_message_id
        window_start_id = selected[0].id if selected else None

        # Check if there are messages not in summary and not in window
        unsummarized_count = len(recent) - len(selected)
        needs_summary = unsummarized_count > 0

        total_tokens = summary_tokens + used_tokens

        return MemoryBlock(
            summary_text=summary_text,
            messages=[
                {"role": msg.role.value, "content": msg.content}
                for msg in selected
            ],
            total_tokens=total_tokens,
            needs_summary_update=needs_summary,
            window_start_message_id=window_start_id,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
docker compose exec api python -m pytest tests/unit/test_conversation_memory.py -v
```

Expected: all 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/conversation_memory.py backend/tests/unit/test_conversation_memory.py
git commit -m "feat(memory): add ConversationMemoryService with MemoryBlock"
```

---

### Task 5: ContextAssembler — Multi-turn + Memory Layer

**Files:**
- Modify: `backend/app/services/context_assembler.py`
- Modify: `backend/tests/unit/test_context_assembler.py`

- [ ] **Step 1: Write failing tests**

Add to `backend/tests/unit/test_context_assembler.py`:

```python
from app.services.conversation_memory import MemoryBlock


def _memory_block(
    summary_text: str | None = None,
    messages: list[dict[str, str]] | None = None,
    total_tokens: int = 0,
) -> MemoryBlock:
    return MemoryBlock(
        summary_text=summary_text,
        messages=messages or [],
        total_tokens=total_tokens,
        needs_summary_update=False,
        window_start_message_id=None,
    )


class TestContextAssemblerWithMemory:
    def test_memory_block_none_backward_compatible(self) -> None:
        asm = _assembler()
        result = asm.assemble(
            chunks=[_chunk()],
            query="What?",
            source_map={uuid.uuid4(): _source_info()},
            memory_block=None,
        )
        # Two messages: system + user (same as before)
        assert len(result.messages) == 2
        assert result.messages[0]["role"] == "system"
        assert result.messages[-1]["role"] == "user"

    def test_memory_block_with_history_creates_multi_turn(self) -> None:
        asm = _assembler()
        block = _memory_block(
            messages=[
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi there!"},
            ],
            total_tokens=10,
        )
        sid = uuid.uuid4()
        result = asm.assemble(
            chunks=[_chunk(source_id=sid)],
            query="What is X?",
            source_map={sid: _source_info()},
            memory_block=block,
        )
        # system + user_hist + assistant_hist + user_query = 4 messages
        assert len(result.messages) == 4
        assert result.messages[0]["role"] == "system"
        assert result.messages[1]["role"] == "user"
        assert result.messages[1]["content"] == "Hello"
        assert result.messages[2]["role"] == "assistant"
        assert result.messages[2]["content"] == "Hi there!"
        assert result.messages[3]["role"] == "user"

    def test_summary_in_system_prompt(self) -> None:
        asm = _assembler()
        block = _memory_block(
            summary_text="User asked about concerts.",
            total_tokens=10,
        )
        sid = uuid.uuid4()
        result = asm.assemble(
            chunks=[_chunk(source_id=sid)],
            query="Tell me more",
            source_map={sid: _source_info()},
            memory_block=block,
        )
        system = result.messages[0]["content"]
        assert "conversation_summary" in system
        assert "User asked about concerts." in system

    def test_summary_before_citation_instructions(self) -> None:
        asm = _assembler()
        block = _memory_block(
            summary_text="Earlier context.",
            total_tokens=5,
        )
        sid = uuid.uuid4()
        result = asm.assemble(
            chunks=[_chunk(source_id=sid)],
            query="Query",
            source_map={sid: _source_info()},
            memory_block=block,
        )
        system = result.messages[0]["content"]
        summary_pos = system.index("conversation_summary")
        citation_pos = system.index("citation_instructions")
        assert summary_pos < citation_pos

    def test_memory_token_count_in_layer_counts(self) -> None:
        asm = _assembler()
        block = _memory_block(
            messages=[
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi"},
            ],
            total_tokens=10,
        )
        sid = uuid.uuid4()
        result = asm.assemble(
            chunks=[_chunk(source_id=sid)],
            query="Q",
            source_map={sid: _source_info()},
            memory_block=block,
        )
        assert "conversation_memory" in result.layer_token_counts
        assert result.layer_token_counts["conversation_memory"] == 10

    def test_summary_only_no_history_still_tracked(self) -> None:
        """Summary exists but no verbatim messages fit in window."""
        asm = _assembler()
        block = _memory_block(
            summary_text="User discussed topics A, B, C.",
            messages=[],  # no verbatim messages
            total_tokens=15,
        )
        sid = uuid.uuid4()
        result = asm.assemble(
            chunks=[_chunk(source_id=sid)],
            query="Q",
            source_map={sid: _source_info()},
            memory_block=block,
        )
        # Summary tokens tracked under conversation_memory, not conversation_summary
        assert "conversation_memory" in result.layer_token_counts
        assert "conversation_summary" not in result.layer_token_counts
        assert result.layer_token_counts["conversation_memory"] == 15
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
docker compose exec api python -m pytest tests/unit/test_context_assembler.py::TestContextAssemblerWithMemory -v
```

Expected: FAIL — `assemble() got an unexpected keyword argument 'memory_block'`

- [ ] **Step 3: Modify ContextAssembler**

Update `backend/app/services/context_assembler.py`:

Add import at top:

```python
from app.services.conversation_memory import MemoryBlock
```

Change the `assemble` method signature to accept `memory_block`:

```python
    def assemble(
        self,
        *,
        chunks: list[RetrievedChunk],
        query: str,
        source_map: dict[uuid.UUID, SourceInfo],
        memory_block: MemoryBlock | None = None,
    ) -> AssembledPrompt:
```

Replace the TODO comment (line 81) and the rest of the method body from line 68 onward with:

```python
        included_promotions = self._resolve_promotions()
        selected_chunks = self._select_chunks(chunks, source_map)

        layers = [
            self._build_layer("system_safety", SYSTEM_SAFETY_POLICY),
            self._build_layer("identity", self.persona_context.identity),
            self._build_layer("soul", self.persona_context.soul),
            self._build_layer("behavior", self.persona_context.behavior),
        ]
        if included_promotions:
            layers.append(
                self._build_layer(
                    "promotions",
                    self._promotions_text(included_promotions),
                )
            )

        # Layer 6: conversation summary (part of memory)
        if memory_block is not None and memory_block.summary_text:
            layers.append(
                self._build_layer(
                    "conversation_summary",
                    f"Earlier in this conversation:\n{memory_block.summary_text}",
                )
            )

        if selected_chunks:
            layers.append(
                self._build_layer(
                    "citation_instructions",
                    self._citation_instructions(),
                )
            )
        layers.append(
            self._build_layer("content_guidelines", self._content_guidelines())
        )

        layer_token_counts = {layer.tag: layer.token_estimate for layer in layers}
        system_content = "\n\n".join(layer.content for layer in layers)

        # Unified memory token accounting: replace separate conversation_summary
        # entry with a single conversation_memory key covering summary + history.
        # This avoids double-counting when summary is in system prompt and history
        # is in multi-turn messages.
        if memory_block is not None and memory_block.total_tokens > 0:
            layer_token_counts.pop("conversation_summary", None)
            layer_token_counts["conversation_memory"] = memory_block.total_tokens

        # Build messages list: system + history pairs + user query with knowledge
        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_content},
        ]

        # Insert conversation history as multi-turn messages
        if memory_block is not None and memory_block.messages:
            messages.extend(memory_block.messages)

        # User query (with knowledge context if available)
        user_sections = [self._build_user_query(query)]
        if selected_chunks:
            knowledge_context = self._build_knowledge_context(selected_chunks, source_map)
            user_sections.insert(0, knowledge_context)
            layer_token_counts["knowledge_context"] = estimate_tokens(knowledge_context)
        layer_token_counts["user_query"] = estimate_tokens(user_sections[-1])
        user_content = "\n\n".join(user_sections)
        messages.append({"role": "user", "content": user_content})

        return AssembledPrompt(
            messages=messages,
            token_estimate=sum(layer_token_counts.values()),
            included_promotions=included_promotions,
            retrieval_chunks_used=len(selected_chunks),
            retrieval_chunks_total=len(chunks),
            layer_token_counts=layer_token_counts,
        )
```

- [ ] **Step 4: Run all context assembler tests**

```bash
docker compose exec api python -m pytest tests/unit/test_context_assembler.py -v
```

Expected: all tests PASS (both old and new).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/context_assembler.py backend/tests/unit/test_context_assembler.py
git commit -m "feat(context): add multi-turn conversation memory to ContextAssembler"
```

---

### Task 6: Summary Generation arq Task

**Files:**
- Create: `backend/app/workers/tasks/summarize.py`
- Create: `backend/tests/unit/test_summary_task.py`
- Modify: `backend/app/workers/tasks/__init__.py`
- Modify: `backend/app/workers/main.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/unit/test_summary_task.py`:

```python
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.workers.tasks.summarize import generate_session_summary


def _make_message(role: str, content: str, msg_id: uuid.UUID | None = None) -> MagicMock:
    msg = MagicMock()
    msg.id = msg_id or uuid.uuid4()
    msg.role.value = role
    msg.content = content
    return msg


@pytest.mark.asyncio
async def test_summary_generated_and_saved() -> None:
    session_id = uuid.uuid4()
    boundary_msg_id = uuid.uuid4()
    window_start_msg_id = uuid.uuid4()

    old_msg = _make_message("user", "old question", msg_id=uuid.uuid4())
    old_reply = _make_message("assistant", "old answer", msg_id=boundary_msg_id)
    unsummarized_msg = _make_message("user", "middle question")
    unsummarized_reply = _make_message("assistant", "middle answer", msg_id=window_start_msg_id)

    mock_session_obj = MagicMock()
    mock_session_obj.id = session_id
    mock_session_obj.summary = "Previous summary."
    mock_session_obj.summary_up_to_message_id = old_reply.id

    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=mock_session_obj)
    mock_db.execute = AsyncMock()
    mock_db.commit = AsyncMock()

    # Messages that need summarization (between boundary and window start)
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [unsummarized_msg, unsummarized_reply]
    mock_db.execute.return_value = mock_result

    mock_llm = AsyncMock()
    mock_llm.complete = AsyncMock()
    mock_llm.complete.return_value = MagicMock(content="Updated summary of the conversation.")

    mock_session_factory = MagicMock()

    ctx = {
        "session_factory": mock_session_factory,
        "summary_llm_service": mock_llm,
        "settings": MagicMock(
            conversation_memory_budget=4096,
            conversation_summary_ratio=0.3,
            conversation_summary_timeout_ms=10000,
            conversation_summary_temperature=0.1,
        ),
    }

    with patch("app.workers.tasks.summarize._open_db_session") as mock_open:
        mock_open.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_open.return_value.__aexit__ = AsyncMock(return_value=False)

        await generate_session_summary(
            ctx,
            str(session_id),
            str(window_start_msg_id),
        )

    mock_llm.complete.assert_awaited_once()
    assert mock_session_obj.summary == "Updated summary of the conversation."
    mock_db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_summary_skipped_when_no_messages_to_summarize() -> None:
    session_id = uuid.uuid4()
    window_start_msg_id = uuid.uuid4()

    mock_session_obj = MagicMock()
    mock_session_obj.id = session_id
    mock_session_obj.summary = None
    mock_session_obj.summary_up_to_message_id = None

    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=mock_session_obj)
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_db.execute.return_value = mock_result

    mock_llm = AsyncMock()
    mock_session_factory = MagicMock()

    ctx = {
        "session_factory": mock_session_factory,
        "summary_llm_service": mock_llm,
        "settings": MagicMock(
            conversation_memory_budget=4096,
            conversation_summary_ratio=0.3,
            conversation_summary_timeout_ms=10000,
            conversation_summary_temperature=0.1,
        ),
    }

    with patch("app.workers.tasks.summarize._open_db_session") as mock_open:
        mock_open.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_open.return_value.__aexit__ = AsyncMock(return_value=False)

        await generate_session_summary(
            ctx,
            str(session_id),
            str(window_start_msg_id),
        )

    mock_llm.complete.assert_not_awaited()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
docker compose exec api python -m pytest tests/unit/test_summary_task.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'app.workers.tasks.summarize'`

- [ ] **Step 3: Implement summary task**

Create `backend/app/workers/tasks/summarize.py`:

```python
from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Message, Session
from app.db.models.enums import MessageRole, MessageStatus
from app.services.token_counter import estimate_tokens

logger = structlog.get_logger(__name__)

SUMMARIZE_SYSTEM_PROMPT_TEMPLATE = (
    "Summarize the following conversation between a user and an AI assistant. "
    "Preserve: key topics discussed, user's questions and intent, important facts mentioned, "
    "any decisions or conclusions reached. "
    "Keep summary under {max_summary_tokens} tokens. "
    "Be concise but complete. Write in the same language as the conversation."
)


@asynccontextmanager
async def _open_db_session(session_factory: Any) -> AsyncSession:
    async with session_factory() as db:
        yield db


async def generate_session_summary(
    ctx: dict[str, Any],
    session_id_str: str,
    window_start_message_id_str: str,
) -> None:
    session_id = uuid.UUID(session_id_str)
    window_start_message_id = uuid.UUID(window_start_message_id_str)
    session_factory = ctx["session_factory"]
    llm_service = ctx["summary_llm_service"]
    settings = ctx["settings"]
    timeout_s = settings.conversation_summary_timeout_ms / 1000
    max_summary_tokens = int(
        settings.conversation_memory_budget * settings.conversation_summary_ratio
    )

    async with _open_db_session(session_factory) as db:
        chat_session = await db.get(Session, session_id)
        if chat_session is None:
            logger.warning("summary_task.session_not_found", session_id=session_id_str)
            return

        # Load messages that need summarization:
        # After summary boundary (or from start) up to window start (exclusive)
        conditions = [
            Message.session_id == session_id,
            Message.status.in_([MessageStatus.RECEIVED, MessageStatus.COMPLETE]),
            Message.id != window_start_message_id,
        ]
        if chat_session.summary_up_to_message_id is not None:
            conditions.append(
                Message.created_at > (
                    select(Message.created_at)
                    .where(Message.id == chat_session.summary_up_to_message_id)
                    .correlate(None)
                    .scalar_subquery()
                )
            )
        conditions.append(
            Message.created_at < (
                select(Message.created_at)
                .where(Message.id == window_start_message_id)
                .correlate(None)
                .scalar_subquery()
            )
        )

        result = await db.execute(
            select(Message)
            .where(*conditions)
            .order_by(Message.created_at)
        )
        messages_to_summarize = result.scalars().all()

        if not messages_to_summarize:
            logger.info(
                "summary_task.no_messages_to_summarize",
                session_id=session_id_str,
            )
            return

        # Build conversation text for summarization
        conversation_lines = []
        if chat_session.summary:
            conversation_lines.append(f"Previous summary: {chat_session.summary}")
            conversation_lines.append("")
            conversation_lines.append("New messages to incorporate:")

        for msg in messages_to_summarize:
            role_label = "User" if msg.role == MessageRole.USER else "Assistant"
            conversation_lines.append(f"{role_label}: {msg.content}")

        conversation_text = "\n".join(conversation_lines)

        # Call LLM for summarization
        try:
            llm_response = await asyncio.wait_for(
                llm_service.complete(
                    [
                        {
                            "role": "system",
                            "content": SUMMARIZE_SYSTEM_PROMPT_TEMPLATE.format(
                                max_summary_tokens=max_summary_tokens,
                            ),
                        },
                        {"role": "user", "content": conversation_text},
                    ]
                ),
                timeout=timeout_s,
            )
        except (TimeoutError, Exception) as error:
            logger.warning(
                "summary_task.llm_failed",
                session_id=session_id_str,
                error=str(error),
            )
            return

        new_summary = llm_response.content
        last_summarized_id = messages_to_summarize[-1].id

        # Atomically update session
        chat_session.summary = new_summary
        chat_session.summary_token_count = estimate_tokens(new_summary)
        chat_session.summary_up_to_message_id = last_summarized_id
        await db.commit()

        logger.info(
            "summary_task.completed",
            session_id=session_id_str,
            summary_tokens=chat_session.summary_token_count,
            messages_summarized=len(messages_to_summarize),
        )
```

- [ ] **Step 4: Register task in workers**

Update `backend/app/workers/tasks/__init__.py`:

```python
from app.workers.tasks.batch_embed import process_batch_embed
from app.workers.tasks.batch_poll import poll_active_batches
from app.workers.tasks.ingestion import process_ingestion
from app.workers.tasks.summarize import generate_session_summary

__all__ = [
    "process_ingestion",
    "process_batch_embed",
    "poll_active_batches",
    "generate_session_summary",
]
```

Update `backend/app/workers/main.py`:

In the imports, add `generate_session_summary`:

```python
from app.workers.tasks import (
    generate_session_summary,
    poll_active_batches,
    process_batch_embed,
    process_ingestion,
)
```

In `on_startup`, add LLM service for summary (after the existing context setup, before the final log line):

```python
    from app.services.llm import LLMService

    summary_model = settings.conversation_summary_model or settings.llm_model
    summary_llm_service = LLMService(
        model=summary_model,
        api_key=settings.llm_api_key,
        api_base=settings.llm_api_base,
        temperature=settings.conversation_summary_temperature,
    )
    ctx["summary_llm_service"] = summary_llm_service
```

In `WorkerSettings.functions`, add `generate_session_summary`:

```python
    functions = [process_ingestion, process_batch_embed, poll_active_batches, generate_session_summary]
```

- [ ] **Step 5: Run tests**

```bash
docker compose exec api python -m pytest tests/unit/test_summary_task.py -v
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/workers/tasks/summarize.py backend/app/workers/tasks/__init__.py backend/app/workers/main.py backend/tests/unit/test_summary_task.py
git commit -m "feat(memory): add async summary generation arq task"
```

---

### Task 7: ChatService Integration

**Files:**
- Modify: `backend/app/services/chat.py`
- Modify: `backend/tests/unit/test_chat_service.py`

- [ ] **Step 1: Write failing tests**

Add to `backend/tests/unit/test_chat_service.py`:

```python
from app.services.conversation_memory import ConversationMemoryService, MemoryBlock


class TestChatServiceWithMemory:
    @pytest.fixture
    def mock_memory_service(self) -> ConversationMemoryService:
        service = AsyncMock(spec=ConversationMemoryService)
        service.build_memory_block = MagicMock(
            return_value=MemoryBlock(
                summary_text=None,
                messages=[
                    {"role": "user", "content": "earlier question"},
                    {"role": "assistant", "content": "earlier answer"},
                ],
                total_tokens=20,
                needs_summary_update=False,
                window_start_message_id=None,
            )
        )
        return service

    @pytest.fixture
    def mock_summary_enqueuer(self) -> AsyncMock:
        return AsyncMock()

    @pytest.mark.asyncio
    async def test_answer_includes_memory_block(
        self,
        db_session,
        seeded_agent,
        mock_retrieval_service,
        mock_llm_service,
        mock_rewrite_service,
        persona_context,
        sample_retrieved_chunk,
        mock_memory_service,
        mock_summary_enqueuer,
    ):
        from app.services.snapshot import SnapshotService

        snapshot_service = SnapshotService(session=db_session)
        context_assembler = ContextAssembler(
            persona_context=persona_context,
            retrieval_context_budget=4096,
            max_citations=5,
            min_retrieved_chunks=1,
        )

        mock_retrieval_service.search = AsyncMock(return_value=[sample_retrieved_chunk])

        service = ChatService(
            session=db_session,
            snapshot_service=snapshot_service,
            retrieval_service=mock_retrieval_service,
            llm_service=mock_llm_service,
            query_rewrite_service=mock_rewrite_service,
            context_assembler=context_assembler,
            min_retrieved_chunks=1,
            conversation_memory_service=mock_memory_service,
            summary_enqueuer=mock_summary_enqueuer,
        )

        # Create session and snapshot for test
        from app.db.models import KnowledgeSnapshot
        from app.db.models.enums import SnapshotStatus

        snapshot = KnowledgeSnapshot(
            id=uuid.uuid7(),
            agent_id=seeded_agent.id,
            knowledge_base_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
            status=SnapshotStatus.ACTIVE,
            name="test",
        )
        db_session.add(snapshot)
        await db_session.commit()

        session = await service.create_session()
        result = await service.answer(session_id=session.id, text="What is X?")

        # Memory service was called
        mock_memory_service.build_memory_block.assert_called_once()

    @pytest.mark.asyncio
    async def test_summary_enqueued_when_needed(
        self,
        db_session,
        seeded_agent,
        mock_retrieval_service,
        mock_llm_service,
        mock_rewrite_service,
        persona_context,
        sample_retrieved_chunk,
        mock_summary_enqueuer,
    ):
        mock_memory_service = AsyncMock(spec=ConversationMemoryService)
        mock_memory_service.build_memory_block = MagicMock(
            return_value=MemoryBlock(
                summary_text=None,
                messages=[],
                total_tokens=0,
                needs_summary_update=True,
                window_start_message_id=uuid.uuid4(),
            )
        )

        from app.services.snapshot import SnapshotService

        snapshot_service = SnapshotService(session=db_session)
        context_assembler = ContextAssembler(
            persona_context=persona_context,
            retrieval_context_budget=4096,
            max_citations=5,
            min_retrieved_chunks=1,
        )

        mock_retrieval_service.search = AsyncMock(return_value=[sample_retrieved_chunk])

        service = ChatService(
            session=db_session,
            snapshot_service=snapshot_service,
            retrieval_service=mock_retrieval_service,
            llm_service=mock_llm_service,
            query_rewrite_service=mock_rewrite_service,
            context_assembler=context_assembler,
            min_retrieved_chunks=1,
            conversation_memory_service=mock_memory_service,
            summary_enqueuer=mock_summary_enqueuer,
        )

        from app.db.models import KnowledgeSnapshot
        from app.db.models.enums import SnapshotStatus

        snapshot = KnowledgeSnapshot(
            id=uuid.uuid7(),
            agent_id=seeded_agent.id,
            knowledge_base_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
            status=SnapshotStatus.ACTIVE,
            name="test",
        )
        db_session.add(snapshot)
        await db_session.commit()

        session = await service.create_session()
        await service.answer(session_id=session.id, text="What is X?")

        mock_summary_enqueuer.assert_awaited_once()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
docker compose exec api python -m pytest tests/unit/test_chat_service.py::TestChatServiceWithMemory -v
```

Expected: FAIL — `ChatService.__init__() got an unexpected keyword argument 'conversation_memory_service'`

- [ ] **Step 3: Modify ChatService**

In `backend/app/services/chat.py`:

Add import:

```python
from app.services.conversation_memory import ConversationMemoryService, MemoryBlock
```

Add `SummaryEnqueuer` protocol and update `__init__`:

```python
from typing import TYPE_CHECKING, Protocol

class SummaryEnqueuer(Protocol):
    async def __call__(self, session_id: str, window_start_message_id: str) -> None: ...
```

Update `__init__` to accept new dependencies:

```python
    def __init__(
        self,
        *,
        session: AsyncSession,
        snapshot_service: SnapshotService,
        retrieval_service: RetrievalService,
        llm_service: LLMService,
        query_rewrite_service: QueryRewriteService,
        context_assembler: ContextAssembler,
        min_retrieved_chunks: int,
        max_citations_per_response: int = 5,
        conversation_memory_service: ConversationMemoryService | None = None,
        summary_enqueuer: SummaryEnqueuer | None = None,
    ) -> None:
        # ... existing assignments ...
        self._conversation_memory_service = conversation_memory_service
        self._summary_enqueuer = summary_enqueuer
```

Add helper method to build memory:

```python
    def _build_memory(self, chat_session: Session, messages: list[Message]) -> MemoryBlock | None:
        if self._conversation_memory_service is None:
            return None
        return self._conversation_memory_service.build_memory_block(
            session=chat_session,
            messages=messages,
        )
```

Add helper method to enqueue summary:

```python
    async def _maybe_enqueue_summary(
        self,
        memory_block: MemoryBlock | None,
        session_id: uuid.UUID,
    ) -> None:
        if (
            memory_block is not None
            and memory_block.needs_summary_update
            and memory_block.window_start_message_id is not None
            and self._summary_enqueuer is not None
        ):
            try:
                await self._summary_enqueuer(
                    str(session_id),
                    str(memory_block.window_start_message_id),
                )
            except Exception as error:
                self._logger.warning(
                    "chat.summary_enqueue_failed",
                    session_id=str(session_id),
                    error=str(error),
                )
```

In the `answer()` method, after `search_query = await self._do_rewrite(...)` and retrieval, before `assembled = self._context_assembler.assemble(...)`:

```python
            history = await self._load_history(chat_session.id, exclude_message_id=user_message.id)
            memory_block = self._build_memory(chat_session, history)
```

Update `assemble()` call to pass `memory_block`:

```python
            assembled = self._context_assembler.assemble(
                chunks=retrieved_chunks,
                query=text,
                source_map=source_map,
                memory_block=memory_block,
            )
```

After the successful return in `answer()`, before `return ChatAnswerResult(...)`:

```python
            await self._maybe_enqueue_summary(memory_block, chat_session.id)
```

Apply the same pattern to `stream_answer()`:
- Build `memory_block` from history after rewrite
- Pass `memory_block` to `assemble()`
- Call `_maybe_enqueue_summary()` after successful streaming (after the `yield ChatStreamDone`)

- [ ] **Step 4: Run all chat service tests**

```bash
docker compose exec api python -m pytest tests/unit/test_chat_service.py -v
```

Expected: all tests PASS (old + new).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/chat.py backend/tests/unit/test_chat_service.py
git commit -m "feat(chat): integrate conversation memory into ChatService"
```

---

### Task 8: Dependency Injection Wiring

**Files:**
- Modify: `backend/app/api/dependencies.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: Add ConversationMemoryService to dependencies.py**

Add import:

```python
from app.services.conversation_memory import ConversationMemoryService
```

Add getter function:

```python
def get_conversation_memory_service(request: Request) -> ConversationMemoryService:
    return request.app.state.conversation_memory_service
```

Add summary enqueuer function:

```python
async def _enqueue_summary(arq_pool: ArqRedis, session_id: str, window_start_message_id: str) -> None:
    job = await arq_pool.enqueue_job(
        "generate_session_summary",
        session_id,
        window_start_message_id,
        _job_id=f"summary:{session_id}",
    )
    if job is None:
        raise RuntimeError("arq returned no job handle for summary task")
```

Update `get_chat_service` to pass new dependencies:

```python
def get_chat_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    snapshot_service: Annotated[SnapshotService, Depends(get_snapshot_service)],
    retrieval_service: Annotated[RetrievalService, Depends(get_retrieval_service)],
    llm_service: Annotated[LLMService, Depends(get_llm_service)],
    query_rewrite_service: Annotated[
        QueryRewriteService, Depends(get_query_rewrite_service)
    ],
    context_assembler: Annotated[ContextAssembler, Depends(get_context_assembler)],
    conversation_memory_service: Annotated[
        ConversationMemoryService, Depends(get_conversation_memory_service)
    ],
) -> ChatService:
    from app.services.chat import ChatService

    arq_pool = request.app.state.arq_pool

    async def summary_enqueuer(session_id: str, window_start_message_id: str) -> None:
        await _enqueue_summary(arq_pool, session_id, window_start_message_id)

    return ChatService(
        session=session,
        snapshot_service=snapshot_service,
        retrieval_service=retrieval_service,
        llm_service=llm_service,
        query_rewrite_service=query_rewrite_service,
        context_assembler=context_assembler,
        min_retrieved_chunks=request.app.state.settings.min_retrieved_chunks,
        max_citations_per_response=request.app.state.settings.max_citations_per_response,
        conversation_memory_service=conversation_memory_service,
        summary_enqueuer=summary_enqueuer,
    )
```

- [ ] **Step 2: Create service in main.py lifespan**

Add to `backend/app/main.py` in the `lifespan` function, after the existing service creation:

```python
    from app.services.conversation_memory import ConversationMemoryService

    app.state.conversation_memory_service = ConversationMemoryService(
        budget=settings.conversation_memory_budget,
        summary_ratio=settings.conversation_summary_ratio,
    )
```

- [ ] **Step 3: Run existing tests to verify no regressions**

```bash
docker compose exec api python -m pytest tests/unit/ -v --timeout=60
```

Expected: all tests PASS.

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/dependencies.py backend/app/main.py
git commit -m "feat(di): wire ConversationMemoryService and summary enqueuer"
```

---

### Task 9: Integration Test — Full Flow

**Files:**
- Create: `backend/tests/integration/test_conversation_memory.py`

- [ ] **Step 1: Write integration test**

```python
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import KnowledgeSnapshot, Message, Session
from app.db.models.enums import (
    MessageRole,
    MessageStatus,
    SessionStatus,
    SnapshotStatus,
)
from app.services.conversation_memory import ConversationMemoryService, MemoryBlock


@pytest.fixture
def memory_service() -> ConversationMemoryService:
    return ConversationMemoryService(budget=4096, summary_ratio=0.3)


@pytest.mark.asyncio
async def test_memory_block_from_real_session(
    db_session: AsyncSession,
    seeded_agent: object,
    memory_service: ConversationMemoryService,
) -> None:
    """Create a session with messages in the DB, then verify build_memory_block works."""
    session = Session(
        id=uuid.uuid7(),
        agent_id=seeded_agent.id,
        status=SessionStatus.ACTIVE,
        message_count=0,
    )
    db_session.add(session)
    await db_session.commit()

    # Add 4 messages
    messages_data = [
        (MessageRole.USER, "What is ProxyMind?", MessageStatus.RECEIVED),
        (MessageRole.ASSISTANT, "ProxyMind is a digital twin platform.", MessageStatus.COMPLETE),
        (MessageRole.USER, "How does it work?", MessageStatus.RECEIVED),
        (MessageRole.ASSISTANT, "It uses RAG to answer questions.", MessageStatus.COMPLETE),
    ]
    for role, content, status in messages_data:
        msg = Message(
            id=uuid.uuid7(),
            session_id=session.id,
            role=role,
            content=content,
            status=status,
        )
        db_session.add(msg)
        session.message_count += 1
    await db_session.commit()

    # Reload session and messages
    await db_session.refresh(session)
    result = await db_session.execute(
        select(Message)
        .where(
            Message.session_id == session.id,
            Message.status.in_([MessageStatus.RECEIVED, MessageStatus.COMPLETE]),
        )
        .order_by(Message.created_at)
    )
    db_messages = list(result.scalars().all())

    block = memory_service.build_memory_block(session=session, messages=db_messages)

    assert block.summary_text is None
    assert len(block.messages) == 4
    assert block.messages[0]["role"] == "user"
    assert block.messages[0]["content"] == "What is ProxyMind?"
    assert block.needs_summary_update is False


@pytest.mark.asyncio
async def test_summary_persisted_and_used(
    db_session: AsyncSession,
    seeded_agent: object,
    memory_service: ConversationMemoryService,
) -> None:
    """Simulate summary being written, verify it's used in next build_memory_block."""
    session = Session(
        id=uuid.uuid7(),
        agent_id=seeded_agent.id,
        status=SessionStatus.ACTIVE,
        message_count=0,
    )
    db_session.add(session)
    await db_session.commit()

    # Add messages
    msg1 = Message(
        id=uuid.uuid7(), session_id=session.id,
        role=MessageRole.USER, content="Old question", status=MessageStatus.RECEIVED,
    )
    msg2 = Message(
        id=uuid.uuid7(), session_id=session.id,
        role=MessageRole.ASSISTANT, content="Old answer", status=MessageStatus.COMPLETE,
    )
    msg3 = Message(
        id=uuid.uuid7(), session_id=session.id,
        role=MessageRole.USER, content="New question", status=MessageStatus.RECEIVED,
    )
    msg4 = Message(
        id=uuid.uuid7(), session_id=session.id,
        role=MessageRole.ASSISTANT, content="New answer", status=MessageStatus.COMPLETE,
    )
    db_session.add_all([msg1, msg2, msg3, msg4])
    session.message_count = 4
    await db_session.commit()

    # Simulate summary was generated for first 2 messages
    session.summary = "User asked an old question and got an answer."
    session.summary_token_count = 15
    session.summary_up_to_message_id = msg2.id
    await db_session.commit()

    # Reload messages
    result = await db_session.execute(
        select(Message)
        .where(
            Message.session_id == session.id,
            Message.status.in_([MessageStatus.RECEIVED, MessageStatus.COMPLETE]),
        )
        .order_by(Message.created_at)
    )
    db_messages = list(result.scalars().all())

    block = memory_service.build_memory_block(session=session, messages=db_messages)

    assert block.summary_text == "User asked an old question and got an answer."
    assert len(block.messages) == 2  # Only msg3 and msg4
    assert block.messages[0]["content"] == "New question"
    assert block.messages[1]["content"] == "New answer"
    assert block.needs_summary_update is False
```

- [ ] **Step 2: Run integration tests**

```bash
docker compose exec api python -m pytest tests/integration/test_conversation_memory.py -v
```

Expected: all tests PASS.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/integration/test_conversation_memory.py
git commit -m "test(memory): add integration tests for conversation memory"
```

---

### Task 10: Test Fixtures + Final Verification

**Files:**
- Modify: `backend/tests/conftest.py` (add mock for memory service)

- [ ] **Step 1: Add mock_memory_service fixture to conftest.py**

Add to `backend/tests/conftest.py`:

```python
from app.services.conversation_memory import ConversationMemoryService, MemoryBlock

@pytest.fixture
def mock_memory_service():
    service = MagicMock(spec=ConversationMemoryService)
    service.build_memory_block = MagicMock(
        return_value=MemoryBlock(
            summary_text=None,
            messages=[],
            total_tokens=0,
            needs_summary_update=False,
            window_start_message_id=None,
        )
    )
    return service
```

Update any `chat_app` fixtures or `get_chat_service` overrides in conftest to pass `conversation_memory_service` and `summary_enqueuer` to `ChatService`.

- [ ] **Step 2: Run full test suite**

```bash
docker compose exec api python -m pytest tests/ -v --timeout=120
```

Expected: all tests PASS.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/conftest.py
git commit -m "test: add conversation memory service mock fixtures"
```

---

### Task 11: Final Cleanup and Verification

- [ ] **Step 1: Run linters**

```bash
docker compose exec api python -m ruff check app/ tests/
docker compose exec api python -m ruff format --check app/ tests/
```

Expected: no errors.

- [ ] **Step 2: Run full test suite one more time**

```bash
docker compose exec api python -m pytest tests/ -v --timeout=120
```

Expected: all tests PASS.

- [ ] **Step 3: Verify migration applies on fresh database**

```bash
docker compose down -v
docker compose up -d
docker compose exec api alembic upgrade head
```

Expected: all migrations apply, including 010.

- [ ] **Step 4: Final commit if any changes**

```bash
git add -A
git commit -m "chore: final cleanup for conversation memory"
```
