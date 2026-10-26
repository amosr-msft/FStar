#!/usr/bin/env python3

import argparse
import hashlib
import json
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


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def summary(values):
    return {
        "observations": values,
        "median": statistics.median(values),
        "min": min(values),
        "max": max(values),
    }


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


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def validate_affinity(root, cpu, script):
    provenance = json.loads((root / "provenance.json").read_text())
    require(
        provenance["runner_sha256"] == sha256(script)
        and provenance["cpu"] == cpu
        and provenance["replay_repetitions"] == 10
        and provenance["matched_repetitions"] == 5
        and provenance["variants"]["baseline"]["commit"]
        == "0e13baff38309523a2074ef8fbc3745b4bc793ad"
        and provenance["variants"]["candidate"]["commit"]
        == "2260651e1f6db17b3d2013664d31e4fcc2c5fbae",
        f"CPU {cpu} affinity provenance differs",
    )
    taskset = Path("/usr/bin/taskset")
    time = Path("/usr/bin/time")
    timeout = Path("/usr/bin/timeout")
    git = Path("/usr/bin/git")
    z3 = Path(
        "/home/amosrobinson/.copilot/session-state/"
        "7081de44-8211-4e82-806b-f466934ac8a6/files/bin/z3-5.3.0"
    )
    source = Path(
        "/home/amosrobinson/.copilot/session-state/"
        "7081de44-8211-4e82-806b-f466934ac8a6/files/"
        "ambient-cache-broad-suite/generated/SimpleAgreement1024.fst"
    )
    stream = Path(
        "/home/amosrobinson/.copilot/session-state/"
        "7081de44-8211-4e82-806b-f466934ac8a6/files/"
        "ambient-cache-simple1024-query-stream/baseline/"
        "queries-SimpleAgreement1024.smt2"
    )
    require(
        provenance["taskset_sha256"] == sha256(taskset)
        and provenance["time_sha256"] == sha256(time)
        and provenance["timeout_sha256"] == sha256(timeout)
        and provenance["git_sha256"] == sha256(git)
        and provenance["z3_sha256"] == sha256(z3)
        and provenance["source_sha256"] == sha256(source)
        and provenance["stream_sha256"] == sha256(stream),
        f"CPU {cpu} tool/input hashes differ",
    )
    worktrees = {
        "baseline": Path("/workspace/wt11/FStar-bv-context-baseline"),
        "candidate": Path("/workspace/wt11/FStar-bv-context"),
    }
    for variant, worktree in worktrees.items():
        binary = worktree / "stage2/out/bin/fstar.exe"
        require(
            provenance["variants"][variant]["binary_sha256"]
            == sha256(binary)
            and provenance["variants"][variant]["checked_dependency_tree"]
            == tree_sha256(worktree / "stage2/out/lib/fstar/ulib.checked"),
            f"CPU {cpu} {variant} compiler/cache differs",
        )
    replay = rows(root / "replay.jsonl")
    matched = rows(root / "matched.jsonl")
    require(
        len(replay) == 10 and len(matched) == 10,
        f"CPU {cpu} row counts differ",
    )
    raw = []
    for row in replay:
        time_path = root / f"replay-{row['repeat']}.time"
        output_path = root / f"replay-{row['repeat']}.out"
        expected_command = [
            str(time), "-v", "-o", str(time_path),
            str(timeout), "--kill-after=5s", "120s",
            str(taskset), "-c", str(cpu),
            str(z3), "-smt2", str(stream),
        ]
        timing = parse_time(time_path)
        output = output_path.read_text()
        require(
            all(row[key] == timing[key] for key in (
                "wall_seconds", "user_seconds", "system_seconds",
                "max_rss_kb",
            ))
            and row["unsat_count"]
            == len(re.findall(r"^unsat$", output, re.M)) == 1025
            and row["final_rlimit_count"] == int(re.findall(
                r":rlimit-count\s+([0-9]+)", output
            )[-1]) == 77059486,
            f"CPU {cpu} replay {row['repeat']} differs",
        )
        require(
            row["command"] == expected_command,
            f"CPU {cpu} replay {row['repeat']} differs",
        )
        raw.extend([
            {"path": str(time_path), "sha256": sha256(time_path)},
            {"path": str(output_path), "sha256": sha256(output_path)},
        ])
    pairs = {}
    for row in matched:
        stem = f"matched-{row['repeat']}-{row['variant']}"
        time_path = root / f"{stem}.time"
        log_path = root / f"{stem}.log"
        timing = parse_time(time_path)
        text = log_path.read_text()
        worktree = worktrees[row["variant"]]
        expected_command = [
            str(time), "-v", "-o", str(time_path),
            str(timeout), "--kill-after=5s", "180s",
            str(taskset), "-c", str(cpu),
            str(worktree / "stage2/out/bin/fstar.exe"),
            "--z3version", "5.3.0", "--smt", str(z3),
            "--include", str(worktree / "stage2/out/lib/fstar/ulib"),
            "--include",
            str(worktree / "stage2/out/lib/fstar/ulib.checked"),
            "--force", "--timing", "--query_stats", str(source),
        ]
        query_times = [
            float(value) for value in re.findall(
                r"Query-stats .*? succeeded in ([0-9.]+) seconds", text
            )
        ]
        require(
            all(row[key] == timing[key] for key in (
                "wall_seconds", "user_seconds", "system_seconds",
                "max_rss_kb",
            ))
            and row["query_count"]
            == len(re.findall(r"Query-stats \(", text)) == 1025
            and row["profiled_declaration_count"]
            == len(re.findall(
                r"profiled FStarC\.TypeChecker\.Tc\.process_one_decl:", text
            )) == 1025,
            f"CPU {cpu} matched row {stem} differs",
        )
        require(
            row["command"] == expected_command
            and row["z3_reported_seconds"] == sum(query_times),
            f"CPU {cpu} matched row {stem} differs",
        )
        row["query_time_quartiles"] = [
            sum(query_times[index * len(query_times) // 4:
                            (index + 1) * len(query_times) // 4])
            for index in range(4)
        ]
        pairs.setdefault(row["repeat"], {})[row["variant"]] = row
        row["voluntary_context_switches"] = timing[
            "voluntary_context_switches"
        ]
        row["involuntary_context_switches"] = timing[
            "involuntary_context_switches"
        ]
        raw.extend([
            {"path": str(time_path), "sha256": sha256(time_path)},
            {"path": str(log_path), "sha256": sha256(log_path)},
        ])
    require(
        len(pairs) == 5
        and all(set(pair) == {"baseline", "candidate"} for pair in pairs.values()),
        f"CPU {cpu} pairs differ",
    )
    require(
        all(
            pair["candidate"]["wall_seconds"]
            < pair["baseline"]["wall_seconds"]
            for pair in pairs.values()
        ),
        f"CPU {cpu} candidate did not win every pair",
    )

    replay_summary = {
        key: summary([row[key] for row in replay])
        for key in ("wall_seconds", "user_seconds", "max_rss_kb")
    }
    matched_summary = {}
    for variant in ("baseline", "candidate"):
        selected = [row for row in matched if row["variant"] == variant]
        matched_summary[variant] = {
            key: summary([row[key] for row in selected])
            for key in (
                "wall_seconds", "user_seconds", "z3_reported_seconds",
                "profiled_declaration_ms", "max_rss_kb",
                "voluntary_context_switches",
                "involuntary_context_switches",
            )
        }
    return {
        "provenance": provenance,
        "replay": replay_summary,
        "matched": matched_summary,
        "pairs": pairs,
        "raw_evidence": raw,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    evidence = args.evidence_root.resolve()
    script = Path(__file__).resolve().parent / "run_affinity_controls.py"
    cpu0 = validate_affinity(
        evidence / "ambient-cache-simple1024-affinity", 0, script
    )
    cpu16 = validate_affinity(
        evidence / "ambient-cache-simple1024-affinity-cpu16", 16, script
    )

    broad_root = evidence / "ambient-cache-broad-suite"
    broad_provenance = json.loads(
        (broad_root / "provenance.json").read_text()
    )
    broad_summary_path = (
        Path(__file__).resolve().parent / "AMBIENT_CACHE_BROAD_SUITE.json"
    )
    broad_summary_artifact = json.loads(broad_summary_path.read_text())
    require(
        broad_provenance["runner_sha256"]
        == sha256(Path(__file__).resolve().parent / "run_ambient_cache_suite.py")
        and broad_summary_artifact["evidence"]["suite"]["sha256"]
        == sha256(broad_root / "measurements.jsonl")
        and broad_summary_artifact["provenance"] == broad_provenance,
        "original broad-suite provenance differs",
    )
    broad = [
        json.loads(line)
        for line in (broad_root / "measurements.jsonl").read_text().splitlines()
    ]
    broad = [row for row in broad if row["workload"] == "simple-1024"]
    require(
        len(broad) == 6
        and {
            (row["variant"], row["repeat"]) for row in broad
        } == {
            (variant, repeat)
            for variant in ("baseline", "candidate")
            for repeat in range(1, 4)
        },
        "original SimpleAgreement rows differ",
    )
    require(
        [(row["repeat"], row["variant"]) for row in broad]
        == [
            (3, "candidate"), (3, "baseline"),
            (2, "baseline"), (2, "candidate"),
            (1, "candidate"), (1, "baseline"),
        ],
        "original pair order differs",
    )
    broad_raw = []
    for row in broad:
        stem = f"{row['repeat']}-simple-1024-{row['variant']}"
        time_path = broad_root / f"{stem}.time"
        timing = parse_time(time_path)
        log_path = broad_root / f"{stem}.log"
        text = log_path.read_text()
        query_times = [
            float(value) for value in re.findall(
                r"Query-stats .*? succeeded in ([0-9.]+) seconds", text
            )
        ]
        root_path = (
            Path("/workspace/wt11/FStar-bv-context-baseline")
            if row["variant"] == "baseline"
            else Path("/workspace/wt11/FStar-bv-context")
        )
        source = broad_root / "generated/SimpleAgreement1024.fst"
        expected_command = [
            "/usr/bin/time", "-v", "-o", str(time_path),
            "timeout", "--kill-after=5s", "300s",
            str(root_path / "stage2/out/bin/fstar.exe"),
            "--z3version", "5.3.0", "--smt",
            "/home/amosrobinson/.copilot/session-state/"
            "7081de44-8211-4e82-806b-f466934ac8a6/files/bin/z3-5.3.0",
            "--include", str(root_path / "stage2/out/lib/fstar/ulib"),
            "--include",
            str(root_path / "stage2/out/lib/fstar/ulib.checked"),
            "--force", "--timing", "--query_stats", str(source),
        ]
        require(
            row["command"] == expected_command
            and all(row[key] == timing[key] for key in (
                "wall_seconds", "user_seconds", "system_seconds",
                "max_rss_kb",
            ))
            and row["query_count"]
            == len(re.findall(r"Query-stats \(", text)) == 1025
            and row["z3_reported_seconds"] == sum(query_times),
            f"original broad row {stem} differs",
        )
        row["voluntary_context_switches"] = timing[
            "voluntary_context_switches"
        ]
        row["involuntary_context_switches"] = timing[
            "involuntary_context_switches"
        ]
        row["query_time_quartiles"] = [
            sum(query_times[index * len(query_times) // 4:
                            (index + 1) * len(query_times) // 4])
            for index in range(4)
        ]
        broad_raw.append({
            "path": str(time_path), "sha256": sha256(time_path)
        })
        broad_raw.append({
            "path": str(log_path), "sha256": sha256(log_path)
        })
    broad_summary = {}
    for variant in ("baseline", "candidate"):
        selected = [row for row in broad if row["variant"] == variant]
        broad_summary[variant] = {
            key: summary([row[key] for row in selected])
            for key in (
                "wall_seconds", "user_seconds", "z3_reported_seconds",
                "involuntary_context_switches",
            )
        }
        broad_summary[variant]["query_time_quartiles"] = [
            row["query_time_quartiles"] for row in selected
        ]
        recorded = broad_summary_artifact["per_workload"]["simple-1024"][
            variant
        ]
        require(
            recorded["wall_seconds"] == broad_summary[variant]["wall_seconds"]
            and recorded["z3_reported_seconds"]
            == broad_summary[variant]["z3_reported_seconds"],
            f"original {variant} summary differs",
        )

    regression_summary_path = (
        Path(__file__).resolve().parent / "SIMPLE1024_REGRESSION_ANALYSIS.json"
    )
    regression_summary = json.loads(regression_summary_path.read_text())
    unpinned = regression_summary["direct_z3_replay"]["summary"][
        "wall_seconds"
    ]
    require(
        unpinned["min"] == 17.95 and unpinned["max"] == 47.39,
        "audited unpinned replay range differs",
    )
    cpu0_replay = cpu0["replay"]["wall_seconds"]
    cpu16_replay = cpu16["replay"]["wall_seconds"]
    cpu0_baseline = cpu0["matched"]["baseline"]["wall_seconds"]
    cpu0_candidate = cpu0["matched"]["candidate"]["wall_seconds"]
    cpu16_baseline = cpu16["matched"]["baseline"]["wall_seconds"]
    cpu16_candidate = cpu16["matched"]["candidate"]["wall_seconds"]
    cpu16_baseline_z3 = cpu16["matched"]["baseline"][
        "z3_reported_seconds"
    ]
    cpu16_candidate_z3 = cpu16["matched"]["candidate"][
        "z3_reported_seconds"
    ]
    original_baseline_switches = broad_summary["baseline"][
        "involuntary_context_switches"
    ]
    original_candidate_switches = broad_summary["candidate"][
        "involuntary_context_switches"
    ]

    output = {
        "date": "2026-10-26",
        "question": (
            "Why did all three original candidate runs appear slower, and "
            "does the correlation survive fixed CPU affinity?"
        ),
        "original_unpinned": broad_summary,
        "fixed_affinity": {"cpu0": cpu0, "cpu16": cpu16},
        "perf_control": {
            "command": (
                "/usr/bin/perf stat -x, -e cycles,instructions "
                "/usr/bin/taskset -c 0 true"
            ),
            "result": (
                "Unavailable without CAP_PERFMON because "
                "perf_event_paranoid=4."
            ),
            "artifact": (
                "A second attempt to preserve the output was blocked by "
                "content-exclusion policy and was not retried."
            ),
        },
        "conclusions": [
            (
                "Fixed affinity substantially narrows direct-replay spread: "
                f"CPU0 is {cpu0_replay['min']:.2f}-{cpu0_replay['max']:.2f} "
                f"seconds and CPU16 {cpu16_replay['min']:.2f}-"
                f"{cpu16_replay['max']:.2f}, versus {unpinned['min']:.2f}-"
                f"{unpinned['max']:.2f} unpinned."
            ),
            (
                "The original candidate-only slowdown does not survive either "
                "fixed-CPU control. Candidate wins all five genuine pairs on "
                "both CPUs."
            ),
            (
                "CPU16 is especially stable: baseline/candidate medians are "
                f"{cpu16_baseline['median']:.2f}/"
                f"{cpu16_candidate['median']:.2f} seconds and Z3 medians "
                f"{cpu16_baseline_z3['median']:.2f}/"
                f"{cpu16_candidate_z3['median']:.2f}."
            ),
            (
                f"Original candidate runs had "
                f"{original_candidate_switches['min']:,}-"
                f"{original_candidate_switches['max']:,} involuntary context "
                f"switches versus {original_baseline_switches['min']:,}-"
                f"{original_baseline_switches['max']:,} for baseline. "
                "This, affinity "
                "sensitivity, and paired reversal support an environmental "
                "scheduler/CPU-execution effect, but do not identify its exact "
                "hardware mechanism."
            ),
        ],
        "limitations": [
            (
                "Affinity constrains placement but does not reserve a CPU from "
                "other host workloads."
            ),
            (
                "No cycles/instructions counters were available, so frequency, "
                "SMT-sibling contention, and other hardware-level causes remain "
                "unresolved."
            ),
            "No production source change was made.",
        ],
        "evidence": {
            "cpu0_provenance": {
                "path": str(
                    evidence
                    / "ambient-cache-simple1024-affinity/provenance.json"
                ),
                "sha256": sha256(
                    evidence
                    / "ambient-cache-simple1024-affinity/provenance.json"
                ),
            },
            "cpu16_provenance": {
                "path": str(
                    evidence
                    / "ambient-cache-simple1024-affinity-cpu16/provenance.json"
                ),
                "sha256": sha256(
                    evidence
                    / "ambient-cache-simple1024-affinity-cpu16/provenance.json"
                ),
            },
            "original_times": broad_raw,
            "audited_broad_summary": {
                "path": str(broad_summary_path),
                "sha256": sha256(broad_summary_path),
            },
            "audited_unpinned_summary": {
                "path": str(regression_summary_path),
                "sha256": sha256(regression_summary_path),
            },
        },
    }
    args.output.write_text(json.dumps(output, indent=2) + "\n")


if __name__ == "__main__":
    main()
