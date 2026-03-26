import app.services.content_type as content_type
from app.services.content_type import compute_content_type_spans
from app.services.promotions import Promotion


def _promo() -> Promotion:
    return Promotion(
        title="AI Book",
        priority="high",
        valid_from=None,
        valid_to=None,
        context="When discussing books.",
        body="Buy the AI Book today",
    )


def test_sentence_with_citation_is_fact() -> None:
    spans = compute_content_type_spans("The sky is blue [source:1].", promotions=[])
    assert len(spans) == 1
    assert spans[0].type == "fact"


def test_sentence_with_promo_keywords_is_promo() -> None:
    spans = compute_content_type_spans("The AI Book is available now.", promotions=[_promo()])
    assert len(spans) == 1
    assert spans[0].type == "promo"


def test_plain_sentence_is_inference() -> None:
    spans = compute_content_type_spans("I think this is interesting.", promotions=[])
    assert len(spans) == 1
    assert spans[0].type == "inference"


def test_fact_wins_over_promo() -> None:
    spans = compute_content_type_spans("The AI Book is available [source:1].", promotions=[_promo()])
    assert spans[0].type == "fact"


def test_adjacent_same_type_spans_are_merged() -> None:
    spans = compute_content_type_spans("First inference. Second inference.", promotions=[])
    assert len(spans) == 1
    assert spans[0].type == "inference"


def test_empty_text_returns_empty_spans() -> None:
    assert compute_content_type_spans("", promotions=[]) == []


def test_full_coverage() -> None:
    text = "A fact [source:1]. An inference."
    spans = compute_content_type_spans(text, promotions=[])
    covered_positions = set()
    for span in spans:
        covered_positions.update(range(span.start, span.end))
    assert covered_positions == set(range(len(text)))


def test_single_keyword_below_threshold_is_not_promo() -> None:
    spans = compute_content_type_spans("AI is transforming the world.", promotions=[_promo()])
    assert spans[0].type == "inference"


def test_multilingual_promo_keywords_are_detected() -> None:
    promo = Promotion(
        title="Книга по ИИ",
        priority="high",
        valid_from=None,
        valid_to=None,
        context="Когда разговор о книгах.",
        body="Купите книгу по ИИ сегодня",
    )

    spans = compute_content_type_spans(
        "Эта книга по ИИ уже доступна сегодня.",
        promotions=[promo],
    )

    assert len(spans) == 1
    assert spans[0].type == "promo"


def test_no_promotions_skips_promo_keyword_matching(monkeypatch) -> None:
    def fail_sentence_keywords(_: str) -> set[str]:
        raise AssertionError("promo keyword matching should be skipped when no promotions exist")

    monkeypatch.setattr(content_type, "_sentence_keywords", fail_sentence_keywords)

    spans = compute_content_type_spans("This should stay an inference.", promotions=[])

    assert len(spans) == 1
    assert spans[0].type == "inference"
