import re

from .config import (AI_GUARDS, AI_PHRASES, CATEGORY_KEYWORDS, CORPORATE_LAUNCH,
                     EXCLUDE_OPINION, HEADLINE_ONLY_CATEGORIES, EXCLUDE_STOCK, GOV_ACTOR_TERMS, NATIONAL_ONLY,
                     OPINION_URL_HINTS, SECTOR_KEYWORDS, SUBJECT_MAX_GAP_WORDS,
                     SUBJECT_VERBS, SUMMARY_MAX_WORDS, TITLE_GOV_TERMS)
from .normalize import clean_text, find_states

_GUARD_RE = re.compile("|".join(AI_GUARDS))
_AI_RE = re.compile(r"\bAI\b")
_PHRASE_RE = re.compile("|".join(AI_PHRASES), re.IGNORECASE)
_GOV_RE = re.compile(r"\b(?:" + "|".join(GOV_ACTOR_TERMS) + r")s?\b", re.IGNORECASE)
_CM_RE = re.compile(r"\bCMs?\b")
_TITLE_GOV_RE = re.compile(r"\b(?:" + "|".join(TITLE_GOV_TERMS) + r")s?\b", re.IGNORECASE)
_SUBJECT_RE = re.compile(
    r"^(?:\W+\w+){0," + str(SUBJECT_MAX_GAP_WORDS) + r"}?\W+(?:" + "|".join(SUBJECT_VERBS) + r")\b",
    re.IGNORECASE)
_STOCK_RE = re.compile("|".join(EXCLUDE_STOCK), re.IGNORECASE)
_OPINION_RE = re.compile("|".join(EXCLUDE_OPINION), re.IGNORECASE)
_NATIONAL_RE = re.compile("|".join(NATIONAL_ONLY))
_CORPORATE_RE = re.compile(CORPORATE_LAUNCH, re.IGNORECASE)
_CATEGORY_RES = {k: re.compile("|".join(v), re.IGNORECASE) for k, v in CATEGORY_KEYWORDS.items()}
_SECTOR_RES = {k: re.compile("|".join(v), re.IGNORECASE) for k, v in SECTOR_KEYWORDS.items()}


def is_ai(text):
    text = _GUARD_RE.sub(" ", text or "")
    return bool(_AI_RE.search(text) or _PHRASE_RE.search(text))


def is_gov_actor(text, title_only=False):
    if _GOV_RE.search(text) or _CM_RE.search(text):
        return True
    if not title_only:
        return False
    if _TITLE_GOV_RE.search(text):
        return True
    # a state name acting as the subject: "Kerala launches ..."
    return any(_SUBJECT_RE.match(text[end:]) for _, _, end in find_states(text))


def excluded_reason(title, url=""):
    if _STOCK_RE.search(title):
        return "excluded_stock"
    if _OPINION_RE.search(title) or any(h in (url or "").lower() for h in OPINION_URL_HINTS):
        return "excluded_opinion"
    return None


def drop_reasons(title, text, state, title_only, url=""):
    """All reasons a row fails, in funnel order; empty list means relevant."""
    reasons = []
    if not is_ai(text):
        reasons.append("not_ai")
    if state is None:
        reasons.append("national_only" if is_national_only(text) else "no_state")
    if not is_gov_actor(text, title_only):
        reasons.append("corporate_launch" if _CORPORATE_RE.search(title) else "no_gov_actor")
    ex = excluded_reason(title, url)
    if ex:
        reasons.append(ex)
    return reasons


def is_national_only(text):
    return bool(_NATIONAL_RE.search(text))


def categorize(title, text):
    category = next((k for k, rx in _CATEGORY_RES.items()
                     if rx.search(title if k in HEADLINE_ONLY_CATEGORIES else text)), "other")
    sector = ""
    if category == "deployment":
        sector = next((k for k, rx in _SECTOR_RES.items() if rx.search(text)), "other")
    return category, sector


def summarize(description, title):
    text = clean_text(description)
    if not text:
        return title
    first = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0]
    words = first.split()
    return " ".join(words[:SUMMARY_MAX_WORDS]) + ("…" if len(words) > SUMMARY_MAX_WORDS else "")
