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


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


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
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    evidence = args.evidence_root.resolve()
    root = Path(__file__).resolve().parent
    files = {
        "broad_suite":
            evidence / "ambient-cache-broad-suite/measurements.jsonl",
        "broad_provenance":
            evidence / "ambient-cache-broad-suite/provenance.json",
        "query_stream":
            evidence / "ambient-cache-simple1024-query-stream/result.json",
        "direct_replay":
            evidence
            / "ambient-cache-simple1024-z3-replay-10/measurements.json",
        "direct_replay_provenance":
            evidence
            / "ambient-cache-simple1024-z3-replay-10/provenance.json",
        "same_executable":
            evidence / "ambient-cache-simple1024-same-exe/measurements.json",
        "same_executable_provenance":
            evidence / "ambient-cache-simple1024-same-exe/provenance.json",
    }
    broad = [
        json.loads(line)
        for line in files["broad_suite"].read_text().splitlines()
    ]
    broad = [row for row in broad if row["workload"] == "simple-1024"]
    require(len(broad) == 6, "expected six broad SimpleAgreement1024 rows")
    broad_provenance = json.loads(files["broad_provenance"].read_text())
    require(
        broad_provenance["runner_sha256"]
        == sha256(root / "run_ambient_cache_suite.py")
        and broad_provenance["cleared_environment"]
        == [
            "FSTAR_LIB", "FSTAR_HOME", "OCAMLRUNPARAM", "CAMLRUNPARAM",
            "FSTAR_PRUNING_REFERENCE", "FSTAR_NO_DEDUP_VC",
        ],
        "broad suite runner/environment differs",
    )
    broad_root = evidence / "ambient-cache-broad-suite"
    broad_raw_evidence = []
    broad_roots = {
        "baseline": Path("/workspace/wt11/FStar-bv-context-baseline"),
        "candidate": Path("/workspace/wt11/FStar-bv-context"),
    }
    for row in broad:
        stem = f"{row['repeat']}-simple-1024-{row['variant']}"
        time_path = broad_root / f"{stem}.time"
        log_path = broad_root / f"{stem}.log"
        timing = parse_time(time_path)
        text = log_path.read_text()
        root_path = broad_roots[row["variant"]]
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
            and all(row[key] == value for key, value in timing.items())
            and row["query_count"]
            == len(re.findall(r"Query-stats \(", text))
            and row["profiled_declaration_ms"] == sum(
                int(value) for value in re.findall(
                    r"profiled FStarC\.TypeChecker\.Tc\.process_one_decl:"
                    r"\s+([0-9]+) ms",
                    text,
                )
            )
            and row["z3_reported_seconds"] == sum(
                float(value) for value in re.findall(
                    r"Query-stats .*? succeeded in ([0-9.]+) seconds",
                    text,
                )
            ),
            f"broad SimpleAgreement row {stem} differs from raw evidence",
        )
        broad_raw_evidence.extend([
            {"path": str(time_path), "sha256": sha256(time_path)},
            {"path": str(log_path), "sha256": sha256(log_path)},
        ])
    query_stream = json.loads(files["query_stream"].read_text())
    require(
        query_stream["provenance"]["source_sha256"]
        == broad_provenance["source_sha256"]["simple-1024"]["shared"]
        and query_stream["provenance"]["variants"]["baseline"]["binary_sha256"]
        == broad_provenance["variants"]["baseline"]["binary_sha256"]
        and query_stream["provenance"]["variants"]["candidate"]["binary_sha256"]
        == broad_provenance["variants"]["candidate"]["binary_sha256"],
        "broad/query stream provenance differs",
    )
    query_provenance = query_stream["provenance"]
    require(
        query_provenance["runner_sha256"]
        == sha256(root / "run_matched_query_stream.py")
        and query_provenance["z3_sha256"] == broad_provenance["z3_sha256"]
        and query_provenance["cleared_environment"]
        == broad_provenance["cleared_environment"]
        and all(
            query_provenance["variants"][variant]
            == {
                key: broad_provenance["variants"][variant][key]
                for key in (
                    "commit", "binary_sha256", "checked_dependency_tree"
                )
            }
            for variant in ("baseline", "candidate")
        ),
        "query-stream runner/environment/cache provenance differs",
    )
    query_root = evidence / "ambient-cache-simple1024-query-stream"
    baseline_stream = (
        query_root / "baseline/queries-SimpleAgreement1024.smt2"
    )
    candidate_stream = (
        query_root / "candidate/queries-SimpleAgreement1024.smt2"
    )
    require(
        baseline_stream.read_bytes() == candidate_stream.read_bytes()
        and sha256(baseline_stream) == query_stream["query_stream_sha256"]
        and baseline_stream.stat().st_size
        == query_stream["query_stream_bytes"],
        "raw query streams differ",
    )
    query_roots = {
        "baseline": Path("/workspace/wt11/FStar-bv-context-baseline"),
        "candidate": Path("/workspace/wt11/FStar-bv-context"),
    }
    for variant, worktree in query_roots.items():
        expected_command = [
            str(worktree / "stage2/out/bin/fstar.exe"),
            "--z3version", "5.3.0", "--smt",
            "/home/amosrobinson/.copilot/session-state/"
            "7081de44-8211-4e82-806b-f466934ac8a6/files/bin/z3-5.3.0",
            "--include", str(worktree / "stage2/out/lib/fstar/ulib"),
            "--include",
            str(worktree / "stage2/out/lib/fstar/ulib.checked"),
            "--force", "--query_stats", "--log_queries",
            str((broad_root / "generated/SimpleAgreement1024.fst").resolve()),
        ]
        require(
            query_stream["commands"][variant] == expected_command
            and sha256(worktree / "stage2/out/bin/fstar.exe")
            == query_provenance["variants"][variant]["binary_sha256"]
            and tree_sha256(worktree / "stage2/out/lib/fstar/ulib.checked")
            == query_provenance["variants"][variant]["checked_dependency_tree"],
            f"{variant} raw query command/artifacts differ",
        )

    replay = json.loads(files["direct_replay"].read_text())
    replay_provenance = json.loads(
        files["direct_replay_provenance"].read_text()
    )
    require(
        len(replay) == 10
        and replay_provenance["runner_sha256"]
        == sha256(root / "run_z3_replay.py")
        and replay_provenance["stream_sha256"]
        == query_stream["query_stream_sha256"]
        and replay_provenance["z3_sha256"]
        == broad_provenance["z3_sha256"]
        and all(row["unsat_count"] == 1025 for row in replay),
        "direct replay provenance differs",
    )
    require(
        sha256(Path(replay_provenance["z3_path"]))
        == replay_provenance["z3_sha256"]
        and sha256(Path(replay_provenance["stream_path"]))
        == replay_provenance["stream_sha256"],
        "direct replay referenced artifacts differ",
    )
    replay_root = evidence / "ambient-cache-simple1024-z3-replay-10"
    replay_counters = []
    replay_raw_evidence = []
    for row in replay:
        output_path = replay_root / f"repeat-{row['repeat']}.out"
        time_path = replay_root / f"repeat-{row['repeat']}.time"
        output = output_path.read_text()
        timing = parse_time(time_path)
        expected_command = [
            "/usr/bin/time", "-v", "-o", str(time_path),
            replay_provenance["z3_path"],
            "-smt2", replay_provenance["stream_path"],
        ]
        require(
            all(row[key] == value for key, value in timing.items())
            and row["command"] == expected_command
            and row["unsat_count"] == len(re.findall(r"^unsat$", output, re.M)),
            f"direct replay {row['repeat']} differs from raw evidence",
        )
        allocations = re.findall(r":num-allocs\s+([0-9]+)", output)
        rlimits = re.findall(r":rlimit-count\s+([0-9]+)", output)
        replay_counters.append({
            "repeat": row["repeat"],
            "final_num_allocs": int(allocations[-1]),
            "final_rlimit_count": int(rlimits[-1]),
        })
        replay_raw_evidence.extend([
            {
                "path": str(output_path),
                "sha256": sha256(output_path),
            },
            {
                "path": str(time_path),
                "sha256": sha256(time_path),
            },
        ])
    require(
        {row["final_rlimit_count"] for row in replay_counters}
        == {77059486},
        "direct replay rlimit counts differ",
    )

    same = json.loads(files["same_executable"].read_text())
    same_provenance = json.loads(
        files["same_executable_provenance"].read_text()
    )
    same_worktree = Path(same_provenance["worktree_path"])
    require(
        len(same) == 10
        and same_provenance["runner_sha256"]
        == sha256(root / "run_same_executable_pruning.py")
        and same_provenance["worktree_commit"]
        == "2260651e1f6db17b3d2013664d31e4fcc2c5fbae"
        and same_provenance["source_sha256"]
        == query_stream["provenance"]["source_sha256"]
        and same_provenance["cleared_environment"]
        == [
            "FSTAR_LIB", "FSTAR_HOME", "OCAMLRUNPARAM", "CAMLRUNPARAM",
            "FSTAR_NO_DEDUP_VC", "FSTAR_PRUNING_REFERENCE",
        ],
        "same-executable provenance differs",
    )
    require(
        same_provenance["z3_sha256"] == broad_provenance["z3_sha256"]
        and same_provenance["fstar_sha256"]
        == "f17a8cad59fd1004f5c03e3f4fcd8b98acaa67462b60c250ddff5aa83d92634d"
        and same_provenance["prims_checked_sha256"]
        == "5441a94334d74e15449e62eafe4f1f163476f3746465063af62b3c07d82bdbb4",
        "same-executable compiler/cache provenance differs",
    )
    require(
        same_provenance["instrumenter_sha256"]
        == sha256(root / "instrument_pruning_reference.py")
        and same_provenance["extracted_pruning_sha256"]
        == sha256(
            same_worktree
            / "stage2/fstarc.ml/FStarC_SMTEncoding_Pruning.ml"
        ),
        "same-executable pruning instrumentation differs",
    )
    require(
        sha256(Path(same_provenance["fstar_path"]))
        == same_provenance["fstar_sha256"]
        and sha256(Path(same_provenance["z3_path"]))
        == same_provenance["z3_sha256"]
        and sha256(Path(same_provenance["source_path"]))
        == same_provenance["source_sha256"]
        and sha256(
            same_worktree
            / "stage2/out/lib/fstar/ulib.checked/Prims.fst.checked"
        ) == same_provenance["prims_checked_sha256"],
        "same-executable referenced artifacts differ",
    )
    pairs = {}
    same_raw_evidence = []
    for row in same:
        stem = f"{row['repeat']}-{row['mode']}"
        time_path = (
            evidence / "ambient-cache-simple1024-same-exe"
            / f"{stem}.time"
        )
        log_path = (
            evidence / "ambient-cache-simple1024-same-exe"
            / f"{stem}.log"
        )
        timing = parse_time(time_path)
        text = log_path.read_text()
        expected_environment = (
            {"FSTAR_PRUNING_REFERENCE": "1"}
            if row["mode"] == "reference" else {}
        )
        expected_command = [
            "/usr/bin/time", "-v", "-o", str(time_path),
            same_provenance["fstar_path"],
            "--z3version", "5.3.0", "--smt",
            same_provenance["z3_path"],
            "--include",
            str(Path(same_provenance["worktree_path"])
                / "stage2/out/lib/fstar/ulib"),
            "--include",
            str(Path(same_provenance["worktree_path"])
                / "stage2/out/lib/fstar/ulib.checked"),
            "--force", "--timing", "--query_stats",
            same_provenance["source_path"],
        ]
        require(
            all(row[key] == value for key, value in timing.items())
            and row["command"] == expected_command
            and row["environment"] == expected_environment
            and row["query_count"]
            == len(re.findall(r"Query-stats \(", text))
            and row["profiled_declaration_ms"] == sum(
                int(value) for value in re.findall(
                    r"profiled FStarC\.TypeChecker\.Tc\.process_one_decl:"
                    r"\s+([0-9]+) ms",
                    text,
                )
            )
            and row["z3_reported_seconds"] == sum(
                float(value) for value in re.findall(
                    r"Query-stats .*? succeeded in ([0-9.]+) seconds",
                    text,
                )
            ),
            f"same-executable row {stem} differs from raw evidence",
        )
        pairs.setdefault(row["repeat"], {})[row["mode"]] = row
        same_raw_evidence.extend([
            {"path": str(time_path), "sha256": sha256(time_path)},
            {"path": str(log_path), "sha256": sha256(log_path)},
        ])
    require(
        len(pairs) == 5
        and all(set(pair) == {"cached", "reference"} for pair in pairs.values())
        and all(
            pair["cached"]["query_count"]
            == pair["reference"]["query_count"] == 1025
            for pair in pairs.values()
        ),
        "same-executable pairs differ",
    )
    require(
        all(
            pair["cached"]["wall_seconds"]
            < pair["reference"]["wall_seconds"]
            for pair in pairs.values()
        ),
        "cached pruning did not win every same-executable pair",
    )

    def mode_summary(rows, key):
        values = [row[key] for row in rows]
        return {
            "observations": values,
            "median": statistics.median(values),
            "min": min(values),
            "max": max(values),
        }

    broad_summary = {}
    for variant in ("baseline", "candidate"):
        selected = [row for row in broad if row["variant"] == variant]
        broad_summary[variant] = {
            key: mode_summary(selected, key)
            for key in (
                "wall_seconds", "user_seconds",
                "profiled_declaration_ms", "z3_reported_seconds",
                "max_rss_kb",
            )
        }
    replay_summary = {
        key: mode_summary(replay, key)
        for key in (
            "wall_seconds", "user_seconds", "system_seconds", "max_rss_kb"
        )
    }
    same_summary = {}
    for mode in ("cached", "reference"):
        selected = [row for row in same if row["mode"] == mode]
        same_summary[mode] = {
            key: mode_summary(selected, key)
            for key in (
                "wall_seconds", "user_seconds",
                "profiled_declaration_ms", "z3_reported_seconds",
                "max_rss_kb",
            )
        }

    output = {
        "date": "2026-10-26",
        "question": (
            "Does the ambient cache cause the repeatable "
            "SimpleAgreement1024 regression, and can it be mitigated safely?"
        ),
        "timer_semantics": {
            "boundary": (
                "FStarC.SMTEncoding.Z3.z3_job calls Timing.record_ms around "
                "doZ3Exe."
            ),
            "included": [
                "writing and flushing the SMT request to the persistent process",
                "waiting for and reading solver stdout through ask_process",
                "Z3 execution",
                "parsing Z3 output",
                "appending query-log result comments when logging is enabled",
            ],
            "excluded": [
                "SolverState.flush and pruning",
                "query declaration construction",
                "mk_input SMT serialization and initial query logging",
                "the remainder of top-level typechecking",
            ],
            "kind": (
                "Elapsed request/wait wall time for the whole check-sat batch, "
                "not Z3-reported CPU time and not per-goal solver time."
            ),
            "source_locations": [
                "src/smtencoding/FStarC.SMTEncoding.Z3.fst:414-479",
                "src/smtencoding/FStarC.SMTEncoding.Z3.fst:576-603",
                "src/smtencoding/FStarC.SMTEncoding.Z3.fst:620-632",
                "src/basic/FStarC.Util-ocaml.fst:380-448",
            ],
        },
        "broad_suite_regression": broad_summary,
        "query_stream": query_stream,
        "direct_z3_replay": {
            "summary": replay_summary,
            "observations": replay,
            "solver_counters": replay_counters,
            "interpretation": (
                "User CPU closely tracks wall time. Identical bytes and exact "
                "final rlimit count replay in 17.95-47.39 seconds. This is "
                "solver process CPU rather than F* compiler work or pipe "
                "waiting, and does not reproduce the broad candidate's "
                "34.62-36.90-second request times."
            ),
        },
        "same_executable_cached_vs_reference": {
            "summary": same_summary,
            "pairs": pairs,
            "interpretation": (
                "Query-scan reuse is faster than forced-fresh query scanning "
                "in every pair in the same executable. Both modes still "
                "maintain the candidate ambient cache and show Z3 variability."
            ),
        },
        "conclusions": [
            (
                "Query-scan reuse does not explain the 1024 regression: "
                "controlling the executable, cached pruning wins every pair. "
                "This does not isolate cache-maintenance or pacing effects."
            ),
            (
                "The broad candidate's elevated Z3 request times do not "
                "reproduce in direct replay or later same-executable cached "
                "runs despite byte-identical input."
            ),
            (
                "No source mitigation is justified. Changing solver settings, "
                "facts, GC, or workload would hide or speculate around the "
                "observed variability rather than fix cache overhead."
            ),
        ],
        "limitations": [
            (
                "The source of the broad-run Z3 slowdown remains unresolved; "
                "rlimit work is identical and Z3 allocation counts are nearly "
                "identical."
            ),
            (
                "Z3 internal num-allocs counters were recorded. F* allocation "
                "counters were not collected, and no restricted artifact "
                "access was retried."
            ),
        ],
        "evidence": {
            name: {"path": str(path), "sha256": sha256(path)}
            for name, path in files.items()
        },
        "raw_evidence": {
            "broad_suite": broad_raw_evidence,
            "direct_replay": replay_raw_evidence,
            "same_executable": same_raw_evidence,
        },
    }
    args.output.write_text(json.dumps(output, indent=2) + "\n")


if __name__ == "__main__":
    main()
