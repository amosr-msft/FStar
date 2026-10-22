#!/usr/bin/env python3

import argparse
import fcntl
import json
import os
import random
import re
import subprocess
from pathlib import Path


WORKLOADS = {
    "normbudget": {
        "cwd": "tests/custard",
        "target": "_output/NormBudget.rejected",
        "artifact": "_output/NormBudget.rejected",
        "ci_seconds": {"baseline": 139.381, "sharing": 157.386},
    },
    "bool-refinement": {
        "cwd": "examples/dsls/bool_refinement",
        "target": "_cache/BoolRefinement.fst.checked",
        "artifact": "_cache/BoolRefinement.fst.checked",
        "ci_seconds": {"baseline": 83.096, "sharing": 94.645},
    },
    "dpe-messages-spec": {
        "cwd": "pulse/share/pulse/examples/dice",
        "target": "_cache/DPE.Messages.Spec.fst.checked",
        "artifact": "_cache/DPE.Messages.Spec.fst.checked",
        "ci_seconds": {"baseline": 92.328, "sharing": 104.970},
    },
    "cbor-pulse": {
        "cwd": "pulse/share/pulse/examples/dice",
        "target": "_cache/CBOR.Pulse.fst.checked",
        "artifact": "_cache/CBOR.Pulse.fst.checked",
        "ci_seconds": {"baseline": 20.650, "sharing": 24.720},
    },
    "cbor-boundary-slice": {
        "cwd": "tests/custard/pulse",
        "target": "_cache/CborBoundarySlice.fst.checked",
        "artifact": "_cache/CborBoundarySlice.fst.checked",
        "ci_seconds": {"baseline": 30.570, "sharing": 35.810},
    },
    "rbtree-intrinsic": {
        "cwd": "examples/data_structures",
        "target": "_cache/RBTreeIntrinsic.fst.checked",
        "artifact": "_cache/RBTreeIntrinsic.fst.checked",
        "ci_seconds": {"baseline": 24.280, "sharing": 28.460},
    },
    "cbor-spec-map": {
        "cwd": "pulse/share/pulse/examples/dice",
        "target": "_cache/CBOR.Spec.Map.fst.checked",
        "artifact": "_cache/CBOR.Spec.Map.fst.checked",
        "ci_seconds": {"baseline": 7.260, "sharing": 9.020},
    },
}

TIME_PATTERNS = {
    "elapsed_seconds": r"Elapsed \(wall clock\) time.*: ([0-9:.]+)$",
    "user_seconds": r"User time \(seconds\): ([0-9.]+)$",
    "system_seconds": r"System time \(seconds\): ([0-9.]+)$",
    "max_rss_kb": r"Maximum resident set size \(kbytes\): (\d+)$",
}


def parse_time(path):
    text = path.read_text()
    result = {}
    elapsed = re.search(TIME_PATTERNS["elapsed_seconds"], text, re.MULTILINE)
    if not elapsed:
        raise RuntimeError(f"missing elapsed time in {path}")
    fields = elapsed.group(1).split(":")
    seconds = float(fields[-1])
    if len(fields) >= 2:
        seconds += 60 * int(fields[-2])
    if len(fields) == 3:
        seconds += 3600 * int(fields[-3])
    result["elapsed_seconds"] = seconds
    for key in ("user_seconds", "system_seconds", "max_rss_kb"):
        match = re.search(TIME_PATTERNS[key], text, re.MULTILINE)
        if not match:
            raise RuntimeError(f"missing {key} in {path}")
        result[key] = int(match.group(1)) if key == "max_rss_kb" else float(match.group(1))
    return result


def parse_mem(path):
    match = re.fullmatch(r"fstar\.mempeak (\d+)\n?", path.read_text())
    if not match:
        raise RuntimeError(f"invalid FSTAR_MEM_REPORT in {path}")
    return int(match.group(1))


def completed_keys(path):
    if not path.exists():
        return set()
    keys = set()
    for line in path.read_text().splitlines():
        row = json.loads(line)
        keys.add((row["workload"], row["side"], row["repetition"]))
    return keys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--sharing", type=Path, required=True)
    parser.add_argument("--z3-bin-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--seed", type=int, default=4760)
    parser.add_argument(
        "--workloads", nargs="+", choices=WORKLOADS, default=list(WORKLOADS)
    )
    args = parser.parse_args()

    roots = {"baseline": args.baseline.resolve(), "sharing": args.sharing.resolve()}
    args.output.mkdir(parents=True, exist_ok=True)
    lock_file = (args.output / "campaign.lock").open("w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as error:
        raise RuntimeError(f"another campaign owns {args.output}") from error
    measurements = args.output / "measurements.jsonl"
    done = completed_keys(measurements)
    env = os.environ.copy()
    env["PATH"] = f"{args.z3_bin_dir.resolve()}:{env['PATH']}"

    jobs = []
    for repetition in range(1, args.repetitions + 1):
        batch = [
            (workload, side, repetition)
            for workload in args.workloads
            for side in ("baseline", "sharing")
            if (workload, side, repetition) not in done
        ]
        random.Random(args.seed + repetition).shuffle(batch)
        jobs.extend(batch)

    for workload, side, repetition in jobs:
        spec = WORKLOADS[workload]
        root = roots[side]
        cwd = root / spec["cwd"]
        artifact = cwd / spec["artifact"]
        artifact.unlink(missing_ok=True)
        stem = f"{repetition:02d}-{workload}-{side}"
        log_path = args.output / f"{stem}.log"
        time_path = args.output / f"{stem}.time"
        mem_path = args.output / f"{stem}.fstarmem"
        wrapper = (
            f"FSTAR_MEM_REPORT={mem_path} "
            f"/usr/bin/time -v -o {time_path}"
        )
        command = ["make", spec["target"], f"RAMON={wrapper}"]
        print(f"RUN {stem}", flush=True)
        with log_path.open("w") as log:
            completed = subprocess.run(
                command, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT
            )
        if completed.returncode != 0:
            raise RuntimeError(f"{stem} failed; see {log_path}")
        if not artifact.exists():
            raise RuntimeError(f"{stem} did not produce {artifact}")

        row = {
            "workload": workload,
            "side": side,
            "repetition": repetition,
            "order_seed": args.seed + repetition,
            "root": str(root),
            "cwd": spec["cwd"],
            "target": spec["target"],
            "command": command,
            "ci_seconds": spec["ci_seconds"][side],
            **parse_time(time_path),
            "fstar_mempeak_bytes": parse_mem(mem_path),
            "artifact_bytes": artifact.stat().st_size,
        }
        with measurements.open("a") as output:
            output.write(json.dumps(row, sort_keys=True) + "\n")
            output.flush()
            os.fsync(output.fileno())
        print(
            f"DONE {stem} elapsed={row['elapsed_seconds']:.2f}s "
            f"heap={row['fstar_mempeak_bytes']}",
            flush=True,
        )


if __name__ == "__main__":
    main()
