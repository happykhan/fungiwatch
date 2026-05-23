#!/usr/bin/env python3
"""Re-run classify_host() and classify_submitter() over cached metadata.

Use this after editing the classifiers in fetch_metadata.py when you want to
update the derived host_category and submitter_category fields without
hitting NCBI again.

    pixi run python reclassify_hosts.py

Walks metadata/*.json, applies the current classifiers to each record,
writes the file back, and prints a before/after summary of category counts.
"""
import json
from collections import Counter
from pathlib import Path

from fetch_metadata import classify_host, classify_submitter

METADATA = Path("metadata")
SKIP = {"all_metadata.json", "all_sra_metadata.json", "last_fetch.json",
        "world.geojson", "sra_counts.json"}


def reclassify_file(path: Path) -> dict:
    """Update host_category and submitter_category in place.

    Returns a dict with before/after counters and change counts for each
    derived field.
    """
    with open(path) as f:
        data = json.load(f)
    blank = {"host_before": Counter(), "host_after": Counter(),
             "sub_before": Counter(), "sub_after": Counter(),
             "host_changed": 0, "sub_changed": 0}
    if not isinstance(data, list):
        return blank

    host_changed = 0
    sub_changed = 0
    host_before, host_after = Counter(), Counter()
    sub_before, sub_after = Counter(), Counter()
    file_dirty = False
    for r in data:
        if not isinstance(r, dict):
            continue
        # Host
        old_h = r.get("host_category")
        new_h = classify_host(
            r.get("host") or "",
            r.get("isolation_source") or "",
            r.get("host_disease") or "",
            r.get("env_broad_scale") or "",
        )
        host_before[old_h or "unknown"] += 1
        host_after[new_h] += 1
        if r.get("host_category") != new_h:
            r["host_category"] = new_h
            file_dirty = True
            if old_h is not None and old_h != new_h:
                host_changed += 1

        # Submitter
        old_s = r.get("submitter_category")
        new_s = classify_submitter(r.get("submitter") or "")
        sub_before[old_s or "other"] += 1
        sub_after[new_s] += 1
        if r.get("submitter_category") != new_s:
            r["submitter_category"] = new_s
            file_dirty = True
            if old_s is not None and old_s != new_s:
                sub_changed += 1

    if file_dirty:
        with open(path, "w") as f:
            json.dump(data, f, indent=2)

    return {"host_before": host_before, "host_after": host_after,
            "sub_before": sub_before, "sub_after": sub_after,
            "host_changed": host_changed, "sub_changed": sub_changed}


def _print_summary(label: str, before: Counter, after: Counter) -> None:
    cats = sorted(set(list(before) + list(after)))
    if not cats:
        return
    width = max(max(len(c) for c in cats), 17)
    print()
    print(f"=== {label} ===")
    print(f"{'category':<{width}}  {'before':>9}  {'after':>9}  {'delta':>9}")
    print("-" * (width + 32))
    for cat in cats:
        b = before.get(cat, 0)
        a = after.get(cat, 0)
        d = a - b
        sign = "+" if d > 0 else ""
        print(f"{cat:<{width}}  {b:>9,}  {a:>9,}  {sign}{d:>8,}")


def main():
    paths = sorted(p for p in METADATA.glob("*.json") if p.name not in SKIP)
    host_before, host_after = Counter(), Counter()
    sub_before, sub_after = Counter(), Counter()
    total_host_changed = 0
    total_sub_changed = 0
    for path in paths:
        r = reclassify_file(path)
        host_before.update(r["host_before"])
        host_after.update(r["host_after"])
        sub_before.update(r["sub_before"])
        sub_after.update(r["sub_after"])
        total_host_changed += r["host_changed"]
        total_sub_changed += r["sub_changed"]
        if r["host_changed"] or r["sub_changed"]:
            print(f"  {path.name:45s}  host {r['host_changed']:>6,}  "
                  f"submitter {r['sub_changed']:>6,}")

    # Rebuild the combined files so generate_report.py sees fresh categories.
    _rebuild_combined()

    print()
    print(f"Total host_category changes:      {total_host_changed:,}")
    print(f"Total submitter_category changes: {total_sub_changed:,}")
    _print_summary("host_category", host_before, host_after)
    _print_summary("submitter_category", sub_before, sub_after)


def _rebuild_combined() -> None:
    """Refresh metadata/all_metadata.json and all_sra_metadata.json."""
    genome, sra = [], []
    for path in sorted(METADATA.glob("*.json")):
        if path.name in SKIP:
            continue
        with open(path) as f:
            data = json.load(f)
        if not isinstance(data, list):
            continue
        (sra if path.name.endswith("_sra.json") else genome).extend(data)
    with open(METADATA / "all_metadata.json", "w") as f:
        json.dump(genome, f, indent=2)
    with open(METADATA / "all_sra_metadata.json", "w") as f:
        json.dump(sra, f, indent=2)
    print(f"Rebuilt all_metadata.json ({len(genome):,} records) "
          f"and all_sra_metadata.json ({len(sra):,} records)")


if __name__ == "__main__":
    main()
