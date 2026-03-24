# S4-03: Citation Builder — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a citation builder that extracts `[source:N]` markers from LLM output, resolves them to structured citations (URL or text), and delivers them via SSE `citations` event.

**Architecture:** Post-stream extraction — after LLM finishes streaming, a stateless `CitationService` parses markers from accumulated content, maps them to source metadata (batch-loaded from PG), and emits a single `citations` SSE event before `done`. Original LLM output stored as-is; structured citations stored in `Message.citations` JSONB.

**Tech Stack:** Python, FastAPI, SQLAlchemy, regex, pytest

**Spec:** `docs/superpowers/specs/2026-03-24-s4-03-citation-builder-design.md`

**Dev standards:** `docs/development.md` — read before writing code, self-review after.

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `backend/app/services/citation.py` | CitationService (stateless): parse markers, build Citation objects, format text citations |
| Modify | `backend/app/services/prompt.py` | Citation instructions in system prompt, new chunk format with titles/anchors |
| Modify | `backend/app/services/chat.py` | Wire citation service: batch load sources, extract citations, emit SSE event, persist, update replay |
| Modify | `backend/app/api/chat.py` | Handle `ChatStreamCitations` event → SSE serialization |
| Modify | `backend/app/api/chat_schemas.py` | Add `CitationResponse` schema, add `citations` to `MessageResponse` + `MessageInHistory` |
| Modify | `backend/tests/conftest.py` | Add `max_citations_per_response` to `chat_app` fixture settings |
| Modify | `backend/app/core/config.py` | Add `max_citations_per_response` setting |
| Modify | `backend/app/api/dependencies.py` | Pass `max_citations_per_response` to `ChatService` |
| Modify | `docs/spec.md` | Update citation protocol: `[source_id:42]` → `[source:N]` |
| Modify | `docs/rag.md` | Update citation protocol: `[source_id:N]` → `[source:N]` |
| Create | `backend/tests/unit/test_citation_service.py` | Unit tests for CitationService |
| Modify | `backend/tests/unit/test_prompt_builder.py` | Update tests for new prompt format |
| Modify | `backend/tests/unit/test_chat_streaming.py` | Add citation-related streaming tests |
| Modify | `backend/tests/integration/test_chat_sse.py` | Integration test: SSE citations event end-to-end |

---

## Task 1: Add `max_citations_per_response` config setting

**Files:**
- Modify: `backend/app/core/config.py`
- Test: `backend/tests/unit/test_config.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/unit/test_config.py`:

```python
def test_max_citations_per_response_default():
    settings = Settings(
        postgres_host="localhost",
        qdrant_host="localhost",
        seaweedfs_host="localhost",
        redis_host="localhost",
    )
    assert settings.max_citations_per_response == 5


def test_max_citations_per_response_custom():
    settings = Settings(
        postgres_host="localhost",
        qdrant_host="localhost",
        seaweedfs_host="localhost",
        redis_host="localhost",
        max_citations_per_response=10,
    )
    assert settings.max_citations_per_response == 10
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/unit/test_config.py::test_max_citations_per_response_default -v`
Expected: FAIL — `max_citations_per_response` not in Settings

- [ ] **Step 3: Write minimal implementation**

In `backend/app/core/config.py`, add to the Settings class (near `min_retrieved_chunks`):

```python
max_citations_per_response: int = Field(default=5, ge=1)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/unit/test_config.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```
feat(config): add max_citations_per_response setting (S4-03)
```

---

## Task 2: Create CitationService with SourceInfo and Citation dataclasses

**Files:**
- Create: `backend/app/services/citation.py`
- Create: `backend/tests/unit/test_citation_service.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/unit/test_citation_service.py`:

```python
from __future__ import annotations

import uuid

import pytest

from app.services.citation import Citation, CitationService, SourceInfo
from app.services.qdrant import RetrievedChunk


def _source_info(
    source_id: uuid.UUID,
    title: str = "Test Source",
    public_url: str | None = None,
    source_type: str = "pdf",
) -> SourceInfo:
    return SourceInfo(
        id=source_id,
        title=title,
        public_url=public_url,
        source_type=source_type,
    )


def _chunk(
    source_id: uuid.UUID,
    text: str = "chunk text",
    anchor_page: int | None = None,
    anchor_chapter: str | None = None,
    anchor_section: str | None = None,
    anchor_timecode: str | None = None,
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        source_id=source_id,
        text_content=text,
        score=0.9,
        anchor_metadata={
            "anchor_page": anchor_page,
            "anchor_chapter": anchor_chapter,
            "anchor_section": anchor_section,
            "anchor_timecode": anchor_timecode,
        },
    )


