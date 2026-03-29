from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class ExpectedChunk(BaseModel):
    source_id: uuid.UUID
    contains: str = Field(min_length=1)


class AnswerExpectations(BaseModel):
    should_refuse: bool = False
    expected_citations: list[uuid.UUID] = Field(default_factory=list)
    persona_tags: list[str] = Field(default_factory=list)
    groundedness_notes: str = ""


class EvalCase(BaseModel):
    id: str = Field(min_length=1)
    query: str = Field(min_length=1)
    expected: list[ExpectedChunk] = Field(default_factory=list)
    answer_expectations: AnswerExpectations | None = None
    tags: list[str] = Field(default_factory=list)


class EvalSuite(BaseModel):
    suite: str = Field(min_length=1)
    description: str = Field(default="")
    snapshot_id: uuid.UUID
    cases: list[EvalCase] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_case_ids(self) -> EvalSuite:
        case_ids = [case.id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("Duplicate case id")
        return self


class ReturnedChunk(BaseModel):
    chunk_id: uuid.UUID
    source_id: uuid.UUID
    score: float
    text: str
    rank: int = Field(ge=1)


class RetrievalResult(BaseModel):
    chunks: list[ReturnedChunk]
    timing_ms: float


class GenerationResult(BaseModel):
    answer: str
    citations: list[dict[str, Any]] = Field(default_factory=list)
    retrieved_chunks: list[ReturnedChunk] = Field(default_factory=list)
    rewritten_query: str
    timing_ms: float
    model: str


class ScorerOutput(BaseModel):
    score: float = Field(ge=0.0, le=1.0)
    details: dict[str, Any] = Field(default_factory=dict)


class CaseResult(BaseModel):
    id: str
    query: str
    status: Literal["ok", "error"]
    scores: dict[str, float] = Field(default_factory=dict)
    details: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    answer: str | None = None
    generation_timing_ms: float | None = None
    judge_scores: dict[str, dict[str, float | int]] | None = None
    judge_reasoning: dict[str, str] | None = None


class MetricSummary(BaseModel):
    mean: float
    min: float
    max: float


class SuiteResult(BaseModel):
    suite: str
    timestamp: str
    config: dict[str, Any]
    summary: dict[str, MetricSummary]
    total_cases: int
    errors: int
    cases: list[CaseResult]
