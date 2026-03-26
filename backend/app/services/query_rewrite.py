from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

import structlog

from app.services.token_counter import CHARS_PER_TOKEN

if TYPE_CHECKING:
    from app.services.llm import LLMService

SYSTEM_PROMPT_RESERVE_TOKENS = 200

REWRITE_SYSTEM_PROMPT = (
    "You are a query rewriting assistant. Given a conversation history and "
    "the user's latest message, reformulate the latest message into a "
    "self-contained search query that captures the full intent.\n\n"
    "Rules:\n"
    "- Output ONLY the rewritten query, nothing else\n"
    "- If the message is already self-contained, return it as-is\n"
    "- Preserve the language of the original query\n"
    "- Do not answer the question, only reformulate it\n"
    "- Include relevant context from the conversation history"
)


class MessageLike(Protocol):
    @property
    def role(self) -> Any: ...

    @property
    def content(self) -> str: ...


@dataclass(slots=True, frozen=True)
class RewriteResult:
    query: str
    is_rewritten: bool
    original_query: str


class QueryRewriteService:
    def __init__(
        self,
        *,
        llm_service: LLMService,
        rewrite_enabled: bool = True,
        timeout_ms: int = 3000,
        token_budget: int = 2048,
        history_messages: int = 10,
        temperature: float = 0.1,
    ) -> None:
        self._llm_service = llm_service
        self._rewrite_enabled = rewrite_enabled
        self._timeout_ms = timeout_ms
        self._token_budget = token_budget
        self._history_messages = history_messages
        self._temperature = temperature
        self._logger = structlog.get_logger(__name__)

    @staticmethod
    def _log_kwargs(*, session_id: str | None = None, **kwargs: object) -> dict[str, object]:
        if session_id is not None:
            kwargs["session_id"] = session_id
        return kwargs

    async def rewrite(
        self,
        query: str,
        history: list[MessageLike],
        *,
        session_id: str | None = None,
    ) -> RewriteResult:
        no_rewrite = RewriteResult(
            query=query,
            is_rewritten=False,
            original_query=query,
        )

        if not self._rewrite_enabled:
            self._logger.debug(
                "query_rewrite.skip",
                **self._log_kwargs(reason="disabled", session_id=session_id),
            )
            return no_rewrite

        if not history:
            self._logger.debug(
                "query_rewrite.skip",
                **self._log_kwargs(reason="empty_history", session_id=session_id),
            )
            return no_rewrite

        trimmed_history = self._trim_history(history, query)
        prompt = self._build_prompt(trimmed_history, query)
        start = asyncio.get_running_loop().time()

        try:
            response = await asyncio.wait_for(
                self._llm_service.complete(prompt, temperature=self._temperature),
                timeout=self._timeout_ms / 1000,
            )
        except TimeoutError:
            self._logger.warning(
                "query_rewrite.timeout",
                **self._log_kwargs(timeout_ms=self._timeout_ms, session_id=session_id),
            )
            return no_rewrite
        except Exception as error:
            self._logger.warning(
                "query_rewrite.error",
                **self._log_kwargs(error=error.__class__.__name__, session_id=session_id),
            )
            return no_rewrite

        rewritten_query = response.content.strip()
        if not rewritten_query:
            self._logger.warning(
                "query_rewrite.error",
                **self._log_kwargs(error="EmptyResponse", session_id=session_id),
            )
            return no_rewrite

        is_rewritten = rewritten_query != query

        self._logger.info(
            "query_rewrite.success",
            **self._log_kwargs(
                history_messages=len(trimmed_history),
                is_rewritten=is_rewritten,
                latency_ms=round((asyncio.get_running_loop().time() - start) * 1000),
                session_id=session_id,
            ),
        )
        return RewriteResult(
            query=rewritten_query,
            is_rewritten=is_rewritten,
            original_query=query,
        )

    def _trim_history(
        self,
        history: list[MessageLike],
        query: str,
    ) -> list[MessageLike]:
        capped_history = history[-self._history_messages :]
        query_tokens = len(query) / CHARS_PER_TOKEN
        available_tokens = self._token_budget - SYSTEM_PROMPT_RESERVE_TOKENS - query_tokens
        if available_tokens <= 0:
            return []

        kept_messages: list[MessageLike] = []
        used_tokens = 0.0
        for message in reversed(capped_history):
            message_tokens = len(message.content) / CHARS_PER_TOKEN
            if used_tokens + message_tokens > available_tokens:
                break
            kept_messages.append(message)
            used_tokens += message_tokens

        kept_messages.reverse()
        return kept_messages

    @staticmethod
    def _build_prompt(history: list[MessageLike], query: str) -> list[dict[str, str]]:
        history_lines = [
            f"{message.role.value.capitalize()}: {message.content}"
            for message in history
        ]
        history_text = "\n".join(history_lines)
        user_content = f"Conversation history:\n{history_text}\n\nCurrent message: {query}"
        return [
            {"role": "system", "content": REWRITE_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]
