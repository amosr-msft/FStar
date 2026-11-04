#!/usr/bin/env python3

import argparse
import hashlib
import json
import re
import statistics
from pathlib import Path


SELECTED = {
    "ext-uint-mask":
        "tests/extraction/backends/_cache/ExtUIntMask.fst.checked.ramon",
    "bv-model":
        "tests/micro-benchmarks/_cache/BvModelAgreesWithZ3.fst.checked.ramon",
    "ext-uint-unsigned":
        "tests/extraction/backends/_cache/ExtUIntUnsigned.fst.checked.ramon",
    "calc-protocol":
        "pulse/share/pulse/examples/protocol/calc/_cache/"
        "Calc.Protocol.fst.checked.ramon",
    "tftp-client-log":
        "pulse/share/pulse/examples/protocol/tftp/_cache/"
        "TFTP.Impl.Client.Log.fst.checked.ramon",
    "calc-log":
        "pulse/share/pulse/examples/protocol/calc/_cache/"
        "Calc.Log.fst.checked.ramon",
}
METRICS = (
    "root_cpu_seconds",
    "child_cpu_seconds",
    "wall_seconds",
    "peak_root_rss_bytes",
    "peak_group_rss_bytes",
    "fstar_heap_peak_bytes",
)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ramon_value(text, key):
    match = re.search(rf"^{re.escape(key)}\s+([0-9.]+)", text, re.M)
    if match is None:
        raise RuntimeError(f"{key} missing")
    return float(match.group(1))


def parse_ramon(path):
    text = path.read_text(errors="replace")
    root = ramon_value(text, "root.utime") + ramon_value(
        text, "root.stime"
    )
    group = ramon_value(text, "group.total")
    argv = [
        match.group(1)
        for match in re.finditer(r"^argv\s+\d+ = (.*)$", text, re.M)
    ]
    return {
        "root_cpu_seconds": root,
        "child_cpu_seconds": group - root,
        "group_cpu_seconds": group,
        "wall_seconds": ramon_value(text, "walltime"),
        "group_mempeak_mib": ramon_value(text, "group.mempeak"),
        "cwd": re.search(r"^cwd\s+(.+)$", text, re.M).group(1),
        "argv": argv,
        "sha256": sha256(path),
    }

def parse_ci_record(path):
    record = parse_ramon(path)
    heap_path = Path(str(path).removesuffix(".ramon") + ".fstarmem")
    if not heap_path.is_file():
        record["fstar_heap_peak_bytes"] = None
        record["fstarmem_sha256"] = None
        return record
    heap = re.search(
        r"fstar\.mempeak\s+([0-9]+)",
        heap_path.read_text(),
    )
    if heap is None:
        raise RuntimeError(f"heap evidence missing in {heap_path}")
    record["fstar_heap_peak_bytes"] = int(heap.group(1))
    record["fstarmem_sha256"] = sha256(heap_path)
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--pulse-campaign", type=Path)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    campaign = args.campaign.resolve()
    artifact = args.artifact.resolve()
    rows = [
        json.loads(line)
        for line in (campaign / "measurements.jsonl").read_text().splitlines()
    ]
    pulse_campaign = (
        args.pulse_campaign.resolve()
        if args.pulse_campaign is not None
        else None
    )
    if pulse_campaign is not None:
        pulse_rows = [
            json.loads(line)
            for line in (
                pulse_campaign / "measurements.jsonl"
            ).read_text().splitlines()
        ]
        pulse_workloads = {
            "calc-protocol", "tftp-client-log", "calc-log"
        }
        rows = [
            row for row in rows
            if row["workload"] not in pulse_workloads
        ] + pulse_rows
    summary = {}
    for workload, relative in SELECTED.items():
        selected = [row for row in rows if row["workload"] == workload]
        repetitions = max(row["repeat"] for row in selected)
        record = {"repetitions": repetitions}
        for variant in ("base", "head"):
            variant_rows = [
                row for row in selected if row["variant"] == variant
            ]
            if len(variant_rows) != repetitions:
                raise RuntimeError(f"{workload}/{variant}: rows differ")
            record[variant] = {
                metric: {
                    "observations": [row[metric] for row in variant_rows],
                    "median": statistics.median(
                        row[metric] for row in variant_rows
                    ),
                }
                for metric in METRICS
            }
        paired = {}
        for metric in METRICS:
            deltas = []
            for repeat in range(1, repetitions + 1):
                pair = {
                    row["variant"]: row
                    for row in selected
                    if row["repeat"] == repeat
                }
                deltas.append(
                    pair["head"][metric] - pair["base"][metric]
                )
            paired[metric] = {
                "observations": deltas,
                "median": statistics.median(deltas),
                "mean": statistics.mean(deltas),
                "positive": sum(delta > 0 for delta in deltas),
            }
        record["paired_head_minus_base"] = paired
        record["ci"] = {
            variant: parse_ci_record(
                artifact / "ramon-files" / variant / relative
            )
            for variant in ("base", "head")
        }
        record["ci"]["paired_head_minus_base"] = {
            metric: (
                None
                if record["ci"]["head"][metric] is None
                or record["ci"]["base"][metric] is None
                else record["ci"]["head"][metric]
                     - record["ci"]["base"][metric]
            )
            for metric in (
                "root_cpu_seconds",
                "child_cpu_seconds",
                "group_cpu_seconds",
                "wall_seconds",
                "group_mempeak_mib",
                "fstar_heap_peak_bytes",
            )
        }
        summary[workload] = record
    output = {
        "baseline": "c68959fe1f070cd66a5ed2e92965185505f109ce",
        "head": "adbf7292f25542a538910711fef79bf4eb8c0bac",
        "ci_run": 41602245606,
        "campaign": {
            "provenance": json.loads(
                (campaign / "provenance.json").read_text()
            ),
            "measurements_sha256": sha256(
                campaign / "measurements.jsonl"
            ),
            "rows": rows,
        },
        "pulse_campaign": (
            None
            if pulse_campaign is None
            else {
                "provenance": json.loads(
                    (pulse_campaign / "provenance.json").read_text()
                ),
                "measurements_sha256": sha256(
                    pulse_campaign / "measurements.jsonl"
                ),
            }
        ),
        "summary": summary,
        "failed_setup_campaign": {
            "path": "/workspace/wt11/pr4797-latest-outlier-loops",
            "failure": (
                "Pulse seed cache omitted Calc.Log before Calc.Protocol; "
                "campaign stopped and no measurements were reused."
            ),
        },
        "evidence": {
            "report_sha256": sha256(artifact / "report.html"),
            "script_sha256": sha256(Path(__file__)),
        },
        "limitations": [
            "CPU sampling has approximately 10 ms resolution.",
            "CPU affinity does not reserve CPU 16.",
            "Local F* heap capacities differ from the hosted CI regime.",
            "Single-process and process-group RSS are sampled, unlike CI cgroup memory.",
        ],
    }
    args.output.write_text(json.dumps(output, indent=2) + "\n")


if __name__ == "__main__":
    main()
