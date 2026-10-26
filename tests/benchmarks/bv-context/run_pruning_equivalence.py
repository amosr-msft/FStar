#!/usr/bin/env python3

import argparse
import hashlib
import json
import os
import re
import shutil
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
    root = Path(__file__).resolve().parent
    worktree = args.worktree.resolve()
    ulib = worktree / "stage2/out/lib/fstar/ulib"
    checked = worktree / "stage2/out/lib/fstar/ulib.checked"
    generated = args.output / "generated"
    if args.output.exists():
        shutil.rmtree(args.output)
    generated.mkdir(parents=True)
    subprocess.run([
        "python", str(root / "generate_simple.py"),
        "--output", str(generated), "--count", "64",
    ], check=True)
    cases = (
        ("simple", generated / "SimpleAgreement64.fst", "SimpleAgreement64"),
        ("scope", root / "PruningCacheScope.fst", "PruningCacheScope"),
        ("pruning", worktree / "tests/tactics/Pruning.fst", "Pruning"),
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
        "prims_checked_sha256": sha256(checked / "Prims.fst.checked"),
        "instrumenter_sha256": sha256(root / "instrument_pruning_reference.py"),
        "runner_sha256": sha256(Path(__file__)),
        "sources": {
            name: sha256(source) for name, source, _ in cases
        },
    }
    (args.output / "provenance.json").write_text(
        json.dumps(provenance, indent=2) + "\n"
    )
    common = [
        "--z3version", "5.3.0", "--smt", str(args.z3.resolve()),
        "--include", str(ulib), "--include", str(checked),
        "--query_stats", "--log_queries",
    ]
    measurements = []
    for name, source, module in cases:
        commands = {}
        environments = {}
        for mode in ("cached", "reference"):
            directory = args.output / f"{name}-{mode}"
            directory.mkdir()
            environment = os.environ.copy()
            if mode == "reference":
                environment["FSTAR_PRUNING_REFERENCE"] = "1"
            command = [str(args.fstar.resolve()), *common, str(source.resolve())]
            with (directory / "run.log").open("w") as log:
                process = subprocess.run(
                    command, cwd=directory, env=environment,
                    stdout=log, stderr=subprocess.STDOUT,
                )
            if process.returncode != 0:
                raise RuntimeError(f"{name}/{mode} failed")
            commands[mode] = command
            environments[mode] = (
                {"FSTAR_PRUNING_REFERENCE": "1"}
                if mode == "reference" else {}
            )
        cached_files = sorted(
            (args.output / f"{name}-cached").glob("queries-*.smt2")
        )
        reference_files = sorted(
            (args.output / f"{name}-reference").glob("queries-*.smt2")
        )
        if (
            not cached_files
            or len(cached_files) != len(reference_files)
            or any(
                left.name != right.name
                or left.read_bytes() != right.read_bytes()
                for left, right in zip(cached_files, reference_files)
            )
        ):
            raise RuntimeError(f"{name}: cached/reference query streams differ")
        combined = b"".join(path.read_bytes() for path in cached_files)
        measurements.append({
            "case": name,
            "module": module,
            "commands": commands,
            "environments": environments,
            "query_files": [path.name for path in cached_files],
            "check_sat_count": sum(
                len(re.findall(rb"\(check-sat\)", path.read_bytes()))
                for path in cached_files
            ),
            "query_stream_bytes": len(combined),
            "identical_query_stream_sha256":
                hashlib.sha256(combined).hexdigest(),
        })
    (args.output / "measurements.json").write_text(
        json.dumps(measurements, indent=2) + "\n"
    )


if __name__ == "__main__":
    main()
