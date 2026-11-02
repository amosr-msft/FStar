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


def read_rows(root):
    path = root / "measurements.jsonl"
    return [
        json.loads(line) for line in path.read_text().splitlines()
    ], path


def observations(rows, variants, repetitions):
    result = {}
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
                    pair = {
                        row["variant"]: row
                        for row in rows
                        if row["workload"] == workload
                        and row["repeat"] == repeat
                    }
                    deltas.append(
                        pair[variant][metric] - pair[baseline][metric]
                    )
                paired[variant][metric] = {
                    "observations": deltas,
                    "median": statistics.median(deltas),
                    "mean": statistics.mean(deltas),
                }
        record["paired_change_from_" + baseline] = paired
        result[workload] = record
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--rebuild", type=Path, required=True)
    parser.add_argument("--dependency", type=Path, required=True)
    parser.add_argument("--startup-rebuild", type=Path, required=True)
    parser.add_argument("--entry-counters", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source_rows, source_path = read_rows(args.source.resolve())
    rebuild_rows, rebuild_path = read_rows(args.rebuild.resolve())
    dependency_rows, dependency_path = read_rows(
        args.dependency.resolve()
    )
    startup_rebuild = json.loads(args.startup_rebuild.read_text())
    entry_counters = json.loads(args.entry_counters.read_text())
    if any("workload" in row for row in dependency_rows):
        raise RuntimeError("dependency rows unexpectedly specify workload")
    dependency_rows = [
        {**row, "workload": "dependency-bug3207"}
        for row in dependency_rows
    ]
    if (
        len(source_rows) != 60
        or len(rebuild_rows) != 24
        or len(dependency_rows) != 60
    ):
        raise RuntimeError("campaign row counts differ")
    output = {
        "source_campaign": {
            "provenance": json.loads(
                (args.source.resolve() / "provenance.json").read_text()
            ),
            "summary": observations(source_rows, ("base", "head"), 5),
            "rows": source_rows,
        },
        "identical_source_rebuild": {
            "provenance": json.loads(
                (args.rebuild.resolve() / "provenance.json").read_text()
            ),
            "summary": observations(
                rebuild_rows, ("original", "rebuild"), 3
            ),
            "rows": rebuild_rows,
        },
        "dependency_focus": {
            "provenance": json.loads(
                (args.dependency.resolve() / "provenance.json").read_text()
            ),
            "summary": observations(
                dependency_rows, ("base", "head", "rebuild"), 20
            ),
            "rows": dependency_rows,
        },
        "entry_counters": entry_counters,
        "startup_rebuild_control": startup_rebuild,
        "evidence": {
            "source_measurements_sha256": sha256(source_path),
            "source_provenance_sha256":
                sha256(args.source.resolve() / "provenance.json"),
            "rebuild_measurements_sha256": sha256(rebuild_path),
            "rebuild_provenance_sha256":
                sha256(args.rebuild.resolve() / "provenance.json"),
            "dependency_measurements_sha256": sha256(dependency_path),
            "dependency_provenance_sha256":
                sha256(args.dependency.resolve() / "provenance.json"),
            "startup_rebuild_sha256": sha256(args.startup_rebuild),
            "entry_counters_sha256": sha256(args.entry_counters),
            "script_sha256": sha256(Path(__file__)),
        },
        "limitations": [
            "Linux process CPU sampling has approximately 10 ms resolution.",
            "Peak RSS is the maximum single process, not process-group RSS.",
            "The campaigns use fixed affinity but do not reserve CPU 16.",
        ],
    }
    args.output.write_text(json.dumps(output, indent=2) + "\n")


if __name__ == "__main__":
    main()
