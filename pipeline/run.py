import argparse
import logging
from collections import Counter

from .config import REGIONS
from .fetch import fetch_newsapi, fetch_rss, load_cached


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
    print("\nBy source_api:")
    for k, v in Counter(r["source_api"] for r in records).most_common():
        print(f"  {k:<18}{v}")

    by_region = Counter(r["query_region"] for r in records)
    print("\nBy query_region:")
    for region in sorted(REGIONS, key=lambda r: (-by_region[r], r)):
        print(f"  {region:<42}{by_region[region]}")

    print(f"\nPossibly truncated queries: {len(truncated)}")
    for q in truncated:
        print(f"  {q}")


if __name__ == "__main__":
    main()
