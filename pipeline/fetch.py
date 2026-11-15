import json
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote_plus

import feedparser
import requests
from dotenv import load_dotenv

from .config import (NEWSAPI_LOOKBACK_DAYS, QUERY_GROUPS, REGIONS,
                     TRUNCATION_THRESHOLD, data_end, quarter_windows)

log = logging.getLogger(__name__)

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"
RSS_DIR = RAW_DIR / "rss"
NEWSAPI_DIR = RAW_DIR / "newsapi"

RSS_URL = "https://news.google.com/rss/search?q={q}&hl=en-IN&gl=IN&ceid=IN:en"
NEWSAPI_URL = "https://newsapi.org/v2/everything"
AI_TERMS = '("AI" OR "artificial intelligence")'
UA = {"User-Agent": "Mozilla/5.0 (compatible; policy-tracker/0.1)"}


def _slug(text):
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _record(source_api, region, title, description, url, source_name,
            source_domain, published_raw, fetched_at):
    return {
        "source_api": source_api,
        "query_region": region,
        "title": title,
        "description": description,
        "url": url,
        "source_name": source_name,
        "source_domain": source_domain,
        "published_raw": published_raw,
        "fetched_at": fetched_at,
    }


def _write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1))


# Google News RSS
def build_rss_query(terms, group_expr, start, end):
    places = " OR ".join(f'"{t}"' if " " in t else t for t in terms)
    return f"({places}) {AI_TERMS} {group_expr} after:{start:%Y-%m-%d} before:{end:%Y-%m-%d}"


def _get_with_backoff(url, headers=None, params=None, retries=3):
    """GET that retries 429/5xx with exponential backoff, returns the response or None."""
    for attempt in range(retries + 1):
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=30)
        except requests.RequestException as exc:
            log.warning("request error (%s)", type(exc).__name__)
            resp = None
        if resp is not None and resp.status_code < 400:
            return resp
        status = resp.status_code if resp is not None else None
        retryable = resp is None or status == 429 or status >= 500
        if not retryable or attempt == retries:
            log.warning("giving up, last status %s", status)
            return resp
        wait = 2 ** (attempt + 1)
        log.warning("status %s, retrying in %ss", status, wait)
        time.sleep(wait)


def _clean_title(title, publisher):
    if publisher and title.endswith(" - " + publisher):
        return title[: -len(publisher) - 3]
    return re.sub(r"\s+-\s+[^-]+$", "", title)


def _parse_rss(content, region, fetched_at):
    feed = feedparser.parse(content)
    items = []
    for e in feed.entries:
        src = e.get("source") or {}
        name = src.get("title", "")
        domain = re.sub(r"^https?://(www\.)?", "", src.get("href", "")).split("/")[0]
        items.append(_record("google_news_rss", region,
                             _clean_title(e.get("title", ""), name),
                             e.get("summary", ""), e.get("link", ""),
                             name, domain, e.get("published", ""), fetched_at))
    return items


def fetch_rss(regions):
    for region in regions:
        for group, expr in QUERY_GROUPS.items():
            for start, end in quarter_windows():
                path = RSS_DIR / f"{_slug(region)}__{group}__{start}_{end}.json"
                if path.exists():
                    continue
                query = build_rss_query(REGIONS[region], expr, start, end)
                url = RSS_URL.format(q=quote_plus(query))
                resp = _get_with_backoff(url, headers=UA)
                time.sleep(1)
                if resp is None or resp.status_code >= 400:
                    log.warning("skipping %s/%s/%s", region, group, start)
                    continue
                fetched_at = _now()
                items = _parse_rss(resp.content, region, fetched_at)
                if len(items) >= TRUNCATION_THRESHOLD:
                    log.warning("possibly truncated (%d items): %s", len(items), query)
                _write(path, {
                    "region": region, "group": group, "query": query,
                    "request_url": url, "fetched_at": fetched_at,
                    "item_count": len(items), "items": items,
                })


# NewsAPI 
def fetch_newsapi(regions):
    load_dotenv()
    key = os.getenv("NEWSAPI_KEY")
    if not key:
        log.warning("NEWSAPI_KEY not set, skipping NewsAPI")
        return
    since = data_end() - timedelta(days=NEWSAPI_LOOKBACK_DAYS)
    for region in regions:
        path = NEWSAPI_DIR / f"{_slug(region)}.json"
        if path.exists():
            continue
        terms = " OR ".join(f'"{t}"' if " " in t else t for t in REGIONS[region])
        query = f"({terms}) AND {AI_TERMS}"
        params = {"q": query, "language": "en", "sortBy": "publishedAt",
                  "pageSize": 100, "searchIn": "title,description", "from": since.isoformat()}
        # key goes in a header so it can't leak through URLs in error messages
        resp = _get_with_backoff(NEWSAPI_URL, headers={"X-Api-Key": key}, params=params)
        time.sleep(1)
        if resp is None:
            log.warning("NewsAPI failed for %s: no response", region)
            continue
        data = resp.json() if resp.content else {}
        if resp.status_code >= 400 or data.get("status") != "ok":
            log.warning("NewsAPI failed for %s: %s %s", region, resp.status_code,
                        data.get("message", ""))
            continue
        fetched_at = _now()
        items = [
            _record("newsapi", region, a.get("title") or "", a.get("description") or "",
                    a.get("url") or "", (a.get("source") or {}).get("name") or "",
                    re.sub(r"^https?://(www\.)?", "", a.get("url") or "").split("/")[0],
                    a.get("publishedAt") or "", fetched_at)
            for a in data.get("articles", [])
        ]
        _write(path, {
            "region": region, "query": query, "fetched_at": fetched_at,
            "total_results": data.get("totalResults"),
            "item_count": len(items), "items": items,
        })


# loading 

def load_cached():
    """Return (records, truncated_queries) from everything under data/raw."""
    records, truncated = [], []
    for path in sorted(RAW_DIR.glob("*/*.json")):
        blob = json.loads(path.read_text())
        records.extend(blob["items"])
        if path.parent.name == "rss" and blob["item_count"] >= TRUNCATION_THRESHOLD:
            truncated.append(blob["query"])
    return records, truncated
