#!/usr/bin/env python3

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fstar", type=Path, required=True)
    parser.add_argument("--z3", type=Path, required=True)
    parser.add_argument("--worktree", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    worktree = args.worktree.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    cases = (
        ("pruning", (), worktree / "tests/tactics/Pruning.fst"),
        (
            "pretyping", ("--ext", "pretyping_axioms"),
            worktree / "tests/tactics/Pruning.fst",
        ),
        (
            "no-ambients", ("--ext", "context_pruning_no_ambients"),
            worktree / "tests/tactics/Pruning.fst",
        ),
        (
            "full-admit", ("--admit_smt_queries", "true"),
            worktree / "tests/micro-benchmarks/BvModelAgreesWithZ3.fst",
        ),
    )
    provenance = {
        "fstar_sha256": sha256(args.fstar),
        "fstar_path": str(args.fstar.resolve()),
        "z3_sha256": sha256(args.z3),
        "z3_path": str(args.z3.resolve()),
        "worktree_path": str(worktree),
        "worktree_commit": subprocess.check_output(
            ["git", "-C", str(worktree), "rev-parse", "HEAD"], text=True
        ).strip(),
        "runner_sha256": sha256(Path(__file__)),
        "sources": {
            name: sha256(source) for name, _, source in cases
        },
    }
    (args.output / "provenance.json").write_text(
        json.dumps(provenance, indent=2) + "\n"
    )
    measurements = []
    for name, options, source in cases:
        command = [
            str(args.fstar.resolve()), "--z3version", "5.3.0",
            "--smt", str(args.z3.resolve()), *options, str(source),
        ]
        log_file = args.output / f"{name}.log"
        with log_file.open("w") as log:
            process = subprocess.run(
                command, cwd=worktree, stdout=log, stderr=subprocess.STDOUT
            )
        text = log_file.read_text()
        if (
            process.returncode != 0
            or not text.rstrip().endswith(
                "All verification conditions discharged successfully"
            )
        ):
            raise RuntimeError(f"{name} failed")
        measurements.append({
            "case": name,
            "options": list(options),
            "command": command,
            "log_sha256": sha256(log_file),
        })
    (args.output / "measurements.json").write_text(
        json.dumps(measurements, indent=2) + "\n"
    )


if __name__ == "__main__":
    main()
