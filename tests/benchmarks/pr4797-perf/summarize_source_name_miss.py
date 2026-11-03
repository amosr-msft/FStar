#!/usr/bin/env python3

import argparse
import hashlib
import json
import statistics
from pathlib import Path


METRICS = (
    "root_cpu_seconds",
    "child_cpu_seconds",
    "wall_seconds",
    "peak_process_rss_bytes",
)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def campaign(path, variants, repetitions):
    root = path.resolve()
    rows = [
        json.loads(line)
        for line in (root / "measurements.jsonl").read_text().splitlines()
    ]
    summary = {}
    for workload in sorted({row["workload"] for row in rows}):
        record = {}
        for variant in variants:
            selected = [
                row for row in rows
                if row["workload"] == workload
                and row["variant"] == variant
            ]
            if len(selected) != repetitions:
                raise RuntimeError(f"{workload}/{variant}: rows differ")
            record[variant] = {
                metric: {
                    "observations": [row[metric] for row in selected],
                    "median": statistics.median(
                        row[metric] for row in selected
                    ),
                }
                for metric in METRICS
            }
        paired = {}
        baseline = variants[0]
        for variant in variants[1:]:
            paired[variant] = {}
            for metric in METRICS:
                deltas = []
                for repeat in range(1, repetitions + 1):
                    group = {
                        row["variant"]: row
                        for row in rows
                        if row["workload"] == workload
                        and row["repeat"] == repeat
                    }
                    deltas.append(
                        group[variant][metric] - group[baseline][metric]
                    )
                paired[variant][metric] = {
                    "observations": deltas,
                    "median": statistics.median(deltas),
                    "mean": statistics.mean(deltas),
                }
        record[f"paired_change_from_{baseline}"] = paired
        summary[workload] = record
    return {
        "provenance": json.loads((root / "provenance.json").read_text()),
        "summary": summary,
        "rows": rows,
        "measurements_sha256": sha256(root / "measurements.jsonl"),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--dependency", type=Path, required=True)
    parser.add_argument("--rebuild", type=Path, required=True)
    parser.add_argument("--rebuilt-source", type=Path, required=True)
    parser.add_argument("--scaling", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = {
        "source_campaign": campaign(
            args.source, ("cached", "optimized"), 5
        ),
        "dependency_campaign": campaign(
            args.dependency, ("cached", "optimized"), 20
        ),
        "optimized_rebuild_control": campaign(
            args.rebuild, ("original", "rebuild"), 5
        ),
        "rebuilt_source_campaign": campaign(
            args.rebuilt_source, ("cached", "optimized"), 5
        ),
        "miss_scaling": json.loads(args.scaling.read_text()),
        "evidence": {
            "miss_scaling_sha256": sha256(args.scaling),
            "script_sha256": sha256(Path(__file__)),
        },
        "limitations": [
            "CPU accounting is sampled at approximately 10 ms resolution.",
            "CPU affinity does not reserve CPU 16.",
            "The miss-scaling control uses nonexistent distinct absolute files.",
        ],
    }
    args.output.write_text(json.dumps(output, indent=2) + "\n")


if __name__ == "__main__":
    main()
