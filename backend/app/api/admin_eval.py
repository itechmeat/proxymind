from __future__ import annotations

import time
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.api.auth import verify_admin_key
from app.api.dependencies import (
    get_context_assembler,
    get_llm_service,
    get_query_rewrite_service,
    get_retrieval_service,
)
from app.api.eval_schemas import (
    EvalChunkResponse,
    EvalGenerateRequest,
    EvalGenerateResponse,
    EvalRetrieveRequest,
    EvalRetrieveResponse,
)
from app.db.session import get_session
from app.services.citation import CitationService, load_source_map
from app.services.context_assembler import ContextAssembler
from app.services.llm import LLMService
from app.services.product_recommendation import ProductRecommendationService
from app.services.prompt import NO_CONTEXT_REFUSAL
from app.services.qdrant import RetrievedChunk
from app.services.query_rewrite import QueryRewriteService
from app.services.retrieval import RetrievalService

router = APIRouter(
    prefix="/api/admin/eval",
    tags=["admin", "eval"],
    dependencies=[Depends(verify_admin_key)],
)
logger = structlog.get_logger(__name__)


def _build_chunk_response(chunk: RetrievedChunk, rank: int) -> EvalChunkResponse:
    return EvalChunkResponse(
        chunk_id=chunk.chunk_id,
        source_id=chunk.source_id,
        score=chunk.score,
        text=chunk.text_content,
        rank=rank,
    )


def _deduplicate_source_ids(chunks: list[RetrievedChunk]) -> list[uuid.UUID]:
    seen: set[uuid.UUID] = set()
    source_ids: list[uuid.UUID] = []
    for chunk in chunks:
        if chunk.source_id in seen:
            continue
        seen.add(chunk.source_id)
        source_ids.append(chunk.source_id)
    return source_ids


@router.post("/retrieve", response_model=EvalRetrieveResponse)
async def eval_retrieve(
    request: Request,
    body: EvalRetrieveRequest,
) -> EvalRetrieveResponse | JSONResponse:
    retrieval_service = request.app.state.retrieval_service
    started_at = time.monotonic()
    try:
        chunks = await retrieval_service.search(
            body.query,
            snapshot_id=body.snapshot_id,
            top_n=body.top_n,
        )
    except Exception:
        logger.exception("Eval retrieve failed", snapshot_id=str(body.snapshot_id))
        return JSONResponse(status_code=500, content={"error": "Internal server error"})
    elapsed_ms = (time.monotonic() - started_at) * 1000

    return EvalRetrieveResponse(
        chunks=[
            _build_chunk_response(chunk, index + 1)
            for index, chunk in enumerate(chunks)
        ],
        timing_ms=round(elapsed_ms, 1),
    )


@router.post("/generate", response_model=EvalGenerateResponse)
async def eval_generate(
    request: Request,
    body: EvalGenerateRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    retrieval_service: Annotated[RetrievalService, Depends(get_retrieval_service)],
    query_rewrite_service: Annotated[QueryRewriteService, Depends(get_query_rewrite_service)],
    context_assembler: Annotated[ContextAssembler, Depends(get_context_assembler)],
    llm_service: Annotated[LLMService, Depends(get_llm_service)],
) -> EvalGenerateResponse | JSONResponse:
    started_at = time.monotonic()
    settings = request.app.state.settings
    try:
        rewrite_result = await query_rewrite_service.rewrite(body.query, [])
        retrieved_chunks = await retrieval_service.search(
            rewrite_result.query,
            snapshot_id=body.snapshot_id,
            top_n=settings.retrieval_top_n,
        )

        selected_chunks: list[RetrievedChunk] = []
        citations: list[dict[str, object]] = []
        answer = NO_CONTEXT_REFUSAL
        model_name = settings.llm_model

        if len(retrieved_chunks) >= settings.min_retrieved_chunks:
            source_map = await load_source_map(session, _deduplicate_source_ids(retrieved_chunks))
            assembled = context_assembler.assemble(
                chunks=retrieved_chunks,
                query=body.query,
                source_map=source_map,
                memory_block=None,
            )
            selected_chunks = retrieved_chunks[: assembled.retrieval_chunks_used]
            llm_response = await llm_service.complete(assembled.messages)
            extracted_citations = CitationService.extract(
                llm_response.content,
                selected_chunks,
                source_map,
                settings.max_citations_per_response,
            )
            citations = [citation.to_dict() for citation in extracted_citations]
            answer = ProductRecommendationService.strip_markers(llm_response.content)
            model_name = llm_response.model_name or settings.llm_model

        elapsed_ms = (time.monotonic() - started_at) * 1000
        return EvalGenerateResponse(
            answer=answer,
            citations=citations,
            retrieved_chunks=[
                _build_chunk_response(chunk, index + 1)
                for index, chunk in enumerate(selected_chunks)
            ],
            rewritten_query=rewrite_result.query,
            timing_ms=round(elapsed_ms, 1),
            model=model_name,
        )
    except Exception:
        logger.exception("Eval generate failed", snapshot_id=str(body.snapshot_id))
        return JSONResponse(status_code=500, content={"error": "Internal server error"})
