# S4-05: Promotions + Context Assembly — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the flat `build_chat_prompt()` function with a layered `ContextAssembler`, add PROMOTIONS.md parsing with date filtering and priority selection, token budget management for retrieval context, and heuristic content type markup.

**Architecture:** A new `ContextAssembler` class orchestrates prompt construction from 8 layers (safety → identity → soul → behavior → promotions → citation instructions → content guidelines → retrieval context + query). Each layer is wrapped in XML tags. A separate `PromotionsService` parses `config/PROMOTIONS.md`. A shared `token_counter` module provides token estimation. Content type spans are computed post-response via backend heuristics.

**Tech Stack:** Python 3.14, FastAPI, Pydantic, structlog, pytest

**Spec:** `docs/superpowers/specs/2026-03-25-s4-05-promotions-context-assembly-design.md`

---

## File Structure

### New Files

| File | Responsibility |
|------|----------------|
| `backend/app/services/token_counter.py` | `estimate_tokens(text) -> int` — shared token estimation |
| `backend/app/services/promotions.py` | `PromotionsService` — parse, filter, sort, select promotions |
| `backend/app/services/context_assembler.py` | `ContextAssembler` — orchestrate all prompt layers + budget |
| `backend/app/services/content_type.py` | `compute_content_type_spans()` — heuristic span classification |
| `backend/tests/unit/test_token_counter.py` | Tests for token estimation |
| `backend/tests/unit/test_promotions.py` | Tests for PROMOTIONS.md parsing and filtering |
| `backend/tests/unit/test_context_assembler.py` | Tests for prompt layer assembly and budget trimming |
| `backend/tests/unit/test_content_type.py` | Tests for content type span heuristics |

### Modified Files

| File | Change |
|------|--------|
| `backend/app/services/query_rewrite.py` | Remove `CHARS_PER_TOKEN`, import from `token_counter` |
| `backend/app/core/config.py` | Add `retrieval_context_budget`, `max_promotions_per_response`, `promotions_file_path` |
| `backend/app/main.py` | Initialize `PromotionsService` in lifespan |
| `backend/app/api/dependencies.py` | Add `get_context_assembler()`, update `get_chat_service()` |
| `backend/app/services/chat.py` | Replace `build_chat_prompt()` calls with `ContextAssembler.assemble()`, add content type spans |
| `backend/app/services/prompt.py` | Retain `_format_chunk_header()` and `NO_CONTEXT_REFUSAL`, remove `build_chat_prompt()` |
| `backend/tests/unit/test_prompt_builder.py` | Remove tests for `build_chat_prompt()` layer ordering; keep `format_chunk_header()` and `NO_CONTEXT_REFUSAL` tests |
| `backend/tests/unit/test_chat_service.py` | Update `_make_service()` helper and `persona_context` fixture — replace `persona_context=` param with `context_assembler=` |
| `backend/tests/unit/test_chat_streaming.py` | Same as `test_chat_service.py`; also replace `build_chat_prompt` monkeypatch (line ~289) with assembler-aware equivalent |
| `backend/tests/unit/test_app_main.py` | Add assertion for `app.state.promotions_service` initialization in lifespan test |
| `backend/tests/conftest.py` | Add `app.state.promotions_service` setup alongside existing `app.state.persona_context` |
| `backend/tests/integration/test_chat_sse.py` | Add `app.state.promotions_service` setup in test fixture |
| `config/PROMOTIONS.md` | Replace template with example promotions in the spec format |

---

## Task 1: Token Counter Module

Extract the shared token estimation constant from `query_rewrite.py` into its own module.

**Files:**
- Create: `backend/app/services/token_counter.py`
- Create: `backend/tests/unit/test_token_counter.py`
- Modify: `backend/app/services/query_rewrite.py:12` (remove `CHARS_PER_TOKEN`)

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/unit/test_token_counter.py
from app.services.token_counter import estimate_tokens


def test_empty_string_returns_zero() -> None:
    assert estimate_tokens("") == 0


def test_short_string() -> None:
    # "hello" = 5 chars, 5 // 3 = 1
    assert estimate_tokens("hello") == 1


def test_longer_string() -> None:
    # "hello world" = 11 chars, 11 // 3 = 3
    assert estimate_tokens("hello world") == 3


def test_deterministic() -> None:
    text = "some test string for token estimation"
    assert estimate_tokens(text) == estimate_tokens(text)


def test_unicode_counted_by_char_length() -> None:
    # CJK: 6 chars, 6 // 3 = 2
    assert estimate_tokens("こんにちは世") == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/unit/test_token_counter.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.token_counter'`

- [ ] **Step 3: Write the implementation**

```python
# backend/app/services/token_counter.py
"""Shared token estimation utility.

Uses a character-based heuristic (1 token ≈ 3 characters) consistent
across all ProxyMind services that need approximate token counting.
Conservative for multilingual text (CJK characters have fewer chars
per token in practice, so the estimate is an overcount — safe for budgets).
"""

from __future__ import annotations

CHARS_PER_TOKEN: int = 3


def estimate_tokens(text: str) -> int:
    """Return an approximate token count for *text*."""
    if not text:
        return 0
    return len(text) // CHARS_PER_TOKEN
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/unit/test_token_counter.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Migrate query_rewrite.py to use the new module**

In `backend/app/services/query_rewrite.py`, replace line 12:

```python
# BEFORE
CHARS_PER_TOKEN = 3

# AFTER
from app.services.token_counter import CHARS_PER_TOKEN
```

- [ ] **Step 6: Run full test suite to verify no regressions**

Run: `cd backend && python -m pytest tests/unit/ -v`
Expected: All existing tests PASS (including `test_query_rewrite.py`)

- [ ] **Step 7: Commit**

```
feat(token): extract shared token estimation module

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

---

## Task 2: Promotions Service

Parse `config/PROMOTIONS.md`, filter by date, sort by priority, select top-N.

**Files:**
- Create: `backend/app/services/promotions.py`
- Create: `backend/tests/unit/test_promotions.py`
- Modify: `config/PROMOTIONS.md`

- [ ] **Step 1: Update config/PROMOTIONS.md with the spec format**

