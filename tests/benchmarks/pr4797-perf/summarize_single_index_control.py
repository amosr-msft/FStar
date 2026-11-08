#!/usr/bin/env python3

import argparse
import hashlib
import json
import re
import statistics
from pathlib import Path


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def summarize_rows(directory):
    rows = [
        json.loads(line)
        for line in (directory / "measurements.jsonl").read_text().splitlines()
    ]
    by_key = {(row["repeat"], row["mode"]): row for row in rows}
    repeats = sorted({row["repeat"] for row in rows})
    absolute = {}
    heaps = {}
    for mode in ("trie", "flat"):
        selected = [row for row in rows if row["mode"] == mode]
        mode_heaps = []
        for row in selected:
            path = directory / f"{row['repeat']}-{mode}" / "fstar.fstarmem"
            match = re.search(
                r"fstar\.mempeak\s+([0-9]+)", path.read_text()
            )
            mode_heaps.append(int(match.group(1)))
        heaps[mode] = mode_heaps
        absolute[mode] = {
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
            "fstar_heap_peak_bytes": statistics.median(mode_heaps),
        }
    paired = {}
    for metric in (
        "root_cpu_seconds", "child_cpu_seconds", "wall_seconds",
        "peak_group_rss_bytes",
    ):
        deltas = [
            by_key[repeat, "flat"][metric] - by_key[repeat, "trie"][metric]
            for repeat in repeats
        ]
        paired[metric] = {
            "deltas": deltas,
            "median": statistics.median(deltas),
            "mean": statistics.mean(deltas),
            "flat_higher": sum(delta > 0 for delta in deltas),
            "pairs": len(deltas),
            "minimum": min(deltas),
            "maximum": max(deltas),
        }
    heap_deltas = [
        flat - trie for flat, trie in zip(heaps["flat"], heaps["trie"])
    ]
    paired["fstar_heap_peak_bytes"] = {
        "deltas": heap_deltas,
        "median": statistics.median(heap_deltas),
        "flat_higher": sum(delta > 0 for delta in heap_deltas),
        "pairs": len(heap_deltas),
    }
    return {
        "provenance": json.loads(
            (directory / "provenance.json").read_text()
        ),
        "measurements_sha256": sha256(directory / "measurements.jsonl"),
        "rows": rows,
        "absolute": absolute,
        "paired_flat_minus_trie": paired,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--timings", type=Path, required=True)
    parser.add_argument("--diagnostics", type=Path, required=True)
    parser.add_argument("--differential", type=Path, required=True)
    parser.add_argument("--prior-dual", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    timing = {
        kind: summarize_rows(args.timings / kind)
        for kind in ("dependency", "long")
    }
    diagnostics = json.loads(
        (args.diagnostics / "result.json").read_text()
    )
    args.output.write_text(json.dumps({
        "summarizer_sha256": sha256(Path(__file__)),
        "single_index_timings": timing,
        "single_index_diagnostics": {
            "result_sha256": sha256(args.diagnostics / "result.json"),
            "result": diagnostics,
        },
        "differential": {
            "sha256": sha256(args.differential),
            "result": json.loads(args.differential.read_text()),
        },
        "prior_dual_index_evidence": {
            "sha256": sha256(args.prior_dual),
            "result": json.loads(args.prior_dual.read_text()),
        },
        "limitations": [
            "The diagnostic mode is selected at module initialization and cannot change within a process.",
            "The instrumented allocation/GC runs are separate from uninstrumented performance timings.",
            "The executable layout is fixed across modes, while selected index construction and retention differ.",
            "perf is unavailable because perf_event_paranoid is 4.",
        ],
    }, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
