import json
import random
from collections import Counter
from pathlib import Path

import pandas as pd

from .config import DATA_END_DATE, quarter_windows

ROOT = Path(__file__).resolve().parent.parent
PROCESSED = ROOT / "data" / "processed"
DOCS = ROOT / "docs"

EVENT_COLS = ["event_id", "state", "state_basis", "title", "date", "date_precision", "category",
              "sector", "summary", "source_name", "source_url", "source_count", "other_sources"]

COLUMN_DEFINITIONS = [
    ("event_id", "Short hash of state + normalized headline of the representative article"),
    ("state", "State or UT the event is about"),
    ("state_basis", "How the state was found: title, description, or query (only one region's search returned it)"),
    ("title", "Headline of the representative article"),
    ("date", "Earliest day-precision publication date in the cluster (IST); blank if unknown"),
    ("date_precision", "day, month or unknown"),
    ("category", "regulation_ethics, policy_mission, institution, partnership_mou, infrastructure, deployment, budget_funding, statement or other"),
    ("sector", "Only for deployment events: education, health, agriculture, policing, citizen_services, other"),
    ("summary", "First sentence of the description, or the headline when none is available"),
    ("source_name", "Publisher of the representative article"),
    ("source_url", "Link to the representative article"),
    ("source_count", "Number of distinct publishers covering the event"),
    ("other_sources", "Other publishers, pipe-separated"),
    ("tier", "Coverage tier of the state: featured, low_coverage or insufficient"),
]


def _public(event, tier):
    row = {k: event[k] for k in EVENT_COLS}
    row["tier"] = tier
    return row


def write_all(events, coverage, stats, seed=0):
    PROCESSED.mkdir(parents=True, exist_ok=True)
    DOCS.mkdir(parents=True, exist_ok=True)
    tier_of = {c["state"]: c["tier"] for c in coverage}
    rows = [_public(e, tier_of[e["state"]]) for e in events]
    all_df = pd.DataFrame(rows, columns=EVENT_COLS + ["tier"])
    all_df.to_csv(PROCESSED / "events_all_states.csv", index=False)

    featured = all_df[all_df["tier"] == "featured"][EVENT_COLS]
    featured.to_csv(PROCESSED / "events.csv", index=False)
    cov_df = pd.DataFrame(coverage)
    cov_df.to_csv(PROCESSED / "state_coverage.csv", index=False)
    with pd.ExcelWriter(PROCESSED / "events.xlsx") as xl:
        featured.to_excel(xl, sheet_name="events", index=False)
        cov_df.to_excel(xl, sheet_name="state_coverage", index=False)
        pd.DataFrame(COLUMN_DEFINITIONS, columns=["column", "definition"]).to_excel(
            xl, sheet_name="column_definitions", index=False)

    rng = random.Random(seed)
    multi = [e for e in events if e["source_count"] >= 2]
    sample = rng.sample(multi, min(15, len(multi)))
    dedup_rows = [{"event_id": e["event_id"], "state": e["state"], "member_title": m["title"],
                   "source_name": m["source_name"], "date": m["date"], "url": m["url"],
                   "is_representative": m["url"] == e["rep_url"]}
                  for e in sample for m in e["members"]]
    pd.DataFrame(dedup_rows).to_csv(PROCESSED / "dedup_sample.csv", index=False)

    rel_rows = []
    for c in coverage:
        if c["tier"] != "featured":
            continue
        evs = [e for e in events if e["state"] == c["state"]]
        for e in rng.sample(evs, min(3, len(evs))):
            rel_rows.append({k: e[k] for k in ["event_id", "state", "title", "category", "sector",
                                               "summary", "source_name", "source_url", "date"]}
                            | {"manual_label": ""})
    _write_relevance_sample(rel_rows)

    biggest = sorted(events, key=lambda e: -len(e["members"]))[:5]
    quality = {
        "funnel": stats["funnel"],
        "drop_reasons": stats["drop_reasons"],
        "articles": stats["articles"],
        "events": len(events),
        "duplicates_collapsed": stats["articles"] - len(events),
        "largest_clusters": [{"event_id": e["event_id"], "state": e["state"], "size": len(e["members"]),
                              "member_titles": [m["title"] for m in e["members"]]} for e in biggest],
        "unknown_date_articles": stats["unknown_date_articles"],
        "unknown_date_events": sum(e["date_precision"] == "unknown" for e in events),
        "relabelled_state_count": stats["relabelled"],
        "state_basis_all_unique_articles": stats["basis_all"],
        "state_basis_events": dict(Counter(e["state_basis"] for e in events)),
        "events_by_tier": dict(Counter(tier_of[e["state"]] for e in events)),
        "states_by_tier": dict(Counter(c["tier"] for c in coverage)),
        "events_by_state": dict(Counter(e["state"] for e in events).most_common()),
        "events_by_category": dict(Counter(e["category"] for e in events).most_common()),
    }
    (PROCESSED / "quality_report.json").write_text(json.dumps(quality, indent=1))

    summary_keys = ["funnel", "articles", "events", "duplicates_collapsed", "events_by_tier",
                    "states_by_tier", "events_by_category"]
    windows = quarter_windows()
    (DOCS / "data.json").write_text(json.dumps({
        "window": {"start": windows[0][0].isoformat(), "end": DATA_END_DATE},
        "events": rows,
        "state_coverage": coverage,
        "quality": {k: quality[k] for k in summary_keys},
    }, indent=1))
    return quality


SUGGESTIONS = ROOT / "data" / "labels" / "suggested_labels.csv"
RELEVANCE_COLS = ["event_id", "state", "title", "category", "sector", "summary", "source_name",
                  "source_url", "date", "suggested_label", "suggested_reason", "manual_label"]


def _write_relevance_sample(rows):
    path = PROCESSED / "relevance_sample.csv"
    if path.exists():
        old = pd.read_csv(path, dtype=str, keep_default_na=False)
        if "manual_label" in old and old["manual_label"].str.strip().any():
            print("relevance_sample.csv has manual labels; leaving it untouched")
            return
    df = pd.DataFrame(rows)
    sugg = (pd.read_csv(SUGGESTIONS, dtype=str, keep_default_na=False)
            if SUGGESTIONS.exists() else pd.DataFrame(columns=["event_id", "suggested_label", "suggested_reason"]))
    df = df.drop(columns=["manual_label"], errors="ignore").merge(sugg, on="event_id", how="left").fillna("")
    df["manual_label"] = ""
    df.reindex(columns=RELEVANCE_COLS, fill_value="").to_csv(path, index=False)


CALIBRATION_COLS = ["state", "date_a", "date_b", "title_a", "title_b", "set_score", "sort_score",
                    "numbers_guard_fired", "merged"]


def calibration(pair_log, n=15):
    """Lowest-scoring merged pairs, and highest-scoring same-state pairs in the date window that stayed apart."""
    merged = sorted((p for p in pair_log if p["merged"]), key=lambda p: (p["set_score"], p["sort_score"]))[:n]
    # pairs already joined through a third article aren't misses
    missed = sorted((p for p in pair_log
                     if not p["merged"] and p["in_window"] and not p["same_cluster"]),
                    key=lambda p: (-p["set_score"], -p["sort_score"]))[:n]
    df = pd.DataFrame(merged + missed, columns=CALIBRATION_COLS)
    df.to_csv(PROCESSED / "dedup_calibration.csv", index=False)
    return merged, missed
