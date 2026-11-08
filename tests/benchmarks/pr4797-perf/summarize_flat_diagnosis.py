#!/usr/bin/env python3

import argparse
import hashlib
import json
import statistics
import subprocess
from pathlib import Path


EXPECTED = {
    "incumbent": (
        "fca8b319b4aaac348a8bed0689bb90043719f9e739f4e13e2a19ca4b10775873"
    ),
    "flat": (
        "1fc100866a296007072c04a6750ad4100563bdfb5fb8588cbd5370b36996acce"
    ),
}


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rows(directory):
    return [
        json.loads(line)
        for line in (directory / "measurements.jsonl").read_text().splitlines()
    ]


def summarize_modes(observations):
    by_key = {
        (row["repeat"], row["mode"]): row for row in observations
    }
    repeats = sorted({row["repeat"] for row in observations})
    result = {"absolute": {}}
    for mode in ("trie", "flat"):
        selected = [row for row in observations if row["mode"] == mode]
        result["absolute"][mode] = {
            "root_cpu_seconds": statistics.median(
                row["root_cpu_seconds"] for row in selected
            ),
            "group_cpu_seconds": statistics.median(
                row["root_cpu_seconds"] + row["child_cpu_seconds"]
                for row in selected
            ),
            "child_cpu_seconds": statistics.median(
                row["child_cpu_seconds"] for row in selected
            ),
            "wall_seconds": statistics.median(
                row["wall_seconds"] for row in selected
            ),
            "sampled_group_rss_bytes": statistics.median(
                row["peak_group_rss_bytes"] for row in selected
            ),
            "fstar_heap_peak_bytes": (
                statistics.median(
                    row["fstar_heap_peak_bytes"] for row in selected
                )
                if all(
                    row.get("fstar_heap_peak_bytes") is not None
                    for row in selected
                )
                else None
            ),
        }
    paired = {}
    for metric in (
        "root_cpu_seconds", "child_cpu_seconds", "wall_seconds",
        "peak_group_rss_bytes",
    ):
        deltas = [
            by_key[repeat, "flat"][metric] - by_key[repeat, "trie"][metric]
            for repeat in repeats
        ]
        paired[metric] = {
            "deltas": deltas,
            "median": statistics.median(deltas),
            "mean": statistics.mean(deltas),
            "flat_higher": sum(delta > 0 for delta in deltas),
        }
    result["paired_flat_minus_trie"] = paired
    return result


def summarize_diagnostics(observations):
    result = {}
    for mode in ("trie", "flat"):
        selected = [row for row in observations if row["mode"] == mode]
        names = selected[0]["diagnostic"]
        result[mode] = {
            name: statistics.median(
                float(row["diagnostic"][name]) for row in selected
            )
            for name in names
            if name != "reported_mode"
        }
    return result


def symbols(binary):
    output = subprocess.check_output(
        ["nm", "-n", str(binary)], text=True, errors="replace"
    )
    modules = (
        "camlFStarC_Find__code_begin",
        "camlFStarC_Parser_Dep__code_begin",
        "camlFStarC_TypeChecker_TcTerm__code_begin",
        "camlFStarC_Main__code_begin",
    )
    result = {}
    for line in output.splitlines():
        fields = line.split()
        if len(fields) >= 3 and fields[-1] in modules:
            result[fields[-1]] = {
                "hex": fields[0],
                "integer": int(fields[0], 16),
            }
    sized = subprocess.check_output(
        ["nm", "-S", "--size-sort", str(binary)],
        text=True,
        errors="replace",
    )
    for line in sized.splitlines():
        fields = line.split()
        if len(fields) >= 4 and fields[-1] == "camlFStarC_Find__entry":
            result["camlFStarC_Find__entry_size"] = {
                "hex": fields[1],
                "integer": int(fields[1], 16),
            }
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--plain", type=Path, required=True)
    parser.add_argument("--timed", type=Path, required=True)
    parser.add_argument("--variant-evidence", type=Path, required=True)
    parser.add_argument("--incumbent-binary", type=Path, required=True)
    parser.add_argument("--flat-binary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    binaries = {
        "incumbent": args.incumbent_binary.resolve(),
        "flat": args.flat_binary.resolve(),
    }
    for name, binary in binaries.items():
        if sha256(binary) != EXPECTED[name]:
            raise RuntimeError(f"{name}: unexpected binary")
    campaigns = {}
    for campaign_name, root in (
        ("plain_same_binary", args.plain.resolve()),
        ("timed_same_binary", args.timed.resolve()),
    ):
        campaigns[campaign_name] = {}
        for kind in ("dependency", "long"):
            directory = root / kind
            observations = rows(directory)
            campaign = {
                "provenance": json.loads(
                    (directory / "provenance.json").read_text()
                ),
                "measurements_sha256": sha256(
                    directory / "measurements.jsonl"
                ),
                "rows": observations,
                "summary": summarize_modes(observations),
            }
            if campaign_name != "plain_same_binary":
                campaign["diagnostics"] = summarize_diagnostics(
                    observations
                )
            campaigns[campaign_name][kind] = campaign
    variant = json.loads(args.variant_evidence.read_text())
    incumbent_symbols = symbols(binaries["incumbent"])
    flat_symbols = symbols(binaries["flat"])
    shifts = {
        name: (
            flat_symbols[name]["integer"]
            - incumbent_symbols[name]["integer"]
        )
        for name in incumbent_symbols
        if name.endswith("__code_begin") and name in flat_symbols
    }
    args.output.write_text(json.dumps({
        "summarizer_sha256": sha256(Path(__file__)),
        "profiler_restriction": {
            "tool": "perf",
            "result": "no supported events",
            "perf_event_paranoid": 4,
            "policy": "permissions were not changed",
        },
        "campaigns": campaigns,
        "separate_binary_evidence": {
            "path": str(args.variant_evidence.resolve()),
            "sha256": sha256(args.variant_evidence),
            "primary_dependency":
                variant["campaigns"]["dependency"]["summary"][
                    "bug-reports-depend"
                ],
            "primary_long":
                variant["campaigns"]["checked"]["summary"]["long"],
            "rebuild_dependency":
                variant["rebuild_control"]["dependency"]["summary"][
                    "bug-reports-depend"
                ],
            "rebuild_long":
                variant["rebuild_control"]["checked"]["summary"]["long"],
        },
        "native_layout": {
            "binaries": {
                name: {
                    "path": str(binary),
                    "sha256": sha256(binary),
                    "bytes": binary.stat().st_size,
                    "symbols": (
                        incumbent_symbols if name == "incumbent"
                        else flat_symbols
                    ),
                }
                for name, binary in binaries.items()
            },
            "flat_minus_incumbent_code_address_bytes": shifts,
        },
    }, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
