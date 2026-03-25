from __future__ import annotations

CHARS_PER_TOKEN: int = 3


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return len(text) // CHARS_PER_TOKEN


class ApproximateTokenizer:
    def count_tokens(self, text: str) -> int:
        if not text:
            return 0
        return max(1, estimate_tokens(text))
