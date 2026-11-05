#!/usr/bin/env python3

import argparse
import itertools
import json
import statistics
from pathlib import Path


CAMPAIGNS = (
    "flat-dependency",
    "flat-checked",
    "flat-checked5",
    "flat-long10",
    "trie-dependency",
    "trie-checked",
    "trie-structural",
)


def median(values):
    return statistics.median(values) if values else None


def mean(values):
    return statistics.mean(values) if values else None


def summarize_process(rows):
    summaries = []
    workloads = sorted({row["workload"] for row in rows})
    for workload in workloads:
        selected = [row for row in rows if row["workload"] == workload]
        variants = sorted({row["variant"] for row in selected})
        by_key = {
            (row["repeat"], row["variant"]): row for row in selected
        }
        repeats = sorted({row["repeat"] for row in selected})
        for before, after in itertools.combinations(variants, 2):
            deltas = {
                "root_cpu_seconds": [],
                "group_cpu_seconds": [],
                "child_cpu_seconds": [],
                "wall_seconds": [],
                "peak_group_rss_bytes": [],
                "fstar_heap_peak_bytes": [],
            }
            for repeat in repeats:
                first = by_key[repeat, before]
                second = by_key[repeat, after]
                deltas["root_cpu_seconds"].append(
                    second["root_cpu_seconds"] - first["root_cpu_seconds"]
                )
                deltas["child_cpu_seconds"].append(
                    second["child_cpu_seconds"] - first["child_cpu_seconds"]
                )
                deltas["group_cpu_seconds"].append(
                    deltas["root_cpu_seconds"][-1]
                    + deltas["child_cpu_seconds"][-1]
                )
                deltas["wall_seconds"].append(
                    second["wall_seconds"] - first["wall_seconds"]
                )
                deltas["peak_group_rss_bytes"].append(
                    second["peak_group_rss_bytes"]
                    - first["peak_group_rss_bytes"]
                )
                if (
                    first.get("fstar_heap_peak_bytes") is not None
                    and second.get("fstar_heap_peak_bytes") is not None
                ):
                    deltas["fstar_heap_peak_bytes"].append(
                        second["fstar_heap_peak_bytes"]
                        - first["fstar_heap_peak_bytes"]
                    )
            summaries.append({
                "workload": workload,
                "before": before,
                "after": after,
                "pairs": len(repeats),
                "median_delta": {
                    key: median(values) for key, values in deltas.items()
                },
                "mean_delta": {
                    key: mean(values) for key, values in deltas.items()
                },
                "after_slower_group_cpu_pairs": sum(
                    value > 0 for value in deltas["group_cpu_seconds"]
                ),
                "paired_group_cpu_deltas":
                    deltas["group_cpu_seconds"],
            })
    return summaries


def summarize_structural(rows):
    summaries = []
    for roots in sorted({row["roots"] for row in rows}):
        selected = [row for row in rows if row["roots"] == roots]
        variants = sorted({row["variant"] for row in selected})
        by_key = {
            (row["repeat"], row["variant"]): row["internal"][0]
            for row in selected
        }
        repeats = sorted({row["repeat"] for row in selected})
        for before, after in itertools.combinations(variants, 2):
            metrics = {}
            for metric in (
                "distinct_seconds", "repeated_seconds", "cold_seconds"
            ):
                ratios = [
                    by_key[repeat, after][metric]
                    / by_key[repeat, before][metric]
                    for repeat in repeats
                ]
                metrics[metric] = {
                    "median_ratio": median(ratios),
                    "mean_ratio": mean(ratios),
                    "after_slower_pairs": sum(
                        ratio > 1 for ratio in ratios
                    ),
                    "pairs": len(ratios),
                }
            summaries.append({
                "roots": roots,
                "before": before,
                "after": after,
                "metrics": metrics,
            })
    return summaries


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    campaigns = []
    for name in CAMPAIGNS:
        directory = args.input / name
        provenance = json.loads(
            (directory / "provenance.json").read_text()
        )
        rows = [
            json.loads(line)
            for line in (directory / "measurements.jsonl")
            .read_text().splitlines()
        ]
        campaigns.append({
            "name": name,
            "provenance": provenance,
            "measurements": rows,
            "summary": (
                summarize_structural(rows)
                if provenance["kind"] == "structural"
                else summarize_process(rows)
            ),
        })
    args.output.write_text(
        json.dumps(campaigns, indent=2, sort_keys=True) + "\n"
    )


if __name__ == "__main__":
    main()