class TestCitationServiceExtract:
    def test_happy_path_single_citation(self):
        sid = uuid.uuid4()
        chunks = [_chunk(sid, anchor_page=42, anchor_chapter="Chapter 5")]
        source_map = {sid: _source_info(sid, title="Clean Architecture")}
        content = "According to the book [source:1], clean code matters."

        result = CitationService.extract(content, chunks, source_map, max_citations=5)

        assert len(result) == 1
        c = result[0]
        assert c.index == 1
        assert c.source_id == sid
        assert c.source_title == "Clean Architecture"
        assert c.url is None
        assert c.anchor["page"] == 42
        assert c.anchor["chapter"] == "Chapter 5"

    def test_multiple_citations(self):
        sid1, sid2 = uuid.uuid4(), uuid.uuid4()
        chunks = [_chunk(sid1), _chunk(sid2)]
        source_map = {
            sid1: _source_info(sid1, title="Source A"),
            sid2: _source_info(sid2, title="Source B"),
        }
        content = "First [source:1] and second [source:2]."

        result = CitationService.extract(content, chunks, source_map, max_citations=5)

        assert len(result) == 2
        assert result[0].index == 1
        assert result[1].index == 2

    def test_invalid_index_ignored(self):
        sid = uuid.uuid4()
        chunks = [_chunk(sid)]
        source_map = {sid: _source_info(sid)}
        content = "Valid [source:1] and invalid [source:99]."

        result = CitationService.extract(content, chunks, source_map, max_citations=5)

        assert len(result) == 1
        assert result[0].index == 1

    def test_no_markers_returns_empty(self):
        sid = uuid.uuid4()
        chunks = [_chunk(sid)]
        source_map = {sid: _source_info(sid)}
        content = "No citations here."

        result = CitationService.extract(content, chunks, source_map, max_citations=5)

        assert result == []

    def test_deduplication_by_source_id(self):
        sid = uuid.uuid4()
        chunks = [
            _chunk(sid, anchor_page=10),
            _chunk(sid, anchor_page=20),
        ]
        source_map = {sid: _source_info(sid)}
        content = "First [source:1] then [source:2]."

        result = CitationService.extract(content, chunks, source_map, max_citations=5)

        assert len(result) == 1
        assert result[0].anchor["page"] == 10  # first occurrence

    def test_max_citations_truncation(self):
        sids = [uuid.uuid4() for _ in range(5)]
        chunks = [_chunk(s) for s in sids]
        source_map = {s: _source_info(s, title=f"S{i}") for i, s in enumerate(sids)}
        content = "[source:1] [source:2] [source:3] [source:4] [source:5]"

        result = CitationService.extract(content, chunks, source_map, max_citations=3)

        assert len(result) == 3
        assert [c.index for c in result] == [1, 2, 3]

    def test_source_not_in_map_skipped(self):
        sid = uuid.uuid4()
        chunks = [_chunk(sid)]
        source_map = {}  # empty — source was deleted
        content = "Citation [source:1]."

        result = CitationService.extract(content, chunks, source_map, max_citations=5)

        assert result == []

    def test_online_source_has_url(self):
        sid = uuid.uuid4()
        chunks = [_chunk(sid)]
        source_map = {sid: _source_info(sid, public_url="https://example.com/book")}
        content = "See [source:1]."

        result = CitationService.extract(content, chunks, source_map, max_citations=5)

        assert result[0].url == "https://example.com/book"

    def test_zero_index_ignored(self):
        sid = uuid.uuid4()
        chunks = [_chunk(sid)]
        source_map = {sid: _source_info(sid)}
        content = "Bad ref [source:0]."

        result = CitationService.extract(content, chunks, source_map, max_citations=5)

        assert result == []


class TestTextCitation:
    def test_full_anchor(self):
        sid = uuid.uuid4()
        chunks = [_chunk(sid, anchor_page=42, anchor_chapter="Chapter 5", anchor_section="Interfaces")]
        source_map = {sid: _source_info(sid, title="Clean Architecture")}
        content = "[source:1]"

        result = CitationService.extract(content, chunks, source_map, max_citations=5)

        assert '"Clean Architecture"' in result[0].text_citation
        assert "Chapter 5" in result[0].text_citation
        assert "p. 42" in result[0].text_citation

    def test_title_only(self):
        sid = uuid.uuid4()
        chunks = [_chunk(sid)]
        source_map = {sid: _source_info(sid, title="README")}
        content = "[source:1]"

        result = CitationService.extract(content, chunks, source_map, max_citations=5)

        assert result[0].text_citation == '"README"'

    def test_timecode_anchor(self):
        sid = uuid.uuid4()
        chunks = [_chunk(sid, anchor_timecode="01:23:45")]
        source_map = {sid: _source_info(sid, title="Podcast Episode 12", source_type="audio")}
        content = "[source:1]"

        result = CitationService.extract(content, chunks, source_map, max_citations=5)

        assert "01:23:45" in result[0].text_citation


