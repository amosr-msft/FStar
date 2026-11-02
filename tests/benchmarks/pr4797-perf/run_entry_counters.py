#!/usr/bin/env python3

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path


COMMIT = "e2c45ed0c4099f8d27ef0d78641ca8b626f4cdcb"
COMPILER_SHA256 = (
    "ee391eec1e3a83ade4ea74411dd556b81bd1d825ebe8ec07096db766312ba460"
)
CHECKED_TREE = {
    "sha256": "59bf4cada8ec7bd5e9a06576354483ad86c23932d4386ab5311e57a778f549b7",
    "files": 379,
}
WORKLOADS = {
    "dependency_bug3207": "tests/bug-reports/closed/Bug3207.fst",
    "normalization": "tests/micro-benchmarks/Normalization.fst",
    "bv_binary_ops": "tests/micro-benchmarks/BvBinaryOps.fst",
}
SOURCE_SHA256 = {
    "dependency_bug3207":
        "4c7ac63546fdd78ce814f4c5e7b1f6bbcd1e9a3fc332d276b5a6cb94263f5f9a",
    "normalization":
        "4a19c19f2357c92b4fd5254af7f4ff0f20f9ce7ee513244cf54b1717c7e5f895",
    "bv_binary_ops":
        "14797b4b4cc3c679a2ccc4efc39bb5e2f6271be5e70e4c20c91ca738996da0ba",
}


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_sha256(path):
    digest = hashlib.sha256()
    files = sorted(item for item in path.rglob("*") if item.is_file())
    for item in files:
        digest.update(str(item.relative_to(path)).encode())
        digest.update(b"\0")
        digest.update(item.read_bytes())
        digest.update(b"\0")
    return {"sha256": digest.hexdigest(), "files": len(files)}


def parse(stderr):
    source = re.search(
        r"PR4797_COUNTER source_file_name=([0-9]+) seconds=([0-9.]+)",
        stderr,
    )
    ranges = re.search(r"PR4797_COUNTER mk_rng=([0-9]+)", stderr)
    if source is None or ranges is None:
        raise RuntimeError("counter output missing")
    return {
        "source_file_name_calls": int(source.group(1)),
        "source_file_name_seconds": float(source.group(2)),
        "mk_rng_calls": int(ranges.group(1)),
        "counter_lines": [source.group(0), ranges.group(0)],
        "stderr_sha256": hashlib.sha256(stderr.encode()).hexdigest(),
    }


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
        raise RuntimeError("worktree does not descend from PR head")
    if subprocess.run([
        "git", "-C", str(worktree), "diff", "--quiet", COMMIT,
        "--", "src", "ulib", "pulse",
    ]).returncode != 0:
        raise RuntimeError("production sources differ from PR head")
    untracked_production = subprocess.check_output([
        "git", "-C", str(worktree), "ls-files", "--others",
        "--exclude-standard", "--", "src", "ulib", "pulse",
    ], text=True).splitlines()
    if untracked_production:
        raise RuntimeError("untracked production sources present")
    version_process = subprocess.run(
        [str(fstar), "--version"],
        text=True,
        capture_output=True,
        check=True,
    )
    if f"commit={COMMIT}" not in version_process.stdout:
        raise RuntimeError("instrumented compiler source differs")
    if sha256(fstar) != COMPILER_SHA256:
        raise RuntimeError("instrumented compiler binary differs")
    checked_tree = tree_sha256(
        worktree / "stage2/out/lib/fstar/ulib.checked"
    )
    if checked_tree != CHECKED_TREE:
        raise RuntimeError("checked dependency tree differs")
    if sha256(z3) != (
        "4da6a0f78424098b600a9112ebb9d8ce45de248a4913c26dd7d472e6dabef6d3"
    ):
        raise RuntimeError("unexpected Z3")
    os.sched_setaffinity(0, {args.cpu})
    environment = os.environ.copy()
    for name in (
        "FSTAR_LIB",
        "FSTAR_HOME",
        "OCAMLRUNPARAM",
        "CAMLRUNPARAM",
        "LD_PRELOAD",
        "LD_LIBRARY_PATH",
        "OCAMLPATH",
        "CAML_LD_LIBRARY_PATH",
    ):
        environment.pop(name, None)
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
        prefix="pr4797-counters-", dir="/workspace/wt11"
    ) as directory:
        temporary = Path(directory)
        for workload, relative in WORKLOADS.items():
            source = (worktree / relative).resolve()
            if sha256(source) != SOURCE_SHA256[workload]:
                raise RuntimeError(f"{workload}: source differs")
            if workload == "dependency_bug3207":
                command = [*common, "--dep", "full", str(source)]
            else:
                cache = temporary / workload / "cache"
                generated = temporary / workload / "output"
                cache.mkdir(parents=True)
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
            results[workload] = {
                **parse(process.stderr),
                "command": command,
                "cwd": str(source.parent),
                "source_sha256": sha256(source),
                "stdout_sha256":
                    hashlib.sha256(process.stdout.encode()).hexdigest(),
            }
    output = {
        "cpu": args.cpu,
        "worktree": str(worktree),
        "worktree_head": head,
        "compiler_commit": COMMIT,
        "compiler_path": str(fstar),
        "compiler_sha256": sha256(fstar),
        "compiler_version": version_process.stdout.strip(),
        "checked_tree": checked_tree,
        "z3_path": str(z3),
        "z3_sha256": sha256(z3),
        "results": results,
        "instrumenter_sha256": sha256(
            Path(__file__).resolve().parent / "instrument_entry_counters.py"
        ),
        "script_sha256": sha256(Path(__file__)),
    }
    args.output.write_text(json.dumps(output, indent=2) + "\n")


if __name__ == "__main__":
    main()
