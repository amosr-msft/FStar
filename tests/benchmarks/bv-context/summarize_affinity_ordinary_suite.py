#!/usr/bin/env python3

import argparse
import hashlib
import json
import math
import random
import re
import statistics
from pathlib import Path


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_sha256(path):
    digest = hashlib.sha256()
    files = sorted(item for item in path.rglob("*") if item.is_file())
    for item in files:
        digest.update(str(item.relative_to(path)).encode())
        digest.update(b"\0")
        digest.update(item.read_bytes())
        digest.update(b"\0")
    return {"sha256": digest.hexdigest(), "files": len(files)}


def parse_time(path):
    text = path.read_text()
    fields = re.search(
        r"Elapsed \(wall clock\) time.*: ([0-9:.]+)$", text, re.M
    ).group(1).split(":")
    wall = float(fields[-1])
    if len(fields) >= 2:
        wall += 60 * int(fields[-2])
    if len(fields) == 3:
        wall += 3600 * int(fields[-3])
    return {
        "wall_seconds": wall,
        "user_seconds": float(re.search(
            r"User time \(seconds\): ([0-9.]+)$", text, re.M
        ).group(1)),
        "system_seconds": float(re.search(
            r"System time \(seconds\): ([0-9.]+)$", text, re.M
        ).group(1)),
        "max_rss_kb": int(re.search(
            r"Maximum resident set size \(kbytes\): ([0-9]+)$", text, re.M
        ).group(1)),
        "voluntary_context_switches": int(re.search(
            r"Voluntary context switches: ([0-9]+)$", text, re.M
        ).group(1)),
        "involuntary_context_switches": int(re.search(
            r"Involuntary context switches: ([0-9]+)$", text, re.M
        ).group(1)),
    }


