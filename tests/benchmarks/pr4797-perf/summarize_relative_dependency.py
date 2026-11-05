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


def paired(rows, variants, repetitions):
    result = {}
    for metric in METRICS:
        deltas = []
        for repeat in range(1, repetitions + 1):
            pair = {
                row["variant"]: row
                for row in rows
                if row["repeat"] == repeat
            }
            deltas.append(
                pair[variants[1]][metric] - pair[variants[0]][metric]
            )
        result[metric] = {
            "observations": deltas,
            "median": statistics.median(deltas),
            "mean": statistics.mean(deltas),
            "positive": sum(delta > 0 for delta in deltas),
        }
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--relative", type=Path, required=True)
    parser.add_argument("--absolute", type=Path, required=True)
    parser.add_argument("--diagnostics", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    relative = args.relative.resolve()
    absolute = args.absolute.resolve()
    diagnostics = args.diagnostics.resolve()
    relative_rows = [
        json.loads(line)
        for line in (relative / "measurements.jsonl").read_text().splitlines()
    ]
    absolute_rows = [
        json.loads(line)
        for line in (absolute / "measurements.jsonl").read_text().splitlines()
        if '"bug-reports-depend"' in line
    ]
    diagnostic_rows = [
        json.loads(line)
        for line in (
            diagnostics / "measurements.jsonl"
        ).read_text().splitlines()
    ]
    profile = {}
    for variant in ("base", "head"):
        selected = [
            row for row in diagnostic_rows
            if row["variant"] == variant
        ]
        profile[variant] = {
            "root_cpu_seconds": {
                "observations":
                    [row["root_cpu_seconds"] for row in selected],
                "median": statistics.median(
                    row["root_cpu_seconds"] for row in selected
                ),
            },
            "counters": {
                name: {
                    "calls": [row["counters"][name]["calls"]
                              for row in selected],
                    "seconds": [row["counters"][name]["seconds"]
                                for row in selected],
                    "median_seconds": statistics.median(
                        row["counters"][name]["seconds"]
                        for row in selected
                    ),
                }
                for name in selected[0]["counters"]
            },
        }
    output = {
        "baseline": "c68959fe1f070cd66a5ed2e92965185505f109ce",
        "head": "adbf7292f25542a538910711fef79bf4eb8c0bac",
        "relative_campaign": {
            "provenance": json.loads(
                (relative / "provenance.json").read_text()
            ),
            "measurements_sha256": sha256(
                relative / "measurements.jsonl"
            ),
            "rows": relative_rows,
            "paired_head_minus_base": paired(
                relative_rows, ("base", "head"), 20
            ),
        },
        "absolute_control": {
            "campaign_provenance": json.loads(
                (absolute / "provenance.json").read_text()
            ),
            "campaign_measurements_sha256": sha256(
                absolute / "measurements.jsonl"
            ),
            "rows": absolute_rows,
            "paired_head_minus_base": paired(
                absolute_rows, ("base", "head"), 5
            ),
        },
        "diagnostics": {
            "result": json.loads(
                (diagnostics / "result.json").read_text()
            ),
            "measurements_sha256": sha256(
                diagnostics / "measurements.jsonl"
            ),
            "rows": diagnostic_rows,
            "profile": profile,
        },
        "evidence": {
            "script_sha256": sha256(Path(__file__)),
        },
        "limitations": [
            "Instrumented timings include Sys.time counter overhead.",
            "CPU sampling has approximately 10 ms resolution.",
            "CPU affinity does not reserve CPU 16.",
        ],
    }
    args.output.write_text(json.dumps(output, indent=2) + "\n")


if __name__ == "__main__":
    main()
