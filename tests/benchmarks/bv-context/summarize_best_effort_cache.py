#!/usr/bin/env python3

import argparse
import hashlib
import json
import math
import statistics
from pathlib import Path


VARIANTS = ("baseline", "corrected", "best_effort")
METRICS = (
    "wall_seconds",
    "user_seconds",
    "system_seconds",
    "max_rss_kb",
    "z3_reported_seconds",
    "voluntary_context_switches",
    "involuntary_context_switches",
)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def summary(values):
    return {
        "observations": values,
        "median": statistics.median(values),
        "min": min(values),
        "max": max(values),
    }


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def summarize_campaign(root, simple_agreement, runner_hash):
    provenance_path = root / "provenance.json"
    measurements_path = root / "measurements.jsonl"
    provenance = json.loads(provenance_path.read_text())
    rows = [
        json.loads(line)
        for line in measurements_path.read_text().splitlines()
    ]
    workloads = provenance["workloads"]
    expected = {
        (variant, workload, repeat)
        for variant in VARIANTS
        for workload in workloads
        for repeat in range(1, 6)
    }
    actual = {
        (row["variant"], row["workload"], row["repeat"])
        for row in rows
    }
    require(
        provenance["runner_sha256"] == runner_hash
        and provenance["cpu"] == 16
        and provenance["triples_per_workload"] == 5
        and provenance["simple_agreement"] == simple_agreement,
        f"{root.name}: campaign provenance differs",
    )
    require(
        len(rows) == len(expected)
        and len(actual) == len(rows)
        and actual == expected,
        f"{root.name}: benchmark cells differ",
    )
    require(
        all(
            row["profiled_declaration_count"]
            == workloads[row["workload"]]["declarations"]
            and row["query_count"] == workloads[row["workload"]]["queries"]
            for row in rows
        ),
        f"{root.name}: work counts differ",
    )
    per_workload = {}
    for workload in workloads:
        record = {"triples": 5}
        for variant in VARIANTS:
            selected = [
                row for row in rows
                if row["workload"] == workload
                and row["variant"] == variant
            ]
            record[variant] = {
                metric: summary([row[metric] for row in selected])
                for metric in METRICS
            }
        baseline = record["baseline"]["wall_seconds"]["median"]
        corrected = record["corrected"]["wall_seconds"]["median"]
        best_effort = record["best_effort"]["wall_seconds"]["median"]
        record["wall_changes"] = {
            "corrected_vs_baseline_seconds": corrected - baseline,
            "corrected_vs_baseline_percent":
                100 * (corrected / baseline - 1),
            "best_effort_vs_baseline_seconds": best_effort - baseline,
            "best_effort_vs_baseline_percent":
                100 * (best_effort / baseline - 1),
            "best_effort_vs_corrected_seconds": best_effort - corrected,
            "best_effort_vs_corrected_percent":
                100 * (best_effort / corrected - 1),
        }
        per_workload[workload] = record
    aggregate = {}
    for variant in VARIANTS:
        aggregate[f"summed_median_{variant}_seconds"] = sum(
            record[variant]["wall_seconds"]["median"]
            for record in per_workload.values()
        )
    baseline_sum = aggregate["summed_median_baseline_seconds"]
    for variant in ("corrected", "best_effort"):
        selected = aggregate[f"summed_median_{variant}_seconds"]
        aggregate[f"summed_median_{variant}_vs_baseline_seconds"] = (
            selected - baseline_sum
        )
        aggregate[f"summed_median_{variant}_vs_baseline_percent"] = (
            100 * (selected / baseline_sum - 1)
        )
        ratios = [
            record[variant]["wall_seconds"]["median"]
            / record["baseline"]["wall_seconds"]["median"]
            for record in per_workload.values()
        ]
        aggregate[f"geomean_{variant}_vs_baseline_percent"] = 100 * (
            math.exp(sum(math.log(value) for value in ratios) / len(ratios))
            - 1
        )
    return {
        "provenance": provenance,
        "per_workload": per_workload,
        "aggregate": aggregate,
        "evidence": {
            "provenance_sha256": sha256(provenance_path),
            "measurements_sha256": sha256(measurements_path),
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ordinary", type=Path, required=True)
    parser.add_argument("--simple", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    runner = Path(__file__).resolve().parent / "run_affinity_ordinary_suite.py"
    runner_hash = sha256(runner)
    output = {
        "date": "2026-10-27",
        "objective": (
            "Compare no cache, corrected full cache, and sparse best-effort "
            "reuse on CPU 16."
        ),
        "ordinary": summarize_campaign(
            args.ordinary.resolve(), False, runner_hash
        ),
        "simple_agreement": summarize_campaign(
            args.simple.resolve(), True, runner_hash
        ),
        "limitations": [
            "CPU affinity does not reserve CPU 16 from other host workloads.",
            "The first two ordinary triples experienced visible host slowdown.",
            "No allocation counters, solver tuning, or workload changes were used.",
        ],
    }
    args.output.write_text(json.dumps(output, indent=2) + "\n")


if __name__ == "__main__":
    main()
