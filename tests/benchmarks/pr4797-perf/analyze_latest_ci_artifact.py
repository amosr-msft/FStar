#!/usr/bin/env python3

import argparse
import hashlib
import json
import math
import re
import statistics
from pathlib import Path


SELECTED = (
    "tests/calc/_cache/Long.fst.checked",
    "tests/hacl/_cache/Lib.Vec.Lemmas.fst.checked",
    "tests/custard/pulse/_cache/CborBoundarySlice.fst.checked",
    (
        "pulse/share/pulse/examples/protocol/calc/_cache/"
        "Calc.Server.Endpoint.fst.checked"
    ),
    (
        "examples/dsls/bool_refinement/_cache/"
        "BoolRefinement.fst.checked"
    ),
    "tests/floats/_output/FloatExtract.krml",
    "tests/extraction/backends/_cache/ExtUIntDivRem.fst.checked",
)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def extract(report, variable):
    match = re.search(
        rf"const {variable} = (\[.*?\]);", report, re.S
    )
    if match is None:
        raise RuntimeError(f"{variable} missing")
    return json.loads(match.group(1))


def value(text, key):
    match = re.search(rf"^{re.escape(key)}\s+([0-9.]+)", text, re.M)
    return float(match.group(1)) if match else None


def parse_raw(root, relative):
    ramon = root / (relative + ".ramon")
    fstarmem = root / (relative + ".fstarmem")
    text = ramon.read_text(errors="replace")
    argv = [
        match.group(1)
        for match in re.finditer(r"^argv\s+\d+ = (.*)$", text, re.M)
    ]
    heap_match = (
        re.search(r"fstar\.mempeak\s+([0-9]+)", fstarmem.read_text())
        if fstarmem.is_file() else None
    )
    root_cpu = value(text, "root.utime") + value(text, "root.stime")
    group_cpu = value(text, "group.total")
    return {
        "cwd": re.search(r"^cwd\s+(.+)$", text, re.M).group(1),
        "argv": argv,
        "root_cpu_seconds": root_cpu,
        "child_cpu_seconds": group_cpu - root_cpu,
        "group_cpu_seconds": group_cpu,
        "wall_seconds": value(text, "walltime"),
        "group_mempeak_mib": value(text, "group.mempeak"),
        "fstar_heap_peak_bytes":
            int(heap_match.group(1)) if heap_match else None,
        "ramon_sha256": sha256(ramon),
        "fstarmem_sha256": sha256(fstarmem) if fstarmem.is_file() else None,
    }


def ranked(rows, key, minimum):
    selected = [row for row in rows if row["base"] >= minimum]
    return sorted(
        selected,
        key=lambda row: (
            row["patch"] / row["base"] - 1
            if key == "ratio" else row["patch"] - row["base"]
        ),
        reverse=True,
    )[:30]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--comment", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    artifact = args.artifact.resolve()
    report_path = artifact / "report.html"
    report = report_path.read_text()
    time_rows = extract(report, "timeData")
    mem_rows = extract(report, "memData")
    by_time = {row["full"]: row for row in time_rows}
    by_mem = {row["full"]: row for row in mem_rows}
    selected = {}
    raw_files = []
    for relative in SELECTED:
        base = parse_raw(artifact / "ramon-files/base", relative)
        head = parse_raw(artifact / "ramon-files/head", relative)
        raw_files.extend(path for path in (
            artifact / "ramon-files/base" / (relative + ".ramon"),
            artifact / "ramon-files/base" / (relative + ".fstarmem"),
            artifact / "ramon-files/head" / (relative + ".ramon"),
            artifact / "ramon-files/head" / (relative + ".fstarmem"),
        ) if path.is_file())
        selected[relative] = {
            "ci_time": by_time[relative],
            "ci_memory_mib": by_mem[relative],
            "base": base,
            "head": head,
        }
    heavy = [
        row for row in time_rows if by_mem[row["full"]]["base"] > 100
        and row["base"] >= 0.1
    ]
    output = {
        "baseline": "9ccacf4a8a392137d5384f8b39500377ebf53f79",
        "head": "31a521edd9ca47c547204cb0609a852206e4342a",
        "matched": len(time_rows),
        "heavy_count": len(heavy),
        "time_geometric_ratio": math.exp(statistics.mean(
            math.log(row["patch"] / row["base"])
            for row in time_rows if row["base"] >= 0.1
        )),
        "heavy_time_geometric_ratio": math.exp(statistics.mean(
            math.log(row["patch"] / row["base"]) for row in heavy
        )),
        "selected": selected,
        "rankings": {
            "time_ratio_baseline_ge_1s": ranked(time_rows, "ratio", 1),
            "time_absolute_baseline_ge_1s":
                ranked(time_rows, "absolute", 1),
            "heavy_time_ratio": sorted(
                heavy,
                key=lambda row: row["patch"] / row["base"] - 1,
                reverse=True,
            )[:30],
            "memory_ratio_baseline_ge_50mib":
                ranked(mem_rows, "ratio", 50),
            "memory_absolute_baseline_ge_50mib":
                ranked(mem_rows, "absolute", 50),
        },
        "provenance": {
            "report_sha256": sha256(report_path),
            "archive_sha256": sha256(args.archive),
            "comment_sha256": sha256(args.comment),
            "run_sha256": sha256(args.run),
            "raw_selected_sha256": hashlib.sha256("".join(
                f"{path.relative_to(artifact)}\0{sha256(path)}\n"
                for path in raw_files
            ).encode()).hexdigest(),
            "script_sha256": sha256(Path(__file__)),
        },
    }
    args.output.write_text(json.dumps(output, indent=2) + "\n")


if __name__ == "__main__":
    main()
