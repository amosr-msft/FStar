#!/usr/bin/env python3

import argparse
import hashlib
import json
import math
import re
import statistics
from pathlib import Path


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def value(text, key):
    match = re.search(rf"^{re.escape(key)}\s+([0-9.]+)", text, re.M)
    return float(match.group(1)) if match else None


def parse_ramon(path):
    text = path.read_text(errors="replace")
    return {
        "group_cpu": value(text, "group.total"),
        "group_user": value(text, "group.utime"),
        "group_system": value(text, "group.stime"),
        "root_user": value(text, "root.utime"),
        "root_system": value(text, "root.stime"),
        "wall": value(text, "walltime"),
    }


def ratio_summary(rows, key):
    pairs = [
        (row["base"][key], row["head"][key])
        for row in rows
        if row["base"][key] is not None
        and row["head"][key] is not None
        and row["base"][key] > 0
    ]
    ratios = [head / base for base, head in pairs]
    return {
        "rows": len(pairs),
        "geometric_mean_ratio":
            math.exp(sum(math.log(ratio) for ratio in ratios) / len(ratios)),
        "median_change_percent":
            statistics.median((ratio - 1) * 100 for ratio in ratios),
        "total_change_seconds": sum(head - base for base, head in pairs),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    artifact = args.artifact.resolve()
    base = artifact / "ramon-files/base"
    head = artifact / "ramon-files/head"
    report_text = (artifact / "report.html").read_text()
    report_match = re.search(
        r"const timeData = (\[.*?\]);",
        report_text,
        re.S,
    )
    if report_match is None:
        raise RuntimeError("timeData not found in report")
    report_rows = json.loads(report_match.group(1))
    rows = []
    raw_files = []
    missing_raw = []
    for report_row in report_rows:
        relative = Path(report_row["full"] + ".ramon")
        base_path = base / relative
        head_path = head / relative
        if not base_path.is_file() or not head_path.is_file():
            missing_raw.append(str(relative))
            continue
        base_metrics = parse_ramon(base_path)
        head_metrics = parse_ramon(head_path)
        if base_metrics["group_cpu"] is None:
            raise RuntimeError(f"missing CPU evidence for {relative}")
        rows.append({
            "path": str(relative),
            "report": report_row,
            "base": base_metrics,
            "head": head_metrics,
        })
        raw_files.extend((base_path, head_path))
    report_included = [
        row for row in report_rows
        if row["base"] >= 0.1
    ]
    included = [
        row for row in rows
        if row["report"]["base"] >= 0.1
    ]
    child_pairs = []
    for row in included:
        base_child = (
            row["base"]["group_cpu"]
            - row["base"]["root_user"]
            - row["base"]["root_system"]
        )
        head_child = (
            row["head"]["group_cpu"]
            - row["head"]["root_user"]
            - row["head"]["root_system"]
        )
        if base_child > 0.05 and head_child > 0:
            child_pairs.append((base_child, head_child))
    child_ratios = [head_cpu / base_cpu for base_cpu, head_cpu in child_pairs]
    duration_bands = {}
    for lower, upper in (
        (0.1, 0.2),
        (0.2, 0.5),
        (0.5, 1.0),
        (1.0, 2.0),
        (2.0, 5.0),
        (5.0, 20.0),
        (20.0, float("inf")),
    ):
        selected = [
            row for row in report_included
            if lower <= row["base"] < upper
        ]
        duration_bands[f"{lower:g}-{upper:g}"] = {
            "rows": len(selected),
            "median_change_seconds": statistics.median(
                row["patch"] - row["base"]
                for row in selected
            ),
            "median_change_percent": statistics.median(
                (row["patch"] / row["base"] - 1) * 100
                for row in selected
            ),
            "total_change_seconds": sum(
                row["patch"] - row["base"]
                for row in selected
            ),
        }
    report_ratios = [row["patch"] / row["base"] for row in report_included]
    output = {
        "baseline": "c68959fe1f070cd66a5ed2e92965185505f109ce",
        "head": "e2c45ed0c4099f8d27ef0d78641ca8b626f4cdcb",
        "report_matched_rows": len(report_rows),
        "report_included_rows": len(report_included),
        "raw_paired_report_rows": len(rows),
        "raw_analyzable_included_rows": len(included),
        "missing_raw_rows": missing_raw,
        "report_group_cpu": {
            "geometric_mean_ratio": math.exp(
                sum(math.log(ratio) for ratio in report_ratios)
                / len(report_ratios)
            ),
            "median_change_percent": statistics.median(
                (ratio - 1) * 100 for ratio in report_ratios
            ),
            "total_change_seconds": sum(
                row["patch"] - row["base"] for row in report_included
            ),
        },
        "raw_metrics": {
            key: ratio_summary(included, key)
            for key in (
                "group_cpu",
                "group_user",
                "group_system",
                "root_user",
                "root_system",
                "wall",
            )
        },
        "inferred_child_cpu": {
            "rows": len(child_pairs),
            "geometric_mean_ratio": math.exp(
                sum(math.log(ratio) for ratio in child_ratios)
                / len(child_ratios)
            ),
            "median_change_percent":
                statistics.median((ratio - 1) * 100 for ratio in child_ratios),
            "total_change_seconds":
                sum(head_cpu - base_cpu for base_cpu, head_cpu in child_pairs),
        },
        "duration_bands": duration_bands,
        "provenance": {
            "report_sha256": sha256(artifact / "report.html"),
            "raw_file_count": len(raw_files),
            "raw_file_sha256": hashlib.sha256(
                "".join(
                    f"{path.relative_to(artifact)}\0{sha256(path)}\n"
                    for path in raw_files
                ).encode()
            ).hexdigest(),
            "script_sha256": sha256(Path(__file__)),
        },
    }
    args.output.write_text(json.dumps(output, indent=2) + "\n")


if __name__ == "__main__":
    main()