class TestCitationToDict:
    def test_to_dict_structure(self):
        sid = uuid.uuid4()
        chunks = [_chunk(sid, anchor_page=1)]
        source_map = {sid: _source_info(sid, title="Test", public_url="https://x.com")}
        content = "[source:1]"

        result = CitationService.extract(content, chunks, source_map, max_citations=5)
        d = result[0].to_dict()

        assert d["index"] == 1
        assert d["source_id"] == str(sid)
        assert d["source_title"] == "Test"
        assert d["source_type"] == "pdf"
        assert d["url"] == "https://x.com"
        assert isinstance(d["anchor"], dict)
        assert isinstance(d["text_citation"], str)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/unit/test_citation_service.py -v`
Expected: FAIL — `app.services.citation` does not exist

- [ ] **Step 3: Write minimal implementation**

Create `backend/app/services/citation.py`:

```python
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from app.services.qdrant import RetrievedChunk

_CITATION_PATTERN = re.compile(r"\[source:(\d+)\]")


@dataclass(slots=True, frozen=True)
class SourceInfo:
    id: uuid.UUID
    title: str
    public_url: str | None
    source_type: str


@dataclass(slots=True, frozen=True)
class Citation:
    index: int
    source_id: uuid.UUID
    source_title: str
    source_type: str
    url: str | None
    anchor: dict[str, int | str | None]
    text_citation: str

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "source_id": str(self.source_id),
            "source_title": self.source_title,
            "source_type": self.source_type,
            "url": self.url,
            "anchor": self.anchor,
            "text_citation": self.text_citation,
        }


def _build_text_citation(title: str, anchor: dict[str, int | str | None]) -> str:
    parts = [f'"{title}"']
    chapter = anchor.get("chapter")
    section = anchor.get("section")
    page = anchor.get("page")
    timecode = anchor.get("timecode")

    if chapter:
        parts.append(str(chapter))
    if section and not chapter:
        parts.append(str(section))
    if page is not None:
        parts.append(f"p. {page}")

    result = ", ".join(parts)
    if timecode:
        result += f" at {timecode}"
    return result


class CitationService:
    @staticmethod
    def extract(
        content: str,
        chunks: list[RetrievedChunk],
        source_map: dict[uuid.UUID, SourceInfo],
        max_citations: int,
    ) -> list[Citation]:
        matches = _CITATION_PATTERN.findall(content)
        if not matches:
            return []

        seen_source_ids: set[uuid.UUID] = set()
        citations: list[Citation] = []

        for index_str in dict.fromkeys(matches):
            index = int(index_str)
            if index < 1 or index > len(chunks):
                continue

            chunk = chunks[index - 1]
            if chunk.source_id in seen_source_ids:
                continue

            info = source_map.get(chunk.source_id)
            if info is None:
                continue

            seen_source_ids.add(chunk.source_id)

            anchor = {
                "page": chunk.anchor_metadata.get("anchor_page"),
                "chapter": chunk.anchor_metadata.get("anchor_chapter"),
                "section": chunk.anchor_metadata.get("anchor_section"),
                "timecode": chunk.anchor_metadata.get("anchor_timecode"),
            }

            citations.append(
                Citation(
                    index=index,
                    source_id=chunk.source_id,
                    source_title=info.title,
                    source_type=info.source_type,
                    url=info.public_url,
                    anchor=anchor,
                    text_citation=_build_text_citation(info.title, anchor),
                )
            )

            if len(citations) >= max_citations:
                break

        return citations
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/unit/test_citation_service.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```
feat(citation): add CitationService with marker parsing and text citation formatting (S4-03)
```

---

## Task 3: Update prompt builder with citation instructions and new chunk format

**Files:**
- Modify: `backend/app/services/prompt.py`
- Modify: `backend/tests/unit/test_prompt_builder.py`

- [ ] **Step 1: Write the failing tests**

Add to or update `backend/tests/unit/test_prompt_builder.py`:

