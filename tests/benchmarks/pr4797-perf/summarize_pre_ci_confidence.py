#!/usr/bin/env python3

import argparse
import hashlib
import json
import math
import statistics
from pathlib import Path


METRICS = (
    "root_cpu_seconds",
    "child_cpu_seconds",
    "wall_seconds",
    "peak_root_rss_bytes",
    "peak_group_rss_bytes",
    "fstar_heap_peak_bytes",
)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--broad", type=Path, required=True)
    parser.add_argument("--memory", type=Path, required=True)
    parser.add_argument("--ownership", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    broad = args.broad.resolve()
    broad_rows = [
        json.loads(line)
        for line in (broad / "measurements.jsonl").read_text().splitlines()
    ]
    provenance = json.loads((broad / "provenance.json").read_text())
    summary = {}
    ratios = []
    for workload in sorted(provenance["selection"]):
        selected = [
            row for row in broad_rows if row["workload"] == workload
        ]
        record = {}
        for variant in ("pr", "fixed"):
            variant_rows = [
                row for row in selected if row["variant"] == variant
            ]
            record[variant] = {
                metric: {
                    "observations": [row[metric] for row in variant_rows],
                    "median": statistics.median(
                        row[metric] for row in variant_rows
                    ),
                }
                for metric in METRICS
            }
        paired = {}
        workload_ratios = []
        for metric in METRICS:
            deltas = []
            for repeat in range(1, provenance["repetitions"] + 1):
                pair = {
                    row["variant"]: row
                    for row in selected
                    if row["repeat"] == repeat
                }
                deltas.append(
                    pair["fixed"][metric] - pair["pr"][metric]
                )
                if metric == "root_cpu_seconds":
                    pr_group = (
                        pair["pr"]["root_cpu_seconds"]
                        + pair["pr"]["child_cpu_seconds"]
                    )
                    fixed_group = (
                        pair["fixed"]["root_cpu_seconds"]
                        + pair["fixed"]["child_cpu_seconds"]
                    )
                    workload_ratios.append(fixed_group / pr_group)
            paired[metric] = {
                "observations": deltas,
                "median": statistics.median(deltas),
                "mean": statistics.mean(deltas),
                "positive": sum(delta > 0 for delta in deltas),
            }
        record["paired_fixed_minus_pr"] = paired
        record["group_cpu_ratios"] = workload_ratios
        ratios.extend(workload_ratios)
        summary[workload] = record
    blocks = []
    for repeat in range(1, provenance["repetitions"] + 1):
        block = []
        for workload in sorted(provenance["selection"]):
            pair = {
                row["variant"]: row
                for row in broad_rows
                if row["workload"] == workload
                and row["repeat"] == repeat
            }
            pr_group = (
                pair["pr"]["root_cpu_seconds"]
                + pair["pr"]["child_cpu_seconds"]
            )
            fixed_group = (
                pair["fixed"]["root_cpu_seconds"]
                + pair["fixed"]["child_cpu_seconds"]
            )
            block.append(fixed_group / pr_group)
        blocks.append({
            "repeat": repeat,
            "geometric_ratio": math.exp(
                statistics.mean(math.log(ratio) for ratio in block)
            ),
            "median_change_percent": statistics.median(
                (ratio - 1) * 100 for ratio in block
            ),
        })
    memory = json.loads(args.memory.read_text())
    ownership = json.loads(args.ownership.read_text())
    output = {
        "broad_campaign": {
            "provenance": provenance,
            "measurements_sha256": sha256(
                broad / "measurements.jsonl"
            ),
            "rows": broad_rows,
            "summary": summary,
            "aggregate": {
                "geometric_ratio": math.exp(
                    statistics.mean(math.log(ratio) for ratio in ratios)
                ),
                "median_change_percent": statistics.median(
                    (ratio - 1) * 100 for ratio in ratios
                ),
                "blocks": blocks,
            },
        },
        "memory_diagnostic": memory,
        "ownership_dependency_evidence": {
            "path": str(args.ownership.resolve()),
            "sha256": sha256(args.ownership),
            "rebuilt_fixed_summary":
                ownership["rebuilt_fixed_triples"]["summary"],
            "fixed_rebuild_summary":
                ownership["fixed_rebuild_control"]["summary"],
        },
        "evidence": {
            "memory_sha256": sha256(args.memory),
            "script_sha256": sha256(Path(__file__)),
        },
        "limitations": [
            "The 15-workload selection is not equivalent to the full CI suite.",
            "Forced major GC memory snapshots are diagnostic only.",
            "Sampled RSS does not measure live OCaml heap.",
            "CPU affinity does not reserve CPU 16.",
        ],
    }
    args.output.write_text(json.dumps(output, indent=2) + "\n")


if __name__ == "__main__":
    main()
