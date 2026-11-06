#!/usr/bin/env python3

import argparse
import hashlib
import json
import math
import random
import statistics
from pathlib import Path


METRICS = (
    "root_cpu_seconds",
    "child_cpu_seconds",
    "group_cpu_seconds",
    "wall_seconds",
    "peak_root_rss_bytes",
    "peak_group_rss_bytes",
    "fstar_heap_peak_bytes",
)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def percentile(values, probability):
    ordered = sorted(values)
    index = (len(ordered) - 1) * probability
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[lower]
    fraction = index - lower
    return (
        ordered[lower] * (1 - fraction)
        + ordered[upper] * fraction
    )


def bootstrap_ci(observations, statistic, seed):
    randomizer = random.Random(seed)
    estimates = []
    for _ in range(10_000):
        sample = [
            observations[randomizer.randrange(len(observations))]
            for _ in observations
        ]
        estimates.append(statistic(sample))
    return {
        "lower_95": percentile(estimates, 0.025),
        "upper_95": percentile(estimates, 0.975),
        "resamples": len(estimates),
        "unit": "paired observation",
    }


def stratified_geometric_ci(pairs, seed):
    randomizer = random.Random(seed)
    estimates = []
    for _ in range(10_000):
        ratios = []
        for workload_pairs in pairs.values():
            for _ in workload_pairs:
                before, after = workload_pairs[
                    randomizer.randrange(len(workload_pairs))
                ]
                ratios.append(
                    after["group_cpu_seconds"]
                    / before["group_cpu_seconds"]
                )
        estimates.append(math.exp(
            statistics.mean(math.log(ratio) for ratio in ratios)
        ))
    return {
        "lower_95": percentile(estimates, 0.025),
        "upper_95": percentile(estimates, 0.975),
        "resamples": len(estimates),
        "unit": "paired observation, independently stratified by workload",
    }


def add_derived(row):
    row = dict(row)
    row["group_cpu_seconds"] = (
        row["root_cpu_seconds"] + row["child_cpu_seconds"]
    )
    return row


def paired_rows(rows, before, after):
    by_key = {
        (row["workload"], row["repeat"], row["variant"]): row
        for row in rows
    }
    return {
        workload: [
            (
                by_key[workload, repeat, before],
                by_key[workload, repeat, after],
            )
            for repeat in sorted({
                row["repeat"]
                for row in rows
                if row["workload"] == workload
            })
        ]
        for workload in sorted({row["workload"] for row in rows})
    }


def direction_counts(rows):
    counts = {}
    for index in range(0, len(rows), 2):
        first, second = rows[index:index + 2]
        if (
            first["workload"] != second["workload"]
            or first["repeat"] != second["repeat"]
        ):
            raise RuntimeError("measurements do not preserve adjacent pairs")
        workload = first["workload"]
        counts.setdefault(workload, {})
        counts[workload][first["variant"]] = (
            counts[workload].get(first["variant"], 0) + 1
        )
    return {
        "per_workload": counts,
        "total": {
            variant: sum(record.get(variant, 0) for record in counts.values())
            for variant in sorted({
                variant
                for record in counts.values()
                for variant in record
            })
        },
    }


def summarize_workload(pairs, seed):
    result = {}
    for metric in METRICS:
        values = [
            after[metric] - before[metric]
            for before, after in pairs
            if before.get(metric) is not None
            and after.get(metric) is not None
        ]
        if not values:
            result[metric] = None
            continue
        result[metric] = {
            "deltas": values,
            "median_delta": statistics.median(values),
            "mean_delta": statistics.mean(values),
            "after_slower": sum(value > 0 for value in values),
            "pairs": len(values),
            "median_bootstrap_95": bootstrap_ci(
                values, statistics.median, seed
            ),
        }
    ratios = [
        after["group_cpu_seconds"] / before["group_cpu_seconds"]
        for before, after in pairs
    ]
    result["group_cpu_ratio"] = {
        "ratios": ratios,
        "geometric_ratio": math.exp(
            statistics.mean(math.log(ratio) for ratio in ratios)
        ),
        "median_ratio": statistics.median(ratios),
        "after_slower": sum(ratio > 1 for ratio in ratios),
    }
    return result


def execution_pairs(rows, before, after):
    result = []
    for index in range(0, len(rows), 2):
        first, second = rows[index:index + 2]
        if (
            first["workload"] != second["workload"]
            or first["repeat"] != second["repeat"]
        ):
            raise RuntimeError("measurements do not preserve adjacent pairs")
        pair = {first["variant"]: first, second["variant"]: second}
        result.append((pair[before], pair[after]))
    return result


