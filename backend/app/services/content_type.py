from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from app.services.promotions import Promotion

_CITATION_PATTERN = re.compile(r"\[source:\d+\]")
_WORD_PATTERN = re.compile(r"[^\W_]+(?:[-'’][^\W_]+)*", re.UNICODE)
_MIN_PROMO_KEYWORD_LENGTH = 2
_MIN_DISTINCT_PROMO_MATCHES = 2
_MIN_LONG_PROMO_KEYWORD_LENGTH = 5


@dataclass(slots=True, frozen=True)
class ContentTypeSpan:
    start: int
    end: int
    type: str


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
    spans = [
        ContentTypeSpan(
            start=start,
            end=end,
            type=_classify_sentence(text[start:end], promo_keywords),
        )
        for start, end in sentences
    ]
    return _merge_adjacent(spans)


def _split_sentences(text: str) -> list[tuple[int, int]]:
    sentences: list[tuple[int, int]] = []
    start = 0
    index = 0
    while index < len(text):
        char = text[index]
        if char in ".!?" and _is_sentence_boundary(text, index):
            next_start = index + 1
            while next_start < len(text) and text[next_start].isspace():
                next_start += 1
            sentences.append((start, next_start))
            start = next_start
            index = next_start
            continue
        index += 1

    if start < len(text):
        sentences.append((start, len(text)))
    return sentences


def _is_sentence_boundary(text: str, index: int) -> bool:
    next_index = index + 1
    if next_index < len(text) and not text[next_index].isspace():
        return not (
            text[index] == "."
            and index > 0
            and text[index - 1].isdigit()
            and text[next_index].isdigit()
        )
    return True


def _classify_sentence(sentence: str, promo_keywords: set[str]) -> str:
    if _CITATION_PATTERN.search(sentence):
        return "fact"
    if (
        promo_keywords
        and len(_sentence_keywords(sentence) & promo_keywords)
        >= _MIN_DISTINCT_PROMO_MATCHES
    ):
        return "promo"
    return "inference"


def _extract_promo_keywords(promotions: list[Promotion]) -> set[str]:
    keyword_counts: Counter[str] = Counter()
    for promotion in promotions:
        keyword_counts.update(_significant_words(f"{promotion.title} {promotion.body}"))
    return {
        keyword
        for keyword, count in keyword_counts.items()
        if count > 1 or len(keyword) >= _MIN_LONG_PROMO_KEYWORD_LENGTH
    }


def _sentence_keywords(sentence: str) -> set[str]:
    return set(_significant_words(sentence))


def _significant_words(text: str) -> list[str]:
    words = [match.group(0).lower() for match in _WORD_PATTERN.finditer(text)]
    return [word for word in words if len(word) >= _MIN_PROMO_KEYWORD_LENGTH]


def _merge_adjacent(spans: list[ContentTypeSpan]) -> list[ContentTypeSpan]:
    if not spans:
        return []

    merged = [spans[0]]
    for span in spans[1:]:
        previous = merged[-1]
        if previous.type == span.type and previous.end == span.start:
            merged[-1] = ContentTypeSpan(start=previous.start, end=span.end, type=previous.type)
            continue
        merged.append(span)
    return merged
