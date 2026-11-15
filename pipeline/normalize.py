import html
import re
from collections import Counter
from datetime import datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from dateutil import parser as dateparser

from .config import (ABBREV_CONTEXT, ABBREV_CONTEXT_WINDOW, ORIGIN_AFTER, ORIGIN_BEFORE,
                     STATE_ABBREVIATIONS, STATE_ALIASES)

IST = ZoneInfo("Asia/Kolkata")
TRACKING_PARAMS = {"fbclid", "gclid", "mc_cid", "mc_eid", "ref", "igshid"}


def _alias_regex(alias):
    body = r"[\s\-]+".join(re.escape(w) for w in alias.split())
    # "New Delhi" is skipped: it's the national dateline on central-government
    # stories, not evidence the story is about the Delhi state government
    prefix = r"(?<![\w&])(?<!New\s)" if alias == "Delhi" else r"(?<![\w&])"
    acronym = alias.isupper() and len(alias) <= 5
    return re.compile(prefix + body + r"(?![\w&])", 0 if acronym else re.IGNORECASE)


_ALIAS_RES = [(state, _alias_regex(a)) for state, names in STATE_ALIASES.items() for a in names]
_ABBREV_RE = re.compile(r"(?<![\w&])(" + "|".join(map(re.escape, STATE_ABBREVIATIONS)) + r")(?![\w&])")
_CONTEXT_RE = re.compile(r"\b(?:" + "|".join(ABBREV_CONTEXT) + r")\b", re.IGNORECASE)
_CM_RE = re.compile(r"\bCM\b")
_WORD_RE = re.compile(r"\S+")
_ORIGIN_AFTER_RE = re.compile(ORIGIN_AFTER, re.IGNORECASE)
_ORIGIN_BEFORE_RE = re.compile(ORIGIN_BEFORE, re.IGNORECASE)


def clean_text(text):
    text = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    return re.sub(r"\s+", " ", text).strip()


def _near_government(text, start, end):
    """True if a government word sits within a few words of the span."""
    before = _WORD_RE.findall(text[:start])[-ABBREV_CONTEXT_WINDOW:]
    after = _WORD_RE.findall(text[end:])[:ABBREV_CONTEXT_WINDOW]
    window = " ".join(before + after)
    return bool(_CONTEXT_RE.search(window) or _CM_RE.search(window))


def _is_origin(text, start, end):
    return bool(_ORIGIN_AFTER_RE.match(text[end:]) or _ORIGIN_BEFORE_RE.search(text[:start]))


def find_states(text):
    """Return [(state, start, end)] for every alias hit, in text order."""
    hits = []
    for state, rx in _ALIAS_RES:
        hits.extend((state, m.start(), m.end()) for m in rx.finditer(text)
                    if not _is_origin(text, m.start(), m.end()))
    # all-caps headlines turn words like "UP" into false abbreviations
    letters = [c for c in text if c.isalpha()]
    shouting = letters and sum(c.isupper() for c in letters) / len(letters) > 0.8
    if not shouting:
        for m in _ABBREV_RE.finditer(text):
            if _near_government(text, m.start(), m.end()):
                hits.append((STATE_ABBREVIATIONS[m.group(1)], m.start(), m.end()))
    return sorted(hits, key=lambda h: h[1])


def _ranked(hits):
    """States by mention count, ties broken by first appearance."""
    counts = Counter(h[0] for h in hits)
    first = {}
    for state, start, _ in hits:
        first.setdefault(state, start)
    return sorted(counts, key=lambda s: (-counts[s], first[s]))


def normalize_state(text):
    ranked = _ranked(find_states(text or ""))
    return ranked[0] if ranked else None


def detect_states(title, description):
    """Title wins; otherwise the most-mentioned state in the description.

    Returns (primary_state, states_mentioned, basis) with basis 'title', 'description' or None.
    """
    t_ranked = _ranked(find_states(title or ""))
    d_ranked = _ranked(find_states(description or ""))
    if t_ranked:
        primary, basis = t_ranked[0], "title"
    elif d_ranked:
        primary, basis = d_ranked[0], "description"
    else:
        primary, basis = None, None
    mentioned = t_ranked + [s for s in d_ranked if s not in t_ranked]
    return primary, "|".join(mentioned), basis


def normalize_date(published_raw):
    """Return (iso_date, precision). Month-only input gives 'YYYY-MM'; nothing is guessed."""
    if not published_raw or not str(published_raw).strip():
        return None, "unknown"
    s = str(published_raw)
    try:
        a = dateparser.parse(s, default=datetime(2000, 1, 1))
        b = dateparser.parse(s, default=datetime(2001, 2, 2))
    except (ValueError, OverflowError):
        return None, "unknown"
    if a.year != b.year or a.month != b.month:
        return None, "unknown"
    if a.day != b.day:
        return a.strftime("%Y-%m"), "month"
    if a.tzinfo is not None:
        a = a.astimezone(IST)
    return a.date().isoformat(), "day"


def canonical_url(url):
    # Only meaningful for newsapi: Google News links are redirect tokens, not publisher URLs.
    parts = urlsplit(url or "")
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k.lower() not in TRACKING_PARAMS]
    return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path, urlencode(query), ""))
