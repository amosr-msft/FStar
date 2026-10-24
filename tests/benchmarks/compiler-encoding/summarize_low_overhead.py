#!/usr/bin/env python3

import argparse
import hashlib
import json
import re
import statistics
import subprocess
from pathlib import Path


VARIANTS = ("master", "interning", "candidate")
MODULES = ("BenchBvLive500", "BenchUIntLive500")


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def summary(values):
    return {
        "observations": values,
        "median": statistics.median(values),
        "min": min(values),
        "max": max(values),
    }


def group(items, fields):
    result = {}
    for item in items:
        key = tuple(item[field] for field in fields)
        result.setdefault(key, []).append(item)
    return result


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def validate_cells(items, fields, expected_keys, repetitions):
    groups = group(items, fields)
    require(set(groups) == set(expected_keys), f"unexpected cells for {fields}")
    for key, values in groups.items():
        repeats = [value["repeat"] for value in values]
        require(
            sorted(repeats) == list(range(1, repetitions + 1)),
            f"incomplete or duplicate cell {key}: {repeats}",
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--master", type=Path, required=True)
    parser.add_argument("--interning", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    roots = {
        "master": args.master.resolve(),
        "interning": args.interning.resolve(),
        "candidate": args.candidate.resolve(),
    }
    input_files = {
        "end_to_end": args.evidence_root / "low-overhead-comparison-v2/measurements.jsonl",
        "profiles": args.evidence_root / "low-overhead-profiles-v2/measurements.jsonl",
        "ordinary": args.evidence_root / "low-overhead-ordinary/measurements.jsonl",
        "candidate_build": args.evidence_root / "decls-sharing-clean-build.log",
        "candidate_boot_diff":
            args.evidence_root / "decls-sharing-clean-boot-diff.log",
        "BvBinaryOps": args.evidence_root / "low-overhead-BvBinaryOps.log",
        "ClassicalSugar": args.evidence_root / "low-overhead-ClassicalSugar.log",
        "structural_comparison":
            args.evidence_root / "low-overhead-structural-comparison.log",
    }
    data = {
        name: rows(path)
        for name, path in input_files.items()
        if name in ("end_to_end", "profiles", "ordinary")
    }
    campaign_provenance = {
        "end_to_end": json.loads(
            (args.evidence_root / "low-overhead-comparison-v2/provenance.json").read_text()
        ),
        "profiles": json.loads(
            (args.evidence_root / "low-overhead-profiles-v2/provenance.json").read_text()
        ),
        "ordinary": json.loads(
            (args.evidence_root / "low-overhead-ordinary/provenance.json").read_text()
        ),
    }
    validate_cells(
        data["end_to_end"],
        ("module", "variant", "mode"),
        [
            (module, variant, mode)
            for module in MODULES
            for variant in VARIANTS
            for mode in ("write", "no-write")
        ],
        5,
    )
    validate_cells(
        data["profiles"],
        ("module", "variant", "mode"),
        [
            (module, variant, "no-write")
            for module in MODULES
            for variant in VARIANTS
        ],
        3,
    )
    validate_cells(
        data["ordinary"],
        ("module", "variant", "mode"),
        [
            (module, variant, mode)
            for module in (
                "Positivity", "TestWellFoundedRecursion"
            )
            for variant in VARIANTS
            for mode in ("write", "no-write")
        ],
        5,
    )

    end_to_end = {}
    for key, values in group(
        data["end_to_end"], ("module", "variant", "mode")
    ).items():
        module, variant, mode = key
        end_to_end.setdefault(module, {}).setdefault(variant, {})[mode] = {
            field: summary([value[field] for value in values])
            for field in (
                "wall_seconds", "user_seconds", "system_seconds",
                "max_rss_kb", "fstar_mempeak_bytes", "checked_bytes",
            )
        }

    profiles = {}
    for key, values in group(data["profiles"], ("module", "variant")).items():
        module, variant = key
        fields = (
            "wall_seconds", "allocated_words", "promoted_words", "major_words",
            "minor_collections", "major_collections", "top_heap_words",
        )
        record = {
            field: summary([value[field] for value in values])
            for field in fields
        }
        for phase in ("decls", "index"):
            for field in ("wall_ms", "cpu_ms", "allocated_words"):
                name = f"{phase}_{field}"
                observations = [
                    value[name] for value in values if name in value
                ]
                if observations:
                    record[name] = summary(observations)
        profiles.setdefault(module, {})[variant] = record

    ordinary = {}
    for key, values in group(
        data["ordinary"], ("module", "variant", "mode")
    ).items():
        module, variant, mode = key
        ordinary.setdefault(module, {}).setdefault(variant, {})[mode] = {
            field: summary([value[field] for value in values])
            for field in (
                "wall_seconds", "max_rss_kb", "fstar_mempeak_bytes",
                "checked_bytes",
            )
        }

    dependent = {}
    dependent_files = {}
    dependent_root = args.evidence_root / "low-overhead-dependent"
    for variant in VARIANTS:
        for representation in ("bv", "uint"):
            for mode in ("metadata", "rooted"):
                path = (
                    dependent_root
                    / f"lowoverhead-{variant}-{representation}"
                    / f"{mode}.jsonl"
                )
                dependent_files[
                    f"{variant}-{representation}-{mode}"
                ] = path
                values = rows(path)
                require(
                    sorted(value["repeat"] for value in values)
                    == list(range(1, 6)),
                    f"incomplete dependent evidence: {path}",
                )
                dependent.setdefault(representation, {}).setdefault(
                    variant, {}
                )[mode] = {
                    "wall_seconds": summary(
                        [value["wall_seconds"] for value in values]
                    ),
                    "peak_rss_kb": summary(
                        [value["peak_rss_kb"] for value in values]
                    ),
                }

    artifacts = {}
    artifact_root = args.evidence_root / "low-overhead-artifacts"
    for module in MODULES:
        artifacts[module] = {}
        for variant in VARIANTS:
            path = artifact_root / variant / f"{module}.fst.checked"
            artifacts[module][variant] = {
                "bytes": path.stat().st_size,
                "sha256": digest(path),
            }

    provenance = {}
    for variant, root in roots.items():
        binary = root / "stage3/out/bin/fstar.exe"
        provenance[variant] = {
            "commit": subprocess.check_output(
                ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
            ).strip(),
            "binary_sha256": digest(binary),
            "binary_bytes": binary.stat().st_size,
        }
    end_provenance = campaign_provenance["end_to_end"]
    require(
        end_provenance["z3_sha256"]
        == campaign_provenance["profiles"]["z3_sha256"]
        == campaign_provenance["ordinary"]["z3_sha256"],
        "campaign Z3 hashes differ",
    )
    for variant in VARIANTS:
        require(
            end_provenance[variant]["commit"] == provenance[variant]["commit"],
            f"end-to-end commit mismatch for {variant}",
        )
        require(
            end_provenance[variant]["binary_sha256"]
            == provenance[variant]["binary_sha256"],
            f"end-to-end binary mismatch for {variant}",
        )
        require(
            campaign_provenance["profiles"][variant]["commit"]
            == provenance[variant]["commit"],
            f"profile commit mismatch for {variant}",
        )
        require(
            campaign_provenance["profiles"][variant]["child_sha256"]
            == end_provenance[variant]["child_sha256"],
            f"profile child mismatch for {variant}",
        )
        require(
            campaign_provenance["ordinary"]["variants"][variant]["commit"]
            == provenance[variant]["commit"],
            f"ordinary commit mismatch for {variant}",
        )
        require(
            campaign_provenance["ordinary"]["variants"][variant]["binary_sha256"]
            == provenance[variant]["binary_sha256"],
            f"ordinary binary mismatch for {variant}",
        )
    require(
        end_provenance["sources"]
        == campaign_provenance["profiles"]["sources"],
        "synthetic source hashes differ",
    )
    ordinary_sources = campaign_provenance["ordinary"]["sources"]
    for variant, root in roots.items():
        for module, relative_path in (
            ("Positivity", "tests/micro-benchmarks/Positivity.fst"),
            (
                "TestWellFoundedRecursion",
                "tests/micro-benchmarks/TestWellFoundedRecursion.fst",
            ),
        ):
            recorded = (
                ordinary_sources[variant][module]
                if variant in ordinary_sources
                else ordinary_sources[module]
            )
            require(
                digest(root / relative_path) == recorded,
                f"ordinary source mismatch for {variant}/{module}",
            )
    for variant in VARIANTS:
        for representation, module in (
            ("bv", "BenchBvLive500"),
            ("uint", "BenchUIntLive500"),
        ):
            child = module.replace("Live500", "Children")
            for mode in ("metadata", "rooted"):
                path = dependent_files[f"{variant}-{representation}-{mode}"]
                for value in rows(path):
                    require(
                        value["fstar_sha256"]
                        == provenance[variant]["binary_sha256"],
                        f"dependent compiler mismatch: {path}",
                    )
                    require(
                        value["smt_sha256"] == end_provenance["z3_sha256"],
                        f"dependent Z3 mismatch: {path}",
                    )
                    require(
                        value["dependency_sha256"]
                        == artifacts[module][variant]["sha256"],
                        f"dependent artifact mismatch: {path}",
                    )
                    require(
                        value["child_sha256"]
                        == end_provenance[variant]["child_sha256"][child],
                        f"dependent child mismatch: {path}",
                    )
    build_log = input_files["candidate_build"].read_text()
    boot_log = input_files["candidate_boot_diff"].read_text()
    failure_pattern = re.compile(r"(^|\n)(?:make(?:\[[0-9]+\])?: \*\*\*|Error:|FAILED)", re.M)
    require(not failure_pattern.search(build_log), "candidate build log has a failure")
    require(
        re.search(r"\nmake: Leaving directory '[^']+'$", build_log.rstrip())
        is not None,
        "candidate build log is incomplete",
    )
    require(not failure_pattern.search(boot_log), "boot-diff log has a failure")
    require(
        boot_log.count("DIFF             STAGE 2 vs STAGE 2+1") == 1
        and re.search(r"\nmake: Leaving directory '[^']+'$", boot_log.rstrip())
        is not None,
        "boot-diff log is incomplete",
    )
    for name in ("BvBinaryOps", "ClassicalSugar"):
        text = input_files[name].read_text()
        require(
            text.rstrip().endswith(
                "All verification conditions discharged successfully"
            )
            and "Verified module:" in text
            and "Error" not in text,
            f"{name} did not pass",
        )
    structural = input_files["structural_comparison"].read_text()
    expected_headings = [
        f"{module} master vs {variant}"
        for module in MODULES
        for variant in ("interning", "candidate")
    ]
    require(
        all(structural.count(heading) == 1 for heading in expected_headings)
        and structural.count(
            "stage1, tc_result/index, and declarations structurally equal"
        ) == 4
        and len(structural.splitlines()) == 8,
        "structural comparisons are incomplete",
    )

    commands = {
        name: [value["command"] for value in values]
        for name, values in data.items()
    }
    commands["dependent"] = [
        value["command"]
        for path in dependent_files.values()
        for value in rows(path)
    ]

    output = {
        "date": "2026-10-24",
        "objective": "Retain most sharing benefits with lower allocation and time overhead",
        "variants": provenance,
        "campaign_provenance": campaign_provenance,
        "candidate_change": {
            "description": (
                "Keep exact term/declaration/top-level interning; omit the "
                "separate pruning-index interning traversal."
            ),
            "source_diff": [
                "M src/smtencoding/FStarC.SMTEncoding.Encode.fst",
                "M src/smtencoding/FStarC.SMTEncoding.Sharing.fst",
            ],
        },
        "fresh_graph_profiles": profiles,
        "end_to_end": end_to_end,
        "ordinary_controls": ordinary,
        "dependent_loading": dependent,
        "artifacts": artifacts,
        "validation": {
            "candidate_build": "passed",
            "candidate_boot_diff": "passed",
            "BvBinaryOps": "passed",
            "ClassicalSugar": "passed",
            "structural_comparisons": [
                "master vs interning BV: equal",
                "master vs candidate BV: equal",
                "master vs interning UInt: equal",
                "master vs candidate UInt: equal",
            ],
            "structural_scope": (
                "stage1, typechecking result/index values, and declarations; "
                "compiler-specific dependency digests ignored"
            ),
        },
        "commands": commands,
        "limitations": [
            "Intrusive profile runs are separate from lightweight production runs.",
            "The UInt major-heap high-water remains threshold-sensitive and bimodal for candidate write runs.",
            "Pass-local UInt timing differs by only a few milliseconds and is susceptible to binary-layout noise.",
            "Five-run medians are descriptive and do not establish statistical significance.",
        ],
        "evidence": {
            **{
                name: {"path": str(path), "sha256": digest(path)}
                for name, path in input_files.items()
            },
            **{
                f"dependent-{name}": {
                    "path": str(path),
                    "sha256": digest(path),
                }
                for name, path in dependent_files.items()
            },
        },
    }
    args.output.write_text(json.dumps(output, indent=2) + "\n")


if __name__ == "__main__":
    main()
