#!/usr/bin/env python3

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def parse_events(path):
    data = json.loads(path.read_text())
    parsed = {}
    for line in data["events"]:
        fields = line.split(",")
        parsed.setdefault(fields[0].removeprefix("CONTEXT_"), {})[
            int(fields[1])
        ] = [float(value) for value in fields[2:]]
    return data["command"], parsed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--baseline-worktree", type=Path, required=True)
    parser.add_argument("--candidate-worktree", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    evidence = args.evidence_root.resolve()
    baseline = args.baseline_worktree.resolve()
    candidate = args.candidate_worktree.resolve()
    files = {
        "baseline_scaling":
            evidence / "bv-simple-scaling/measurements.jsonl",
        "baseline_scaling_provenance":
            evidence / "bv-simple-scaling/provenance.json",
        "candidate_scaling":
            evidence / "ambient-cache-simple-scaling/measurements.jsonl",
        "candidate_scaling_provenance":
            evidence / "ambient-cache-simple-scaling/provenance.json",
        "baseline_trace":
            evidence / "bv-context-trace-v2/events.json",
        "baseline_trace_provenance":
            evidence / "bv-context-trace-v2/provenance.json",
        "candidate_trace":
            evidence / "ambient-cache-context-trace-v2/events.json",
        "candidate_trace_provenance":
            evidence / "ambient-cache-context-trace-v2/provenance.json",
        "full_candidate":
            evidence / "ambient-cache-full-bv/measurements.jsonl",
        "full_candidate_provenance":
            evidence / "ambient-cache-full-bv/provenance.json",
        "correctness":
            evidence / "ambient-cache-correctness-v2/measurements.json",
        "correctness_provenance":
            evidence / "ambient-cache-correctness-v2/provenance.json",
        "validation":
            evidence / "ambient-cache-validation/measurements.json",
        "validation_provenance":
            evidence / "ambient-cache-validation/provenance.json",
        "candidate_build": evidence / "ambient-cache-build.log",
        "candidate_boot_diff": evidence / "ambient-cache-boot-diff.log",
    }
    provenance = {
        name: json.loads(path.read_text())
        for name, path in files.items()
        if name.endswith("_provenance")
    }
    z3_hashes = {
        item["z3_sha256"] for item in provenance.values()
    }
    require(len(z3_hashes) == 1, "evidence used different Z3 binaries")
    baseline_commit = subprocess.check_output(
        ["git", "-C", str(baseline), "rev-parse", "HEAD"], text=True
    ).strip()
    candidate_commit = subprocess.check_output(
        ["git", "-C", str(candidate), "rev-parse", "HEAD"], text=True
    ).strip()
    require(
        baseline_commit == "0e13baff38309523a2074ef8fbc3745b4bc793ad",
        "baseline worktree moved",
    )
    require(
        candidate_commit == "734a73c5184b123bfbf2341a3570f823eaa2dc1a",
        "candidate worktree moved",
    )
    require(
        provenance["baseline_scaling_provenance"]["fstar_sha256"]
        == "a9de01ceb7b1e4cb043739073dfc8e1e74264d47a24ecd579730a72009dde7e1",
        "baseline scaling compiler differs",
    )
    require(
        provenance["candidate_scaling_provenance"]["fstar_sha256"]
        == digest(candidate / "stage2/out/bin/fstar.exe"),
        "candidate scaling compiler differs",
    )
    require(
        provenance["baseline_scaling_provenance"]["generator_sha256"]
        == provenance["candidate_scaling_provenance"]["generator_sha256"]
        == digest(Path(__file__).resolve().parent / "generate_simple.py"),
        "scaling generators differ",
    )
    require(
        provenance["candidate_scaling_provenance"]["plan"]
        == [
            {"count": count, "groups": 1, "group": 0}
            for count in (256, 512, 1024, 2048, 4096)
        ],
        "candidate scaling plan differs",
    )
    current_scaling_runner = digest(
        Path(__file__).resolve().parent / "run_simple_scaling.py"
    )
    producer_scaling_runner = (
        provenance["candidate_scaling_provenance"]["runner_sha256"]
    )
    resume_validation_path = None
    if producer_scaling_runner != current_scaling_runner:
        resume_validation_path = (
            evidence
            / "ambient-cache-simple-scaling"
            / f"resume-validation-{current_scaling_runner[:12]}.json"
        )
        resume_validation = json.loads(resume_validation_path.read_text())
        require(
            resume_validation["producer_runner_sha256"]
            == producer_scaling_runner
            and resume_validation["resume_runner_sha256"]
            == current_scaling_runner
            and resume_validation["plan"]
            == provenance["candidate_scaling_provenance"]["plan"]
            and resume_validation["measurements_sha256"]
            == digest(files["candidate_scaling"]),
            "candidate scaling resume validation differs",
        )

    baseline_rows = {
        row["count"]: row
        for row in rows(files["baseline_scaling"])
        if row["groups"] == 1 and row["count"] <= 4096
    }
    candidate_rows = {
        row["count"]: row for row in rows(files["candidate_scaling"])
    }
    require(
        set(baseline_rows) == set(candidate_rows)
        == {256, 512, 1024, 2048, 4096},
        "matched scaling counts differ",
    )
    scaling = []
    for count in sorted(baseline_rows):
        old = baseline_rows[count]
        new = candidate_rows[count]
        require(
            old["source_sha256"] == new["source_sha256"],
            f"source differs at count {count}",
        )
        scaling.append({
            "count": count,
            "baseline": {
                key: old[key] for key in (
                    "wall_seconds", "decl_ms_sum", "decl_ms_median",
                    "decl_ms_last", "z3_reported_seconds", "max_rss_kb",
                )
            },
            "candidate": {
                key: new[key] for key in (
                    "wall_seconds", "decl_ms_sum", "decl_ms_median",
                    "decl_ms_last", "z3_reported_seconds", "max_rss_kb",
                )
            },
            "wall_change_percent":
                100 * (new["wall_seconds"] / old["wall_seconds"] - 1),
            "declaration_time_change_percent":
                100 * (new["decl_ms_sum"] / old["decl_ms_sum"] - 1),
        })

    _, baseline_trace = parse_events(files["baseline_trace"])
    candidate_command, candidate_trace = parse_events(files["candidate_trace"])
    require(
        provenance["baseline_trace_provenance"]["source_sha256"]
        == provenance["candidate_trace_provenance"]["source_sha256"]
        == baseline_rows[1024]["source_sha256"],
        "phase trace source differs",
    )
    candidate_trace_provenance = provenance["candidate_trace_provenance"]
    require(
        candidate_trace_provenance["worktree_commit"] == candidate_commit
        and candidate_trace_provenance["z3_sha256"] == next(iter(z3_hashes))
        and candidate_trace_provenance["instrumenter_sha256"]
        == digest(Path(__file__).resolve().parent / "instrument_context.py")
        and candidate_trace_provenance["runner_sha256"]
        == digest(Path(__file__).resolve().parent / "run_context_trace.py"),
        "candidate trace provenance differs",
    )
    phase = {}
    for count in (128, 256, 512, 768, 1024):
        old_prune = baseline_trace["PRUNE"][count]
        new_prune = candidate_trace["PRUNE"][count]
        phase[count] = {
            "baseline": {
                "prune_ms": old_prune[0],
                "retained_declarations": int(old_prune[2]),
                "solve_ms": baseline_trace["SOLVE"][count][0],
                "z3_ms": int(baseline_trace["ASK"][count][1]),
                "process_decl_ms": baseline_trace["TC"][count][0],
            },
            "candidate": {
                "prune_ms": new_prune[0],
                "retained_declarations": int(new_prune[2]),
                "solve_ms": candidate_trace["SOLVE"][count][0],
                "z3_ms": int(candidate_trace["ASK"][count][1]),
                "process_decl_ms": candidate_trace["TC"][count][0],
            },
        }

    full = rows(files["full_candidate"])
    require(
        len(full) == 1
        and full[0]["query_count"] == 5809
        and full[0]["profiled_declaration_count"] == 5835,
        "full BV candidate result is incomplete",
    )
    full_source = (
        candidate / "tests/micro-benchmarks/BvModelAgreesWithZ3.fst"
    )
    require(
        provenance["full_candidate_provenance"]["source_sha256"]
        == digest(full_source),
        "full BV source differs",
    )

    comparisons = json.loads(files["correctness"].read_text())
    require(
        [(item["case"], item["check_sat_count"]) for item in comparisons]
        == [("simple", 65), ("scope", 6), ("pruning", 29)],
        "correctness comparisons differ",
    )
    correctness_provenance = json.loads(
        files["correctness_provenance"].read_text()
    )
    require(
        correctness_provenance["worktree_commit"] == candidate_commit
        and correctness_provenance["z3_sha256"] == next(iter(z3_hashes))
        and correctness_provenance["instrumenter_sha256"]
        == digest(
            Path(__file__).resolve().parent
            / "instrument_pruning_reference.py"
        ),
        "correctness provenance differs",
    )
    correctness_root = evidence / "ambient-cache-correctness-v2"
    correctness_sources = {
        "simple": correctness_root / "generated/SimpleAgreement64.fst",
        "scope": Path(__file__).resolve().parent / "PruningCacheScope.fst",
        "pruning": candidate / "tests/tactics/Pruning.fst",
    }
    require(
        all(
            correctness_provenance["sources"][name] == digest(path)
            for name, path in correctness_sources.items()
        ),
        "correctness sources differ",
    )
    for case, module in (
        ("simple", "SimpleAgreement64"),
        ("scope", "PruningCacheScope"),
    ):
        cached = correctness_root / f"{case}-cached/queries-{module}.smt2"
        reference = (
            correctness_root / f"{case}-reference/queries-{module}.smt2"
        )
        require(
            cached.read_bytes() == reference.read_bytes(),
            f"{case} query streams differ",
        )
    cached_pruning = sorted(
        (correctness_root / "pruning-cached").glob("queries-*.smt2")
    )
    reference_pruning = sorted(
        (correctness_root / "pruning-reference").glob("queries-*.smt2")
    )
    require(
        len(cached_pruning) == len(reference_pruning) == 10
        and all(
            left.name == right.name
            and left.read_bytes() == right.read_bytes()
            for left, right in zip(cached_pruning, reference_pruning)
        ),
        "existing pruning query streams differ",
    )
    query_files = {
        "simple": sorted(
            (correctness_root / "simple-cached").glob("queries-*.smt2")
        ),
        "scope": sorted(
            (correctness_root / "scope-cached").glob("queries-*.smt2")
        ),
        "pruning": cached_pruning,
    }
    for item in comparisons:
        paths = query_files[item["case"]]
        combined = b"".join(path.read_bytes() for path in paths)
        source = correctness_sources[item["case"]].resolve()
        expected_command = [
            correctness_provenance["fstar_path"],
            "--z3version", "5.3.0",
            "--smt", correctness_provenance["z3_path"],
            "--include",
            str(Path(correctness_provenance["worktree_path"])
                / "stage2/out/lib/fstar/ulib"),
            "--include",
            str(Path(correctness_provenance["worktree_path"])
                / "stage2/out/lib/fstar/ulib.checked"),
            "--query_stats", "--log_queries", str(source),
        ]
        require(
            item["query_files"] == [path.name for path in paths]
            and item["check_sat_count"]
            == sum(path.read_bytes().count(b"(check-sat)") for path in paths)
            and item["query_stream_bytes"] == len(combined)
            and item["identical_query_stream_sha256"]
            == hashlib.sha256(combined).hexdigest()
            and item["environments"]["cached"] == {}
            and item["environments"]["reference"]
            == {"FSTAR_PRUNING_REFERENCE": "1"},
            f"{item['case']} recorded equivalence data differs",
        )
        require(
            item["commands"]["cached"] == expected_command
            and item["commands"]["reference"] == expected_command,
            f"{item['case']} recorded equivalence data differs",
        )
    build_log = files["candidate_build"].read_text()
    boot_log = files["candidate_boot_diff"].read_text()
    require(
        build_log.rstrip().endswith(
            "make: Leaving directory '/workspace/wt11/FStar-bv-context'"
        )
        and "make: ***" not in build_log,
        "candidate build did not complete",
    )
    require(
        "DIFF             STAGE 2 vs STAGE 2+1" in boot_log
        and "make: ***" not in boot_log,
        "candidate boot-diff did not complete",
    )
    validation = json.loads(files["validation"].read_text())
    validation_provenance = json.loads(
        files["validation_provenance"].read_text()
    )
    require(
        [item["case"] for item in validation]
        == ["pruning", "pretyping", "no-ambients", "full-admit"]
        and validation_provenance["worktree_commit"] == candidate_commit
        and validation_provenance["fstar_sha256"]
        == digest(candidate / "stage3/out/bin/fstar.exe")
        and validation_provenance["z3_sha256"] == next(iter(z3_hashes)),
        "validation provenance differs",
    )
    require(
        validation_provenance["sources"]["pruning"]
        == validation_provenance["sources"]["pretyping"]
        == validation_provenance["sources"]["no-ambients"]
        == digest(candidate / "tests/tactics/Pruning.fst")
        and validation_provenance["sources"]["full-admit"]
        == digest(full_source),
        "validation sources differ",
    )
    require(
        correctness_provenance["runner_sha256"]
        == digest(
            Path(__file__).resolve().parent / "run_pruning_equivalence.py"
        )
        and validation_provenance["runner_sha256"]
        == digest(
            Path(__file__).resolve().parent
            / "run_ambient_cache_validation.py"
        ),
        "validation runners differ",
    )
    expected_validation = {
        "pruning": [],
        "pretyping": ["--ext", "pretyping_axioms"],
        "no-ambients": ["--ext", "context_pruning_no_ambients"],
        "full-admit": ["--admit_smt_queries", "true"],
    }
    validation_sources = {
        "pruning": candidate / "tests/tactics/Pruning.fst",
        "pretyping": candidate / "tests/tactics/Pruning.fst",
        "no-ambients": candidate / "tests/tactics/Pruning.fst",
        "full-admit":
            candidate / "tests/micro-benchmarks/BvModelAgreesWithZ3.fst",
    }
    for item in validation:
        log = evidence / "ambient-cache-validation" / f"{item['case']}.log"
        expected_command = [
            validation_provenance["fstar_path"],
            "--z3version", "5.3.0",
            "--smt", validation_provenance["z3_path"],
            *expected_validation[item["case"]],
            str(validation_sources[item["case"]]),
        ]
        require(
            item["options"] == expected_validation[item["case"]]
            and item["log_sha256"] == digest(log)
            and item["command"] == expected_command,
            f"{item['case']} validation record differs",
        )

    output = {
        "date": "2026-10-26",
        "objective": (
            "Prototype an incremental solver-scope-local cache of ambient "
            "pruning reachability without dropping ambient facts."
        ),
        "revisions": {
            "baseline_source": baseline_commit,
            "candidate": candidate_commit,
            "candidate_branch":
                "users/amos/20261026-fstar-pruning-ambient-cache",
            "baseline_scaling_binary_sha256":
                provenance["baseline_scaling_provenance"]["fstar_sha256"],
            "candidate_binary_sha256":
                provenance["candidate_scaling_provenance"]["fstar_sha256"],
            "z3_sha256": next(iter(z3_hashes)),
        },
        "design": {
            "scope": "immutable pruning_state, inherited per solver level",
            "cached": [
                "residual trigger-to-assumption map",
                "residual assumption-to-trigger alternatives",
                "ambient-reached assumption names",
                "ambient-reached symbol names",
                "direct macro inputs for one-level late expansion",
            ],
            "extension": (
                "New roots process old waiters; new triggered assumptions "
                "subtract all old reached symbols; activated assumptions close "
                "transitively; late macros expose one-level body names."
            ),
            "query_behavior": (
                "Normal queries copy the cached residual state, scan query "
                "roots temporarily, and discard query-local reachability."
            ),
            "fallbacks": [
                "pretyping_axioms uses the original fresh scan",
                "context_pruning_no_ambients uses the original fresh scan",
            ],
            "unchanged": [
                "ambient fact retention",
                "multi-trigger alternatives and conjunctions",
                "lazy declaration resolution",
                "fact filtering and declaration ordering",
                "solver push/pop/reset ownership",
            ],
        },
        "correctness": {
            "query_stream_equivalence": comparisons,
            "tests": validation,
        },
        "simple_scaling": scaling,
        "phase_trace": {
            "command": candidate_command,
            "counts": phase,
        },
        "full_bv": {
            "candidate": full[0],
            "historical_baseline_user_supplied_seconds": [751, 753],
            "comparison_limitation": (
                "The candidate uses a same-source rebuild whose binary differs "
                "from the preserved historical baseline binary."
            ),
        },
        "memory": {
            "rss_observation": (
                "Candidate peak RSS is -4.2, -1.8, -2.5, +2.4, and -0.6 MB at "
                "256, 512, 1024, 2048, and 4096 declarations respectively; "
                "no material peak-RSS increase is visible."
            ),
            "allocation": (
                "A focused OCaml allocation-counter command was blocked by "
                "the organization content-exclusion policy; allocation "
                "overhead remains unmeasured."
            ),
        },
        "conclusions": [
            (
                "The cache preserves exact solver query streams in the "
                "focused comparisons and passes fallback/scope regressions."
            ),
            (
                "At 4096 declarations wall time falls from 1052.14 to 799.06 "
                "seconds (-24.1%); declaration time falls 25.0%."
            ),
            (
                "At declaration 512 pruning falls from 14.78 to 7.93 ms and "
                "at 1024 from 31.96 to 14.88 ms, with retained declaration "
                "counts unchanged. Intrusive Z3 timing is variable."
            ),
            (
                "The full BV workload completes in 479.77 seconds with "
                "74.21 seconds reported by Z3; the unchanged Z3 component "
                "shows that persistent solver accumulation remains."
            ),
        ],
        "limitations": [
            (
                "Full-BV comparison uses a rebuilt candidate and a "
                "user-supplied historical baseline, not matched binary builds."
            ),
            (
                "The cache retains persistent maps/sets; peak RSS shows no "
                "material increase, but allocation overhead was not measured."
            ),
            (
                "No production fix or PR is proposed; this is an experiment "
                "branch only."
            ),
        ],
        "evidence": {
            **{
                name: {"path": str(path), "sha256": digest(path)}
                for name, path in files.items()
            },
            **(
                {
                    "candidate_resume_validation": {
                        "path": str(resume_validation_path),
                        "sha256": digest(resume_validation_path),
                    }
                }
                if resume_validation_path is not None else {}
            ),
        },
    }
    args.output.write_text(json.dumps(output, indent=2) + "\n")


if __name__ == "__main__":
    main()