def summary(values):
    return {
        "observations": values,
        "median": statistics.median(values),
        "min": min(values),
        "max": max(values),
    }


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    evidence = args.evidence_root.resolve()
    root = evidence / "ambient-cache-ordinary-affinity-cpu16"
    script_root = Path(__file__).resolve().parent
    provenance_path = root / "provenance.json"
    measurements_path = root / "measurements.jsonl"
    provenance = json.loads(provenance_path.read_text())
    require(
        provenance["runner_sha256"]
        == sha256(script_root / "run_affinity_ordinary_suite.py")
        and provenance["cpu"] == 16
        and provenance["pairs_per_workload"] == 5,
        "ordinary affinity provenance differs",
    )
    worktrees = {
        "baseline": Path("/workspace/wt11/FStar-bv-context-baseline"),
        "candidate": Path("/workspace/wt11/FStar-bv-context"),
    }
    expected_commits = {
        "baseline": "0e13baff38309523a2074ef8fbc3745b4bc793ad",
        "candidate": "2260651e1f6db17b3d2013664d31e4fcc2c5fbae",
    }
    expected_binaries = {
        "baseline":
            "92170e8deb7866a34c5ca71989cbb4e0a61b17bf49829ba5f080b02f14b7d012",
        "candidate":
            "83c2f0de76d2915cae3231e1c2621009f4101f25fba45b5046366de538b97208",
    }
    require(
        provenance["z3_sha256"]
        == "4da6a0f78424098b600a9112ebb9d8ce45de248a4913c26dd7d472e6dabef6d3"
        and provenance["ocaml_version"] == "4.14.2"
        and provenance["set_environment"] == {"LC_ALL": "C", "LANG": "C"},
        "ordinary affinity toolchain/environment differs",
    )
    for name, tool in provenance["tools"].items():
        require(
            sha256(Path(tool["path"])) == tool["sha256"],
            f"{name} tool differs",
        )
    for variant, worktree in worktrees.items():
        selected = provenance["variants"][variant]
        require(
            selected["commit"] == expected_commits[variant]
            and selected["binary_sha256"] == expected_binaries[variant]
            == sha256(worktree / "stage2/out/bin/fstar.exe")
            and selected["checked_dependency_tree"]
            == tree_sha256(worktree / "stage2/out/lib/fstar/ulib.checked"),
            f"{variant} compiler/cache provenance differs",
        )
    for workload, spec in provenance["workloads"].items():
        for worktree in worktrees.values():
            require(
                sha256(worktree / spec["source"])
                == provenance["source_sha256"][workload],
                f"{workload} source provenance differs",
            )
    rows = [
        json.loads(line)
        for line in measurements_path.read_text().splitlines()
    ]
    expected = {
        (variant, workload, repeat)
        for variant in ("baseline", "candidate")
        for workload in provenance["workloads"]
        for repeat in range(1, 6)
    }
    require(
        len(rows) == 70
        and len({
            (row["variant"], row["workload"], row["repeat"])
            for row in rows
        }) == 70
        and {
            (row["variant"], row["workload"], row["repeat"])
            for row in rows
        } == expected,
        "ordinary affinity cells differ",
    )
    randomizer = random.Random(4781)
    pairs = [
        (workload, repeat)
        for workload in provenance["workloads"]
        for repeat in range(1, 6)
    ]
    randomizer.shuffle(pairs)
    expected_order = []
    for workload, repeat in pairs:
        variants = list(worktrees)
        randomizer.shuffle(variants)
        expected_order.extend(
            (variant, workload, repeat) for variant in variants
        )
    require(
        [
            (row["variant"], row["workload"], row["repeat"])
            for row in rows
        ] == expected_order,
        "ordinary affinity pair order differs",
    )
    raw_evidence = []
    for row in rows:
        stem = f"{row['repeat']}-{row['workload']}-{row['variant']}"
        time_path = root / f"{stem}.time"
        log_path = root / f"{stem}.log"
        timing = parse_time(time_path)
        text = log_path.read_text()
        raw_declarations = len(re.findall(
            r"profiled FStarC\.TypeChecker\.Tc\.process_one_decl:", text
        ))
        raw_queries = len(re.findall(r"Query-stats \(", text))
        raw_z3 = sum(float(value) for value in re.findall(
            r"Query-stats .*? succeeded in ([0-9.]+) seconds", text
        ))
        spec = provenance["workloads"][row["workload"]]
        worktree = worktrees[row["variant"]]
        expected_command = [
            provenance["tools"]["time"]["path"], "-v", "-o", str(time_path),
            provenance["tools"]["timeout"]["path"],
            "--kill-after=5s", "300s",
            provenance["tools"]["taskset"]["path"], "-c", "16",
            str(worktree / "stage2/out/bin/fstar.exe"),
            "--z3version", "5.3.0", "--smt",
            "/home/amosrobinson/.copilot/session-state/"
            "7081de44-8211-4e82-806b-f466934ac8a6/files/bin/z3-5.3.0",
            "--include", str(worktree / "stage2/out/lib/fstar/ulib"),
            "--include",
            str(worktree / "stage2/out/lib/fstar/ulib.checked"),
            "--force", "--timing", "--query_stats",
            str(worktree / spec["source"]),
        ]
        require(
            row["command"] == expected_command
            and all(row[key] == value for key, value in timing.items())
            and row["profiled_declaration_count"]
            == raw_declarations == spec["declarations"]
            and row["query_count"] == raw_queries == spec["queries"]
            and row["z3_reported_seconds"] == raw_z3,
            f"{stem}: raw evidence differs",
        )
        raw_evidence.extend([
            {"path": str(time_path), "sha256": sha256(time_path)},
            {"path": str(log_path), "sha256": sha256(log_path)},
        ])
    per_workload = {}
    for workload in provenance["workloads"]:
        record = {"pairs": 5}
        for variant in ("baseline", "candidate"):
            selected = [
                row for row in rows
                if row["workload"] == workload
                and row["variant"] == variant
            ]
            record[variant] = {
                key: summary([row[key] for row in selected])
                for key in (
                    "wall_seconds", "user_seconds", "system_seconds",
                    "max_rss_kb", "z3_reported_seconds",
                    "voluntary_context_switches",
                    "involuntary_context_switches",
                )
            }
        baseline_wall = record["baseline"]["wall_seconds"]["median"]
        candidate_wall = record["candidate"]["wall_seconds"]["median"]
        baseline_rss = record["baseline"]["max_rss_kb"]["median"]
        candidate_rss = record["candidate"]["max_rss_kb"]["median"]
        record["absolute_wall_change_seconds"] = (
            candidate_wall - baseline_wall
        )
        record["wall_change_percent"] = 100 * (
            candidate_wall / baseline_wall - 1
        )
        record["rss_change_percent"] = 100 * (
            candidate_rss / baseline_rss - 1
        )
        per_workload[workload] = record
    baseline_sum = sum(
        record["baseline"]["wall_seconds"]["median"]
        for record in per_workload.values()
    )
    candidate_sum = sum(
        record["candidate"]["wall_seconds"]["median"]
        for record in per_workload.values()
    )
    ratios = [
        record["candidate"]["wall_seconds"]["median"]
        / record["baseline"]["wall_seconds"]["median"]
        for record in per_workload.values()
    ]
    regressions = sorted(
        [
            {
                "workload": workload,
                "absolute_wall_change_seconds":
                    record["absolute_wall_change_seconds"],
                "wall_change_percent": record["wall_change_percent"],
            }
            for workload, record in per_workload.items()
            if record["wall_change_percent"] > 0
        ],
        key=lambda item: item["wall_change_percent"],
        reverse=True,
    )
    unchanged = [
        workload for workload, record in per_workload.items()
        if record["absolute_wall_change_seconds"] == 0
    ]
    output = {
        "date": "2026-10-26",
        "objective": (
            "Repeat the seven successful ordinary workloads under the "
            "validated CPU-16 affinity protocol."
        ),
        "provenance": provenance,
        "per_workload": per_workload,
        "aggregate": {
            "workloads": len(per_workload),
            "pairs_per_workload": 5,
            "rows": len(rows),
            "summed_median_baseline_seconds": baseline_sum,
            "summed_median_candidate_seconds": candidate_sum,
            "summed_median_change_seconds": candidate_sum - baseline_sum,
            "summed_median_change_percent": 100 * (
                candidate_sum / baseline_sum - 1
            ),
            "geometric_mean_change_percent": 100 * (
                math.exp(sum(math.log(value) for value in ratios) / len(ratios))
                - 1
            ),
            "regressions": regressions,
            "unchanged_medians": unchanged,
        },
        "interpretation": [
            (
                "CPU-16 control removes broad host-placement regimes; "
                "context-switch observations remain visible per workload."
            ),
            (
                "No ordinary workload shows a meaningful absolute regression. "
                "Subsecond percentage changes are dominated by 0.01-second "
                "reporting granularity."
            ),
            (
                "The cache does not improve ordinary workloads, but the "
                "controlled repeat also does not reproduce a material ordinary "
                "regression."
            ),
        ],
        "limitations": [
            "CPU affinity does not reserve CPU 16 from other host workloads.",
            "No allocation counters were run.",
            "No benchmark/workload source changes or tuning were made.",
        ],
        "evidence": {
            "provenance": {
                "path": str(provenance_path),
                "sha256": sha256(provenance_path),
            },
            "measurements": {
                "path": str(measurements_path),
                "sha256": sha256(measurements_path),
            },
            "raw": raw_evidence,
        },
    }
    args.output.write_text(json.dumps(output, indent=2) + "\n")


if __name__ == "__main__":
    main()