```python
import uuid

from app.services.citation import SourceInfo
from app.services.prompt import build_chat_prompt
from app.services.qdrant import RetrievedChunk


def _chunk(source_id=None, text="chunk text", score=0.9, **anchor_kwargs):
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        source_id=source_id or uuid.uuid4(),
        text_content=text,
        score=score,
        anchor_metadata={
            "anchor_page": anchor_kwargs.get("anchor_page"),
            "anchor_chapter": anchor_kwargs.get("anchor_chapter"),
            "anchor_section": anchor_kwargs.get("anchor_section"),
            "anchor_timecode": anchor_kwargs.get("anchor_timecode"),
        },
    )


def _source_info(source_id, title="Test", public_url=None):
    return SourceInfo(id=source_id, title=title, public_url=public_url, source_type="pdf")


class TestCitationInstructions:
    def test_citation_instructions_present_when_chunks_and_source_map(self, persona_context):
        sid = uuid.uuid4()
        chunks = [_chunk(source_id=sid)]
        source_map = {sid: _source_info(sid)}
        messages = build_chat_prompt("query", chunks, persona_context, source_map=source_map)
        system_content = messages[0]["content"]

        assert "[source:N]" in system_content
        assert "Do not generate URLs" in system_content

    def test_citation_instructions_absent_when_no_chunks(self, persona_context):
        messages = build_chat_prompt("query", [], persona_context, source_map={})
        system_content = messages[0]["content"]

        assert "[source:N]" not in system_content

    def test_citation_instructions_absent_when_source_map_none(self, persona_context):
        sid = uuid.uuid4()
        chunks = [_chunk(source_id=sid)]
        messages = build_chat_prompt("query", chunks, persona_context)
        system_content = messages[0]["content"]

        assert "[source:N]" not in system_content


class TestNewChunkFormat:
    def test_chunk_format_with_source_map(self, persona_context):
        sid = uuid.uuid4()
        chunks = [_chunk(source_id=sid, anchor_page=42, anchor_chapter="Chapter 5")]
        source_map = {sid: _source_info(sid, title="Clean Architecture")}
        messages = build_chat_prompt("query", chunks, persona_context, source_map=source_map)
        user_content = messages[1]["content"]

        assert "[Source 1]" in user_content
        assert "Clean Architecture" in user_content
        assert "Chapter 5" in user_content
        assert "page: 42" in user_content
        assert "score=" not in user_content

    def test_legacy_format_when_source_map_none(self, persona_context):
        sid = uuid.uuid4()
        chunks = [_chunk(source_id=sid)]
        messages = build_chat_prompt("query", chunks, persona_context)
        user_content = messages[1]["content"]

        assert "[Chunk 1]" in user_content
        assert "source_id=" in user_content

    def test_score_not_in_prompt_with_source_map(self, persona_context):
        sid = uuid.uuid4()
        chunks = [_chunk(source_id=sid, score=0.9876)]
        source_map = {sid: _source_info(sid)}
        messages = build_chat_prompt("query", chunks, persona_context, source_map=source_map)
        user_content = messages[1]["content"]

        assert "0.9876" not in user_content
        assert "score" not in user_content
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/unit/test_prompt_builder.py -v -k "Citation or NewChunkFormat"`
Expected: FAIL — signature mismatch or missing instructions

- [ ] **Step 3: Update prompt.py implementation**

Replace the content of `backend/app/services/prompt.py`:

```python
from __future__ import annotations

import uuid

from app.persona.loader import PersonaContext
from app.persona.safety import SYSTEM_SAFETY_POLICY
from app.services.qdrant import RetrievedChunk

# Avoid circular import: use TYPE_CHECKING for SourceInfo
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.citation import SourceInfo

NO_CONTEXT_REFUSAL = "I could not find an answer to that in the knowledge base."

CITATION_INSTRUCTIONS = """\
## Citation Instructions
When your answer is based on the knowledge context below, cite sources \
using [source:N] where N is the source number.
- Place citations inline, immediately after the relevant statement.
- Do not generate URLs or links. Only use source numbers provided.
- Cite only the most relevant sources for knowledge-based facts.
- Do not cite inferences or small talk."""


def _format_chunk_header(
    index: int,
    chunk: RetrievedChunk,
    source_map: dict[uuid.UUID, SourceInfo],
) -> str:
    info = source_map.get(chunk.source_id)
    if info is None:
        return f"[Source {index}]"

    parts = [f'title: "{info.title}"']
    anchor = chunk.anchor_metadata
    if anchor.get("anchor_chapter"):
        parts.append(f"chapter: \"{anchor['anchor_chapter']}\"")
    if anchor.get("anchor_section"):
        parts.append(f"section: \"{anchor['anchor_section']}\"")
    if anchor.get("anchor_page") is not None:
        parts.append(f"page: {anchor['anchor_page']}")
    if anchor.get("anchor_timecode"):
        parts.append(f"timecode: {anchor['anchor_timecode']}")

    return f"[Source {index}] ({', '.join(parts)})"


def build_chat_prompt(
    query: str,
    chunks: list[RetrievedChunk],
    persona: PersonaContext,
    source_map: dict[uuid.UUID, SourceInfo] | None = None,
) -> list[dict[str, str]]:
    system_sections = [SYSTEM_SAFETY_POLICY]
    if persona.identity:
        system_sections.append(persona.identity)
    if persona.soul:
        system_sections.append(persona.soul)
    if persona.behavior:
        system_sections.append(persona.behavior)

    if chunks and source_map is not None:
        system_sections.append(CITATION_INSTRUCTIONS)

    user_sections: list[str] = []

    if chunks:
        context_lines = ["Knowledge context:"]
        for index, chunk in enumerate(chunks, start=1):
            if source_map is not None:
                header = _format_chunk_header(index, chunk, source_map)
            else:
                header = (
                    f"[Chunk {index}] source_id={chunk.source_id} "
                    f"score={chunk.score:.4f}"
                )
            context_lines.append(header)
            context_lines.append(chunk.text_content)
        user_sections.append("\n".join(context_lines))

    user_sections.append(f"Question:\n{query}")
    return [
        {"role": "system", "content": "\n\n".join(system_sections)},
        {"role": "user", "content": "\n\n".join(user_sections)},
    ]
```

