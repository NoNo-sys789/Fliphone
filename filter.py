"""
filter.py – Content filter for Phonebooth V2.

Philosophy
----------
We censor slurs and targeted hate speech, NOT general profanity.
Words like "fuck", "shit", "damn" etc. pass through untouched.
The goal is to prevent the bot being a harassment tool, not a swear jar.

How it works
------------
- Case-insensitive exact word matching (with word boundaries)
- Basic leet-speak normalisation (3→e, 4→a, 1→i, 0→o, @→a, $→s)
- Matched words are replaced with [censored]
- Returns (filtered_text, was_censored: bool)
"""

import re
from typing import Optional

# ── Word list ─────────────────────────────────────────────────────────────────
# Slurs and targeted hate speech only.
# Mild/general profanity is intentionally NOT included.
_BLOCKED: list[str] = [
    # Racial slurs
    "nigger", "nigga", "nigg3r", "n1gger", "n1gga",
    "chink", "ch1nk", "gook", "g00k",
    "spic", "sp1c", "wetback", "w3tback",
    "kike", "k1ke",
    "raghead", "sandnigger", "sand nigger",
    "cracker",   # context-dependent but commonly used as slur
    "coon", "c00n",
    "jap",
    "towelhead",
    "zipperhead",
    "beaner",
    "gringo",    # often used aggressively
    "honky",
    "darkie",

    # Homophobic / transphobic slurs
    "faggot", "f4ggot", "fag",
    "dyke", "dy ke",
    "tranny", "tr4nny",
    "shemale", "she male",

    # Ableist slurs
    "retard", "ret4rd", "ret@rd",
    "retarded",
    "spastic",

    # Misogynistic slurs
    "cunt",   # included — primarily used as a targeted attack word
    "whore",  # context — included as it's mostly used to demean
    "sl ut",

    # General hate / harassment terms
    "kys",          # kill yourself
    "kill yourself",
    "go kill",
    "neck yourself",
    "rope yourself",
    "drink bleach",
    "die slowl",    # partial — catches "die slowly"

    # Nazi / extremist symbols as text
    "heil hitler", "heil h1tler",
    "1488",
    "14 88",
    "white power",
    "white supremacy",
    "white pride",
    "kkk",
    "ku klux",
]

# Pre-compile: one pattern per entry, word-boundary aware
# We also build a leet-normalised version for matching

_LEET_MAP = str.maketrans({
    "3": "e", "4": "a", "1": "i", "0": "o",
    "@": "a", "$": "s", "!": "i", "5": "s",
})


def _normalise(text: str) -> str:
    """Lowercase + leet-speak → plain letters."""
    return text.lower().translate(_LEET_MAP)


def _make_pattern(word: str) -> re.Pattern:
    """
    Build a regex that matches the word (after normalisation) with word
    boundaries.  Multi-word phrases use flexible whitespace matching.
    """
    escaped = re.escape(_normalise(word))
    # Allow any whitespace between words in multi-word phrases
    escaped = re.sub(r"\\ ", r"\\s+", escaped)
    return re.compile(r"(?<!\w)" + escaped + r"(?!\w)", re.IGNORECASE)


_PATTERNS: list[re.Pattern] = [_make_pattern(w) for w in _BLOCKED]


# ── Public API ────────────────────────────────────────────────────────────────

def filter_message(text: str) -> tuple[str, bool]:
    """
    Apply the content filter to `text`.

    Returns
    -------
    (filtered_text, was_censored)
        filtered_text  – text with blocked words replaced by [censored]
        was_censored   – True if at least one replacement was made
    """
    if not text:
        return text, False

    normalised = _normalise(text)
    censored   = False
    result     = text  # we'll replace in the original (preserves casing elsewhere)

    for pattern in _PATTERNS:
        if pattern.search(normalised):
            # Replace in original text by matching the same positions
            # We do this by running the pattern on the normalised string,
            # then replacing those spans in the original.
            new_result = []
            last       = 0
            for m in pattern.finditer(normalised):
                new_result.append(result[last:m.start()])
                new_result.append("[censored]")
                last = m.end()
                censored = True
            new_result.append(result[last:])
            result     = "".join(new_result)
            normalised = _normalise(result)   # re-normalise for next pattern

    return result, censored


def should_warn(text: str) -> bool:
    """Shortcut: returns True if the message contains a blocked word."""
    _, hit = filter_message(text)
    return hit
