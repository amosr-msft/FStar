#!/usr/bin/env python3

import argparse
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path


COUNTS = (256, 512, 1024, 2048, 4096, 5808)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def elapsed_seconds(text):
    match = re.search(r"Elapsed \(wall clock\) time.*: ([0-9:.]+)$", text, re.M)
    fields = match.group(1).split(":")
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
    parser.add_argument("--timeout", type=int, default=1200)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    generated = args.output / "generated"
    args.output.mkdir(parents=True, exist_ok=True)
    generated.mkdir(exist_ok=True)
    lock = (args.output / "campaign.lock").open("w")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    results = args.output / "measurements.jsonl"
    plan = (
        [(count, 1, 0) for count in COUNTS if count != 5808]
        + [(5808, 64, group) for group in range(64)]
        + [(5808, 1, 0)]
    )
    provenance = {
        "fstar_sha256": sha256(args.fstar),
        "z3_sha256": sha256(args.z3),
        "generator_sha256": sha256(root / "generate_simple.py"),
        "runner_sha256": sha256(Path(__file__)),
        "timeout_seconds": args.timeout,
        "fstar_version": subprocess.check_output(
            [str(args.fstar), "--version"], text=True
        ).strip(),
        "plan": [
            {"count": count, "groups": groups, "group": group}
            for count, groups, group in plan
        ],
    }
    provenance_file = args.output / "provenance.json"
    provenance_v1 = args.output / "provenance-v1.json"
    provenance_v2 = args.output / "provenance-v2.json"
    provenance_v3 = args.output / "provenance-v3.json"
    old_generator = (
        "b3f435feaf570bf3a4424085882cd67a616349e9efb1bb4ed35ae4367e0f6ca8"
    )
    new_generator = (
        "b80798e1ab39085d2ff9cc7d5093d2f58902129455ef1fb05a2c963aa8373d73"
    )
    if provenance_v1.exists():
        provenance["prior_generator_sha256"] = old_generator
    if provenance_file.exists():
        existing = json.loads(provenance_file.read_text())
        if existing != provenance:
            extended_migration = (
                provenance_v1.exists()
                and provenance_v2.exists()
                and not provenance_v3.exists()
                and {
                    key: value for key, value in provenance.items()
                    if key in existing
                } == existing
            )
            if extended_migration:
                expected_keys = set(plan)
                if results.exists():
                    for line in results.read_text().splitlines():
                        row = json.loads(line)
                        key = (row["count"], row["groups"], row["group"])
                        if (
                            key not in expected_keys
                            or f"{args.timeout}s" not in row["command"]
                            or row["command"][row["command"].index("timeout") + 2]
                            != f"{args.timeout}s"
                        ):
                            raise RuntimeError(
                                "existing rows failed extended migration"
                            )
                shutil.copyfile(provenance_file, provenance_v3)
                provenance_file.write_text(
                    json.dumps(provenance, indent=2) + "\n"
                )
                existing = provenance
            if existing == provenance:
                pass
            else:
                migration_base = {
                    key: value for key, value in existing.items()
                    if key != "generator_sha256"
                }
                current_base = {
                    key: value for key, value in provenance.items()
                    if key not in (
                        "generator_sha256", "prior_generator_sha256",
                        "runner_sha256", "timeout_seconds", "fstar_version",
                        "plan",
                    )
                }
                can_migrate = (
                    not provenance_v1.exists()
                    and not provenance_v2.exists()
                    and existing.get("generator_sha256") == old_generator
                    and provenance["generator_sha256"] == new_generator
                    and migration_base == current_base
                )
                if not can_migrate:
                    raise RuntimeError(
                        "output directory has incompatible provenance"
                    )
                if results.exists():
                    for line in results.read_text().splitlines():
                        row = json.loads(line)
                        source = (
                            generated / f"SimpleAgreement{row['count']}.fst"
                        )
                        if (
                            row["groups"] != 1
                            or not source.exists()
                            or sha256(source) != row["source_sha256"]
                        ):
                            raise RuntimeError(
                                "existing rows failed provenance migration"
                            )
                shutil.copyfile(provenance_file, provenance_v1)
                provenance["prior_generator_sha256"] = old_generator
                provenance_v2.write_text(
                    json.dumps(provenance, indent=2) + "\n"
                )
                provenance_file.write_text(
                    json.dumps(provenance, indent=2) + "\n"
                )
    else:
        provenance_file.write_text(json.dumps(provenance, indent=2) + "\n")
    completed = set()
    if results.exists():
        for line in results.read_text().splitlines():
            row = json.loads(line)
            completed.add((row["count"], row["groups"], row["group"]))

    jobs = plan
    for count, groups, group in jobs:
        if (count, groups, group) in completed:
            continue
        if groups == 1:
            source = generated / f"SimpleAgreement{count}.fst"
        else:
            source = generated / f"SimpleAgreement{count}G{group:02d}.fst"
        if not source.exists():
            command = [
                "python", str(root / "generate_simple.py"),
                "--output", str(generated), "--count", str(count),
                "--groups", str(groups),
            ]
            subprocess.run(command, check=True)
        stem = f"{count}-g{groups:02d}-{group:02d}"
        log_file = args.output / f"{stem}.log"
        time_file = args.output / f"{stem}.time"
        command = [
            "/usr/bin/time", "-v", "-o", str(time_file),
            "timeout", "--kill-after=5s", f"{args.timeout}s",
            str(args.fstar), "--z3version", "5.3.0",
            "--smt", str(args.z3), "--timing", "--query_stats",
            str(source),
        ]
        prior_timeout = (
            log_file.exists()
            and time_file.exists()
            and "Exit status: 124" in time_file.read_text()
        )
        if prior_timeout:
            returncode = 124
        else:
            with log_file.open("w") as log:
                process = subprocess.run(
                    command, stdout=log, stderr=subprocess.STDOUT
                )
            returncode = process.returncode
        if returncode not in (0, 124):
            raise RuntimeError(f"{stem} failed; see {log_file}")
        text = log_file.read_text()
        timed = [
            (int(identifier), int(value))
            for identifier, value in re.findall(
                r"agreement_([0-9]+), profiled "
                r"FStarC\.TypeChecker\.Tc\.process_one_decl:\s+([0-9]+) ms",
                text,
            )
        ]
        queries = [
            (int(identifier), float(seconds), float(rlimit))
            for identifier, seconds, rlimit in re.findall(
            r"Query-stats \([^,]+\.agreement_([0-9]+), 1\).*?"
            r"succeeded in ([0-9.]+) seconds.*?used rlimit ([0-9.]+)",
            text,
        )]
        quotient, remainder = divmod(count, groups)
        expected = quotient + (1 if group < remainder else 0)
        start = group * quotient + min(group, remainder)
        completed_ids = [identifier for identifier, _ in timed]
        query_ids = [identifier for identifier, _, _ in queries]
        expected_ids = list(range(start, start + len(timed)))
        if completed_ids != expected_ids or query_ids != expected_ids:
            raise RuntimeError(
                f"{stem}: incomplete rows are not a contiguous matching prefix"
            )
        if returncode == 0 and len(timed) != expected:
            raise RuntimeError(f"{stem}: expected {expected}, got {len(timed)}")
        times = [value for _, value in timed]
        time_text = time_file.read_text()
        row = {
            "status": "success" if returncode == 0 else "timeout",
            "count": count,
            "groups": groups,
            "group": group,
            "declarations": expected,
            "completed_declarations": len(times),
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
            "decl_ms_max": max(times),
            "z3_reported_seconds": sum(seconds for _, seconds, _ in queries),
            "rlimit_last": queries[-1][2],
            "command": command,
        }
        with results.open("a") as stream:
            stream.write(json.dumps(row, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())


if __name__ == "__main__":
    main()
