#!/usr/bin/env python3

import argparse
import hashlib
import itertools
import json
import math
import statistics
from pathlib import Path


VARIANTS = ("incumbent", "forest", "flat")
METRICS = (
    "root_cpu_seconds",
    "child_cpu_seconds",
    "group_cpu_seconds",
    "wall_seconds",
    "peak_root_rss_bytes",
    "peak_group_rss_bytes",
    "fstar_heap_peak_bytes",
)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def add_derived(row):
    row = dict(row)
    row["group_cpu_seconds"] = (
        row["root_cpu_seconds"] + row["child_cpu_seconds"]
    )
    return row


def direction_counts(rows, variants):
    counts = {}
    for index in range(0, len(rows), 3):
        group = rows[index:index + 3]
        keys = {(row["workload"], row["repeat"]) for row in group}
        if len(keys) != 1:
            raise RuntimeError("measurements do not preserve adjacent triples")
        workload = group[0]["workload"]
        counts.setdefault(workload, {
            f"{left}_before_{right}": 0
            for left, right in itertools.permutations(variants, 2)
        })
        positions = {
            row["variant"]: position for position, row in enumerate(group)
        }
        for left, right in itertools.combinations(variants, 2):
            if positions[left] < positions[right]:
                counts[workload][f"{left}_before_{right}"] += 1
            else:
                counts[workload][f"{right}_before_{left}"] += 1
    return counts


def summarize_pairs(rows, variants):
    by_key = {
        (row["workload"], row["repeat"], row["variant"]): row
        for row in rows
    }
    summary = {}
    for workload in sorted({row["workload"] for row in rows}):
        repeats = sorted({
            row["repeat"] for row in rows if row["workload"] == workload
        })
        comparisons = {}
        for before, after in itertools.combinations(variants, 2):
            metrics = {}
            for metric in METRICS:
                deltas = [
                    by_key[workload, repeat, after][metric]
                    - by_key[workload, repeat, before][metric]
                    for repeat in repeats
                    if by_key[workload, repeat, after].get(metric) is not None
                    and by_key[workload, repeat, before].get(metric) is not None
                ]
                metrics[metric] = None if not deltas else {
                    "deltas": deltas,
                    "median_delta": statistics.median(deltas),
                    "mean_delta": statistics.mean(deltas),
                    "after_slower": sum(delta > 0 for delta in deltas),
                    "pairs": len(deltas),
                }
            ratios = [
                by_key[workload, repeat, after]["group_cpu_seconds"]
                / by_key[workload, repeat, before]["group_cpu_seconds"]
                for repeat in repeats
            ]
            comparisons[f"{after}_minus_{before}"] = {
                "metrics": metrics,
                "group_cpu_geometric_ratio": math.exp(
                    statistics.mean(math.log(ratio) for ratio in ratios)
                ),
                "group_cpu_ratios": ratios,
            }
        summary[workload] = comparisons
    return summary


def aggregate_checked(rows):
    by_key = {
        (row["workload"], row["repeat"], row["variant"]): row
        for row in rows
    }
    cells = sorted({
        (row["workload"], row["repeat"]) for row in rows
    })
    aggregate = {}
    for before, after in itertools.combinations(VARIANTS, 2):
        ratios = [
            by_key[workload, repeat, after]["group_cpu_seconds"]
            / by_key[workload, repeat, before]["group_cpu_seconds"]
            for workload, repeat in cells
        ]
        aggregate[f"{after}_over_{before}"] = {
            "group_cpu_geometric_ratio": math.exp(
                statistics.mean(math.log(ratio) for ratio in ratios)
            ),
            "group_cpu_total_ratio": (
                sum(
                    by_key[workload, repeat, after]["group_cpu_seconds"]
                    for workload, repeat in cells
                )
                / sum(
                    by_key[workload, repeat, before]["group_cpu_seconds"]
                    for workload, repeat in cells
                )
            ),
            "root_cpu_total_ratio": (
                sum(
                    by_key[workload, repeat, after]["root_cpu_seconds"]
                    for workload, repeat in cells
                )
                / sum(
                    by_key[workload, repeat, before]["root_cpu_seconds"]
                    for workload, repeat in cells
                )
            ),
            "child_cpu_total_ratio": (
                sum(
                    by_key[workload, repeat, after]["child_cpu_seconds"]
                    for workload, repeat in cells
                )
                / sum(
                    by_key[workload, repeat, before]["child_cpu_seconds"]
                    for workload, repeat in cells
                )
            ),
            "wall_total_ratio": (
                sum(
                    by_key[workload, repeat, after]["wall_seconds"]
                    for workload, repeat in cells
                )
                / sum(
                    by_key[workload, repeat, before]["wall_seconds"]
                    for workload, repeat in cells
                )
            ),
        }
    return aggregate


def summarize_structural(rows):
    summary = {}
    for roots in sorted({row["roots"] for row in rows}):
        selected = [row for row in rows if row["roots"] == roots]
        by_key = {
            (row["repeat"], row["variant"]): row["internal"][0]
            for row in selected
        }
        comparisons = {}
        repeats = sorted({row["repeat"] for row in selected})
        for before, after in itertools.combinations(VARIANTS, 2):
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
                    "ratios": ratios,
                    "median_ratio": statistics.median(ratios),
                    "mean_ratio": statistics.mean(ratios),
                    "after_slower": sum(ratio > 1 for ratio in ratios),
                }
            comparisons[f"{after}_over_{before}"] = metrics
        summary[str(roots)] = comparisons
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--rebuild", type=Path, required=True)
    parser.add_argument("--differential", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    campaigns = {}
    for name in ("dependency", "checked", "structural"):
        directory = args.input / name
        rows = [
            add_derived(json.loads(line))
            for line in (directory / "measurements.jsonl")
            .read_text().splitlines()
        ]
        campaign = {
            "provenance": json.loads(
                (directory / "provenance.json").read_text()
            ),
            "measurements_sha256": sha256(
                directory / "measurements.jsonl"
            ),
            "rows": rows,
            "direction_counts": direction_counts(rows, VARIANTS),
        }
        if name == "structural":
            campaign["summary"] = summarize_structural(rows)
        else:
            campaign["summary"] = summarize_pairs(rows, VARIANTS)
            if name == "checked":
                campaign["aggregate"] = aggregate_checked(rows)
        campaigns[name] = campaign
    rebuild = {}
    rebuild_variants = (
        "incumbent-rebuild", "forest-rebuild", "flat-rebuild"
    )
    for name in ("dependency", "checked"):
        directory = args.rebuild / name
        rows = [
            add_derived(json.loads(line))
            for line in (directory / "measurements.jsonl")
            .read_text().splitlines()
        ]
        rebuild[name] = {
            "provenance": json.loads(
                (directory / "provenance.json").read_text()
            ),
            "measurements_sha256": sha256(
                directory / "measurements.jsonl"
            ),
            "rows": rows,
            "direction_counts": direction_counts(
                rows, rebuild_variants
            ),
            "summary": summarize_pairs(rows, rebuild_variants),
        }
    args.output.write_text(json.dumps({
        "summarizer_sha256": sha256(Path(__file__)),
        "differential": {
            "sha256": sha256(args.differential),
            "result": json.loads(args.differential.read_text()),
        },
        "campaigns": campaigns,
        "rebuild_control": rebuild,
    }, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
