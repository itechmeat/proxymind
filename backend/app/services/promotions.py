from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)

_VALID_PRIORITIES = {"high", "medium", "low"}
_PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}
_SECTION_RE = re.compile(r"^##\s+(.+)$", re.MULTILINE)
_META_LINE_RE = re.compile(r"^-\s+\*\*(.+?):\*\*\s*(.*)$")


@dataclass(slots=True, frozen=True)
class Promotion:
    title: str
    priority: str
    valid_from: dt.date | None
    valid_to: dt.date | None
    context: str
    body: str
    catalog_item_sku: str | None = None


class PromotionsService:
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

        promotions: list[Promotion] = []
        for title, section_body in self._split_sections():
            promotion = self._parse_section(title, section_body)
            if promotion is not None:
                promotions.append(promotion)
        return promotions

    def get_active(
        self,
        *,
        today: dt.date | None = None,
        max_promotions: int | None = None,
    ) -> list[Promotion]:
        effective_today = today or dt.date.today()
        promotions = [
            promotion
            for promotion in self.parse()
            if self._is_active(promotion, effective_today)
        ]
        promotions.sort(key=lambda promotion: _PRIORITY_ORDER.get(promotion.priority, 2))
        if max_promotions is not None:
            return promotions[:max_promotions]
        return promotions

    def _split_sections(self) -> list[tuple[str, str]]:
        matches = list(_SECTION_RE.finditer(self._text))
        if not matches:
            return []

        sections: list[tuple[str, str]] = []
        for index, match in enumerate(matches):
            title = match.group(1).strip()
            start = match.end()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(self._text)
            sections.append((title, self._text[start:end].strip()))
        return sections

    def _parse_section(self, title: str, section_body: str) -> Promotion | None:
        metadata: dict[str, str] = {}
        body_lines: list[str] = []
        metadata_started = False
        body_started = False

        for line in section_body.splitlines():
            stripped = line.strip()
            if not body_started and not stripped:
                if metadata_started:
                    body_started = True
                continue

            if not body_started:
                match = _META_LINE_RE.match(stripped)
                if match is not None:
                    metadata_started = True
                    metadata[match.group(1).strip().lower()] = match.group(2).strip()
                    continue
                body_started = True

            body_lines.append(line)

        body = "\n".join(body_lines).strip()
        if not body:
            logger.warning("promotions.empty_body", title=title)
            return None

        priority = metadata.get("priority", "low").lower()
        if priority not in _VALID_PRIORITIES:
            logger.warning("promotions.invalid_priority", title=title, priority=priority)
            priority = "low"

        raw_valid_from = metadata.get("valid from")
        raw_valid_to = metadata.get("valid to")
        valid_from = self._parse_date(raw_valid_from, title=title, field="valid_from")
        valid_to = self._parse_date(raw_valid_to, title=title, field="valid_to")
        if raw_valid_from and valid_from is None:
            return None
        if raw_valid_to and valid_to is None:
            return None

        return Promotion(
            title=title,
            priority=priority,
            valid_from=valid_from,
            valid_to=valid_to,
            context=metadata.get("context", ""),
            body=body,
            catalog_item_sku=metadata.get("catalog item") or None,
        )

    @staticmethod
    def _parse_date(value: str | None, *, title: str, field: str) -> dt.date | None:
        if not value:
            return None
        try:
            return dt.date.fromisoformat(value)
        except ValueError:
            logger.warning("promotions.invalid_date", title=title, field=field, value=value)
            return None

    @staticmethod
    def _is_active(promotion: Promotion, today: dt.date) -> bool:
        if promotion.valid_to is not None and today > promotion.valid_to:
            return False
        if promotion.valid_from is not None and today < promotion.valid_from:
            return False
        return True