- [ ] **Step 4: Run all prompt tests**

Run: `cd backend && python -m pytest tests/unit/test_prompt_builder.py -v`
Expected: all PASS (both new and existing tests)

- [ ] **Step 5: Commit**

```
feat(prompt): add citation instructions and source-aware chunk format (S4-03)
```

---

## Task 4: Add `ChatStreamCitations` event and wire SSE serialization

**Files:**
- Modify: `backend/app/services/chat.py` (lines 59-72 — add dataclass and update union)
- Modify: `backend/app/api/chat.py` (add citations event handling in `format_event`)

- [ ] **Step 1: Add ChatStreamCitations dataclass**

In `backend/app/services/chat.py`, after `ChatStreamError` (line 69) and before the type alias (line 72), add:

```python
@dataclass(slots=True, frozen=True)
class ChatStreamCitations:
    citations: list  # list[Citation] — avoiding import for decoupling
```

Update the type alias (line 72):

```python
ChatStreamEvent = (
    ChatStreamMeta | ChatStreamToken | ChatStreamDone | ChatStreamError | ChatStreamCitations
)
```

- [ ] **Step 2: Add SSE serialization for citations event**

In `backend/app/api/chat.py`:

1. Add `ChatStreamCitations` to the imports from `app.services.chat`.

2. In the `format_event()` function (line 87), update the type hint and add a branch for `ChatStreamCitations` before the `ChatStreamDone` branch:

```python
def format_event(
    event: ChatStreamMeta | ChatStreamToken | ChatStreamDone | ChatStreamError | ChatStreamCitations,
) -> str:
    # ... existing branches ...
    if isinstance(event, ChatStreamCitations):
        return _format_sse(
            "citations",
            {"citations": [c.to_dict() for c in event.citations]},
        )
    if isinstance(event, ChatStreamDone):
    # ... rest unchanged ...
```

Note: `format_event` is a regular function that returns `str`, not a generator. Use `return`, not `yield`.

- [ ] **Step 3: Run existing SSE tests to verify nothing broke**

Run: `cd backend && python -m pytest tests/ -v -k "chat" --timeout=30`
Expected: all existing tests PASS

- [ ] **Step 4: Commit**

```
feat(chat): add ChatStreamCitations event type and SSE serialization (S4-03)
```

---

## Task 5: Wire citation builder into ChatService.stream_answer()

**Files:**
- Modify: `backend/app/services/chat.py`
- Modify: `backend/app/api/dependencies.py`
- Modify: `backend/tests/unit/test_chat_streaming.py`

- [ ] **Step 1: Update `_chunk` helper to support anchor metadata**

In `backend/tests/unit/test_chat_streaming.py`, update the `_chunk` helper (lines 51-67):

```python
def _chunk(
    *,
    source_id: uuid.UUID | None = None,
    text_content: str = "retrieved chunk",
    anchor_page: int | None = None,
    anchor_chapter: str | None = None,
    anchor_section: str | None = None,
    anchor_timecode: str | None = None,
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        source_id=source_id or uuid.uuid4(),
        text_content=text_content,
        score=0.91,
        anchor_metadata={
            "anchor_page": anchor_page,
            "anchor_chapter": anchor_chapter,
            "anchor_section": anchor_section,
            "anchor_timecode": anchor_timecode,
        },
    )
```

- [ ] **Step 2: Update `_make_service` helper to accept `max_citations_per_response`**

Update the `_make_service` helper (lines 80-109) — add parameter and pass through:

