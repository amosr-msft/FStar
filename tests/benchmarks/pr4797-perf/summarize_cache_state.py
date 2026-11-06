#!/usr/bin/env python3

import argparse
import hashlib
import itertools
import json
import statistics
from pathlib import Path


def median(values):
    return statistics.median(values) if values else None


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def summarize(rows):
    summaries = []
    for workload in sorted({row["workload"] for row in rows}):
        selected = [row for row in rows if row["workload"] == workload]
        by_key = {
            (row["repeat"], row["variant"]): row for row in selected
        }
        variants = sorted({row["variant"] for row in selected})
        for before_name, after_name in itertools.combinations(variants, 2):
            cpu = []
            wall = []
            rss = []
            heap = []
            for repeat in sorted({row["repeat"] for row in selected}):
                before = by_key[repeat, before_name]
                after = by_key[repeat, after_name]
                cpu.append(
                    after["root_cpu_seconds"] + after["child_cpu_seconds"]
                    - before["root_cpu_seconds"]
                    - before["child_cpu_seconds"]
                )
                wall.append(
                    after["wall_seconds"] - before["wall_seconds"]
                )
                rss.append(
                    after["peak_group_rss_bytes"]
                    - before["peak_group_rss_bytes"]
                )
                if (
                    before.get("fstar_heap_peak_bytes") is not None
                    and after.get("fstar_heap_peak_bytes") is not None
                ):
                    heap.append(
                        after["fstar_heap_peak_bytes"]
                        - before["fstar_heap_peak_bytes"]
                    )
            summaries.append({
                "workload": workload,
                "before": before_name,
                "after": after_name,
                "pairs": len(cpu),
                "median_group_cpu_delta_seconds": median(cpu),
                "median_wall_delta_seconds": median(wall),
                "median_group_rss_delta_bytes": median(rss),
                "median_fstar_heap_delta_bytes": median(heap),
                "after_slower_group_cpu_pairs":
                    sum(value > 0 for value in cpu),
                "group_cpu_deltas_seconds": cpu,
            })
    return summaries


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    campaigns = []
    for name in ("dependency", "checked", "rebuild-control"):
        directory = args.input / name
        rows = [
            json.loads(line)
            for line in (directory / "measurements.jsonl")
            .read_text().splitlines()
        ]
        campaigns.append({
            "name": name,
            "provenance": json.loads(
                (directory / "provenance.json").read_text()
            ),
            "measurements": rows,
            "summary": summarize(rows),
        })
    args.output.write_text(json.dumps({
        "summarizer_sha256": sha256(Path(__file__)),
        "campaigns": campaigns,
    }, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
