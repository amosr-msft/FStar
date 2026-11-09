#!/usr/bin/env python3

import argparse
import hashlib
import json
import math
import random
import statistics
from pathlib import Path


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def percentile(values, probability):
    values = sorted(values)
    position = (len(values) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return values[lower]
    fraction = position - lower
    return values[lower] * (1 - fraction) + values[upper] * fraction


def bootstrap_median(values, seed):
    randomizer = random.Random(seed)
    estimates = [
        statistics.median(
            values[randomizer.randrange(len(values))]
            for _ in values
        )
        for _ in range(10_000)
    ]
    return {
        "lower_95": percentile(estimates, 0.025),
        "upper_95": percentile(estimates, 0.975),
        "resamples": len(estimates),
    }


def summarize(rows, seed):
    by_key = {
        (row["repeat"], row["variant"]): row for row in rows
    }
    repeats = sorted({row["repeat"] for row in rows})
    absolute = {}
    for variant in ("base", "head"):
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
            "fstar_heap_peak_bytes": statistics.median(
                row["fstar_heap_peak_bytes"] for row in selected
            ),
            "sampled_group_rss_bytes": statistics.median(
                row["peak_group_rss_bytes"] for row in selected
            ),
        }
    paired = {}
    for metric in (
        "root_cpu_seconds", "child_cpu_seconds", "wall_seconds",
        "fstar_heap_peak_bytes", "peak_group_rss_bytes",
    ):
        deltas = [
            by_key[repeat, "head"][metric]
            - by_key[repeat, "base"][metric]
            for repeat in repeats
        ]
        paired[metric] = {
            "deltas": deltas,
            "median": statistics.median(deltas),
            "mean": statistics.mean(deltas),
            "head_higher": sum(delta > 0 for delta in deltas),
            "pairs": len(deltas),
            "minimum": min(deltas),
            "maximum": max(deltas),
            "median_bootstrap_95": bootstrap_median(
                deltas, seed
            ),
        }
    group_deltas = [
        (
            by_key[repeat, "head"]["root_cpu_seconds"]
            + by_key[repeat, "head"]["child_cpu_seconds"]
            - by_key[repeat, "base"]["root_cpu_seconds"]
            - by_key[repeat, "base"]["child_cpu_seconds"]
        )
        for repeat in repeats
    ]
    ratios = [
        (
            by_key[repeat, "head"]["root_cpu_seconds"]
            + by_key[repeat, "head"]["child_cpu_seconds"]
        ) / (
            by_key[repeat, "base"]["root_cpu_seconds"]
            + by_key[repeat, "base"]["child_cpu_seconds"]
        )
        for repeat in repeats
    ]
    paired["group_cpu_seconds"] = {
        "deltas": group_deltas,
        "median": statistics.median(group_deltas),
        "mean": statistics.mean(group_deltas),
        "head_higher": sum(delta > 0 for delta in group_deltas),
        "pairs": len(group_deltas),
        "minimum": min(group_deltas),
        "maximum": max(group_deltas),
        "median_bootstrap_95": bootstrap_median(
            group_deltas, seed + 100
        ),
        "geometric_ratio": math.exp(
            statistics.mean(math.log(ratio) for ratio in ratios)
        ),
    }
    return {"absolute": absolute, "paired_head_minus_base": paired}


def load_rows(directory):
    rows = [
        json.loads(line)
        for line in (directory / "measurements.jsonl").read_text().splitlines()
    ]
    return {
        "provenance": json.loads(
            (directory / "provenance.json").read_text()
        ),
        "measurements_sha256": sha256(
            directory / "measurements.jsonl"
        ),
        "rows": rows,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--artifact-analysis", type=Path, required=True)
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--cbor-extension", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = [
        json.loads(line)
        for line in (args.results / "measurements.jsonl")
        .read_text().splitlines()
    ]
    targets = {}
    for index, target in enumerate(sorted({
        row["target"] for row in rows
    })):
        targets[target] = summarize(
            [row for row in rows if row["target"] == target],
            5123 + index,
        )
    extension = load_rows(args.cbor_extension)
    combined_cbor = [
        row for row in rows if row["target"] == "cbor-boundary"
    ]
    offset = max(row["repeat"] for row in combined_cbor)
    combined_cbor.extend({
        **row, "repeat": row["repeat"] + offset
    } for row in extension["rows"])
    args.output.write_text(json.dumps({
        "summarizer_sha256": sha256(Path(__file__)),
        "artifact_analysis": {
            "sha256": sha256(args.artifact_analysis),
            "result": json.loads(args.artifact_analysis.read_text()),
        },
        "preparation": {
            "sha256": sha256(args.prepared / "provenance.json"),
            "provenance": json.loads(
                (args.prepared / "provenance.json").read_text()
            ),
        },
        "campaign": {
            "provenance": json.loads(
                (args.results / "provenance.json").read_text()
            ),
            "measurements_sha256": sha256(
                args.results / "measurements.jsonl"
            ),
            "rows": rows,
            "targets": targets,
        },
        "cbor_extension": {
            **extension,
            "summary": summarize(extension["rows"], 5179),
            "combined_summary": summarize(combined_cbor, 5189),
        },
        "limitations": [
            "Selected targets do not establish or exclude the 1,283-test heavy aggregate.",
            "CPU 16 affinity does not reserve the CPU from host activity.",
            "Local F* heap regimes differ from some CI observations.",
            "Checked outputs are compiler-specific; semantic equivalence is inferred from successful exact-source runs, not byte identity.",
        ],
    }, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
