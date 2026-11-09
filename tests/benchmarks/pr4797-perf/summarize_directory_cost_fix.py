#!/usr/bin/env python3

import argparse
import hashlib
import json
import statistics
from pathlib import Path


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--diagnostic", type=Path, required=True)
    parser.add_argument("--stat-trace", type=Path, required=True)
    parser.add_argument("--path-diagnosis", type=Path, required=True)
    parser.add_argument("--differential", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    benchmark = args.benchmark.resolve()
    stat_trace_result = json.loads(
        (args.stat_trace / "result.json").read_text()
    )
    flat_trace = next(
        row for row in stat_trace_result["rows"]
        if row["fixture"] == "original_flat"
    )
    cwd_failures = dict(flat_trace["failure_parent_counts"])[
        flat_trace["cwd"]
    ]
    cwd_unique_paths = dict(flat_trace["failure_parent_unique_paths"])[
        flat_trace["cwd"]
    ]
    command_line_files = 585
    rows = [
        json.loads(line)
        for line in (benchmark / "measurements.jsonl").read_text().splitlines()
    ]
    by_key = {
        (row["repeat"], row["variant"]): row for row in rows
    }
    repeats = sorted({row["repeat"] for row in rows})
    absolute = {}
    for variant in ("trie", "flat"):
        selected = [row for row in rows if row["variant"] == variant]
        absolute[variant] = {
            "root_cpu_seconds": statistics.median(
                row["root_cpu_seconds"] for row in selected
            ),
            "child_cpu_seconds": statistics.median(
                row["child_cpu_seconds"] for row in selected
            ),
            "wall_seconds": statistics.median(
                row["wall_seconds"] for row in selected
            ),
            "sampled_group_rss_bytes": statistics.median(
                row["peak_group_rss_bytes"] for row in selected
            ),
        }
    paired = {}
    for metric in (
        "root_cpu_seconds", "child_cpu_seconds", "wall_seconds",
        "peak_group_rss_bytes",
    ):
        deltas = [
            by_key[repeat, "flat"][metric]
            - by_key[repeat, "trie"][metric]
            for repeat in repeats
        ]
        paired[metric] = {
            "deltas": deltas,
            "median": statistics.median(deltas),
            "mean": statistics.mean(deltas),
            "fixed_higher": sum(delta > 0 for delta in deltas),
            "minimum": min(deltas),
            "maximum": max(deltas),
        }
    args.output.write_text(json.dumps({
        "summarizer_sha256": sha256(Path(__file__)),
        "fix_benchmark": {
            "provenance": json.loads(
                (benchmark / "provenance.json").read_text()
            ),
            "measurements_sha256": sha256(
                benchmark / "measurements.jsonl"
            ),
            "rows": rows,
            "absolute": absolute,
            "paired_fixed_minus_pre_fix": paired,
        },
        "fix_diagnostic": {
            "sha256": sha256(args.diagnostic / "result.json"),
            "result": json.loads(
                (args.diagnostic / "result.json").read_text()
            ),
        },
        "failed_stat_trace": {
            "sha256": sha256(args.stat_trace / "result.json"),
            "result": stat_trace_result,
        },
        "path_diagnosis": {
            "sha256": sha256(args.path_diagnosis),
            "result": json.loads(args.path_diagnosis.read_text()),
        },
        "fixed_differential": {
            "sha256": sha256(args.differential),
            "result": json.loads(args.differential.read_text()),
        },
        "cause": {
            "command_line_files": command_line_files,
            "unique_missing_paths_in_cwd": cwd_unique_paths,
            "failed_probes_per_duplicate_root":
                cwd_failures // command_line_files,
            "duplicate_cwd_failures": cwd_failures,
            "multiplication_check": (
                command_line_files
                * (cwd_failures // command_line_files)
            ),
        },
    }, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
