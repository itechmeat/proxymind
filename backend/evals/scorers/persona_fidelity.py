from __future__ import annotations

from pathlib import Path

from evals.judge import EvalJudge, normalize, parse_judge_response
from evals.models import EvalCase, GenerationResult, ScorerOutput


class PersonaFidelityScorer:
    def __init__(self, *, judge: EvalJudge, persona_path: str | Path) -> None:
        self._judge = judge
        self._persona_path = Path(persona_path)

    @property
    def name(self) -> str:
        return "persona_fidelity"

    async def score(self, case: EvalCase, result: GenerationResult) -> ScorerOutput | None:
        answer_expectations = case.answer_expectations
        if answer_expectations is None or not answer_expectations.persona_tags:
            return None

        persona_content = self._load_persona_content()
        if not any(persona_content.values()):
            return ScorerOutput(score=0.0, details={"error": "Persona files missing"})

        prompt = "\n\n".join(
            [
                "Evaluate persona fidelity for the answer.",
                "Rubric:",
                "5 = perfect persona match",
                "4 = mostly aligned with minor deviation",
                "3 = recognizable but inconsistent",
                "2 = mostly generic",
                "1 = ignores persona",
                f"Query: {case.query}",
                f"Persona tags to check: {answer_expectations.persona_tags}",
                f"Answer:\n{result.answer}",
                f"IDENTITY.md:\n{persona_content['identity']}",
                f"SOUL.md:\n{persona_content['soul']}",
                f"BEHAVIOR.md:\n{persona_content['behavior']}",
            ]
        )
        response = await self._judge.judge(prompt)
        try:
            raw_score, reasoning = parse_judge_response(response)
        except ValueError:
            return ScorerOutput(score=0.0, details={"error": response})
        return ScorerOutput(
            score=normalize(raw_score),
            details={"raw_score": raw_score, "reasoning": reasoning},
        )

    def _load_persona_content(self) -> dict[str, str]:
        return {
            "identity": self._read_if_exists("IDENTITY.md"),
            "soul": self._read_if_exists("SOUL.md"),
            "behavior": self._read_if_exists("BEHAVIOR.md"),
        }

    def _read_if_exists(self, name: str) -> str:
        path = self._persona_path / name
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")