```markdown
## New Book: "AI in Practice"

- **Priority:** high
- **Valid from:** 2026-01-15
- **Valid to:** 2026-06-30
- **Context:** When the conversation touches AI, machine learning, or practical applications of neural networks.

My new book "AI in Practice" covers real-world applications of modern AI systems.
Available at the online store with a 20% launch discount.

## Upcoming Conference: Tech Summit 2026

- **Priority:** medium
- **Valid from:** 2026-03-01
- **Valid to:** 2026-04-15
- **Context:** When discussing conferences, networking, or professional development.

Join me at Tech Summit 2026 in Berlin. Early bird tickets available until April 1.
```

- [ ] **Step 2: Write the failing tests**

```python
# backend/tests/unit/test_promotions.py
from __future__ import annotations

import datetime

import pytest

from app.services.promotions import Promotion, PromotionsService


VALID_PROMOTIONS_MD = """\
## Book Launch

- **Priority:** high
- **Valid from:** 2020-01-01
- **Valid to:** 2099-12-31
- **Context:** When discussing books or reading.

Check out my new book about AI.

## Old Conference

- **Priority:** medium
- **Valid from:** 2020-01-01
- **Valid to:** 2020-06-30
- **Context:** When discussing events.

This conference already happened.

## Future Event

- **Priority:** low
- **Valid from:** 2099-01-01
- **Valid to:** 2099-12-31
- **Context:** Future event hint.

This event is far in the future.

## Always Active

- **Priority:** low

This promotion has no date bounds.
"""


def test_parse_extracts_all_sections() -> None:
    service = PromotionsService(promotions_text=VALID_PROMOTIONS_MD)
    promos = service.parse()
    assert len(promos) == 4
    assert promos[0].title == "Book Launch"
    assert promos[0].priority == "high"
    assert promos[0].body == "Check out my new book about AI."


def test_parse_extracts_dates() -> None:
    service = PromotionsService(promotions_text=VALID_PROMOTIONS_MD)
    promos = service.parse()
    assert promos[0].valid_from == datetime.date(2020, 1, 1)
    assert promos[0].valid_to == datetime.date(2099, 12, 31)


def test_parse_missing_dates_are_none() -> None:
    service = PromotionsService(promotions_text=VALID_PROMOTIONS_MD)
    promos = service.parse()
    always_active = [p for p in promos if p.title == "Always Active"][0]
    assert always_active.valid_from is None
    assert always_active.valid_to is None


def test_parse_missing_context_is_empty() -> None:
    service = PromotionsService(promotions_text=VALID_PROMOTIONS_MD)
    promos = service.parse()
    always_active = [p for p in promos if p.title == "Always Active"][0]
    assert always_active.context == ""


def test_filter_removes_expired(monkeypatch: pytest.MonkeyPatch) -> None:
    service = PromotionsService(promotions_text=VALID_PROMOTIONS_MD)
    today = datetime.date(2025, 6, 15)
    active = service.get_active(today=today)
    titles = [p.title for p in active]
    assert "Old Conference" not in titles
    assert "Book Launch" in titles


def test_filter_removes_not_yet_active() -> None:
    service = PromotionsService(promotions_text=VALID_PROMOTIONS_MD)
    today = datetime.date(2025, 6, 15)
    active = service.get_active(today=today)
    titles = [p.title for p in active]
    assert "Future Event" not in titles


def test_filter_keeps_no_date_bounds() -> None:
    service = PromotionsService(promotions_text=VALID_PROMOTIONS_MD)
    today = datetime.date(2025, 6, 15)
    active = service.get_active(today=today)
    titles = [p.title for p in active]
    assert "Always Active" in titles


def test_sort_by_priority() -> None:
    service = PromotionsService(promotions_text=VALID_PROMOTIONS_MD)
    today = datetime.date(2025, 6, 15)
    active = service.get_active(today=today)
    assert active[0].priority == "high"
    assert active[1].priority == "low"


def test_select_top_n() -> None:
    service = PromotionsService(promotions_text=VALID_PROMOTIONS_MD)
    today = datetime.date(2025, 6, 15)
    selected = service.get_active(today=today, max_promotions=1)
    assert len(selected) == 1
    assert selected[0].title == "Book Launch"


def test_empty_text_returns_empty_list() -> None:
    service = PromotionsService(promotions_text="")
    assert service.get_active() == []


def test_invalid_priority_defaults_to_low() -> None:
    md = "## Test\n\n- **Priority:** urgent\n\nBody text here."
    service = PromotionsService(promotions_text=md)
    promos = service.parse()
    assert promos[0].priority == "low"


def test_invalid_date_skips_promotion() -> None:
    md = "## Test\n\n- **Priority:** high\n- **Valid to:** not-a-date\n\nBody."
    service = PromotionsService(promotions_text=md)
    promos = service.parse()
    assert len(promos) == 0


def test_empty_body_skips_promotion() -> None:
    md = "## No Body\n\n- **Priority:** high\n"
    service = PromotionsService(promotions_text=md)
    promos = service.parse()
    assert len(promos) == 0


def test_file_loading_from_path(tmp_path) -> None:
    promo_file = tmp_path / "PROMOTIONS.md"
    promo_file.write_text("## Test Promo\n\n- **Priority:** high\n\nA body.", encoding="utf-8")
    service = PromotionsService.from_file(promo_file)
    promos = service.parse()
    assert len(promos) == 1
    assert promos[0].title == "Test Promo"


def test_file_not_found_returns_empty(tmp_path) -> None:
    service = PromotionsService.from_file(tmp_path / "missing.md")
    assert service.get_active() == []
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/unit/test_promotions.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.promotions'`

- [ ] **Step 4: Write the implementation**