def summarize_broad(rows):
    pairs = paired_rows(rows, "pr", "fixed")
    workloads = {
        workload: summarize_workload(workload_pairs, 4900 + index)
        for index, (workload, workload_pairs) in enumerate(pairs.items())
    }
    ordered_pairs = execution_pairs(rows, "pr", "fixed")
    block_size = len(pairs)
    blocks = []
    for index in range(0, len(ordered_pairs), block_size):
        block_pairs = ordered_pairs[index:index + block_size]
        ratios = [
            after["group_cpu_seconds"] / before["group_cpu_seconds"]
            for before, after in block_pairs
        ]
        blocks.append({
            "execution_block": index // block_size + 1,
            "first_pair_index": index + 1,
            "last_pair_index": index + len(block_pairs),
            "workloads": [
                before["workload"] for before, _ in block_pairs
            ],
            "group_cpu_geometric_ratio": math.exp(
                statistics.mean(math.log(ratio) for ratio in ratios)
            ),
            "group_cpu_total_ratio": (
                sum(after["group_cpu_seconds"] for _, after in block_pairs)
                / sum(before["group_cpu_seconds"] for before, _ in block_pairs)
            ),
            "median_change_percent": statistics.median(
                (ratio - 1) * 100 for ratio in ratios
            ),
        })
    all_pairs = [
        pair for workload_pairs in pairs.values() for pair in workload_pairs
    ]

    aggregate = {
        "group_cpu_geometric_ratio": math.exp(statistics.mean(
            math.log(after["group_cpu_seconds"] / before["group_cpu_seconds"])
            for before, after in all_pairs
        )),
        "group_cpu_total_ratio": (
            sum(after["group_cpu_seconds"] for _, after in all_pairs)
            / sum(before["group_cpu_seconds"] for before, _ in all_pairs)
        ),
        "root_cpu_total_ratio": (
            sum(after["root_cpu_seconds"] for _, after in all_pairs)
            / sum(before["root_cpu_seconds"] for before, _ in all_pairs)
        ),
        "child_cpu_total_ratio": (
            sum(after["child_cpu_seconds"] for _, after in all_pairs)
            / sum(before["child_cpu_seconds"] for before, _ in all_pairs)
        ),
        "wall_total_ratio": (
            sum(after["wall_seconds"] for _, after in all_pairs)
            / sum(before["wall_seconds"] for before, _ in all_pairs)
        ),
        "group_cpu_geometric_bootstrap_95":
            stratified_geometric_ci(pairs, 4891),
        "execution_blocks": blocks,
        "execution_block_geometric_ratio": {
            "median": statistics.median(
                block["group_cpu_geometric_ratio"] for block in blocks
            ),
            "minimum": min(
                block["group_cpu_geometric_ratio"] for block in blocks
            ),
            "maximum": max(
                block["group_cpu_geometric_ratio"] for block in blocks
            ),
        },
    }
    return {"workloads": workloads, "aggregate": aggregate}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--broad", type=Path, required=True)
    parser.add_argument("--dependency", type=Path, required=True)
    parser.add_argument("--order-control", type=Path, required=True)
    parser.add_argument("--rebuild-control", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    campaigns = {}
    for name, directory in (
        ("broad", args.broad.resolve()),
        ("dependency", args.dependency.resolve()),
        ("order_control", args.order_control.resolve()),
        ("rebuild_control", args.rebuild_control.resolve()),
    ):
        rows = [
            add_derived(json.loads(line))
            for line in (directory / "measurements.jsonl")
            .read_text().splitlines()
        ]
        provenance = json.loads(
            (directory / "provenance.json").read_text()
        )
        campaigns[name] = {
            "provenance": provenance,
            "measurements_sha256": sha256(
                directory / "measurements.jsonl"
            ),
            "rows": rows,
            "direction_counts": direction_counts(rows),
        }
    campaigns["broad"]["summary"] = summarize_broad(
        campaigns["broad"]["rows"]
    )
    dependency_pairs = paired_rows(
        campaigns["dependency"]["rows"], "master", "final"
    )
    campaigns["dependency"]["summary"] = summarize_workload(
        dependency_pairs["bug-reports-depend"], 4897
    )
    campaigns["order_control"]["summary"] = summarize_broad(
        campaigns["order_control"]["rows"]
    )
    rebuild_pairs = paired_rows(
        campaigns["rebuild_control"]["rows"],
        "master-rebuild",
        "final-rebuild",
    )
    campaigns["rebuild_control"]["summary"] = {
        workload: summarize_workload(pairs, 4919 + index)
        for index, (workload, pairs) in enumerate(rebuild_pairs.items())
    }
    args.output.write_text(json.dumps({
        "summarizer_sha256": sha256(Path(__file__)),
        "campaigns": campaigns,
        "limitations": [
            "The 15 checked workloads are a selected set, not the full CI suite.",
            "Aggregate bootstrap intervals resample paired observations independently within workload; per-workload intervals resample that workload's pairs.",
            "CPU 16 affinity does not reserve the CPU from host activity.",
            "Sampled RSS is distinct from reported peak OCaml heap.",
        ],
    }, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
