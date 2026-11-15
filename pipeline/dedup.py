import hashlib
import re
from collections import Counter
from datetime import date

from rapidfuzz import fuzz

from .config import (NATIONAL_OUTLETS, NEAR_DUP_DAYS, SET_THRESHOLD,
                     SET_THRESHOLD_NO_DATE, SORT_THRESHOLD)


def norm_title(title, source_name=""):
    t = title.lower().strip()
    m = re.search(r"\s[-|–—]\s([^-|–—]+)$", t)
    if m and m.group(1).strip() == (source_name or "").lower().strip():
        t = t[: m.start()]
    t = re.sub(r"[^\w\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _day(a):
    return date.fromisoformat(a["date"]) if a["date_precision"] == "day" and a["date"] else None


def _publisher(a):
    return (a["source_name"] or a["source_domain"]).strip().lower()


_NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


def numbers(title):
    """Digit numbers in a title, normalized so '₹1,150 crore' gives {'1150'}. Number words are ignored."""
    out = set()
    for tok in _NUM_RE.findall(title):
        val = float(tok.replace(",", "").rstrip("."))
        out.add(str(int(val)) if val == int(val) else str(val))
    return out


def _numbers_guard(title_a, title_b):
    na, nb = numbers(title_a), numbers(title_b)
    return bool(na and nb and not (na & nb))


def cluster(articles, pair_log=None):
    """Group articles into events: exact url/title matches, then fuzzy same-state matches.

    If pair_log is a list, every same-state pair is appended to it with its scores.
    """
    n = len(articles)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        parent[find(i)] = find(j)

    norms = [norm_title(a["title"], a["source_name"]) for a in articles]
    days = [_day(a) for a in articles]

    seen_url, seen_title = {}, {}
    for i, a in enumerate(articles):
        for seen, key in ((seen_url, a["url"]), (seen_title, (a["state"], norms[i]))):
            if key in seen:
                union(i, seen[key])
            else:
                seen[key] = i

    by_state = {}
    for i, a in enumerate(articles):
        by_state.setdefault(a["state"], []).append(i)
    pairs = []
    for idx in by_state.values():
        for x, i in enumerate(idx):
            for j in idx[x + 1:]:
                set_score = fuzz.token_set_ratio(norms[i], norms[j])
                sort_score = fuzz.token_sort_ratio(norms[i], norms[j])
                guard = _numbers_guard(articles[i]["title"], articles[j]["title"])
                if days[i] and days[j]:
                    in_window = abs((days[i] - days[j]).days) <= NEAR_DUP_DAYS
                    ok = in_window and set_score >= SET_THRESHOLD
                else:
                    in_window = None
                    ok = set_score >= SET_THRESHOLD_NO_DATE
                ok = ok and sort_score >= SORT_THRESHOLD and not guard
                if ok:
                    union(i, j)
                pairs.append((i, j, set_score, sort_score, guard, in_window, ok))

    groups = {}
    for i, a in enumerate(articles):
        groups.setdefault(find(i), []).append(a)
    if pair_log is not None:
        for i, j, set_score, sort_score, guard, in_window, ok in pairs:
            pair_log.append({
                "state": articles[i]["state"], "date_a": articles[i]["date"], "date_b": articles[j]["date"],
                "title_a": articles[i]["title"], "title_b": articles[j]["title"],
                "set_score": round(set_score, 1), "sort_score": round(sort_score, 1),
                "numbers_guard_fired": guard, "merged": ok,
                "in_window": in_window, "same_cluster": find(i) == find(j),
            })
    return list(groups.values())


def _is_national(a):
    name, dom = a["source_name"].lower(), a["source_domain"].lower()
    return any(re.search(r"\b" + re.escape(o.lower()) + r"\b", name) or d in dom
               for o, d in NATIONAL_OUTLETS)


def _rank(a):
    gov = a["source_domain"].lower().endswith(".gov.in")
    # summary stands in for description length; Google News rows only have the title
    return (not gov, not _is_national(a), a["state_basis"] != "title",
            -len(a["summary"]), a["date"] or "9999")


def build_event(members):
    rep = min(members, key=_rank)
    cats = Counter(m["category"] for m in members)
    top, count = cats.most_common(1)[0]
    category = top if count * 2 > len(members) and top != rep["category"] else rep["category"]
    sector = ""
    if category == "deployment":
        sector = next((m["sector"] for m in [rep] + members if m["sector"]), "")

    day_dates = sorted(m["date"] for m in members if m["date_precision"] == "day" and m["date"])
    month_dates = sorted(m["date"] for m in members if m["date_precision"] == "month" and m["date"])
    if day_dates:
        date_, precision = day_dates[0], "day"
    elif month_dates:
        date_, precision = month_dates[0], "month"
    else:
        date_, precision = "", "unknown"

    publishers, seen = [], set()
    for m in [rep] + members:
        if _publisher(m) and _publisher(m) not in seen:
            seen.add(_publisher(m))
            publishers.append(m["source_name"] or m["source_domain"])
    event_id = hashlib.sha1(
        f"{rep['state']}|{norm_title(rep['title'], rep['source_name'])}".encode()).hexdigest()[:10]
    return {
        "event_id": event_id, "state": rep["state"], "state_basis": rep["state_basis"],
        "title": rep["title"], "date": date_, "date_precision": precision,
        "category": category, "sector": sector, "summary": rep["summary"],
        "source_name": rep["source_name"], "source_url": rep["url"],
        "source_count": len(publishers), "other_sources": "|".join(publishers[1:]),
        "publishers": publishers, "members": members, "rep_url": rep["url"],
    }


def build_events(articles, pair_log=None):
    events = [build_event(c) for c in cluster(articles, pair_log)]
    return sorted(events, key=lambda e: (e["state"], e["date"], e["event_id"]))