```python
# backend/app/services/promotions.py
"""PROMOTIONS.md parser — reads, filters, and selects active promotions.

File format: Markdown with ``## Title`` sections. Each section contains
key-value metadata lines (``- **Key:** value``) followed by body text.
See design spec for full format definition.
"""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)

_VALID_PRIORITIES = {"high", "medium", "low"}
_PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}
_SECTION_RE = re.compile(r"^##\s+(.+)$", re.MULTILINE)
_META_RE = re.compile(r"^-\s+\*\*(.+?):\*\*\s*(.*)$", re.MULTILINE)


class _SkipSentinel:
    """Sentinel to signal that a promotion should be skipped due to parse error."""
    pass


_SKIP = _SkipSentinel


@dataclass(slots=True, frozen=True)
class Promotion:
    title: str
    priority: str  # "high" | "medium" | "low"
    valid_from: datetime.date | None
    valid_to: datetime.date | None
    context: str
    body: str


class PromotionsService:
    """Parse and filter promotions from markdown text or a file path."""

    def __init__(self, *, promotions_text: str) -> None:
        self._text = promotions_text

    @classmethod
    def from_file(cls, path: Path) -> PromotionsService:
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            logger.warning("promotions.file_not_found", path=str(path))
            text = ""
        return cls(promotions_text=text)

    def parse(self) -> list[Promotion]:
        if not self._text.strip():
            return []

        sections = self._split_sections()
        promotions: list[Promotion] = []

        for title, section_body in sections:
            promo = self._parse_section(title, section_body)
            if promo is not None:
                promotions.append(promo)

        return promotions

    def get_active(
        self,
        *,
        today: datetime.date | None = None,
        max_promotions: int | None = None,
    ) -> list[Promotion]:
        if today is None:
            today = datetime.date.today()

        all_promos = self.parse()
        active = [p for p in all_promos if self._is_active(p, today)]
        active.sort(key=lambda p: _PRIORITY_ORDER.get(p.priority, 2))
        if max_promotions is not None:
            active = active[:max_promotions]
        return active

    def _split_sections(self) -> list[tuple[str, str]]:
        matches = list(_SECTION_RE.finditer(self._text))
        if not matches:
            return []

        sections: list[tuple[str, str]] = []
        for i, match in enumerate(matches):
            title = match.group(1).strip()
            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(self._text)
            body = self._text[start:end].strip()
            sections.append((title, body))
        return sections

    def _parse_section(self, title: str, section_body: str) -> Promotion | None:
        meta: dict[str, str] = {}
        for match in _META_RE.finditer(section_body):
            key = match.group(1).strip().lower()
            value = match.group(2).strip()
            meta[key] = value

        # Extract body: everything after the last metadata line
        body_text = _META_RE.sub("", section_body).strip()

        if not body_text:
            logger.warning("promotions.empty_body", title=title)
            return None

        priority = meta.get("priority", "low").lower()
        if priority not in _VALID_PRIORITIES:
            logger.warning("promotions.invalid_priority", title=title, priority=priority)
            priority = "low"

        valid_from = self._parse_date(meta.get("valid from"), title, "valid_from")
        valid_to = self._parse_date(meta.get("valid to"), title, "valid_to")

        # If any date parsing returned the sentinel _SKIP, skip this promotion
        if valid_from is _SKIP or valid_to is _SKIP:
            return None

        context = meta.get("context", "")

        return Promotion(
            title=title,
            priority=priority,
            valid_from=valid_from,
            valid_to=valid_to,
            context=context,
            body=body_text,
        )

    @staticmethod
    def _parse_date(
        value: str | None, title: str, field: str
    ) -> datetime.date | None | type[_SKIP]:
        if not value:
            return None
        try:
            return datetime.date.fromisoformat(value)
        except ValueError:
            logger.warning(
                "promotions.invalid_date",
                title=title,
                field=field,
                value=value,
            )
            return _SKIP

    @staticmethod
    def _is_active(promo: Promotion, today: datetime.date) -> bool:
        if promo.valid_to is not None and today > promo.valid_to:
            return False
        if promo.valid_from is not None and today < promo.valid_from:
            return False
        return True


```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/unit/test_promotions.py -v`
Expected: All 15 tests PASS

- [ ] **Step 6: Commit**

```
feat(promotions): add PROMOTIONS.md parser with date filtering and priority selection

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

---

## Task 3: Configuration Changes

Add new settings for context assembly.

**Files:**
- Modify: `backend/app/core/config.py:50-53`

- [ ] **Step 1: Add new settings to config.py**

After line 52 (`max_citations_per_response`), add:

```python
    retrieval_context_budget: int = Field(default=4096, ge=1)
    max_promotions_per_response: int = Field(default=1, ge=0)
    promotions_file_path: str = Field(default=str(REPO_ROOT / "config" / "PROMOTIONS.md"))
```

- [ ] **Step 2: Run existing tests to verify no regressions**

Run: `cd backend && python -m pytest tests/unit/ -v`
Expected: All tests PASS (new fields have defaults, no breaking change)

- [ ] **Step 3: Commit**

