from app.services.token_counter import estimate_tokens


def test_empty_string_returns_zero() -> None:
    assert estimate_tokens("") == 0


def test_short_string() -> None:
    assert estimate_tokens("hello") == 1


def test_longer_string() -> None:
    assert estimate_tokens("hello world") == 3


def test_deterministic() -> None:
    text = "some test string for token estimation"
    assert estimate_tokens(text) == estimate_tokens(text)


def test_unicode_counted_by_char_length() -> None:
    assert estimate_tokens("こんにちは世") == 2