```python
def _make_service(
    db_session: AsyncSession,
    *,
    persona_context: PersonaContext,
    retrieval_result: list[RetrievedChunk] | Exception | None = None,
    stream_tokens: tuple[str, ...] = ("Hello", " world"),
    stream_error: Exception | None = None,
    min_retrieved_chunks: int = 1,
    max_citations_per_response: int = 5,
) -> tuple[ChatService, SimpleNamespace, SimpleNamespace]:
    # ... existing mock setup unchanged ...

    service = ChatService(
        session=db_session,
        snapshot_service=SnapshotService(session=db_session),
        retrieval_service=retrieval_service,
        llm_service=llm_service,
        persona_context=persona_context,
        min_retrieved_chunks=min_retrieved_chunks,
        max_citations_per_response=max_citations_per_response,
    )
    return service, retrieval_service, llm_service
```

- [ ] **Step 3: Add imports at top of test file**

```python
from app.services.citation import SourceInfo
from app.services.chat import ChatStreamCitations
```

- [ ] **Step 4: Write the failing test**

Add to `backend/tests/unit/test_chat_streaming.py`:

```python
@pytest.mark.asyncio
async def test_stream_answer_emits_citations_event(
    db_session: AsyncSession,
    persona_context: PersonaContext,
) -> None:
    """When LLM returns [source:N] markers, a citations event is emitted."""
    await _create_snapshot(db_session, status=SnapshotStatus.ACTIVE)
    source_id = uuid.uuid4()
    chunk = _chunk(
        source_id=source_id,
        text_content="Chapter about clean code",
        anchor_page=42,
        anchor_chapter="Chapter 5",
    )
    source_info = SourceInfo(
        id=source_id,
        title="Clean Architecture",
        public_url=None,
        source_type="pdf",
    )

    service, _, _ = _make_service(
        db_session,
        persona_context=persona_context,
        retrieval_result=[chunk],
        stream_tokens=("Based on the book [source:1], clean code matters.",),
    )
    # Mock the source loading
    service._load_source_map = AsyncMock(return_value={source_id: source_info})

    session = await service.create_session()
    events = await _collect_events(service, session_id=session.id, text="question")

    citation_events = [e for e in events if isinstance(e, ChatStreamCitations)]
    assert len(citation_events) == 1
    assert len(citation_events[0].citations) == 1
    assert citation_events[0].citations[0].source_title == "Clean Architecture"

    # Verify order: meta → tokens → citations → done
    event_types = [type(e).__name__ for e in events]
    citations_idx = event_types.index("ChatStreamCitations")
    done_idx = event_types.index("ChatStreamDone")
    assert citations_idx < done_idx
```

- [ ] **Step 5: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/unit/test_chat_streaming.py::test_stream_answer_emits_citations_event -v`
Expected: FAIL — `max_citations_per_response` not accepted / `_load_source_map` doesn't exist

- [ ] **Step 6: Implement source loading and citation wiring in ChatService**

In `backend/app/services/chat.py`:

**Add imports:**
```python
from app.services.citation import Citation, CitationService, SourceInfo
from sqlalchemy import select as sa_select
from app.db.models import Source
```

**Add `max_citations_per_response` to constructor:**
```python
def __init__(
    self,
    *,
    session: AsyncSession,
    snapshot_service: SnapshotService,
    retrieval_service: RetrievalService,
    llm_service: LLMService,
    persona_context: PersonaContext,
    min_retrieved_chunks: int,
    max_citations_per_response: int = 5,
) -> None:
    # ... existing assignments ...
    self._max_citations_per_response = max_citations_per_response
```

**Add `_load_source_map` method:**
```python
async def _load_source_map(
    self, source_ids: list[uuid.UUID],
) -> dict[uuid.UUID, SourceInfo]:
    if not source_ids:
        return {}
    stmt = sa_select(
        Source.id, Source.title, Source.public_url, Source.source_type,
    ).where(
        Source.id.in_(source_ids),
        Source.deleted_at.is_(None),
    )
    rows = await self._session.execute(stmt)
    return {
        row.id: SourceInfo(
            id=row.id,
            title=row.title,
            public_url=row.public_url,
            source_type=row.source_type.value if hasattr(row.source_type, "value") else str(row.source_type),
        )
        for row in rows
    }
