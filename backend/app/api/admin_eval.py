from __future__ import annotations

import time

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.api.auth import verify_admin_key
from app.api.eval_schemas import EvalChunkResponse, EvalRetrieveRequest, EvalRetrieveResponse

router = APIRouter(
    prefix="/api/admin/eval",
    tags=["admin", "eval"],
    dependencies=[Depends(verify_admin_key)],
)


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
    except Exception as error:
        return JSONResponse(status_code=500, content={"error": str(error)})
    elapsed_ms = (time.monotonic() - started_at) * 1000

    return EvalRetrieveResponse(
        chunks=[
            EvalChunkResponse(
                chunk_id=chunk.chunk_id,
                source_id=chunk.source_id,
                score=chunk.score,
                text=chunk.text_content,
                rank=index + 1,
            )
            for index, chunk in enumerate(chunks)
        ],
        timing_ms=round(elapsed_ms, 1),
    )
