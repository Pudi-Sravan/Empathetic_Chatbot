import re

# Narrow phrase sets avoid treating ordinary sentiment as proof of efficacy.
POSITIVE = re.compile(r"\b(?:that|it|this)\s+(?:worked|helped)(?:\s+(?:a lot|so much|really))?\b|\b(?:worked|helped)\s+(?:a lot|so much|really)\b|\bmade (?:him|her|them) calmer\b", re.I)
NEGATIVE = re.compile(r"\b(made (it|him|her|them) worse|didn'?t work|wasn'?t helpful|backfired)\b", re.I)


def feedback_signal(text: str) -> int:
    """Return +1, -1, or 0. Negative wins if a message contains both."""
    if NEGATIVE.search(text):
        return -1
    if POSITIVE.search(text):
        return 1
    return 0
