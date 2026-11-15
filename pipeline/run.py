import argparse
import hashlib
import json
import logging
import random
from collections import Counter
from pathlib import Path

import pandas as pd

from .classify import categorize, drop_reasons, is_national_only, summarize
from .config import REGIONS, data_end, quarter_windows
from .coverage import coverage_table
from .dedup import build_events
from .export import calibration, write_all
from .precision import compute as compute_precision, update_outputs
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

        date, precision = normalize_date(r["published_raw"])
        reasons = drop_reasons(title, text, state, title_only=not desc, url=url, basis=basis,
                               source_name=r["source_name"], source_domain=r["source_domain"])
        # older stories re-published inside the search window
        if date and not (quarter_windows()[0][0].isoformat() <= date <= data_end().isoformat()):
            reasons.append("out_of_window")
        if reasons:
            dropped.append({"title": title, "query_regions": "|".join(regions),
                            "state": state or "", "source_api": r["source_api"],
                            "drop_reason": ";".join(reasons)})
            continue
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
             ("not excluded", {"excluded_stock", "excluded_opinion", "incident_not_policy", "foreign_government",
                                 "national_actor", "foreign_outlet"}),
             ("in data window", {"out_of_window"})]
    for label, reasons in order:
        n -= sum(first[x] for x in reasons)
        stages.append((label, n))
    return stages, first


def _previous_run():
    """Tiers and counts from the last run's outputs, read before they are overwritten."""
    tiers, counts = {}, {"articles": "n/a", "events": "n/a"}
    cov = PROCESSED / "state_coverage.csv"
    if cov.exists():
        tiers = dict(pd.read_csv(cov)[["state", "tier"]].values)
    rep = PROCESSED / "quality_report.json"
    if rep.exists():
        q = json.loads(rep.read_text())
        counts = {"articles": q["articles"], "events": q["events"]}
    return tiers, counts


def _print_pairs(pairs):
    for p in pairs:
        print(f"  [{p['state']}] set={p['set_score']} sort={p['sort_score']} "
              f"guard={p['numbers_guard_fired']} {p['date_a']}/{p['date_b']}")
        print(f"      A: {p['title_a'][:105]}")
        print(f"      B: {p['title_b'][:105]}")


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
    unique = unique_articles(records)
    kept, dropped, relabelled, basis_all = process(unique)
    PROCESSED.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(kept, columns=ARTICLE_COLS).to_csv(PROCESSED / "articles.csv", index=False)
    pd.DataFrame(dropped, columns=["title", "query_regions", "drop_reason"]) \
        .to_csv(PROCESSED / "dropped.csv", index=False)

    stages, first = funnel(len(records), len(unique), dropped)

    # phase 3 starts from the written articles.csv
    articles = pd.read_csv(PROCESSED / "articles.csv", dtype=str, keep_default_na=False).to_dict("records")
    prev_tier, prev_counts = _previous_run()
    pair_log = []
    events = build_events(articles, pair_log)
    coverage = coverage_table(events)
    stats = {"funnel": stages, "drop_reasons": dict(first), "articles": len(articles),
             "relabelled": relabelled, "basis_all": dict(basis_all),
             "unknown_date_articles": sum(a["date_precision"] == "unknown" for a in articles)}
    quality = write_all(events, coverage, stats)
    merged_pairs, missed_pairs = calibration(pair_log)
    labelled = compute_precision()
    if labelled:
        update_outputs(labelled)  # write_all rebuilds the JSON files, so re-attach precision

    print(f"\nArticles -> events: before {prev_counts['articles']} -> {prev_counts['events']}, "
          f"after {len(articles)} -> {len(events)} ({len(articles) - len(events)} duplicates collapsed)")
    print("\nCoverage (tier change | state | events cats pubs months multi query share | reason):")
    for c in coverage:
        before = prev_tier.get(c["state"], "?")
        change = c["tier"] if before == c["tier"] else f"{before} -> {c['tier']}"
        print(f"  {change:<30}{c['state']:<42}{c['events']:>4}{c['distinct_categories']:>4}"
              f"{c['distinct_publishers']:>4}{c['active_months']:>4}{c['multi_source_events']:>4}"
              f"{c['query_basis_events']:>4}{c['query_basis_share']:>6.2f}  {c['reason']}")
    print(f"States by tier: {quality['states_by_tier']}")

    print("\n10 lowest-scoring merged pairs (possible over-merges)")
    _print_pairs(merged_pairs[:10])
    rel = pd.read_csv(PROCESSED / "relevance_sample.csv", dtype=str, keep_default_na=False)
    print(f"\nrelevance_sample.csv ({len(rel)} events): event_id | state | category | title")
    for _, r in rel.iterrows():
        print(f"  {r['event_id']} | {r['state']} | {r['category']} | {r['title'][:110]}")


if __name__ == "__main__":
    main()
