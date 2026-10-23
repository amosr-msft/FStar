#!/usr/bin/env python3

import argparse
import hashlib
import json
import re
import statistics
import subprocess
from pathlib import Path


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def summary(rows, variant, module, mode, keys):
    selected = [
        row for row in rows
        if row["variant"] == variant
        and row["module"] == module
        and row["mode"] == mode
    ]
    result = {}
    for key in keys:
        if any(key not in row for row in selected):
            raise RuntimeError(f"{variant}/{module}/{mode}: missing {key}")
        values = [row[key] for row in selected]
        result[key] = {
            "observations": values,
            "median": statistics.median(values),
            "min": min(values),
            "max": max(values),
        }
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--master", type=Path, required=True)
    parser.add_argument("--interning", type=Path, required=True)
    parser.add_argument("--z3", type=Path, required=True)
    args = parser.parse_args()
    evidence = args.evidence_root.resolve()
    repository = Path(__file__).resolve().parent
    end_to_end = [
        json.loads(line)
        for line in (evidence / "master-comparison/measurements.jsonl").read_text().splitlines()
    ]
    profiles = json.loads((evidence / "master-profiles/measurements.json").read_text())
    ordinary = json.loads((evidence / "master-ordinary/measurements.json").read_text())
    for row in profiles:
        if row["mode"] == "write":
            if "store_values_to_cache_wall_ms" not in row:
                raise RuntimeError("write profile missing storage timing")
        else:
            if "store_values_to_cache_wall_ms" in row:
                raise RuntimeError("no-write profile unexpectedly stored output")
            row["store_values_to_cache_wall_ms"] = 0
    variants = ("master", "interning")
    modules = ("BenchBvLive500", "BenchUIntLive500")
    expected = {
        (variant, module, mode, repeat)
        for variant in variants for module in modules
        for mode in ("write", "no-write") for repeat in range(1, 6)
    }
    actual = {
        (row["variant"], row["module"], row["mode"], row["repeat"])
        for row in end_to_end
    }
    if len(end_to_end) != 40 or actual != expected:
        raise RuntimeError("end-to-end matrix incomplete")
    profile_expected = {
        (variant, module, mode, repeat)
        for variant in variants for module in modules
        for mode in ("write", "no-write") for repeat in range(1, 4)
    }
    profile_actual = {
        (row["variant"], row["module"], row["mode"], row["repeat"])
        for row in profiles
    }
    if len(profiles) != 24 or profile_actual != profile_expected:
        raise RuntimeError("profile matrix incomplete")
    ordinary_expected = {
        (variant, module, mode, repeat)
        for variant in variants
        for module in ("Positivity", "TestWellFoundedRecursion")
        for mode in ("write", "no-write") for repeat in range(1, 6)
    }
    ordinary_actual = {
        (row["variant"], row["module"], row["mode"], row["repeat"])
        for row in ordinary
    }
    if len(ordinary) != 40 or ordinary_actual != ordinary_expected:
        raise RuntimeError("ordinary matrix incomplete")
    roots = {
        "master": args.master.resolve(),
        "interning": args.interning.resolve(),
    }
    commits = {
        "master": "9a10b2ccb1f17064ec496ee315acc6a5f99adf2a",
        "interning": "56e8ac31da209fc56899a225f9a9e6a4b5d37619",
    }
    provenance = {}
    for variant, root in roots.items():
        actual_commit = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
        ).strip()
        if actual_commit != commits[variant]:
            raise RuntimeError(f"{variant}: unexpected commit")
        binary = root / "stage3/out/bin/fstar.exe"
        version = subprocess.check_output([str(binary), "--version"], text=True)
        provenance[variant] = {
            "commit": actual_commit,
            "version": version.splitlines(),
            "binary_sha256": sha256(binary),
            "binary_bytes": binary.stat().st_size,
        }
    patch = subprocess.check_output([
        "git", "-C", str(args.interning), "diff", "--name-status",
        commits["master"], commits["interning"],
    ], text=True).splitlines()
    if patch != [
        "M\tsrc/smtencoding/FStarC.SMTEncoding.Encode.fst",
        "A\tsrc/smtencoding/FStarC.SMTEncoding.Sharing.fst",
    ]:
        raise RuntimeError("unexpected interning patch scope")
    result = {
        "date": "2026-10-23",
        "primary_question": "Pinned current upstream master without interning versus the same master plus only PR #4760's net main interning patch",
        "provenance": provenance,
        "patch_scope": patch,
        "z3": {
            "version": subprocess.check_output([str(args.z3), "--version"], text=True).strip(),
            "sha256": sha256(args.z3),
        },
        "end_to_end": {"repetitions_per_cell": 5, "modules": {}},
        "profiles": {"repetitions_per_cell": 3, "modules": {}},
        "ordinary_controls": {},
        "dependent_loading": {},
        "evidence_sha256": {},
        "validation": {
            "stage3_builds": "pass",
            "interning_boot_diff": "pass",
            "BvBinaryOps": "pass",
            "ClassicalSugar": "pass",
            "artifact_structure": "stage 1, stored tc_result/index, and declarations equal; dependency digests excluded",
        },
    }
    for row in end_to_end:
        executable = next(
            Path(arg) for arg in row["command"]
            if isinstance(arg, str) and arg.endswith("/fstar.exe")
        )
        if sha256(executable) != provenance[row["variant"]]["binary_sha256"]:
            raise RuntimeError("end-to-end row compiler provenance mismatch")
        smt = Path(row["command"][row["command"].index("--smt") + 1])
        if sha256(smt) != result["z3"]["sha256"]:
            raise RuntimeError("end-to-end row solver provenance mismatch")
    end_keys = (
        "wall_seconds", "user_seconds", "system_seconds", "max_rss_kb",
        "fstar_mempeak_bytes", "checked_bytes",
    )
    for module in modules:
        result["end_to_end"]["modules"][module] = {
            variant: {
                mode: summary(end_to_end, variant, module, mode, end_keys)
                for mode in ("write", "no-write")
            }
            for variant in variants
        }
        profile_keys = (
            "wall_seconds", "process_one_decl_ms", "simplify_vc_ms",
            "encode_sig_ms", "encode_signature_wall_ms", "summarize_elts_wall_ms",
            "give_index_to_z3_wall_ms", "store_values_to_cache_wall_ms",
            "z3_aggregate_ms", "checked_files_ms", "allocated_words",
            "promoted_words", "major_words", "minor_collections",
            "major_collections", "top_heap_words",
        )
        result["profiles"]["modules"][module] = {
            variant: {
                mode: summary(profiles, variant, module, mode, profile_keys)
                for mode in ("write", "no-write")
            }
            for variant in variants
        }
        for row in profiles:
            if row["module"] == module and row["variant"] == "interning":
                for key in ("intern_decls_wall_ms", "intern_decls_allocated_words"):
                    if key not in row:
                        raise RuntimeError(f"interning profile missing {key}")
        result["profiles"]["modules"][module]["interning_pass"] = {
            mode: summary(
                profiles, "interning", module, mode,
                ("intern_decls_wall_ms", "intern_decls_allocated_words"),
            )
            for mode in ("write", "no-write")
        }
        interning_rows = [
            row for row in profiles
            if row["module"] == module and row["variant"] == "interning"
        ]
        index_values = []
        for row in interning_rows:
            log = evidence / (
                f"master-profiles/{row['repeat']}-{module}-interning-{row['mode']}.log"
            )
            text = log.read_text()
            match = re.search(
                r"SHARING_ANALYSIS,index,([0-9.]+),([0-9.]+),([0-9.]+)",
                text,
            )
            if not match:
                raise RuntimeError(f"{log}: missing index analysis")
            index_values.append({
                "mode": row["mode"], "repeat": row["repeat"],
                "wall_ms": float(match.group(1)),
                "allocated_words": int(float(match.group(3))),
            })
        result["profiles"]["modules"][module]["interning_index"] = index_values
    for module in ("Positivity", "TestWellFoundedRecursion"):
        result["ordinary_controls"][module] = {
            variant: {
                mode: summary(
                    ordinary, variant, module, mode,
                    ("wall_seconds", "fstar_mempeak_bytes", "checked_bytes"),
                )
                for mode in ("write", "no-write")
            }
            for variant in variants
        }
    for row in ordinary:
        executable = next(
            Path(arg) for arg in row["command"]
            if isinstance(arg, str) and arg.endswith("/fstar.exe")
        )
        if sha256(executable) != provenance[row["variant"]]["binary_sha256"]:
            raise RuntimeError("ordinary row compiler provenance mismatch")
        smt = Path(row["command"][row["command"].index("--smt") + 1])
        if sha256(smt) != result["z3"]["sha256"]:
            raise RuntimeError("ordinary row solver provenance mismatch")
    for variant in variants:
        for representation in ("bv", "uint"):
            for mode in ("metadata", "rooted"):
                path = evidence / f"master-dependent/{variant}-{representation}-{mode}.jsonl"
                rows = [json.loads(line) for line in path.read_text().splitlines()]
                if len(rows) != 5 or {row["repeat"] for row in rows} != set(range(1, 6)):
                    raise RuntimeError(f"{path}: expected five rows")
                if any(
                    row["fstar_sha256"] != provenance[variant]["binary_sha256"]
                    or row["smt_sha256"] != result["z3"]["sha256"]
                    for row in rows
                ):
                    raise RuntimeError(f"{path}: tool provenance mismatch")
                result["dependent_loading"][
                    f"{variant}-{representation}-{mode}"
                ] = {
                    "wall_seconds": {
                        "observations": [row["wall_seconds"] for row in rows],
                        "median": statistics.median(row["wall_seconds"] for row in rows),
                    },
                    "peak_rss_kb": {
                        "observations": [row["peak_rss_kb"] for row in rows],
                        "median": statistics.median(row["peak_rss_kb"] for row in rows),
                    },
                    "command": rows[0]["command"],
                }
    evidence_files = {
        "end_to_end": evidence / "master-comparison/measurements.jsonl",
        "profiles": evidence / "master-profiles/measurements.json",
        "ordinary": evidence / "master-ordinary/measurements.json",
        "master_build": evidence / "master-no-intern-build.log",
        "interning_build": evidence / "master-interning-build.log",
        "boot_diff": evidence / "master-interning-boot-diff.log",
        "runner": repository / "run_master_comparison.py",
        "profile_runner": repository / "run_master_profiles.py",
        "ordinary_runner": repository / "run_master_ordinary.py",
        "instrumenter": repository / "instrument_extracted_analysis.py",
        "dependent_runner": repository / "measure_dependent.py",
        "summarizer": repository / "summarize_master_comparison.py",
        "master_build": evidence / "master-no-intern-build.log",
        "interning_build": evidence / "master-interning-build.log",
        "boot_diff": evidence / "master-interning-boot-diff.log",
        "bv_test": evidence / "master-interning-bv.log",
        "classical_test": evidence / "master-interning-classical.log",
        "structural_comparison": evidence / "master-artifacts/structural.log",
    }
    for variant in variants:
        for representation in ("bv", "uint"):
            for mode in ("metadata", "rooted"):
                key = f"dependent_{variant}_{representation}_{mode}"
                evidence_files[key] = evidence / (
                    f"master-dependent/{variant}-{representation}-{mode}.jsonl"
                )
    result["evidence_sha256"] = {
        name: sha256(path) for name, path in evidence_files.items()
    }
    result["instrumented_binaries"] = {
        variant: sha256(evidence / f"master-instrumented/fstar-{name}.exe")
        for variant, name in (("master", "no-intern"), ("interning", "interning"))
    }
    for row in profiles:
        executable = next(
            Path(arg) for arg in row["command"]
            if isinstance(arg, str) and arg.endswith(".exe")
        )
        if sha256(executable) != result["instrumented_binaries"][row["variant"]]:
            raise RuntimeError("profile row compiler provenance mismatch")
    result["commands"] = {
        "end_to_end_examples": {
            f"{variant}-{module}-{mode}": next(
                row["command"] for row in end_to_end
                if row["variant"] == variant
                and row["module"] == module and row["mode"] == mode
            )
            for variant in variants for module in modules
            for mode in ("write", "no-write")
        },
        "profile_examples": {
            f"{variant}-{module}-{mode}": next(
                row["command"] for row in profiles
                if row["variant"] == variant
                and row["module"] == module and row["mode"] == mode
            )
            for variant in variants for module in modules
            for mode in ("write", "no-write")
        },
        "ordinary_examples": {
            f"{variant}-{module}-{mode}": next(
                row["command"] for row in ordinary
                if row["variant"] == variant
                and row["module"] == module and row["mode"] == mode
            )
            for variant in variants
            for module in ("Positivity", "TestWellFoundedRecursion")
            for mode in ("write", "no-write")
        },
    }
    artifact_root = evidence / "master-artifacts"
    result["artifacts"] = {
        f"{variant}-{representation}": {
            "sha256": sha256(
                artifact_root / variant /
                f"Bench{representation}Live500.fst.checked"
            ),
            "bytes": (
                artifact_root / variant /
                f"Bench{representation}Live500.fst.checked"
            ).stat().st_size,
        }
        for variant in variants for representation in ("Bv", "UInt")
    }
    result["evidence_sha256"]["comparator_source"] = sha256(
        repository / "compare_checked_structure.ml"
    )
    (repository / "MASTER_INTERNING_COMPARISON.json").write_text(
        json.dumps(result, indent=2) + "\n"
    )


if __name__ == "__main__":
    main()