```
feat(config): add retrieval_context_budget and promotions settings

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

---

## Task 4: Context Assembler

The core of S4-05. Orchestrates all prompt layers with XML tags and budget management.

**Files:**
- Create: `backend/app/services/context_assembler.py`
- Create: `backend/tests/unit/test_context_assembler.py`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/unit/test_context_assembler.py
from __future__ import annotations

import uuid

from app.persona.loader import PersonaContext
from app.services.citation import SourceInfo
from app.services.context_assembler import AssembledPrompt, ContextAssembler
from app.services.promotions import Promotion
from app.services.qdrant import RetrievedChunk


def _persona(
    *,
    identity: str = "I am the twin.",
    soul: str = "I speak calmly.",
    behavior: str = "I avoid politics.",
) -> PersonaContext:
    return PersonaContext(
        identity=identity,
        soul=soul,
        behavior=behavior,
        config_commit_hash="abc123",
        config_content_hash="def456",
    )


def _chunk(
    text: str, *, source_id: uuid.UUID | None = None, score: float = 0.9
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        source_id=source_id or uuid.uuid4(),
        text_content=text,
        score=score,
        anchor_metadata={
            "anchor_page": 1,
            "anchor_chapter": "Chapter",
            "anchor_section": "Section",
            "anchor_timecode": None,
        },
    )


def _source_info(source_id: uuid.UUID, *, title: str = "Test Source") -> SourceInfo:
    return SourceInfo(id=source_id, title=title, public_url=None, source_type="pdf")


def _promo(
    *,
    title: str = "Test Promo",
    priority: str = "high",
    context: str = "When relevant.",
    body: str = "Buy this product.",
) -> Promotion:
    return Promotion(
        title=title,
        priority=priority,
        valid_from=None,
        valid_to=None,
        context=context,
        body=body,
    )


def _assembler(
    *,
    persona: PersonaContext | None = None,
    promotions: list[Promotion] | None = None,
    retrieval_context_budget: int = 4096,
    max_citations: int = 5,
    min_retrieved_chunks: int = 1,
) -> ContextAssembler:
    return ContextAssembler(
        persona_context=persona or _persona(),
        active_promotions=promotions or [],
        retrieval_context_budget=retrieval_context_budget,
        max_citations=max_citations,
        min_retrieved_chunks=min_retrieved_chunks,
    )


class TestLayerOrdering:
    def test_system_message_has_xml_tags_in_order(self) -> None:
        chunk = _chunk("Some knowledge")
        source_map = {chunk.source_id: _source_info(chunk.source_id)}
        result = _assembler(promotions=[_promo()]).assemble(
            chunks=[chunk],
            query="What?",
            source_map=source_map,
        )
        system = result.messages[0]["content"]
        assert system.index("<system_safety>") < system.index("<identity>")
        assert system.index("<identity>") < system.index("<soul>")
        assert system.index("<soul>") < system.index("<behavior>")
        assert system.index("<behavior>") < system.index("<promotions>")
        assert system.index("<promotions>") < system.index("<citation_instructions>")
        assert system.index("<citation_instructions>") < system.index("<content_guidelines>")

    def test_each_tag_has_closing_tag(self) -> None:
        chunk = _chunk("Knowledge")
        source_map = {chunk.source_id: _source_info(chunk.source_id)}
        result = _assembler(promotions=[_promo()]).assemble(
            chunks=[chunk], query="Q?", source_map=source_map
        )
        system = result.messages[0]["content"]
        for tag in ["system_safety", "identity", "soul", "behavior",
                     "promotions", "citation_instructions", "content_guidelines"]:
            assert f"<{tag}>" in system
            assert f"</{tag}>" in system


class TestPromotionsLayer:
    def test_no_promotions_omits_tag(self) -> None:
        result = _assembler(promotions=[]).assemble(
            chunks=[_chunk("K")], query="Q?", source_map={}
        )
        assert "<promotions>" not in result.messages[0]["content"]

    def test_promotion_injected_with_content(self) -> None:
        result = _assembler(promotions=[_promo(body="Special offer!")]).assemble(
            chunks=[_chunk("K")], query="Q?", source_map={}
        )
        assert "Special offer!" in result.messages[0]["content"]
        assert "<promotions>" in result.messages[0]["content"]

    def test_included_promotions_in_result(self) -> None:
        promo = _promo()
        result = _assembler(promotions=[promo]).assemble(
            chunks=[_chunk("K")], query="Q?", source_map={}
        )
        assert result.included_promotions == [promo]


class TestCitationInstructions:
    def test_absent_when_no_chunks(self) -> None:
        result = _assembler().assemble(chunks=[], query="Q?", source_map={})
        assert "<citation_instructions>" not in result.messages[0]["content"]

    def test_present_when_chunks_exist(self) -> None:
        chunk = _chunk("K")
        source_map = {chunk.source_id: _source_info(chunk.source_id)}
        result = _assembler().assemble(chunks=[chunk], query="Q?", source_map=source_map)
        assert "<citation_instructions>" in result.messages[0]["content"]
        assert "[source:N]" in result.messages[0]["content"]


class TestRetrievalBudget:
    def test_all_chunks_fit_in_budget(self) -> None:
        chunks = [_chunk("short") for _ in range(3)]
        result = _assembler(retrieval_context_budget=4096).assemble(
            chunks=chunks, query="Q?", source_map={}
        )
        assert result.retrieval_chunks_used == 3
        assert result.retrieval_chunks_total == 3

    def test_chunks_trimmed_when_over_budget(self) -> None:
        # Each chunk ~1000 chars ≈ 333 tokens. Budget = 500 tokens → only 1 fits.
        chunks = [_chunk("x" * 1000, score=0.9 - i * 0.1) for i in range(3)]
        result = _assembler(retrieval_context_budget=500).assemble(
            chunks=chunks, query="Q?", source_map={}
        )
        assert result.retrieval_chunks_used < 3
        assert result.retrieval_chunks_total == 3

    def test_min_retrieved_chunks_overrides_budget(self) -> None:
        # One big chunk exceeds budget, but min_retrieved_chunks=1 forces inclusion
        chunks = [_chunk("x" * 3000)]
        result = _assembler(
            retrieval_context_budget=100, min_retrieved_chunks=1
        ).assemble(chunks=chunks, query="Q?", source_map={})
        assert result.retrieval_chunks_used == 1

    def test_all_chunks_exceed_budget_with_min_zero(self) -> None:
        # Budget is tiny, min_retrieved_chunks=0 allows LLM call without context
        chunks = [_chunk("x" * 3000)]
        result = _assembler(
            retrieval_context_budget=1, min_retrieved_chunks=0
        ).assemble(chunks=chunks, query="Q?", source_map={})
        assert result.retrieval_chunks_used == 0
        assert result.retrieval_chunks_total == 1
        # No <knowledge_context> tag in user message
        assert "<knowledge_context>" not in result.messages[1]["content"]

    def test_all_chunks_exceed_budget_with_min_one(self) -> None:
        # Budget is tiny, but min_retrieved_chunks=1 forces inclusion
        chunks = [_chunk("x" * 3000)]
        result = _assembler(
            retrieval_context_budget=1, min_retrieved_chunks=1
        ).assemble(chunks=chunks, query="Q?", source_map={})
        assert result.retrieval_chunks_used == 1


class TestUserMessage:
    def test_user_message_contains_query(self) -> None:
        result = _assembler().assemble(
            chunks=[_chunk("K")], query="Tell me about AI", source_map={}
        )
        assert "Tell me about AI" in result.messages[1]["content"]
        assert "<user_query>" in result.messages[1]["content"]

    def test_user_message_contains_knowledge_context_tag(self) -> None:
        result = _assembler().assemble(
            chunks=[_chunk("Knowledge text")], query="Q?", source_map={}
        )
        assert "<knowledge_context>" in result.messages[1]["content"]
        assert "Knowledge text" in result.messages[1]["content"]

    def test_no_knowledge_context_when_no_chunks_selected(self) -> None:
        result = _assembler(min_retrieved_chunks=0).assemble(
            chunks=[], query="Q?", source_map={}
        )
        assert "<knowledge_context>" not in result.messages[1]["content"]


class TestEmptyPersona:
    def test_empty_identity_produces_empty_tag(self) -> None:
        result = _assembler(persona=_persona(identity="")).assemble(
            chunks=[], query="Q?", source_map={}
        )
        system = result.messages[0]["content"]
        assert "<identity>" in system
        assert "</identity>" in system

    def test_all_empty_persona_still_has_safety(self) -> None:
        result = _assembler(
            persona=_persona(identity="", soul="", behavior="")
        ).assemble(chunks=[], query="Q?", source_map={})
        assert "<system_safety>" in result.messages[0]["content"]


class TestTokenEstimate:
    def test_token_estimate_is_positive(self) -> None:
        result = _assembler().assemble(
            chunks=[_chunk("Knowledge")], query="Question?", source_map={}
        )
        assert result.token_estimate > 0

    def test_layer_token_counts_populated(self) -> None:
        result = _assembler(promotions=[_promo()]).assemble(
            chunks=[_chunk("K")], query="Q?", source_map={}
        )
        assert "system_safety" in result.layer_token_counts
        assert "identity" in result.layer_token_counts
        assert "promotions" in result.layer_token_counts
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/unit/test_context_assembler.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.context_assembler'`

