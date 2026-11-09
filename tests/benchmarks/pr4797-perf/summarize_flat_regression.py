#!/usr/bin/env python3

import argparse
import hashlib
import json
import statistics
from pathlib import Path


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_rows(directory):
    return [
        json.loads(line)
        for line in (directory / "measurements.jsonl").read_text().splitlines()
    ]


def medians(rows, labels, fields):
    result = {}
    for label, predicate in labels.items():
        selected = [row for row in rows if predicate(row)]
        result[label] = {
            field: statistics.median(row[field] for row in selected)
            for field in fields
        }
        result[label]["observations"] = len(selected)
    return result


def paired(rows, label, left, right, fields):
    by_key = {(row["repeat"], label(row)): row for row in rows}
    repeats = sorted({row["repeat"] for row in rows})
    result = {}
    for field in fields:
        deltas = [
            by_key[repeat, right][field] - by_key[repeat, left][field]
            for repeat in repeats
        ]
        result[field] = {
            "deltas": deltas,
            "median": statistics.median(deltas),
            "mean": statistics.mean(deltas),
            "right_higher": sum(delta > 0 for delta in deltas),
            "minimum": min(deltas),
            "maximum": max(deltas),
        }
    return result


def normalized_depend_sha256(path):
    lines = [
        line for line in path.read_text().splitlines()
        if not line.startswith("# Hash:")
    ]
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--standalone", type=Path, required=True)
    parser.add_argument("--staged-matrix", type=Path, required=True)
    parser.add_argument("--staged-pair", type=Path, required=True)
    parser.add_argument("--cwd-matrix", type=Path, required=True)
    parser.add_argument("--rusage", type=Path, required=True)
    parser.add_argument("--flatcopy-rusage", type=Path, required=True)
    parser.add_argument("--strace", type=Path, required=True)
    parser.add_argument("--phase", type=Path, required=True)
    parser.add_argument("--staged-smoke", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    staged_pair_rows = load_rows(args.staged_pair)
    cwd_matrix_rows = load_rows(args.cwd_matrix)
    rusage_rows = load_rows(args.rusage)
    flatcopy_rows = load_rows(args.flatcopy_rusage)
    staged_matrix_rows = load_rows(args.staged_matrix)
    staged_pair_summary = {
        "absolute": medians(
            staged_pair_rows,
            {
                variant: (
                    lambda row, variant=variant:
                    row["variant"] == variant
                )
                for variant in ("trie", "flat")
            },
            (
                "root_cpu_seconds", "child_cpu_seconds",
                "wall_seconds", "peak_group_rss_bytes",
            ),
        ),
        "paired_flat_minus_trie": paired(
            staged_pair_rows, lambda row: row["variant"],
            "trie", "flat",
            (
                "root_cpu_seconds", "child_cpu_seconds",
                "wall_seconds", "peak_group_rss_bytes",
            ),
        ),
    }
    cwd_matrix_summary = medians(
        cwd_matrix_rows,
        {
            f"{binary}_binary_{cwd}_cwd": (
                lambda row, binary=binary, cwd=cwd:
                row["binary"] == binary and row["cwd_variant"] == cwd
            )
            for binary in ("trie", "flat")
            for cwd in ("trie", "flat")
        },
        ("root_cpu_seconds", "wall_seconds", "peak_group_rss_bytes"),
    )
    rusage_summary = {}
    for name, rows in (
        ("controlled", rusage_rows),
        ("flatcopy", flatcopy_rows),
    ):
        rusage_summary[name] = {}
        for fixture in sorted({row["fixture"] for row in rows}):
            selected = [row for row in rows if row["fixture"] == fixture]
            rusage_summary[name][fixture] = {
                field: statistics.median(
                    row["usage"][field] for row in selected
                )
                for field in selected[0]["usage"]
            }
            rusage_summary[name][fixture]["wall_seconds"] = (
                statistics.median(
                    row["wall_seconds"] for row in selected
                )
            )
    phase = json.loads((args.phase / "result.json").read_text())
    manifests = {}
    for name in phase["manifests"]:
        path = args.phase / f"{name}.roots"
        lines = path.read_text().splitlines()
        manifests[name] = {
            **phase["manifests"][name],
            "file_count": sum(line.startswith("FILE\t") for line in lines),
            "root_count": sum(line.startswith("ROOT-") for line in lines),
        }
    smoke_trie = (
        args.staged_smoke / "1-trie-binary-trie-checked.depend"
    )
    smoke_flat = (
        args.staged_smoke / "1-flat-binary-trie-checked.depend"
    )
    result = {
        "summarizer_sha256": sha256(Path(__file__)),
        "standalone_evidence": {
            "sha256": sha256(args.standalone),
            "result": json.loads(args.standalone.read_text()),
        },
        "staged_pair": {
            "provenance": json.loads(
                (args.staged_pair / "provenance.json").read_text()
            ),
            "measurements_sha256": sha256(
                args.staged_pair / "measurements.jsonl"
            ),
            "rows": staged_pair_rows,
            "summary": staged_pair_summary,
        },
        "crossed_binary_checked_matrix": {
            "provenance": json.loads(
                (args.staged_matrix / "provenance.json").read_text()
            ),
            "measurements_sha256": sha256(
                args.staged_matrix / "measurements.jsonl"
            ),
            "rows": staged_matrix_rows,
            "summary": medians(
                staged_matrix_rows,
                {
                    f"{binary}_binary_{checked}_checked": (
                        lambda row, binary=binary, checked=checked:
                        row["binary"] == binary
                        and row["checked"] == checked
                    )
                    for binary in ("trie", "flat")
                    for checked in ("trie", "flat")
                },
                ("root_cpu_seconds", "wall_seconds"),
            ),
        },
        "binary_cwd_matrix": {
            "provenance": json.loads(
                (args.cwd_matrix / "provenance.json").read_text()
            ),
            "measurements_sha256": sha256(
                args.cwd_matrix / "measurements.jsonl"
            ),
            "rows": cwd_matrix_rows,
            "summary": cwd_matrix_summary,
        },
        "rusage": {
            "summary": rusage_summary,
            "controlled": {
                "provenance": json.loads(
                    (args.rusage / "provenance.json").read_text()
                ),
                "measurements_sha256": sha256(
                    args.rusage / "measurements.jsonl"
                ),
                "rows": rusage_rows,
            },
            "flatcopy": {
                "provenance": json.loads(
                    (args.flatcopy_rusage / "provenance.json").read_text()
                ),
                "measurements_sha256": sha256(
                    args.flatcopy_rusage / "measurements.jsonl"
                ),
                "rows": flatcopy_rows,
            },
        },
        "strace": json.loads((args.strace / "result.json").read_text()),
        "root_manifests": {
            "provenance": phase["provenance"],
            "summary": manifests,
        },
        "semantic_output": {
            "trie_sha256": sha256(smoke_trie),
            "flat_sha256": sha256(smoke_flat),
            "trie_normalized_sha256":
                normalized_depend_sha256(smoke_trie),
            "flat_normalized_sha256":
                normalized_depend_sha256(smoke_flat),
            "known_difference": (
                "compiler hash header; normalized bodies are identical"
            ),
        },
        "limitations": [
            "Built-in dependency profiling emitted no component records.",
            "perf remains unavailable because perf_event_paranoid is 4.",
            "strace syscall counts match, but syscall timing under tracing is perturbing.",
            "The original-worktree system-time difference is localized to filesystem/path state, not a specific kernel directory structure.",
        ],
    }
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n"
    )


if __name__ == "__main__":
    main()
