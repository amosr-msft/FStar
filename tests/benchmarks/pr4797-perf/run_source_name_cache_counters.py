#!/usr/bin/env python3

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path


COMMIT = "f4886d2decd874cd0008e31d6ba07c7da43c5ba4"
COMPILER = "4b568862ebb2a7f2b4b424dc21d3ae953b15171ba19c1cee83291fdc745d6d98"
WORKLOADS = {
    "dependency_bug3207": "tests/bug-reports/closed/Bug3207.fst",
    "normalization": "tests/micro-benchmarks/Normalization.fst",
}


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--worktree", type=Path, required=True)
    parser.add_argument("--fstar", type=Path, required=True)
    parser.add_argument("--z3", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cpu", type=int, default=16)
    args = parser.parse_args()
    worktree = args.worktree.resolve()
    fstar = args.fstar.resolve()
    z3 = args.z3.resolve()
    head = subprocess.check_output(
        ["git", "-C", str(worktree), "rev-parse", "HEAD"], text=True
    ).strip()
    if subprocess.run([
        "git", "-C", str(worktree), "merge-base", "--is-ancestor",
        COMMIT, head,
    ]).returncode != 0:
        raise RuntimeError("unexpected worktree revision")
    if subprocess.run([
        "git", "-C", str(worktree), "diff", "--quiet", COMMIT,
        "--", "src", "ulib", "pulse",
    ]).returncode != 0:
        raise RuntimeError("production sources differ")
    if sha256(fstar) != COMPILER:
        raise RuntimeError("unexpected diagnostic compiler")
    if sha256(z3) != (
        "4da6a0f78424098b600a9112ebb9d8ce45de248a4913c26dd7d472e6dabef6d3"
    ):
        raise RuntimeError("unexpected Z3")
    os.sched_setaffinity(0, {args.cpu})
    environment = os.environ.copy()
    environment.update({"LC_ALL": "C", "LANG": "C"})
    common = [
        str(fstar),
        "--z3version", "5.3.0",
        "--smt", str(z3),
        "--include", str(worktree / "stage2/out/lib/fstar/ulib"),
        "--include", str(worktree / "stage2/out/lib/fstar/ulib.checked"),
    ]
    results = {}
    with tempfile.TemporaryDirectory(
        prefix="source-name-cache-counters-", dir="/workspace/wt11"
    ) as directory:
        temporary = Path(directory)
        for workload, relative in WORKLOADS.items():
            source = (worktree / relative).resolve()
            if workload == "dependency_bug3207":
                command = [*common, "--dep", "full", str(source)]
            else:
                cache = temporary / "cache"
                generated = temporary / "output"
                cache.mkdir()
                generated.mkdir()
                command = [
                    *common,
                    "--silent",
                    "--odir", str(generated),
                    "--cache_dir", str(cache),
                    "--already_cached", "Prims,FStar",
                    "--warn_error", "-321",
                    "--force",
                    "-c", str(source),
                    "-o", str(cache / f"{source.name}.checked"),
                ]
            process = subprocess.run(
                command,
                cwd=source.parent,
                env=environment,
                text=True,
                capture_output=True,
                check=True,
            )
            match = re.search(
                r"PR4797_SOURCE_CACHE calls=([0-9]+) misses=([0-9]+)",
                process.stderr,
            )
            if match is None:
                raise RuntimeError(f"{workload}: counters missing")
            calls = int(match.group(1))
            misses = int(match.group(2))
            results[workload] = {
                "calls": calls,
                "misses": misses,
                "hits": calls - misses,
                "command": command,
                "cwd": str(source.parent),
                "source_sha256": sha256(source),
                "stderr_sha256":
                    hashlib.sha256(process.stderr.encode()).hexdigest(),
            }
    output = {
        "cpu": args.cpu,
        "worktree": str(worktree),
        "worktree_head": head,
        "commit": COMMIT,
        "compiler_path": str(fstar),
        "compiler_sha256": sha256(fstar),
        "z3_path": str(z3),
        "z3_sha256": sha256(z3),
        "results": results,
        "instrumenter_sha256": sha256(
            Path(__file__).resolve().parent
            / "instrument_source_name_cache.py"
        ),
        "script_sha256": sha256(Path(__file__)),
    }
    args.output.write_text(json.dumps(output, indent=2) + "\n")


if __name__ == "__main__":
    main()