- [ ] **Step 3: Write the implementation**

```python
# backend/app/services/context_assembler.py
"""ContextAssembler — orchestrates all prompt layers for chat generation.

Builds the full LLM prompt from layers (safety, persona, promotions,
citation instructions, content guidelines, retrieval context, user query)
with XML tags and token budget management for retrieval context.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from app.persona.loader import PersonaContext
from app.persona.safety import SYSTEM_SAFETY_POLICY
from app.services.promotions import Promotion
from app.services.prompt import format_chunk_header, NO_CONTEXT_REFUSAL
from app.services.qdrant import RetrievedChunk
from app.services.token_counter import estimate_tokens

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.citation import SourceInfo


@dataclass(slots=True, frozen=True)
class PromptLayer:
    tag: str
    content: str
    token_estimate: int


@dataclass(slots=True, frozen=True)
class AssembledPrompt:
    messages: list[dict[str, str]]
    token_estimate: int
    included_promotions: list[Promotion]
    retrieval_chunks_used: int
    retrieval_chunks_total: int
    layer_token_counts: dict[str, int]


class ContextAssembler:
    """Build the full LLM prompt from all layers with budget management."""

    def __init__(
        self,
        *,
        persona_context: PersonaContext,
        active_promotions: list[Promotion],
        retrieval_context_budget: int = 4096,
        max_citations: int = 5,
        min_retrieved_chunks: int = 1,
    ) -> None:
        self.persona_context = persona_context
        self._promotions = active_promotions
        self._retrieval_budget = retrieval_context_budget
        self._max_citations = max_citations
        self._min_retrieved_chunks = min_retrieved_chunks

    def assemble(
        self,
        *,
        chunks: list[RetrievedChunk],
        query: str,
        source_map: dict[uuid.UUID, SourceInfo],
    ) -> AssembledPrompt:
        # Build system layers
        layers: list[PromptLayer] = [
            self._build_safety_layer(),
            self._build_persona_layer("identity", self.persona_context.identity),
            self._build_persona_layer("soul", self.persona_context.soul),
            self._build_persona_layer("behavior", self.persona_context.behavior),
        ]

        if self._promotions:
            layers.append(self._build_promotions_layer())

        # TODO(S4-06): Insert conversation memory layer here.
        # _build_memory_layer() will return a <conversation_memory> block
        # containing recent messages + summary. Budget management will trim
        # memory first (summary instead of full history), then retrieval.
        # See docs/plan.md S4-06 and docs/rag.md § Context assembly.

        has_chunks = len(chunks) > 0
        if has_chunks:
            layers.append(self._build_citation_instructions())

        layers.append(self._build_content_guidelines())

        # Build retrieval context with budget
        selected_chunks, retrieval_layer = self._build_retrieval_context(
            chunks, source_map
        )

        # Assemble system message
        system_parts = [self._wrap_tag(layer) for layer in layers]
        system_content = "\n\n".join(system_parts)

        # Assemble user message
        user_content = self._build_user_message(
            retrieval_layer, query
        )

        # Compute token estimates
        layer_token_counts: dict[str, int] = {}
        for layer in layers:
            layer_token_counts[layer.tag] = layer.token_estimate
        if retrieval_layer:
            layer_token_counts["knowledge_context"] = estimate_tokens(retrieval_layer)

        total_tokens = estimate_tokens(system_content) + estimate_tokens(user_content)

        return AssembledPrompt(
            messages=[
                {"role": "system", "content": system_content},
                {"role": "user", "content": user_content},
            ],
            token_estimate=total_tokens,
            included_promotions=list(self._promotions),
            retrieval_chunks_used=len(selected_chunks),
            retrieval_chunks_total=len(chunks),
            layer_token_counts=layer_token_counts,
        )

    def _build_safety_layer(self) -> PromptLayer:
        return PromptLayer(
            tag="system_safety",
            content=SYSTEM_SAFETY_POLICY,
            token_estimate=estimate_tokens(SYSTEM_SAFETY_POLICY),
        )

    def _build_persona_layer(self, tag: str, content: str) -> PromptLayer:
        return PromptLayer(
            tag=tag,
            content=content,
            token_estimate=estimate_tokens(content),
        )

    def _build_promotions_layer(self) -> PromptLayer:
        promo = self._promotions[0]  # max_promotions_per_response already applied
        parts = [
            "You have one active promotion below. Mention it ONLY when it is naturally",
            "relevant to the conversation topic. Do not force or shoehorn it.",
            "Never mention more than one promotion per response.",
            "If the promotion is not relevant to the current question, do not mention it at all.",
            "",
            f"Title: {promo.title}",
        ]
        if promo.context:
            parts.append(f"Context hint: {promo.context}")
        parts.append(f"Details: {promo.body}")
        content = "\n".join(parts)
        return PromptLayer(
            tag="promotions",
            content=content,
            token_estimate=estimate_tokens(content),
        )

    def _build_citation_instructions(self) -> PromptLayer:
        content = (
            "Retrieved knowledge chunks are labeled [1], [2], etc.\n"
            "When your response uses information from a chunk, cite it as [source:N]\n"
            "where N is the chunk number. Rules:\n"
            "- Cite only chunks you actually use.\n"
            "- Place citations inline, immediately after the relevant statement.\n"
            "- Never generate URLs — only use [source:N] markers.\n"
            f"- Maximum {self._max_citations} citations per response."
        )
        return PromptLayer(
            tag="citation_instructions",
            content=content,
            token_estimate=estimate_tokens(content),
        )

    def _build_content_guidelines(self) -> PromptLayer:
        content = (
            "Your response may contain three types of content:\n"
            "- Facts supported by retrieved sources — always cite with [source:N].\n"
            "- Inferences you derive from your knowledge — present as reasoning, not fact.\n"
            "- A recommendation from your active promotion — weave naturally if relevant.\n"
            "Keep these types distinct. Do not present inferences as sourced facts."
        )
        return PromptLayer(
            tag="content_guidelines",
            content=content,
            token_estimate=estimate_tokens(content),
        )

    def _build_retrieval_context(
        self,
        chunks: list[RetrievedChunk],
        source_map: dict[uuid.UUID, SourceInfo],
    ) -> tuple[list[RetrievedChunk], str]:
        if not chunks:
            return [], ""

        selected: list[RetrievedChunk] = []
        formatted_chunks: list[str] = []
        accumulated_tokens = 0

        for index, chunk in enumerate(chunks, start=1):
            header = format_chunk_header(index, chunk, source_map)
            formatted = f"{header}\n{chunk.text_content}"
            chunk_tokens = estimate_tokens(formatted)

            if accumulated_tokens + chunk_tokens > self._retrieval_budget:
                # Check min_retrieved_chunks override
                if len(selected) < self._min_retrieved_chunks:
                    selected.append(chunk)
                    formatted_chunks.append(formatted)
                    accumulated_tokens += chunk_tokens
                    continue
                break

            selected.append(chunk)
            formatted_chunks.append(formatted)
            accumulated_tokens += chunk_tokens

        # Ensure min_retrieved_chunks from the front if budget was too tight
        # but we still have available chunks
        while len(selected) < self._min_retrieved_chunks and len(selected) < len(chunks):
            index = len(selected) + 1
            chunk = chunks[len(selected)]
            header = format_chunk_header(index, chunk, source_map)
            formatted = f"{header}\n{chunk.text_content}"
            selected.append(chunk)
            formatted_chunks.append(formatted)

        return selected, "\n\n".join(formatted_chunks)

    @staticmethod
    def _build_user_message(retrieval_context: str, query: str) -> str:
        parts: list[str] = []
        if retrieval_context:
            parts.append(f"<knowledge_context>\n{retrieval_context}\n</knowledge_context>")
        parts.append(f"<user_query>\n{query}\n</user_query>")
        return "\n\n".join(parts)

    @staticmethod
    def _wrap_tag(layer: PromptLayer) -> str:
        return f"<{layer.tag}>\n{layer.content}\n</{layer.tag}>"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/unit/test_context_assembler.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```
