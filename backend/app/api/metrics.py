from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response

from app.api.auth import verify_metrics_access
from app.services.metrics import CONTENT_TYPE_LATEST, render_metrics

router = APIRouter(include_in_schema=False)


@router.get("/metrics")
async def metrics(
    _: Annotated[None, Depends(verify_metrics_access)],
) -> Response:
    return Response(content=render_metrics(), media_type=CONTENT_TYPE_LATEST)
