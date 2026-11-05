#!/usr/bin/env python3

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path


COMMIT = "adbf7292f25542a538910711fef79bf4eb8c0bac"
COMPILER = "380aba953c7ebe0d871ac2a8abc8d514b6bc34bb1ca2310f2685d6edd99f1259"


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--worktree", type=Path, required=True)
    parser.add_argument("--fstar", type=Path, required=True)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cpu", type=int, default=16)
    args = parser.parse_args()
    worktree = args.worktree.resolve()
    fstar = args.fstar.resolve()
    if subprocess.run([
        "git", "-C", str(worktree), "merge-base", "--is-ancestor",
        COMMIT, "HEAD",
    ]).returncode != 0:
        raise RuntimeError("unexpected worktree ancestry")
    if subprocess.run([
        "git", "-C", str(worktree), "diff", "--quiet", COMMIT,
        "--", "src", "ulib", "pulse",
    ]).returncode != 0:
        raise RuntimeError("production sources differ")
    if sha256(fstar) != COMPILER:
        raise RuntimeError("diagnostic compiler differs")
    campaign = args.campaign.resolve()
    rows = [
        json.loads(line)
        for line in (campaign / "measurements.jsonl").read_text().splitlines()
    ]
    row = next(
        row for row in rows
        if row["workload"] == "bug-reports-depend"
        and row["variant"] == "head"
    )
    args.output.mkdir(parents=True, exist_ok=True)
    if any(args.output.iterdir()):
        raise RuntimeError("output must be empty")
    command = list(row["command"])
    command[0] = str(fstar)
    for flag, name, directory in (
        ("--odir", "output", True),
        ("--cache_dir", "cache", True),
        ("-o", ".depend", False),
    ):
        index = command.index(flag) + 1
        path = args.output / name
        if directory:
            path.mkdir()
        command[index] = str(path)
    os.sched_setaffinity(0, {args.cpu})
    log = args.output / "run.log"
    with log.open("w") as stream:
        process = subprocess.run(
            command,
            cwd=row["cwd"],
            stdout=stream,
            stderr=subprocess.STDOUT,
        )
    if process.returncode != 0:
        raise RuntimeError("diagnostic dependency command failed")
    text = log.read_text()
    source = re.search(
        r"PR4797_DEP_SOURCE_NAMES calls=([0-9]+) seconds=([0-9.]+)",
        text,
    )
    relative = re.search(
        r"PR4797_RELATIVE_SOURCE calls=([0-9]+) seconds=([0-9.]+)",
        text,
    )
    if source is None or relative is None:
        raise RuntimeError("diagnostic counters missing")
    result = {
        "cpu": args.cpu,
        "worktree": str(worktree),
        "worktree_head": subprocess.check_output(
            ["git", "-C", str(worktree), "rev-parse", "HEAD"], text=True
        ).strip(),
        "compiler_commit": COMMIT,
        "compiler_path": str(fstar),
        "compiler_sha256": sha256(fstar),
        "command": command,
        "cwd": row["cwd"],
        "source_file_name_calls": int(source.group(1)),
        "source_file_name_seconds": float(source.group(2)),
        "relative_source_path_normalized_calls": int(relative.group(1)),
        "relative_source_path_normalized_seconds":
            float(relative.group(2)),
        "log_sha256": sha256(log),
        "campaign_measurements_sha256": sha256(
            campaign / "measurements.jsonl"
        ),
        "instrumenter_sha256": sha256(
            Path(__file__).resolve().parent
            / "instrument_dependency_source_names.py"
        ),
        "script_sha256": sha256(Path(__file__)),
    }
    (args.output / "result.json").write_text(
        json.dumps(result, indent=2) + "\n"
    )


if __name__ == "__main__":
    main()