feat(prompt): add ContextAssembler with layered XML prompt and budget management

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

---

## Task 5: Content Type Spans

Heuristic post-processing to classify response fragments as fact/inference/promo.

**Files:**
- Create: `backend/app/services/content_type.py`
- Create: `backend/tests/unit/test_content_type.py`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/unit/test_content_type.py
from __future__ import annotations

from app.services.content_type import ContentTypeSpan, compute_content_type_spans
from app.services.promotions import Promotion


def _promo(*, title: str = "AI Book", body: str = "Buy the AI Book today") -> Promotion:
    return Promotion(
        title=title, priority="high", valid_from=None,
        valid_to=None, context="", body=body,
    )


def test_citation_marks_fact() -> None:
    text = "The sky is blue [source:1]. It is nice outside."
    spans = compute_content_type_spans(text, promotions=[])
    fact_spans = [s for s in spans if s.type == "fact"]
    assert len(fact_spans) >= 1
    assert "blue [source:1]" in text[fact_spans[0].start : fact_spans[0].end]


def test_plain_text_marks_inference() -> None:
    text = "I think this is interesting."
    spans = compute_content_type_spans(text, promotions=[])
    assert len(spans) == 1
    assert spans[0].type == "inference"
    assert spans[0].start == 0
    assert spans[0].end == len(text)


def test_promo_keywords_mark_promo() -> None:
    text = "You should check out the AI Book today."
    spans = compute_content_type_spans(text, promotions=[_promo()])
    promo_spans = [s for s in spans if s.type == "promo"]
    assert len(promo_spans) >= 1


def test_citation_wins_over_promo() -> None:
    text = "The AI Book covers this topic [source:1]."
    spans = compute_content_type_spans(text, promotions=[_promo()])
    matching = [s for s in spans if text[s.start : s.end].strip().endswith("[source:1].")]
    assert all(s.type == "fact" for s in matching)


def test_single_keyword_not_enough_for_promo() -> None:
    # Only "AI" matches — not enough (need ≥2)
    text = "AI is transforming the world."
    spans = compute_content_type_spans(text, promotions=[_promo()])
    assert all(s.type != "promo" for s in spans)


def test_adjacent_same_type_merged() -> None:
    text = "First inference. Second inference."
    spans = compute_content_type_spans(text, promotions=[])
    assert len(spans) == 1
    assert spans[0].type == "inference"


def test_empty_text_returns_empty() -> None:
    spans = compute_content_type_spans("", promotions=[])
    assert spans == []


def test_full_coverage() -> None:
    text = "Facts here [source:1]. And some thinking. Buy the AI Book today."
    spans = compute_content_type_spans(text, promotions=[_promo()])
    # Union of all spans should cover the full text
    covered = set()
    for span in spans:
        covered.update(range(span.start, span.end))
    assert covered == set(range(len(text)))


def test_no_promotions_skips_promo_matching() -> None:
    text = "You should check out the AI Book today."
    spans = compute_content_type_spans(text, promotions=[])
    assert all(s.type != "promo" for s in spans)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/unit/test_content_type.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.content_type'`

