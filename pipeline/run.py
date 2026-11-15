import argparse
import hashlib
import logging
import random
from collections import Counter
from pathlib import Path

import pandas as pd

from .classify import categorize, drop_reasons, is_national_only, summarize
from .config import REGIONS
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
             ("not excluded", {"excluded_stock", "excluded_opinion"})]
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
    print("\nDrop reasons (first failing check), by source_api:")
    by_src = Counter((d["drop_reason"].split(";")[0], d["source_api"]) for d in dropped)
    for reason, total in first.most_common():
        parts = ", ".join(f"{s}={by_src[(reason, s)]}" for s in ("google_news_rss", "newsapi"))
        print(f"  {reason:<20}{total:<7}({parts})")

    print("\nstate_basis, all unique articles (before filtering):")
    for k, v in basis_all.most_common():
        print(f"  {k:<14}{v}")
    print("state_basis, kept articles:")
    for k, v in Counter(a["state_basis"] for a in kept).most_common():
        print(f"  {k:<14}{v}")
    print(f"Detected state not among query regions: {relabelled}")

    print("\nCategory distribution (kept):")
    cats = Counter(a["category"] for a in kept)
    for k, v in cats.most_common():
        print(f"  {k:<20}{v:<6}{100 * v / len(kept):.1f}%")
    dep = Counter(a["sector"] for a in kept if a["category"] == "deployment")
    print("Deployment sectors: " + ", ".join(f"{k}={v}" for k, v in dep.most_common()))

    by_region = Counter(a["state"] for a in kept)
    print(f"\nRelevant unique articles by state ({len(kept)} total):")
    for region in sorted(REGIONS, key=lambda r: (-by_region[r], r)):
        print(f"  {region:<42}{by_region[region]}")

    rng = random.Random(1)
    print("\n10 random KEPT rows (title | state/basis | category | sector):")
    for a in rng.sample(kept, min(10, len(kept))):
        print(f"  {a['title'][:95]} | {a['state']}/{a['state_basis']} | {a['category']} | {a['sector'] or '-'}")


if __name__ == "__main__":
    main()
