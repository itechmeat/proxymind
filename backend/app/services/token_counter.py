from __future__ import annotations

import math

CHARS_PER_TOKEN: int = 3


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, math.ceil(len(text) / CHARS_PER_TOKEN))


class ApproximateTokenizer:
    def count_tokens(self, text: str) -> int:
        return estimate_tokens(text)