- [ ] **Step 3: Write the implementation**

```python
# backend/app/services/content_type.py
"""Heuristic content type markup for response fragments.

Classifies each sentence as fact (has citation), promo (matches promotion
keywords), or inference (everything else). Produces character-level spans
for storage in message.content_type_spans.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.services.promotions import Promotion

_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+|$")
_CITATION_RE = re.compile(r"\[source:\d+\]")
# Words shorter than 3 chars are excluded from keyword matching (stopwords)
_MIN_KEYWORD_LENGTH = 3
_MIN_KEYWORD_MATCHES = 2


@dataclass(slots=True, frozen=True)
class ContentTypeSpan:
    start: int
    end: int
    type: str  # "fact" | "inference" | "promo"


def compute_content_type_spans(
    text: str,
    *,
    promotions: list[Promotion],
) -> list[ContentTypeSpan]:
    if not text:
        return []

    sentences = _split_sentences(text)
    if not sentences:
        return []

    promo_keywords = _extract_promo_keywords(promotions) if promotions else set()

    raw_spans: list[ContentTypeSpan] = []
    for start, end in sentences:
        sentence_text = text[start:end]
        span_type = _classify_sentence(sentence_text, promo_keywords)
        raw_spans.append(ContentTypeSpan(start=start, end=end, type=span_type))

    return _merge_adjacent(raw_spans)


def _split_sentences(text: str) -> list[tuple[int, int]]:
    """Split text into (start, end) character ranges per sentence."""
    sentences: list[tuple[int, int]] = []
    pos = 0
    for match in _SENTENCE_RE.finditer(text):
        end = match.start()
        if end > pos:
            sentences.append((pos, end))
        pos = match.end()
    # Catch trailing text after last split
    if pos < len(text):
        sentences.append((pos, len(text)))
    # If no sentences found, treat entire text as one
    if not sentences and text.strip():
        sentences.append((0, len(text)))
    return sentences


def _classify_sentence(sentence: str, promo_keywords: set[str]) -> str:
    if _CITATION_RE.search(sentence):
        return "fact"
    if promo_keywords and _matches_promo(sentence, promo_keywords):
        return "promo"
    return "inference"


def _matches_promo(sentence: str, keywords: set[str]) -> bool:
    sentence_lower = sentence.lower()
    matches = sum(1 for kw in keywords if kw in sentence_lower)
    return matches >= _MIN_KEYWORD_MATCHES


def _extract_promo_keywords(promotions: list[Promotion]) -> set[str]:
    keywords: set[str] = set()
    for promo in promotions:
        words = re.findall(r"\w+", f"{promo.title} {promo.body}")
        for word in words:
            if len(word) >= _MIN_KEYWORD_LENGTH:
                keywords.add(word.lower())
    return keywords


def _merge_adjacent(spans: list[ContentTypeSpan]) -> list[ContentTypeSpan]:
    if not spans:
        return []

    merged: list[ContentTypeSpan] = [spans[0]]
    for span in spans[1:]:
        last = merged[-1]
        if span.type == last.type:
            merged[-1] = ContentTypeSpan(start=last.start, end=span.end, type=last.type)
        else:
            # Extend last span to cover whitespace gap
            if span.start > last.end:
                merged[-1] = ContentTypeSpan(start=last.start, end=span.start, type=last.type)
            merged.append(span)

    # Ensure last span covers to end of text
    return merged
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/unit/test_content_type.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```
feat(content-type): add heuristic content type span classification

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

---

## Task 6: Wire Into Chat Pipeline

Connect all new components into the existing chat flow.

**Files:**
- Modify: `backend/app/main.py:155-159`
- Modify: `backend/app/api/dependencies.py:83-117`
- Modify: `backend/app/services/chat.py:20,96-116,217-224,389-412,424-447`
- Modify: `backend/app/services/prompt.py` (remove `build_chat_prompt`, keep helpers)
- Modify: `backend/tests/unit/test_prompt_builder.py` (remove `build_chat_prompt` tests, keep chunk header tests)
- Modify: `backend/tests/unit/test_chat_service.py` (update `_make_service()` and persona fixture for ContextAssembler)
- Modify: `backend/tests/unit/test_chat_streaming.py` (same + update `build_chat_prompt` monkeypatch)
- Modify: `backend/tests/unit/test_app_main.py` (add promotions_service lifespan assertion)
- Modify: `backend/tests/conftest.py` (add `app.state.promotions_service` setup)
- Modify: `backend/tests/integration/test_chat_sse.py` (add `app.state.promotions_service` setup)

- [ ] **Step 1: Initialize PromotionsService in main.py lifespan**

After `app.state.persona_context = persona_loader.load()` (line 159), add:

```python
        from app.services.promotions import PromotionsService
        app.state.promotions_service = PromotionsService.from_file(
            Path(settings.promotions_file_path)
        )
```

The `promotions_file_path` setting defaults to an absolute path via `REPO_ROOT` (same pattern as `persona_dir` and `config_dir`), so no relative path resolution is needed at startup.

- [ ] **Step 2: Add dependency injection for ContextAssembler**

In `backend/app/api/dependencies.py`, add:

```python
from app.services.context_assembler import ContextAssembler
from app.services.promotions import PromotionsService


def get_promotions_service(request: Request) -> PromotionsService:
    return request.app.state.promotions_service


def get_context_assembler(
    request: Request,
    persona_context: Annotated[PersonaContext, Depends(get_persona_context)],
    promotions_service: Annotated[PromotionsService, Depends(get_promotions_service)],
) -> ContextAssembler:
    settings = request.app.state.settings
    active_promos = promotions_service.get_active(
        max_promotions=settings.max_promotions_per_response,
    )
    return ContextAssembler(
        persona_context=persona_context,
        active_promotions=active_promos,
        retrieval_context_budget=settings.retrieval_context_budget,
        max_citations=settings.max_citations_per_response,
        min_retrieved_chunks=settings.min_retrieved_chunks,
    )
```

