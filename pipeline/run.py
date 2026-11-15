import argparse
import hashlib
import logging
import random
from collections import Counter
from pathlib import Path

import pandas as pd

from .classify import categorize, drop_reasons, is_national_only, summarize
from .config import REGIONS
from .coverage import coverage_table
from .dedup import build_events
from .export import write_all
from .fetch import fetch_newsapi, fetch_rss, load_cached
from .normalize import canonical_url, clean_text, detect_states, normalize_date

PROCESSED = Path(__file__).resolve().parent.parent / "data" / "processed"
ARTICLE_COLS = ["article_id", "state", "state_basis", "states_mentioned", "query_regions", "title",
                "date", "date_precision", "category", "sector", "summary", "source_name",
                "source_domain", "url", "source_api"]


def _article_id(r):
    url = r["url"] if r["source_api"] == "google_news_rss" else canonical_url(r["url"])
    return url, hashlib.sha1(url.encode()).hexdigest()[:12]


def unique_articles(records):
    """Collapse rows sharing an article_id, remembering every region that returned them."""
    by_id = {}
    for r in records:
        url, aid = _article_id(r)
        if aid not in by_id:
            by_id[aid] = {"rec": r, "url": url, "regions": []}
        if r["query_region"] not in by_id[aid]["regions"]:
            by_id[aid]["regions"].append(r["query_region"])
    return by_id


def process(unique):
    kept, dropped = [], []
    relabelled = 0
    basis_all = Counter()
    for aid, u in unique.items():
        r, url, regions = u["rec"], u["url"], u["regions"]
        is_rss = r["source_api"] == "google_news_rss"
        title = clean_text(r["title"])
        # the RSS description is just an anchor repeating the title
        desc = "" if is_rss else clean_text(r["description"])
        text = f"{title} {desc}".strip()

        state, mentioned, basis = detect_states(title, desc)
        if state and state not in regions:
            relabelled += 1
        # a single-region hit is a usable label, unless the story reads as national
        if state is None and len(regions) == 1 and not is_national_only(text):
            state, mentioned, basis = regions[0], regions[0], "query"
        basis_all[basis or "none"] += 1

        reasons = drop_reasons(title, text, state, title_only=not desc, url=url)
        if reasons:
            dropped.append({"title": title, "query_regions": "|".join(regions),
                            "state": state or "", "source_api": r["source_api"],
                            "drop_reason": ";".join(reasons)})
            continue
        date, precision = normalize_date(r["published_raw"])
        category, sector = categorize(title, text)
        kept.append({
            "article_id": aid, "state": state, "state_basis": basis, "states_mentioned": mentioned,
            "query_regions": "|".join(regions), "title": title,
            "date": date or "", "date_precision": precision,
            "category": category, "sector": sector,
            "summary": summarize(desc, title),
            "source_name": r["source_name"], "source_domain": r["source_domain"],
            "url": url, "source_api": r["source_api"],
        })
    return kept, dropped, relabelled, basis_all


def funnel(n_raw, n_unique, dropped):
    first = Counter(d["drop_reason"].split(";")[0] for d in dropped)
    stages = [("raw records", n_raw), ("unique articles", n_unique)]
    n = n_unique
    # each stage removes rows whose first failing reason belongs to it
    order = [("passed AI check", {"not_ai"}),
             ("state assigned", {"no_state", "national_only"}),
             ("government actor", {"no_gov_actor", "corporate_launch"}),
             ("not excluded", {"excluded_stock", "excluded_opinion", "incident_not_policy"})]
    for label, reasons in order:
        n -= sum(first[x] for x in reasons)
        stages.append((label, n))
    return stages, first


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", help="skip fetching, load data/raw only")
    ap.add_argument("--regions", help='comma-separated, e.g. "Karnataka,Kerala"')
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    regions = list(REGIONS)
    if args.regions:
        regions = [r.strip() for r in args.regions.split(",") if r.strip()]
        unknown = [r for r in regions if r not in REGIONS]
        if unknown:
            ap.error(f"unknown regions: {unknown}")

    if not args.offline:
        fetch_rss(regions)
        fetch_newsapi(regions)

    records, truncated = load_cached()
    print(f"\nTotal raw records: {len(records)}")
    for k, v in Counter(r["source_api"] for r in records).most_common():
        print(f"  {k:<18}{v}")
    print(f"Possibly truncated queries: {len(truncated)}")
    for q in truncated:
        print(f"  {q}")

    unique = unique_articles(records)
    kept, dropped, relabelled, basis_all = process(unique)
    PROCESSED.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(kept, columns=ARTICLE_COLS).to_csv(PROCESSED / "articles.csv", index=False)
    pd.DataFrame(dropped, columns=["title", "query_regions", "drop_reason"]) \
        .to_csv(PROCESSED / "dropped.csv", index=False)

    stages, first = funnel(len(records), len(unique), dropped)
    print("\nFunnel:")
    for label, n in stages:
        print(f"  {label:<20}{n}")
    print("\nDrop reasons (first failing check):")
    for reason, total in first.most_common():
        print(f"  {reason:<22}{total}")
    print(f"\nstate_basis (kept): {dict(Counter(a['state_basis'] for a in kept))}")

    # phase 3 starts from the written articles.csv
    articles = pd.read_csv(PROCESSED / "articles.csv", dtype=str, keep_default_na=False).to_dict("records")
    events = build_events(articles)
    coverage = coverage_table(events)
    stats = {"funnel": stages, "drop_reasons": dict(first), "articles": len(articles),
             "relabelled": relabelled, "basis_all": dict(basis_all),
             "unknown_date_articles": sum(a["date_precision"] == "unknown" for a in articles)}
    quality = write_all(events, coverage, stats)

    print("\nCategory distribution (events):")
    cats = Counter(e["category"] for e in events)
    for k, v in cats.most_common():
        print(f"  {k:<20}{v:<6}{100 * v / len(events):.1f}%")
    print(f"  % other: {100 * cats['other'] / len(events):.1f}   % statement: {100 * cats['statement'] / len(events):.1f}")

    print(f"\nArticles -> events: {len(articles)} -> {len(events)} "
          f"({len(articles) - len(events)} duplicates collapsed)")
    print("\n5 largest clusters:")
    for c in quality["largest_clusters"]:
        print(f"  [{c['state']}] size {c['size']}")
        for t in c["member_titles"][:6]:
            print(f"      - {t[:100]}")

    print("\nCoverage (tier | state | events cats pubs months multi query | reason):")
    for c in coverage:
        print(f"  {c['tier']:<13}{c['state']:<42}{c['events']:>4}{c['distinct_categories']:>4}"
              f"{c['distinct_publishers']:>4}{c['active_months']:>4}{c['multi_source_events']:>4}"
              f"{c['query_basis_events']:>4}  {c['reason']}")
    print(f"States by tier: {quality['states_by_tier']}")

    sample = pd.read_csv(PROCESSED / "dedup_sample.csv", dtype=str, keep_default_na=False)
    print("\n5 clusters from dedup_sample.csv:")
    for eid in list(dict.fromkeys(sample["event_id"]))[:5]:
        grp = sample[sample["event_id"] == eid]
        print(f"  {eid} [{grp.iloc[0]['state']}]")
        for _, m in grp.iterrows():
            mark = "*" if m["is_representative"] == "True" else " "
            print(f"    {mark} {m['date'] or '????-??-??'} {m['source_name'][:22]:<22} {m['member_title'][:80]}")


if __name__ == "__main__":
    main()
