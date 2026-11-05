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


def geo(values):
    return math.exp(statistics.mean(math.log(value) for value in values))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--dependency-rebuild", type=Path, required=True)
    parser.add_argument("--diagnostic", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    campaign = args.campaign.resolve()
    provenance = json.loads((campaign / "provenance.json").read_text())
    rows = [
        json.loads(line)
        for line in (campaign / "measurements.jsonl").read_text().splitlines()
    ]
    summary = {}
    local_ratios = []
    checked_ratios = []
    for workload in sorted(provenance["selection"]):
        selected = [row for row in rows if row["workload"] == workload]
        record = {}
        for variant in ("base", "head"):
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
        ratios = []
        for metric in METRICS:
            deltas = []
            for repeat in range(1, provenance["repetitions"] + 1):
                pair = {
                    row["variant"]: row
                    for row in selected
                    if row["repeat"] == repeat
                }
                deltas.append(
                    pair["head"][metric] - pair["base"][metric]
                )
                if metric == "root_cpu_seconds":
                    base_group = (
                        pair["base"]["root_cpu_seconds"]
                        + pair["base"]["child_cpu_seconds"]
                    )
                    head_group = (
                        pair["head"]["root_cpu_seconds"]
                        + pair["head"]["child_cpu_seconds"]
                    )
                    ratios.append(head_group / base_group)
            paired[metric] = {
                "observations": deltas,
                "median": statistics.median(deltas),
                "mean": statistics.mean(deltas),
                "positive": sum(delta > 0 for delta in deltas),
            }
        record["paired_head_minus_base"] = paired
        record["group_cpu_ratios"] = ratios
        spec = provenance["selection"][workload]
        record["ci_ratio"] = (
            spec["ci_head_seconds"] / spec["ci_base_seconds"]
        )
        summary[workload] = record
        local_ratios.extend(ratios)
        if workload != "bug-reports-depend":
            checked_ratios.extend(ratios)
    blocks = []
    for repeat in range(1, provenance["repetitions"] + 1):
        ratios = []
        ratios_without_dep = []
        for workload in sorted(provenance["selection"]):
            pair = {
                row["variant"]: row
                for row in rows
                if row["workload"] == workload
                and row["repeat"] == repeat
            }
            base = (
                pair["base"]["root_cpu_seconds"]
                + pair["base"]["child_cpu_seconds"]
            )
            head = (
                pair["head"]["root_cpu_seconds"]
                + pair["head"]["child_cpu_seconds"]
            )
            ratios.append(head / base)
            if workload != "bug-reports-depend":
                ratios_without_dep.append(head / base)
        blocks.append({
            "repeat": repeat,
            "geometric_ratio": geo(ratios),
            "median_change_percent":
                statistics.median((ratio - 1) * 100 for ratio in ratios),
            "checked_geometric_ratio": geo(ratios_without_dep),
            "checked_median_change_percent": statistics.median(
                (ratio - 1) * 100 for ratio in ratios_without_dep
            ),
        })
    rebuild = args.dependency_rebuild.resolve()
    rebuild_rows = [
        json.loads(line)
        for line in (rebuild / "measurements.jsonl").read_text().splitlines()
    ]
    rebuild_paired = {}
    for metric in METRICS[:-1]:
        deltas = []
        for repeat in range(1, 6):
            pair = {
                row["variant"]: row
                for row in rebuild_rows
                if row["repeat"] == repeat
            }
            deltas.append(
                pair["rebuild"][metric] - pair["original"][metric]
            )
        rebuild_paired[metric] = {
            "observations": deltas,
            "median": statistics.median(deltas),
            "mean": statistics.mean(deltas),
        }
    diagnostic = json.loads(args.diagnostic.read_text())
    ci_ratios = [
        details["ci_head_seconds"] / details["ci_base_seconds"]
        for details in provenance["selection"].values()
    ]
    checked_ci_ratios = [
        details["ci_head_seconds"] / details["ci_base_seconds"]
        for workload, details in provenance["selection"].items()
        if workload != "bug-reports-depend"
    ]
    output = {
        "baseline": "c68959fe1f070cd66a5ed2e92965185505f109ce",
        "head": "adbf7292f25542a538910711fef79bf4eb8c0bac",
        "campaign": {
            "provenance": provenance,
            "measurements_sha256": sha256(
                campaign / "measurements.jsonl"
            ),
            "rows": rows,
        },
        "summary": summary,
        "aggregate": {
            "local_all_geometric_ratio": geo(local_ratios),
            "local_all_median_change_percent": statistics.median(
                (ratio - 1) * 100 for ratio in local_ratios
            ),
            "local_checked_geometric_ratio": geo(checked_ratios),
            "local_checked_median_change_percent": statistics.median(
                (ratio - 1) * 100 for ratio in checked_ratios
            ),
            "selected_ci_geometric_ratio": geo(ci_ratios),
            "selected_ci_median_change_percent": statistics.median(
                (ratio - 1) * 100 for ratio in ci_ratios
            ),
            "selected_checked_ci_geometric_ratio": geo(
                checked_ci_ratios
            ),
            "selected_checked_ci_median_change_percent":
                statistics.median(
                    (ratio - 1) * 100
                    for ratio in checked_ci_ratios
                ),
            "blocks": blocks,
        },
        "dependency_rebuild_control": {
            "provenance": json.loads(
                (rebuild / "provenance.json").read_text()
            ),
            "measurements_sha256": sha256(
                rebuild / "measurements.jsonl"
            ),
            "rows": rebuild_rows,
            "paired_rebuild_minus_original": rebuild_paired,
        },
        "dependency_diagnostic": diagnostic,
        "evidence": {
            "script_sha256": sha256(Path(__file__)),
            "diagnostic_sha256": sha256(args.diagnostic),
        },
        "limitations": [
            "The representative set is direction-balanced, not a random sample.",
            "Absolute source arguments are required by the remote path grant.",
            "CPU sampling has approximately 10 ms resolution.",
            "CPU affinity does not reserve CPU 16.",
        ],
    }
    args.output.write_text(json.dumps(output, indent=2) + "\n")


if __name__ == "__main__":
    main()