Update `get_chat_service()` — replace `persona_context` parameter with `context_assembler`:

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
) -> ChatService:
    from app.services.chat import ChatService

    return ChatService(
        session=session,
        snapshot_service=snapshot_service,
        retrieval_service=retrieval_service,
        llm_service=llm_service,
        query_rewrite_service=query_rewrite_service,
        context_assembler=context_assembler,
        min_retrieved_chunks=request.app.state.settings.min_retrieved_chunks,
        max_citations_per_response=request.app.state.settings.max_citations_per_response,
    )
```

- [ ] **Step 3: Update ChatService constructor and methods**

In `backend/app/services/chat.py`:

Update imports — replace `build_chat_prompt` import:

```python
# Remove:
from app.services.prompt import NO_CONTEXT_REFUSAL, build_chat_prompt

# Add:
from app.services.prompt import NO_CONTEXT_REFUSAL
from app.services.context_assembler import ContextAssembler
from app.services.content_type import compute_content_type_spans
```

Update `__init__` — replace `persona_context` with `context_assembler`:

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
) -> None:
    # ...
    self._context_assembler = context_assembler
    # Remove: self._persona_context = persona_context
```

Access persona hashes through the assembler's public `persona_context` attribute:

```python
@property
def _persona_context(self) -> PersonaContext:
    return self._context_assembler.persona_context
```

Update `stream_answer()` — replace `build_chat_prompt()` call (around line 407):

```python
# BEFORE:
prompt = build_chat_prompt(
    text,
    retrieved_chunks,
    self._persona_context,
    source_map=source_map,
)

# AFTER:
assembled = self._context_assembler.assemble(
    chunks=retrieved_chunks,
    query=text,
    source_map=source_map,
)
prompt = assembled.messages
```

After citations are extracted and before commit (around line 435), add content type spans:

```python
assistant_message.content_type_spans = [
    {"start": s.start, "end": s.end, "type": s.type}
    for s in compute_content_type_spans(
        assistant_message.content,
        promotions=assembled.included_promotions,
    )
]
```

Apply the same changes to the `answer()` method (non-streaming path, around line 217).

- [ ] **Step 4: Simplify prompt.py**

Remove `build_chat_prompt()` function and `CITATION_INSTRUCTIONS` constant from `backend/app/services/prompt.py`. Rename `_format_chunk_header` to `format_chunk_header` (now imported by `ContextAssembler`). Keep `format_chunk_header()` and `NO_CONTEXT_REFUSAL`.

- [ ] **Step 5: Update test_prompt_builder.py**

Remove tests that tested `build_chat_prompt()` layer ordering and persona injection — these are now covered by `test_context_assembler.py`. Specifically, remove these tests:
- `test_system_message_starts_with_safety_policy`
- `test_system_message_contains_persona_layers_in_order`
- `test_empty_persona_fields_are_skipped`
- `test_all_empty_persona_still_has_safety_policy`
- `test_adversarial_persona_content_still_keeps_safety_policy_first`
- `test_build_chat_prompt_includes_context_and_question`
- `test_build_chat_prompt_supports_multiple_chunks`
- `test_build_chat_prompt_omits_context_block_for_empty_chunks`
- `test_citation_instructions_present_when_chunks_and_source_map`
- `test_citation_instructions_present_when_source_map_is_empty_dict`
- `test_citation_instructions_absent_when_source_map_none`

Keep these tests (update import from `_format_chunk_header` to `format_chunk_header`):
- `test_chunk_format_with_source_map`
- `test_chunk_format_includes_anchor_metadata_when_available`
- `test_no_context_refusal_constant_exists`

- [ ] **Step 6: Update test_chat_service.py and test_chat_streaming.py**

Both files have a `_make_service()` helper and `persona_context` fixture that create `ChatService` with `persona_context=` parameter. Update:

1. In `_make_service()` helper: replace `persona_context` param with `context_assembler`. Create a minimal `ContextAssembler` using the fixture persona_context:

```python
from app.services.context_assembler import ContextAssembler

# In _make_service():
context_assembler = ContextAssembler(
    persona_context=persona_context,
    active_promotions=[],
    retrieval_context_budget=4096,
    max_citations=5,
    min_retrieved_chunks=1,
)
# Pass to ChatService:
ChatService(..., context_assembler=context_assembler, ...)
```

2. In `test_chat_streaming.py` line ~289: replace `build_chat_prompt` monkeypatch with assembler-aware approach (monkeypatch `ContextAssembler.assemble` or capture calls to `LLMService.stream`).

3. Verify all existing test assertions for `config_commit_hash` and `config_content_hash` still pass — these flow through `context_assembler.persona_context` → `ChatService._persona_context` property.

- [ ] **Step 7: Update test_app_main.py and conftest.py**

In `test_app_main.py`: add assertion that `app.state.promotions_service` is initialized in the lifespan test.

In `tests/conftest.py` and `tests/integration/test_chat_sse.py`: add `app.state.promotions_service` setup alongside existing `app.state.persona_context`:

```python
from app.services.promotions import PromotionsService
app.state.promotions_service = PromotionsService(promotions_text="")
```

- [ ] **Step 8: Run the full test suite**

Run: `cd backend && python -m pytest tests/unit/ -v`
Expected: All tests PASS (including config hash assertions in chat tests)

- [ ] **Step 9: Commit**

```
feat(chat): wire ContextAssembler and content type spans into chat pipeline (S4-05)

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

---

## Task 7: Integration Verification

End-to-end verification that all pieces work together.

**Files:**
- All files from Tasks 1-6

- [ ] **Step 1: Run full unit test suite**

Run: `cd backend && python -m pytest tests/unit/ -v --tb=short`
Expected: All tests PASS

- [ ] **Step 2: Run linter**

Run: `cd backend && ruff check app/ tests/`
Expected: No errors

- [ ] **Step 3: Run type check (if configured)**

Run: `cd backend && python -m mypy app/services/token_counter.py app/services/promotions.py app/services/context_assembler.py app/services/content_type.py --ignore-missing-imports`
Expected: No errors

- [ ] **Step 4: Verify PROMOTIONS.md example parses correctly**

Run: `cd backend && python -c "from app.services.promotions import PromotionsService; from pathlib import Path; s = PromotionsService.from_file(Path('../config/PROMOTIONS.md')); print(s.get_active())"`
Expected: Prints active promotions list

- [ ] **Step 5: Final commit (if any fixes)**

```
fix(s4-05): address integration issues

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```
