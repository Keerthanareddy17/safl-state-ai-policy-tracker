import hashlib
import re
from collections import Counter
from datetime import date

from rapidfuzz import fuzz

from .config import (NATIONAL_OUTLETS, NEAR_DUP_DAYS, NEAR_DUP_RATIO,
                     NEAR_DUP_RATIO_NO_DATE)


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


def cluster(articles):
    """Group articles into events: exact url/title matches, then fuzzy same-state matches."""
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
    for idx in by_state.values():
        for x, i in enumerate(idx):
            for j in idx[x + 1:]:
                if find(i) == find(j):
                    continue
                ratio = fuzz.token_set_ratio(norms[i], norms[j])
                if days[i] and days[j]:
                    ok = abs((days[i] - days[j]).days) <= NEAR_DUP_DAYS and ratio >= NEAR_DUP_RATIO
                else:
                    ok = ratio >= NEAR_DUP_RATIO_NO_DATE
                if ok:
                    union(i, j)

    groups = {}
    for i, a in enumerate(articles):
        groups.setdefault(find(i), []).append(a)
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


def build_events(articles):
    events = [build_event(c) for c in cluster(articles)]
    return sorted(events, key=lambda e: (e["state"], e["date"], e["event_id"]))
