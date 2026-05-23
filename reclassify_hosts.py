#!/usr/bin/env python3
"""Re-run classify_host() over every cached metadata record in place.

Use this after editing the classifier in fetch_metadata.py when you want to
update the derived host_category field without hitting NCBI again.

    pixi run python reclassify_hosts.py

Walks metadata/*.json, applies the current classify_host() to each record,
writes the file back, and prints a before/after summary of category counts.
"""
import json
from collections import Counter
from pathlib import Path

from fetch_metadata import classify_host

METADATA = Path("metadata")
SKIP = {"all_metadata.json", "all_sra_metadata.json", "last_fetch.json",
        "world.geojson", "sra_counts.json"}


def reclassify_file(path: Path) -> tuple[Counter, Counter, int]:
    """Update host_category in place. Returns (before_counts, after_counts, changed)."""
    with open(path) as f:
        data = json.load(f)
    if not isinstance(data, list):
        return Counter(), Counter(), 0

    before = Counter()
    after = Counter()
    changed = 0
    for r in data:
        if not isinstance(r, dict):
            continue
        old = r.get("host_category") or "unknown"
        new = classify_host(
            r.get("host") or "",
            r.get("isolation_source") or "",
            r.get("host_disease") or "",
            r.get("env_broad_scale") or "",
        )
        before[old] += 1
        after[new] += 1
        if old != new:
            r["host_category"] = new
            changed += 1

    if changed:
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
    return before, after, changed


def main():
    paths = sorted(p for p in METADATA.glob("*.json") if p.name not in SKIP)
    total_before = Counter()
    total_after = Counter()
    total_changed = 0
    for path in paths:
        before, after, changed = reclassify_file(path)
        total_before.update(before)
        total_after.update(after)
        total_changed += changed
        if changed:
            print(f"  {path.name:45s}  {changed:>6,} updated")

    print()
    print(f"Total records re-classified: {total_changed:,}")
    print()
    cats = sorted(set(list(total_before) + list(total_after)))
    width = max(len(c) for c in cats)
    print(f"{'category':<{width}}  {'before':>9}  {'after':>9}  {'delta':>9}")
    print("-" * (width + 32))
    for cat in cats:
        b = total_before.get(cat, 0)
        a = total_after.get(cat, 0)
        d = a - b
        sign = "+" if d > 0 else ""
        print(f"{cat:<{width}}  {b:>9,}  {a:>9,}  {sign}{d:>8,}")


if __name__ == "__main__":
    main()
