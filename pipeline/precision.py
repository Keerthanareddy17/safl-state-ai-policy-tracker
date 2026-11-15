import json

import pandas as pd

from .export import DOCS, PROCESSED

POSITIVE = {"relevant", "yes", "y", "1"}
NEGATIVE = {"not_relevant", "not relevant", "no", "n", "0"}


def _stats(ok, states):
    df = pd.DataFrame({"ok": ok, "state": states})
    per_state = {
        s: {"labelled": len(g), "relevant": int(g["ok"].sum()), "precision": round(float(g["ok"].mean()), 3)}
        for s, g in df.groupby("state")
    }
    return {"labelled": len(df), "relevant": int(df["ok"].sum()),
            "overall_precision": round(float(df["ok"].mean()), 3), "per_state": per_state}


def _both(df, labels):
    strict = labels.isin(POSITIVE)
    note = df["manual_note"].str.strip().str.lower() if "manual_note" in df else pd.Series("", index=df.index)
    return {"strict": _stats(strict, df["state"]), "lenient": _stats(strict | (note == "statement"), df["state"])}


def compute(sample_path=PROCESSED / "relevance_sample.csv", events_path=PROCESSED / "events_all_states.csv"):
    """Return {"strict", "lenient"} precision from manual_label, or None if nothing is labelled.

    strict uses manual_label as given; lenient also counts rows whose manual_note is
    "statement" as relevant (a leader's statement is in scope even without an action).
    """
    if not sample_path.exists():
        return None
    df = pd.read_csv(sample_path, dtype=str, keep_default_na=False)
    labels = df["manual_label"].str.strip().str.lower()
    df = df[labels.isin(POSITIVE | NEGATIVE)]
    if df.empty:
        return None
    labels = labels[df.index]
    result = _both(df, labels)
    # sampled events that survived later exclusions (e.g. the cross-border outlet fix)
    if events_path.exists():
        live = set(pd.read_csv(events_path, dtype=str, keep_default_na=False)["event_id"])
        keep = df["event_id"].isin(live)
        result["current_output"] = _both(df[keep], labels[keep])
    return result


def update_outputs(result):
    report = PROCESSED / "quality_report.json"
    data = DOCS / "data.json"
    q = json.loads(report.read_text())
    q["precision"] = result
    report.write_text(json.dumps(q, indent=1))
    d = json.loads(data.read_text())
    d["quality"]["precision"] = result
    data.write_text(json.dumps(d, indent=1))


def main():
    result = compute()
    if result is None:
        print("No manual_label values in relevance_sample.csv; skipping precision.")
        return
    update_outputs(result)
    for kind in ("strict", "lenient"):
        r = result[kind]
        print(f"{kind.capitalize()} precision: {r['overall_precision']:.1%} ({r['relevant']}/{r['labelled']})")
    for kind in ("strict", "lenient"):
        r = result["current_output"][kind]
        print(f"Current output, {kind}: {r['overall_precision']:.1%} ({r['relevant']}/{r['labelled']})")
    print("Per state (strict / lenient):")
    for state, s in sorted(result["strict"]["per_state"].items(), key=lambda kv: kv[1]["precision"]):
        l = result["lenient"]["per_state"][state]
        print(f"  {state:<16}{s['relevant']}/{s['labelled']} {s['precision']:.0%}   /   {l['relevant']}/{l['labelled']} {l['precision']:.0%}")


if __name__ == "__main__":
    main()
