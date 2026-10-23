#!/usr/bin/env python3

import argparse
import hashlib
import json
import statistics
import subprocess
from pathlib import Path


def read_rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def observations(rows, field):
    values = [row[field] for row in rows]
    return {
        "observations": values,
        "median": statistics.median(values),
        "min": min(values),
        "max": max(values),
    }


def grouped(rows, fields):
    groups = {}
    for row in rows:
        key = tuple(row[field] for field in fields)
        groups.setdefault(key, []).append(row)
    return groups


def boundary(row, name):
    return next(item for item in row["snapshots"] if item["name"] == name)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--master", type=Path, required=True)
    parser.add_argument("--interning", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    evidence_files = {
        "matched": args.evidence_root / "uint-heap-diagnostics-valid/measurements.jsonl",
        "liveness": args.evidence_root / "uint-heap-liveness/measurements.jsonl",
        "cross_dependencies": args.evidence_root / "uint-heap-cross/measurements.jsonl",
        "bv_liveness": args.evidence_root / "bv-heap-liveness/measurements.jsonl",
        "file_phases": args.evidence_root / "uint-decl-phases-v2/measurements.jsonl",
        "declaration_phases": args.evidence_root / "uint-decl-phases-v2/measurements.jsonl",
        "after_cache_gc": args.evidence_root / "uint-after-cache-gc/measurements.jsonl",
    }
    rows = {name: read_rows(path) for name, path in evidence_files.items()}
    matched_uint = [
        row for row in rows["matched"]
        if row["analysis_mode"] == "lightweight"
        and row["module"] == "BenchUIntLive500"
    ]
    matched_bv = [
        row for row in rows["matched"]
        if row["analysis_mode"] == "lightweight"
        and row["module"] == "BenchBvLive500"
    ]

    matched = {}
    for key, group in grouped(matched_uint, ("variant", "mode")).items():
        variant, mode = key
        matched.setdefault(variant, {})[mode] = {
            field: observations(group, field)
            for field in ("fstar_mempeak_bytes", "max_rss_kb", "wall_seconds")
        }

    liveness = {}
    for row in rows["liveness"]:
        liveness.setdefault(row["variant"], {})[row["mode"]] = {
            "encode_signature_before": boundary(row, "encode_signature.before"),
            "encode_signature_after": boundary(row, "encode_signature.after"),
            "after_declaration_interning": (
                boundary(row, "decls.after")
                if row["variant"] == "interning" else None
            ),
            "after_pruning_summary": boundary(row, "summarize_elts.after"),
            "after_index_interning": (
                boundary(row, "index.after")
                if row["variant"] == "interning" else None
            ),
            "reachability": row["reachability"],
        }

    cross = {}
    for key, group in grouped(
        rows["cross_dependencies"], ("variant", "dependency_variant")
    ).items():
        compiler, dependencies = key
        cross[f"{compiler}_compiler__{dependencies}_dependencies"] = {
            "fstar_mempeak_bytes": observations(group, "fstar_mempeak_bytes"),
            "max_rss_kb": observations(group, "max_rss_kb"),
        }

    file_phases = {}
    for row in rows["file_phases"]:
        child = next(
            event for event in row["file_events"]
            if event["phase"] == "cache.after"
            and event["file"] == "BenchUIntChildren.fst"
        )
        file_phases[row["variant"]] = {
            "after_benchmark_child_load": child,
            "before_final_encoding": boundary(row, "encode_signature.before"),
        }

    declaration_phases = {}
    for row in rows["declaration_phases"]:
        events = row["declaration_events"]
        transitions = []
        for index, event in enumerate(events):
            if index == 0 or event["top_heap_words"] != events[index - 1]["top_heap_words"]:
                transitions.append({"event_index": index, **event})
        step_events = [
            event for event in events
            if event["declaration"] == "let step"
        ]
        declaration_phases[row["variant"]] = {
            "event_count": len(events),
            "heap_growth_transitions": transitions,
            "final_step": step_events,
        }

    production_hashes = {}
    for variant, root in (
        ("master", args.master),
        ("interning", args.interning),
    ):
        binary = root / "stage3/out/bin/fstar.exe"
        production_hashes[variant] = {
            "commit": subprocess.check_output(
                ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
            ).strip(),
            "binary_sha256": digest(binary),
        }

    output = {
        "date": "2026-10-23",
        "question": "Mechanism of the UInt Live-500 compile heap regression",
        "production_provenance": production_hashes,
        "gc_control": dict(zip(
            (
                "minor_heap_size_words", "major_heap_increment",
                "space_overhead", "verbose", "max_overhead",
                "stack_limit", "allocation_policy",
            ),
            rows["liveness"][0]["gc_control"],
        )),
        "matched_lightweight_uint": matched,
        "forced_gc_liveness": liveness,
        "crossed_compiler_and_dependency_graphs": cross,
        "file_phase_trace": file_phases,
        "declaration_phase_trace": declaration_phases,
        "bv_control": {
            variant: {
                "fstar_mempeak_bytes": observations(group, "fstar_mempeak_bytes"),
                "max_rss_kb": observations(group, "max_rss_kb"),
            }
            for (variant,), group in grouped(matched_bv, ("variant",)).items()
        },
        "bv_forced_gc_liveness": {
            row["variant"]: {
                "encode_signature_before": boundary(row, "encode_signature.before"),
                "encode_signature_after": boundary(row, "encode_signature.after"),
                "after_declaration_interning": (
                    boundary(row, "decls.after")
                    if row["variant"] == "interning" else None
                ),
                "after_pruning_summary": boundary(row, "summarize_elts.after"),
                "reachability": row["reachability"],
            }
            for row in rows["bv_liveness"]
        },
        "diagnostic_controls": {
            "forced_gc_after_benchmark_child_load": [
                {
                    "variant": row["variant"],
                    "repeat": row["repeat"],
                    "fstar_mempeak_bytes": row["fstar_mempeak_bytes"],
                    "max_rss_kb": row["max_rss_kb"],
                    "before_final_encoding": boundary(
                        row, "encode_signature.before"
                    ),
                }
                for row in rows["after_cache_gc"]
            ],
        },
        "conclusions": {
            "proven": [
                "The normal matched UInt peak repeats at 725590016 bytes on master and 926916608 bytes with main interning.",
                "The higher historical heap capacity is reached during typechecking of the final step declaration, before final encoding or either interning pass.",
                "The declaration and index interning passes reduce live retained data; they do not create the peak.",
                "At the forced-GC boundary before final encoding, interning has fewer live words than master.",
                "Dependency loading itself finishes while both variants still have the same small heap.",
                "The final step performs the same number of minor collections; one fewer completed major collection coincides with the interning process landing in a larger major-heap capacity bucket.",
                "The crossed compiler/dependency campaign is threshold-sensitive and does not cleanly isolate dependency shape: its master/master control shifted to 759144448 bytes.",
            ],
            "inferred": [
                "The regression is an OCaml major-heap growth/high-water effect caused by allocation and collection pacing during typechecking, not a 27.7% increase in reachable compiler data.",
                "Loaded graph shape, executable layout, and diagnostic allocation can perturb the promotion schedule enough to cross a different capacity threshold; their individual contributions remain unresolved.",
            ],
            "limitations": [
                "Intrusive snapshots change the exact capacity bucket, so production peaks and instrumented absolute peaks are not mixed.",
                "The 2x2 compiler/dependency probe is threshold-sensitive: one crossed cell was bimodal.",
                "Production binary hashes were rechecked around the campaign but were not embedded in each legacy measurement row; the runner now rejects resumed rows without matching provenance.",
                "OCAMLRUNPARAM was observed unset before the campaign but was not stored in each legacy measurement row.",
                "No production GC tuning or forced collection is recommended from this diagnostic evidence.",
            ],
        },
        "evidence": {
            name: {"path": str(path), "sha256": digest(path)}
            for name, path in evidence_files.items()
        },
    }
    args.output.write_text(json.dumps(output, indent=2) + "\n")


if __name__ == "__main__":
    main()
