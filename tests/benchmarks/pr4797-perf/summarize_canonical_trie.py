#!/usr/bin/env python3

import argparse
import hashlib
import json
import statistics
from pathlib import Path


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def add_derived(row):
    row = dict(row)
    row["group_cpu_seconds"] = (
        row["root_cpu_seconds"] + row["child_cpu_seconds"]
    )
    return row


def summarize(rows, before="incumbent", after="canonical"):
    result = {}
    for workload in sorted({row["workload"] for row in rows}):
        selected = [row for row in rows if row["workload"] == workload]
        by_key = {
            (row["repeat"], row["variant"]): row for row in selected
        }
        repeats = sorted({row["repeat"] for row in selected})
        metrics = {}
        for metric in (
            "root_cpu_seconds", "child_cpu_seconds", "group_cpu_seconds",
            "wall_seconds", "peak_root_rss_bytes",
            "peak_group_rss_bytes", "fstar_heap_peak_bytes",
        ):
            deltas = [
                by_key[repeat, after][metric]
                - by_key[repeat, before][metric]
                for repeat in repeats
                if by_key[repeat, "canonical"].get(metric) is not None
                and by_key[repeat, "incumbent"].get(metric) is not None
            ]
            metrics[metric] = None if not deltas else {
                "deltas": deltas,
                "median_delta": statistics.median(deltas),
                "mean_delta": statistics.mean(deltas),
                "canonical_slower": sum(delta > 0 for delta in deltas),
                "pairs": len(deltas),
            }
        result[workload] = metrics
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--differential", type=Path, required=True)
    parser.add_argument("--rebuild", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    campaigns = {}
    for name in ("dependency", "checked"):
        directory = args.input / name
        rows = [
            add_derived(json.loads(line))
            for line in (directory / "measurements.jsonl")
            .read_text().splitlines()
        ]
        campaigns[name] = {
            "provenance": json.loads(
                (directory / "provenance.json").read_text()
            ),
            "measurements_sha256": sha256(
                directory / "measurements.jsonl"
            ),
            "rows": rows,
            "summary": summarize(rows),
        }
    rebuild_rows = [
        add_derived(json.loads(line))
        for line in (args.rebuild / "measurements.jsonl")
        .read_text().splitlines()
    ]
    args.output.write_text(json.dumps({
        "summarizer_sha256": sha256(Path(__file__)),
        "differential": {
            "sha256": sha256(args.differential),
            "result": json.loads(args.differential.read_text()),
        },
        "campaigns": campaigns,
        "rebuild_control": {
            "provenance": json.loads(
                (args.rebuild / "provenance.json").read_text()
            ),
            "measurements_sha256": sha256(
                args.rebuild / "measurements.jsonl"
            ),
            "rows": rebuild_rows,
            "canonical_minus_incumbent":
                summarize(rebuild_rows),
            "canonical_rebuild_minus_incumbent":
                summarize(
                    rebuild_rows, "incumbent", "canonical-rebuild"
                ),
            "canonical_rebuild_minus_canonical":
                summarize(
                    rebuild_rows, "canonical", "canonical-rebuild"
                ),
        },
    }, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
