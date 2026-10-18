"""Small text helpers for Memory v2: no model, no network, no files. Easy to test.

  - tokens / overlap: a cheap "how alike are these two notes" score (used when embeddings aren't there)
  - extract_date / expiry_for: the calendar date a note talks about ("test on 12 Nov")
  - sensitive_text: family, health or money, so a notification can use neutral words
"""

import math
import re
from collections import Counter
from datetime import date, datetime, time as dtime, timedelta

STOPWORDS = frozenset(
    "a an and are as at be been but by for from has have he her his i in is it its of on or our she so that the "
    "their them they this to was we were will with you your user users uses also about into than then there "
    "which who what when how not no yes do does did can could would should may might very more most".split())

_WORD = re.compile(r"[a-z0-9çğıöşü]+", re.I)


def stem(word: str) -> str:
    """'meetings' -> 'meeting', 'studies' -> 'study'. Crude on purpose: same on both sides of a comparison."""
    word = word.casefold()
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def tokens(text: str) -> list[str]:
    return [stem(w) for w in _WORD.findall(text) if w.casefold() not in STOPWORDS and len(w) > 1]


def token_set(text: str) -> frozenset[str]:
    return frozenset(tokens(text))


def overlap(a: str, b: str) -> float:
    """Jaccard of the two notes' word stems, 0..1 (1 = the same words)."""
    x, y = token_set(a), token_set(b)
    return len(x & y) / len(x | y) if x and y else 0.0


class Lexicon:
    """Word weights (rarer word = heavier) over a set of notes, for TF-IDF-style matching."""

    def __init__(self, texts: list[str]) -> None:
        self.n = max(1, len(texts))
        self.df = Counter(w for t in texts for w in token_set(t))

    def idf(self, word: str) -> float:
        return math.log(1 + self.n / (1 + self.df.get(word, 0)))

    def score(self, query: str, text: str) -> float:
        """Share of the query's weight found in the text, 0..1."""
        want = token_set(query)
        if not want:
            return 0.0
        have = token_set(text)
        total = sum(self.idf(w) for w in want)
        return sum(self.idf(w) for w in want & have) / total if total else 0.0


# --- dates -----------------------------------------------------------------------------

_MONTHS = {m: i for i, names in enumerate(
    ["jan january", "feb february", "mar march", "apr april", "may", "jun june", "jul july", "aug august",
     "sep sept september", "oct october", "nov november", "dec december"], 1) for m in names.split()}
_MONTH = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
_ISO = re.compile(r"\b(20\d\d)-(\d\d)-(\d\d)\b")
_DAY_FIRST = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?{_MONTH}\b(?:,?\s+(20\d\d))?", re.I)
_MONTH_FIRST = re.compile(rf"\b{_MONTH}\s+(\d{{1,2}})(?:st|nd|rd|th)?\b(?:,?\s+(20\d\d))?", re.I)
# A date in these notes is a birthday or a log entry, not something that expires.
_NOT_AN_EVENT = re.compile(r"\b(born|birthday|birth date|age \d+|since|newly|enabled|started|created|added)\b", re.I)


def extract_date(text: str, ref: date) -> date | None:
    """The first calendar date in the text ("12 Nov", "Nov 12, 2026", "2026-11-12"). With no year it's
    the next time that day comes round (this year, unless it was more than ~6 months ago)."""
    found = []
    for m in _ISO.finditer(text):
        found.append((m.start(), int(m[1]), int(m[2]), int(m[3]), True))
    for m in _DAY_FIRST.finditer(text):
        found.append((m.start(), int(m[3]) if m[3] else 0, _MONTHS[m[2].casefold()], int(m[1]), bool(m[3])))
    for m in _MONTH_FIRST.finditer(text):
        found.append((m.start(), int(m[3]) if m[3] else 0, _MONTHS[m[1].casefold()], int(m[2]), bool(m[3])))
    for _, year, month, day, has_year in sorted(found):
        try:
            if has_year:
                return date(year, month, day)
            d = date(ref.year, month, day)
            return d if (ref - d).days <= 180 else date(ref.year + 1, month, day)
        except ValueError:
            continue
    return None


def expiry_for(text: str, ref: date) -> float | None:
    """When a note about an upcoming date stops being true: the end of that day (a timestamp), or None
    when there's no date, it's not later than `ref`, or it's a birthday / log line."""
    if _NOT_AN_EVENT.search(text):
        return None
    when = extract_date(text, ref)
    if when is None or when <= ref:
        return None
    return datetime.combine(when + timedelta(days=1), dtime.min).timestamp()


def without_dates(text: str) -> str:
    """The text with its dates cut out, so "test on 12 Nov" and "test moved to 19 Nov" compare as the same subject."""
    for pattern in (_ISO, _DAY_FIRST, _MONTH_FIRST):
        text = pattern.sub(" ", text)
    return text


CHANGE_CUE = re.compile(r"\b(moved|rescheduled|postponed|delayed|pushed|brought forward|changed|now|instead|new date)\b", re.I)

# --- sensitive topics ------------------------------------------------------------------

_SENSITIVE = re.compile(
    r"\b(mother|father|mom|mum|dad|parents?|sister|brother|cousin|grand(?:mother|father|ma|pa)|aunt|uncle|family|"
    r"girlfriend|boyfriend|doctor|hospital|medicine|medication|therapy|therapist|anxiety|depress\w*|diagnos\w*|"
    r"allerg\w*|illness|sick|health|surgery|"
    r"salary|debt|loan|bank|savings|allowance|tax|income)\b", re.I)


def sensitive_text(text: str) -> bool:
    """Family, health or money: a notification about it should use neutral words."""
    return bool(_SENSITIVE.search(text))


def private_text(text: str) -> bool:
    """Text the user keeps private: never sent to a hosted model."""
    return "#private" in text.casefold()