```

**Modify `stream_answer()` — after retrieval (line ~289), before prompt assembly (line ~362):**

After `source_ids = self._deduplicate_source_ids(retrieved_chunks)`:
```python
source_map = await self._load_source_map(source_ids)
```

Update `build_chat_prompt` call:
```python
prompt = build_chat_prompt(text, retrieved_chunks, self._persona_context, source_map=source_map)
```

**After LLM stream loop completes (after `assistant_message.content = "".join(content_buffer)`, before commit):**

```python
citations = CitationService.extract(
    assistant_message.content,
    retrieved_chunks,
    source_map,
    self._max_citations_per_response,
)
assistant_message.citations = [c.to_dict() for c in citations]
```

**After commit, before yielding `ChatStreamDone`, yield:**
```python
yield ChatStreamCitations(citations=citations)
```

- [ ] **Step 7: Update dependencies.py**

In `backend/app/api/dependencies.py`, update `get_chat_service()` to pass the new setting:

```python
max_citations_per_response=request.app.state.settings.max_citations_per_response,
```

- [ ] **Step 8: Update integration test fixture**

In `backend/tests/conftest.py`, update the `chat_app` fixture's `app.state.settings` (line 282) to include the new setting:

```python
app.state.settings = SimpleNamespace(
    min_retrieved_chunks=1,
    sse_heartbeat_interval_seconds=15,
    sse_inter_token_timeout_seconds=30,
    max_citations_per_response=5,
)
```

Without this, all integration tests using `chat_app`/`chat_client` will fail because `get_chat_service()` now reads `max_citations_per_response` from settings.

- [ ] **Step 9: Run tests**

Run: `cd backend && python -m pytest tests/unit/test_chat_streaming.py tests/integration/test_chat_sse.py -v`
Expected: all PASS

- [ ] **Step 10: Commit**

```
feat(chat): wire citation builder into stream_answer with source loading (S4-03)
```

---

## Task 6: Update idempotent replay to include citations

**Files:**
- Modify: `backend/app/services/chat.py` (method `_replay_complete`)
- Modify: `backend/tests/unit/test_chat_streaming.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/unit/test_chat_streaming.py`:

```python
@pytest.mark.asyncio
async def test_idempotent_replay_includes_citations_event(
    db_session: AsyncSession,
    persona_context: PersonaContext,
) -> None:
    """Replay of a COMPLETE message should include a citations event from DB."""
    await _create_snapshot(db_session, status=SnapshotStatus.ACTIVE)
    source_id = uuid.uuid4()
    source_info = SourceInfo(
        id=source_id, title="Test Source", public_url=None, source_type="pdf",
    )

    service, _, _ = _make_service(
        db_session,
        persona_context=persona_context,
        retrieval_result=[_chunk(source_id=source_id)],
        stream_tokens=("Answer [source:1].",),
    )
    service._load_source_map = AsyncMock(return_value={source_id: source_info})

    session = await service.create_session()

    # First call — generates response with citations
    events1 = await _collect_events(
        service, session_id=session.id, text="q", idempotency_key="key1",
    )
    # Verify first call produced citations
    assert any(isinstance(e, ChatStreamCitations) for e in events1)

    # Second call with same key — replay from DB
    events2 = await _collect_events(
        service, session_id=session.id, text="q", idempotency_key="key1",
    )

    citation_events = [e for e in events2 if isinstance(e, ChatStreamCitations)]
    assert len(citation_events) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/unit/test_chat_streaming.py::test_idempotent_replay_includes_citations_event -v`
Expected: FAIL — replay doesn't yield ChatStreamCitations

- [ ] **Step 3: Update `_replay_complete` method**

In `backend/app/services/chat.py`, modify `_replay_complete()`:

After yielding `ChatStreamToken` and before yielding `ChatStreamDone`, add:

```python
# Replay saved citations
replay_citations: list[Citation] = []
if assistant_message.citations:
    replay_citations = [
        Citation(
            index=c["index"],
            source_id=uuid.UUID(c["source_id"]) if isinstance(c["source_id"], str) else c["source_id"],
            source_title=c.get("source_title", ""),
            source_type=c.get("source_type", ""),
            url=c.get("url"),
            anchor=c.get("anchor", {}),
            text_citation=c.get("text_citation", ""),
        )
        for c in assistant_message.citations
    ]
yield ChatStreamCitations(citations=replay_citations)
```

- [ ] **Step 4: Run tests**

Run: `cd backend && python -m pytest tests/unit/test_chat_streaming.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```
feat(chat): include citations event in idempotent replay (S4-03)
```

---

## Task 7: Add CitationResponse schema and update MessageResponse + MessageInHistory

**Files:**
- Modify: `backend/app/api/chat_schemas.py`

- [ ] **Step 1: Add CitationResponse and AnchorResponse schemas**

In `backend/app/api/chat_schemas.py`, add:

```python
class AnchorResponse(BaseModel):
    page: int | None = None
    chapter: str | None = None
    section: str | None = None
    timecode: str | None = None


class CitationResponse(BaseModel):
    index: int
    source_id: str
    source_title: str
    source_type: str
    url: str | None = None
    anchor: AnchorResponse
    text_citation: str
```

- [ ] **Step 2: Add `citations` field to `MessageInHistory`**

Note: `POST /api/chat/messages` returns an SSE stream (not `MessageResponse`). Citations are delivered via the SSE `citations` event. `MessageResponse` is used internally (e.g., by `from_message()` in non-streaming paths) — add `citations` there too for consistency, but the primary API surface is `MessageInHistory` in `GET /api/chat/sessions/:id`.

