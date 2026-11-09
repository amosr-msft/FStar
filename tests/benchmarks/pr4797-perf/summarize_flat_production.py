#!/usr/bin/env python3

import argparse
import hashlib
import json
import statistics
from pathlib import Path


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def summarize(directory):
    rows = [
        json.loads(line)
        for line in (directory / "measurements.jsonl").read_text().splitlines()
    ]
    by_key = {
        (row["repeat"], row["variant"]): row for row in rows
    }
    repeats = sorted({row["repeat"] for row in rows})
    absolute = {}
    for variant in ("canonical", "flat-production"):
        selected = [row for row in rows if row["variant"] == variant]
        absolute[variant] = {
            "root_cpu_seconds": statistics.median(
                row["root_cpu_seconds"] for row in selected
            ),
            "child_cpu_seconds": statistics.median(
                row["child_cpu_seconds"] for row in selected
            ),
            "group_cpu_seconds": statistics.median(
                row["root_cpu_seconds"] + row["child_cpu_seconds"]
                for row in selected
            ),
            "wall_seconds": statistics.median(
                row["wall_seconds"] for row in selected
            ),
            "sampled_group_rss_bytes": statistics.median(
                row["peak_group_rss_bytes"] for row in selected
            ),
            "fstar_heap_peak_bytes": statistics.median(
                row["fstar_heap_peak_bytes"] for row in selected
                if row.get("fstar_heap_peak_bytes") is not None
            ) if any(
                row.get("fstar_heap_peak_bytes") is not None
                for row in selected
            ) else None,
        }
    paired = {}
    for metric in (
        "root_cpu_seconds", "child_cpu_seconds", "wall_seconds",
        "peak_group_rss_bytes", "fstar_heap_peak_bytes",
    ):
        deltas = [
            by_key[repeat, "flat-production"][metric]
            - by_key[repeat, "canonical"][metric]
            for repeat in repeats
            if by_key[repeat, "flat-production"].get(metric) is not None
            and by_key[repeat, "canonical"].get(metric) is not None
        ]
        paired[metric] = None if not deltas else {
            "deltas": deltas,
            "median": statistics.median(deltas),
            "mean": statistics.mean(deltas),
            "flat_higher": sum(delta > 0 for delta in deltas),
            "pairs": len(deltas),
            "minimum": min(deltas),
            "maximum": max(deltas),
        }
    return {
        "provenance": json.loads(
            (directory / "provenance.json").read_text()
        ),
        "measurements_sha256": sha256(directory / "measurements.jsonl"),
        "rows": rows,
        "absolute": absolute,
        "paired_flat_minus_canonical": paired,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--differential", type=Path, required=True)
    parser.add_argument("--single-index", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(json.dumps({
        "summarizer_sha256": sha256(Path(__file__)),
        "campaigns": {
            "dependency": summarize(args.input / "dependency"),
            "long": summarize(args.input / "long"),
        },
        "differential": {
            "sha256": sha256(args.differential),
            "result": json.loads(args.differential.read_text()),
        },
        "corrected_same_binary_control": {
            "sha256": sha256(args.single_index),
            "result": json.loads(args.single_index.read_text()),
        },
    }, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
