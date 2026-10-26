#!/usr/bin/env python3

import argparse
import hashlib
import json
import math
import re
import statistics
from pathlib import Path


ORDINARY = {
    "bv-binary-ops", "classical-sugar", "norm-vs-smt", "normalization",
    "positivity", "well-founded-recursion", "bug3207",
}


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


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
    root = Path(__file__).resolve().parent
    files = {
        "suite": evidence / "ambient-cache-broad-suite/measurements.jsonl",
        "suite_provenance":
            evidence / "ambient-cache-broad-suite/provenance.json",
        "suite_runner_log":
            evidence / "ambient-cache-broad-suite.runner.log",
        "bug3207": evidence / "ambient-cache-bug3207/measurements.jsonl",
        "bug3207_provenance":
            evidence / "ambient-cache-bug3207/provenance.json",
        "simple1024_query_stream":
            evidence / "ambient-cache-simple1024-query-stream/result.json",
    }
    suite = rows(files["suite"])
    provenance = json.loads(files["suite_provenance"].read_text())
    require(len(suite) == 50, "broad suite row count differs")
    require(
        provenance["runner_sha256"]
        == sha256(root / "run_ambient_cache_suite.py"),
        "broad suite runner differs",
    )
    require(
        provenance["variants"]["baseline"]["commit"]
        == "0e13baff38309523a2074ef8fbc3745b4bc793ad"
        and provenance["variants"]["candidate"]["commit"]
        == "2260651e1f6db17b3d2013664d31e4fcc2c5fbae",
        "broad suite revisions differ",
    )
    expected_rows = {
        (variant, workload, repeat)
        for workload, spec in provenance["workloads"].items()
        for repeat in range(1, spec["repetitions"] + 1)
        for variant in ("baseline", "candidate")
    }
    actual_rows = {
        (row["variant"], row["workload"], row["repeat"]) for row in suite
    }
    require(
        len(actual_rows) == len(suite) and actual_rows == expected_rows,
        "broad suite cells differ",
    )
    per_workload = {}
    for workload, spec in provenance["workloads"].items():
        selected = [row for row in suite if row["workload"] == workload]
        statuses = sorted({row["status"] for row in selected})
        record = {
            "category": spec["category"],
            "repetitions_per_variant": spec["repetitions"],
            "statuses": statuses,
        }
        if statuses == ["success"]:
            for variant in ("baseline", "candidate"):
                variant_rows = [
                    row for row in selected if row["variant"] == variant
                ]
                record[variant] = {
                    field: summary([row[field] for row in variant_rows])
                    for field in (
                        "wall_seconds", "max_rss_kb",
                        "profiled_declaration_ms", "z3_reported_seconds",
                    )
                }
                record[variant]["profiled_declaration_count"] = sorted({
                    row["profiled_declaration_count"] for row in variant_rows
                })
                record[variant]["query_count"] = sorted({
                    row["query_count"] for row in variant_rows
                })
            record["wall_change_percent"] = 100 * (
                record["candidate"]["wall_seconds"]["median"]
                / record["baseline"]["wall_seconds"]["median"] - 1
            )
            record["rss_change_percent"] = 100 * (
                record["candidate"]["max_rss_kb"]["median"]
                / record["baseline"]["max_rss_kb"]["median"] - 1
            )
        else:
            require(
                statuses == ["failure"]
                and {row["variant"] for row in selected}
                == {"baseline", "candidate"},
                f"{workload}: unexpected unsuccessful rows",
            )
            errors = {}
            for variant in ("baseline", "candidate"):
                log = (
                    evidence / "ambient-cache-broad-suite"
                    / f"1-{workload}-{variant}.log"
                )
                text = log.read_text()
                errors[variant] = {
                    "log_sha256": sha256(log),
                    "error_codes": sorted(set(re.findall(
                        r"\* Error ([0-9]+)", text
                    ))),
                    "first_error": next(
                        line.strip() for line in text.splitlines()
                        if line.startswith("* Error")
                    ),
                }
            record["failure"] = {
                "matched": True,
                "reason": (
                    "Both historical-compiler source checks fail with the "
                    "same pre-existing hasEq nat verification errors."
                ),
                "errors": errors,
            }
            require(
                errors["baseline"]["error_codes"]
                == errors["candidate"]["error_codes"]
                and "19" in errors["baseline"]["error_codes"]
                and all(
                    "Failed to prove: Prims.hasEq Prims.nat"
                    in (
                        evidence / "ambient-cache-broad-suite"
                        / f"1-{workload}-{variant}.log"
                    ).read_text()
                    for variant in ("baseline", "candidate")
                ),
                f"{workload}: matched failure diagnostics differ",
            )
        per_workload[workload] = record

    bug_rows = rows(files["bug3207"])
    bug_provenance = json.loads(files["bug3207_provenance"].read_text())
    require(
        len(bug_rows) == 6
        and bug_provenance["runner_sha256"]
        == sha256(root / "run_matched_fstar_workload.py"),
        "Bug3207 supplement differs",
    )
    require(
        bug_provenance["z3_sha256"] == provenance["z3_sha256"],
        "Bug3207 Z3 provenance differs",
    )
    require(
        {
            variant: {
                key: bug_provenance["variants"][variant][key]
                for key in ("commit", "binary_sha256", "checked_dependency_tree")
            }
            for variant in ("baseline", "candidate")
        }
        == {
            variant: {
                key: provenance["variants"][variant][key]
                for key in ("commit", "binary_sha256", "checked_dependency_tree")
            }
            for variant in ("baseline", "candidate")
        },
        "Bug3207 variant provenance differs",
    )
    require(
        bug_provenance["source"]
        == "tests/bug-reports/closed/Bug3207.fst"
        and bug_provenance["source_sha256"]
        == "4c7ac63546fdd78ce814f4c5e7b1f6bbcd1e9a3fc332d276b5a6cb94263f5f9a"
        and bug_provenance["ocaml_version"] == "4.14.2"
        and bug_provenance["repetitions"] == 3,
        "Bug3207 source or sample count differs",
    )
    require(
        {
            (row["variant"], row["repeat"]) for row in bug_rows
        } == {
            (variant, repeat)
            for variant in ("baseline", "candidate")
            for repeat in range(1, 4)
        },
        "Bug3207 cells differ",
    )
    bug = {
        "category": "large-regression",
        "repetitions_per_variant": 3,
        "statuses": ["success"],
    }
    for variant in ("baseline", "candidate"):
        selected = [row for row in bug_rows if row["variant"] == variant]
        bug[variant] = {
            field: summary([row[field] for row in selected])
            for field in ("wall_seconds", "max_rss_kb", "z3_reported_seconds")
        }
        bug[variant]["profiled_declaration_count"] = sorted({
            row["profiled_declaration_count"] for row in selected
        })
        bug[variant]["query_count"] = sorted({
            row["query_count"] for row in selected
        })
    bug["wall_change_percent"] = 100 * (
        bug["candidate"]["wall_seconds"]["median"]
        / bug["baseline"]["wall_seconds"]["median"] - 1
    )
    bug["rss_change_percent"] = 100 * (
        bug["candidate"]["max_rss_kb"]["median"]
        / bug["baseline"]["max_rss_kb"]["median"] - 1
    )
    per_workload["bug3207"] = bug

    successful = {
        name: record for name, record in per_workload.items()
        if record["statuses"] == ["success"]
    }
    regressions = sorted(
        (
            {
                "workload": name,
                "wall_change_percent": record["wall_change_percent"],
                "absolute_median_change_seconds": (
                    record["candidate"]["wall_seconds"]["median"]
                    - record["baseline"]["wall_seconds"]["median"]
                ),
            }
            for name, record in successful.items()
            if record["wall_change_percent"] > 0
        ),
        key=lambda item: item["wall_change_percent"],
        reverse=True,
    )
    improvements = sorted(
        (
            {
                "workload": name,
                "wall_change_percent": record["wall_change_percent"],
                "absolute_median_change_seconds": (
                    record["candidate"]["wall_seconds"]["median"]
                    - record["baseline"]["wall_seconds"]["median"]
                ),
            }
            for name, record in successful.items()
            if record["wall_change_percent"] < 0
        ),
        key=lambda item: item["wall_change_percent"],
    )
    ordinary = {
        name: record for name, record in successful.items()
        if name in ORDINARY
    }
    ordinary_ratios = [
        record["candidate"]["wall_seconds"]["median"]
        / record["baseline"]["wall_seconds"]["median"]
        for record in ordinary.values()
    ]
    ordinary_baseline_sum = sum(
        record["baseline"]["wall_seconds"]["median"]
        for record in ordinary.values()
    )
    ordinary_candidate_sum = sum(
        record["candidate"]["wall_seconds"]["median"]
        for record in ordinary.values()
    )
    query_stream = json.loads(
        files["simple1024_query_stream"].read_text()
    )
    require(
        query_stream["provenance"]["variants"]["baseline"]["binary_sha256"]
        == provenance["variants"]["baseline"]["binary_sha256"]
        and query_stream["provenance"]["variants"]["candidate"]["binary_sha256"]
        == provenance["variants"]["candidate"]["binary_sha256"]
        and query_stream["provenance"]["source_sha256"]
        == provenance["source_sha256"]["simple-1024"]["shared"],
        "SimpleAgreement1024 query-stream provenance differs",
    )
    require(
        query_stream["provenance"]["runner_sha256"]
        == sha256(root / "run_matched_query_stream.py")
        and query_stream["provenance"]["z3_sha256"] == provenance["z3_sha256"]
        and {
            variant: query_stream["provenance"]["variants"][variant]
            for variant in ("baseline", "candidate")
        } == {
            variant: {
                key: provenance["variants"][variant][key]
                for key in (
                    "commit", "binary_sha256", "checked_dependency_tree"
                )
            }
            for variant in ("baseline", "candidate")
        },
        "SimpleAgreement1024 query-run provenance differs",
    )
    query_root = evidence / "ambient-cache-simple1024-query-stream"
    baseline_query = query_root / "baseline/queries-SimpleAgreement1024.smt2"
    candidate_query = query_root / "candidate/queries-SimpleAgreement1024.smt2"
    require(
        baseline_query.read_bytes() == candidate_query.read_bytes()
        and query_stream["baseline_query_stream_sha256"]
        == query_stream["candidate_query_stream_sha256"]
        == query_stream["query_stream_sha256"]
        == sha256(baseline_query)
        and query_stream["query_stream_bytes"] == baseline_query.stat().st_size,
        "SimpleAgreement1024 raw query streams differ",
    )
    runner_log = files["suite_runner_log"].read_text()
    require(
        (
            "list-tot-properties/baseline#1=failure"
            in runner_log
            and "list-tot-properties/candidate#1=failure" in runner_log
        ),
        "broad suite failure summary differs",
    )

    output = {
        "date": "2026-10-26",
        "objective": (
            "Broaden matched baseline/corrected-candidate benchmarking beyond "
            "the original synthetic campaign."
        ),
        "selection": {
            "rationale": [
                "SimpleAgreement 1024/2048: accumulated-context scaling",
                "full BV width-3: preserved real context-heavy benchmark",
                "small and medium ordinary microbenchmarks",
                "normalization and SMT-normalization controls",
                "BvBinaryOps: representative ordinary BV verification",
                "Bug3207: larger 242-declaration/523-query regression",
                "FStar.List.Tot.Properties: attempted large library source check",
            ],
            "broad_suite_rows": len(suite),
            "workloads_attempted": len(per_workload),
        },
        "provenance": provenance,
        "per_workload": per_workload,
        "aggregate": {
            "successful_workloads": len(successful),
            "failed_workloads": [
                name for name, record in per_workload.items()
                if record["statuses"] != ["success"]
            ],
            "improvements": improvements,
            "regressions": regressions,
            "ordinary_workloads": {
                "count": len(ordinary),
                "summed_median_baseline_seconds": ordinary_baseline_sum,
                "summed_median_candidate_seconds": ordinary_candidate_sum,
                "summed_median_change_percent": 100 * (
                    ordinary_candidate_sum / ordinary_baseline_sum - 1
                ),
                "geometric_mean_change_percent": 100 * (
                    math.exp(
                        sum(math.log(value) for value in ordinary_ratios)
                        / len(ordinary_ratios)
                    ) - 1
                ),
            },
        },
        "simple_1024_query_stream": query_stream,
        "interpretation": [
            (
                "The cache helps the largest context-heavy cases: full BV "
                "improves 30.9% and SimpleAgreement2048 improves 16.6%."
            ),
            (
                "SimpleAgreement1024 regresses 32.4% in three matched pairs. "
                "The 3.55 MB query stream is byte-identical, and the regression "
                "is entirely accompanied by higher measured Z3 time; cause "
                "remains unresolved."
            ),
            (
                "Ordinary workloads do not show a speedup: summed medians "
                "increase about 1.1%, with every individual median between "
                "+0.2% and +9.1%. Every absolute change is below 0.1 seconds."
            ),
            (
                "Full-BV candidate peak RSS is 4.3% higher; context-heavy RSS "
                "elsewhere is flat or lower. No allocation counters were run."
            ),
        ],
        "failures": {
            "list-tot-properties": (
                "Both variants fail the forced source check with matching "
                "historical-compiler hasEq nat Error 19 diagnostics. It is "
                "reported, not excluded or converted into a timing result."
            )
        },
        "evidence": {
            name: {"path": str(path), "sha256": sha256(path)}
            for name, path in files.items()
        },
    }
    args.output.write_text(json.dumps(output, indent=2) + "\n")


if __name__ == "__main__":
    main()