Add to `MessageInHistory` (used by `GET /api/chat/sessions/:id` via `SessionWithMessagesResponse`):

```python
citations: list[CitationResponse] | None = None
```

Add to `MessageResponse` (for consistency in internal usage):

```python
citations: list[CitationResponse] | None = None
```

`MessageInHistory` uses `from_attributes=True`, so the `citations` field maps automatically from `Message.citations` JSONB. Verify Pydantic parses the JSONB dicts into `CitationResponse` objects correctly — if not, add a validator.

- [ ] **Step 3: Run existing API tests to verify nothing broke**

Run: `cd backend && python -m pytest tests/ -v -k "chat" --timeout=30`
Expected: all PASS

- [ ] **Step 4: Commit**

```
feat(api): add CitationResponse schema and citations to MessageResponse + MessageInHistory (S4-03)
```

---

## Task 8: Update upstream documentation

**Files:**
- Modify: `docs/spec.md`
- Modify: `docs/rag.md`

- [ ] **Step 1: Update docs/spec.md citation protocol**

In `docs/spec.md`, around line 170, update:

Old: `The LLM returns a response in Markdown format, referencing sources via source_id (e.g., [source_id:42]).`

New: `The LLM returns a response in Markdown format, referencing sources via ordinal index (e.g., [source:1], [source:2]). The ordinal corresponds to the position of the source in the knowledge context provided in the prompt.`

- [ ] **Step 2: Update docs/rag.md citation protocol**

In `docs/rag.md`, around line 198, update:

Old: `The LLM references sources via [source_id:N].`

New: `The LLM references sources via [source:N] where N is the ordinal index of the source in the prompt context.`

- [ ] **Step 3: Commit**

```
docs: update citation protocol to [source:N] ordinal format (S4-03)
```

---

## Task 9: Integration test — full SSE citation flow

**Files:**
- Modify: `backend/tests/integration/test_chat_sse.py`

- [ ] **Step 1: Write integration test**

Add to `backend/tests/integration/test_chat_sse.py`. Follow existing patterns: use `chat_client`, `session_factory`, `mock_retrieval_service`, `sample_retrieved_chunk` fixtures; create session via API; import from `httpx_sse` directly.

```python
@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_sse_stream_includes_citations_event(
    chat_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    mock_retrieval_service,
    sample_retrieved_chunk,
) -> None:
    """Full flow: send message → SSE stream includes meta, tokens, citations, done."""
    await _create_snapshot(session_factory, status=SnapshotStatus.ACTIVE)
    mock_retrieval_service.search.return_value = [sample_retrieved_chunk]

    session_resp = await chat_client.post("/api/chat/sessions", json={})
    session_id = session_resp.json()["id"]

    async with aconnect_sse(
        chat_client,
        "POST",
        "/api/chat/messages",
        json={"session_id": session_id, "text": "Tell me about the topic"},
    ) as event_source:
        events = [(sse.event, json.loads(sse.data)) async for sse in event_source.aiter_sse()]

    event_types = [e[0] for e in events]

    # citations event is always present (even if empty) and comes before done
    assert "meta" in event_types
    assert "citations" in event_types
    assert "done" in event_types
    assert event_types.index("citations") < event_types.index("done")

    # citations event has expected structure
    citations_data = next(e[1] for e in events if e[0] == "citations")
    assert "citations" in citations_data
    assert isinstance(citations_data["citations"], list)
```

- [ ] **Step 2: Run integration test**

Run: `cd backend && python -m pytest tests/integration/test_chat_sse.py::test_sse_stream_includes_citations_event -v`
Expected: PASS (may need mock adjustments depending on test fixtures)

- [ ] **Step 3: Run full test suite**

Run: `cd backend && python -m pytest tests/ -v --timeout=60`
Expected: all PASS

- [ ] **Step 4: Commit**

```
test(chat): add integration test for SSE citations event flow (S4-03)
```

---

## Task 10: Final verification and cleanup

- [ ] **Step 1: Re-read `docs/development.md` and self-review**

Read `docs/development.md`. Verify all code follows project standards.

- [ ] **Step 2: Run full CI test suite**

Run: `cd backend && python -m pytest tests/ -v --timeout=60`
Expected: all PASS

- [ ] **Step 3: Verify no regressions in existing tests**

Run: `cd backend && python -m pytest tests/unit/test_chat_service.py tests/unit/test_chat_streaming.py tests/integration/test_chat_sse.py -v`
Expected: all PASS (existing + new)

- [ ] **Step 4: Verify config version constraints**

Check `docs/spec.md` for version minimums. Verify no new dependencies were added below spec minimums.

- [ ] **Step 5: Final commit with all changes**

If any uncommitted cleanup remains:
```
chore(citation): final cleanup and self-review (S4-03)
```
