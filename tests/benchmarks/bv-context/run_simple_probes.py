#!/usr/bin/env python3

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path


PROBES = (
    ("baseline", 2048, ()),
    ("no-ambients", 2048, ("--ext", "context_pruning_no_ambients")),
    ("admit", 4096, ("--admit_smt_queries", "true")),
    ("lax", 4096, ("--lax",)),
)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def elapsed_seconds(text):
    fields = re.search(
        r"Elapsed \(wall clock\) time.*: ([0-9:.]+)$", text, re.M
    ).group(1).split(":")
    seconds = float(fields[-1])
    if len(fields) >= 2:
        seconds += 60 * int(fields[-2])
    if len(fields) == 3:
        seconds += 3600 * int(fields[-3])
    return seconds


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fstar", type=Path, required=True)
    parser.add_argument("--z3", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    generated = args.output / "generated"
    generated.mkdir(parents=True, exist_ok=True)
    results = args.output / "measurements.jsonl"
    provenance = {
        "fstar_sha256": sha256(args.fstar),
        "z3_sha256": sha256(args.z3),
        "generator_sha256": sha256(root / "generate_simple.py"),
        "runner_sha256": sha256(Path(__file__)),
        "probe_plan": [
            {"probe": probe, "count": count, "options": list(options)}
            for probe, count, options in PROBES
        ],
    }
    provenance_file = args.output / "provenance.json"
    provenance_v1 = args.output / "provenance-v1.json"
    if provenance_file.exists():
        existing = json.loads(provenance_file.read_text())
        if existing != provenance:
            old_keys = {"fstar_sha256", "z3_sha256", "generator_sha256"}
            can_migrate = (
                not provenance_v1.exists()
                and set(existing) == old_keys
                and all(existing[key] == provenance[key] for key in old_keys)
            )
            if not can_migrate:
                raise RuntimeError("incompatible provenance")
            plan = {
                probe: (count, list(options))
                for probe, count, options in PROBES
            }
            if results.exists():
                for line in results.read_text().splitlines():
                    row = json.loads(line)
                    if row["probe"] not in plan:
                        raise RuntimeError("existing probe is absent from plan")
                    count, options = plan[row["probe"]]
                    source = generated / f"SimpleAgreement{count}.fst"
                    if (
                        row["count"] != count
                        or row["options"] != options
                        or not source.exists()
                        or sha256(source) != row["source_sha256"]
                    ):
                        raise RuntimeError("existing probe failed migration")
            shutil.copyfile(provenance_file, provenance_v1)
            provenance_file.write_text(json.dumps(provenance, indent=2) + "\n")
    else:
        provenance_file.write_text(json.dumps(provenance, indent=2) + "\n")
    completed = set()
    if results.exists():
        for line in results.read_text().splitlines():
            completed.add(json.loads(line)["probe"])
    for probe, count, options in PROBES:
        if probe in completed:
            continue
        source = generated / f"SimpleAgreement{count}.fst"
        if not source.exists():
            subprocess.run([
                "python", str(root / "generate_simple.py"),
                "--output", str(generated), "--count", str(count),
            ], check=True)
        log_file = args.output / f"{probe}.log"
        time_file = args.output / f"{probe}.time"
        command = [
            "/usr/bin/time", "-v", "-o", str(time_file),
            str(args.fstar), "--z3version", "5.3.0", "--smt", str(args.z3),
            "--timing", "--query_stats", *options, str(source),
        ]
        with log_file.open("w") as log:
            process = subprocess.run(
                command, stdout=log, stderr=subprocess.STDOUT
            )
        if process.returncode != 0:
            raise RuntimeError(f"{probe} failed; see {log_file}")
        text = log_file.read_text()
        times = [
            int(value)
            for value in re.findall(
                r"agreement_[0-9]+, profiled "
                r"FStarC\.TypeChecker\.Tc\.process_one_decl:\s+([0-9]+) ms",
                text,
            )
        ]
        queries = [
            (float(seconds), float(rlimit))
            for seconds, rlimit in re.findall(
                r"Query-stats \([^,]+\.agreement_[0-9]+, 1\).*?"
                r"succeeded in ([0-9.]+) seconds.*?used rlimit ([0-9.]+)",
                text,
            )
        ]
        if len(times) != count:
            raise RuntimeError(f"{probe}: expected {count} timings")
        time_text = time_file.read_text()
        row = {
            "probe": probe,
            "count": count,
            "options": list(options),
            "source_sha256": sha256(source),
            "wall_seconds": elapsed_seconds(time_text),
            "max_rss_kb": int(re.search(
                r"Maximum resident set size \(kbytes\): ([0-9]+)$",
                time_text, re.M,
            ).group(1)),
            "decl_ms_sum": sum(times),
            "decl_ms_first": times[0],
            "decl_ms_median": sorted(times)[len(times) // 2],
            "decl_ms_last": times[-1],
            "query_count": len(queries),
            "z3_reported_seconds": sum(seconds for seconds, _ in queries),
            "rlimit_last": queries[-1][1] if queries else None,
            "command": command,
        }
        with results.open("a") as stream:
            stream.write(json.dumps(row, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())


if __name__ == "__main__":
    main()
