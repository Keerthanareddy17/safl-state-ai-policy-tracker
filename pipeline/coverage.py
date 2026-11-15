from .config import (FEATURED_MIN_ACTIVE_MONTHS, FEATURED_MIN_CATEGORIES,
                     FEATURED_MAX_QUERY_SHARE, FEATURED_MIN_EVENTS,
                     FEATURED_MIN_PUBLISHERS,
                     LOW_COVERAGE_MIN_EVENTS, NON_SUBSTANTIVE_CATEGORIES, REGIONS)

TIER_ORDER = {"featured": 0, "low_coverage": 1, "insufficient": 2}


def coverage_table(events):
    rows = []
    for region in REGIONS:
        evs = [e for e in events if e["state"] == region]
        publishers = {p.lower() for e in evs for p in e["publishers"]}
        row = {
            "state": region,
            "events": len(evs),
            "distinct_categories": len({e["category"] for e in evs} - NON_SUBSTANTIVE_CATEGORIES),
            "distinct_publishers": len(publishers),
            "active_months": len({e["date"][:7] for e in evs if e["date"]}),
            "multi_source_events": sum(e["source_count"] >= 2 for e in evs),
            "query_basis_events": sum(e["state_basis"] == "query" for e in evs),
        }
        row["query_basis_share"] = round(row["query_basis_events"] / len(evs), 2) if evs else 0.0
        checks = [("events", FEATURED_MIN_EVENTS), ("distinct_categories", FEATURED_MIN_CATEGORIES),
                  ("distinct_publishers", FEATURED_MIN_PUBLISHERS), ("active_months", FEATURED_MIN_ACTIVE_MONTHS)]
        failed = [f"{k} {row[k]}<{need}" for k, need in checks if row[k] < need]
        if row["query_basis_share"] > FEATURED_MAX_QUERY_SHARE:
            failed.append(f"query_basis_share {row['query_basis_share']:.2f}>{FEATURED_MAX_QUERY_SHARE:.2f}")
        if not failed:
            row["tier"] = "featured"
        elif row["events"] >= LOW_COVERAGE_MIN_EVENTS:
            row["tier"] = "low_coverage"
        else:
            row["tier"] = "insufficient"
        row["reason"] = "; ".join(failed)
        rows.append(row)
    return sorted(rows, key=lambda r: (TIER_ORDER[r["tier"]], -r["events"], r["state"]))
