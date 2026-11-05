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
    "peak_group_rss_bytes",
)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def campaign(path, variants, repetitions, workload_key=None):
    root = path.resolve()
    rows = [
        json.loads(line)
        for line in (root / "measurements.jsonl").read_text().splitlines()
    ]
    workloads = (
        sorted({row[workload_key] for row in rows})
        if workload_key is not None
        else [None]
    )
    summary = {}
    for workload in workloads:
        selected = (
            [row for row in rows if row[workload_key] == workload]
            if workload_key is not None
            else rows
        )
        record = {}
        for variant in variants:
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
        for variant in variants[1:]:
            paired[variant] = {}
            for metric in METRICS:
                deltas = []
                for repeat in range(1, repetitions + 1):
                    group = {
                        row["variant"]: row
                        for row in selected
                        if row["repeat"] == repeat
                    }
                    deltas.append(
                        group[variant][metric]
                        - group[variants[0]][metric]
                    )
                paired[variant][metric] = {
                    "observations": deltas,
                    "median": statistics.median(deltas),
                    "mean": statistics.mean(deltas),
                    "positive": sum(delta > 0 for delta in deltas),
                }
        record[f"paired_change_from_{variants[0]}"] = paired
        summary[workload or "dependency"] = record
    return {
        "provenance": json.loads((root / "provenance.json").read_text()),
        "measurements_sha256": sha256(root / "measurements.jsonl"),
        "rows": rows,
        "summary": summary,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--original", type=Path, required=True)
    parser.add_argument("--rebuilt", type=Path, required=True)
    parser.add_argument("--rebuild-control", type=Path, required=True)
    parser.add_argument("--source-controls", type=Path, required=True)
    parser.add_argument("--diagnostic", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    diagnostic = args.diagnostic.resolve()
    diagnostic_rows = [
        json.loads(line)
        for line in (
            diagnostic / "measurements.jsonl"
        ).read_text().splitlines()
    ]
    output = {
        "original_build_triples": campaign(
            args.original, ("base", "pr", "fixed"), 20
        ),
        "rebuilt_fixed_triples": campaign(
            args.rebuilt, ("base", "pr", "fixed"), 20
        ),
        "fixed_rebuild_control": campaign(
            args.rebuild_control, ("original", "rebuild"), 20
        ),
        "source_controls": campaign(
            args.source_controls,
            ("base", "pr", "fixed"),
            5,
            "workload",
        ),
        "fixed_diagnostic": {
            "result": json.loads(
                (diagnostic / "result.json").read_text()
            ),
            "measurements_sha256": sha256(
                diagnostic / "measurements.jsonl"
            ),
            "rows": diagnostic_rows,
        },
        "evidence": {
            "script_sha256": sha256(Path(__file__)),
        },
        "limitations": [
            "Independent native builds differ substantially in dependency timing.",
            "Instrumented timings include Sys.time counter overhead.",
            "CPU sampling has approximately 10 ms resolution.",
            "CPU affinity does not reserve CPU 16.",
        ],
    }
    args.output.write_text(json.dumps(output, indent=2) + "\n")


if __name__ == "__main__":
    main()
