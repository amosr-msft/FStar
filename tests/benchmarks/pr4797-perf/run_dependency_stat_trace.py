#!/usr/bin/env python3

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
from collections import Counter
from pathlib import Path


BINARY = "207e478416f8fae3bd3c3b33914f2a5a9504fbcaf2d3d4745d9cc5914e0734b9"
Z3 = "4da6a0f78424098b600a9112ebb9d8ce45de248a4913c26dd7d472e6dabef6d3"
PATH_PATTERN = re.compile(
    r'newfstatat\([^,]+, "((?:[^"\\]|\\.)*)"[^=]*= (-?\d+)'
)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def decode(value):
    return bytes(value, "utf-8").decode("unicode_escape")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trie", type=Path, required=True)
    parser.add_argument("--flat", type=Path, required=True)
    parser.add_argument("--fresh", type=Path, required=True)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--z3", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cpu", type=int, default=16)
    args = parser.parse_args()
    trie = args.trie.resolve()
    binary_source = trie / "stage3/out/bin/fstar.exe"
    if sha256(binary_source) != BINARY or sha256(args.z3.resolve()) != Z3:
        raise RuntimeError("unexpected binary or Z3")
    directories = {
        "original_trie": trie / "tests/bug-reports/closed",
        "original_flat":
            args.flat.resolve() / "tests/bug-reports/closed",
        "fresh_flat_copy": args.fresh.resolve(),
    }
    stage = args.stage.resolve()
    if stage.exists():
        raise RuntimeError("stage path must not exist")
    shutil.copytree(trie / "stage3/out", stage)
    binary = stage / "bin/fstar.exe"
    sources = [
        path.name
        for pattern in ("*.fst", "*.fsti")
        for path in sorted(directories["original_trie"].glob(pattern))
    ]
    args.output.mkdir(parents=True, exist_ok=True)
    if any(args.output.iterdir()):
        raise RuntimeError("output must be empty")
    os.sched_setaffinity(0, {args.cpu})
    environment = os.environ.copy()
    environment.update({
        "LC_ALL": "C", "LANG": "C",
        "FSTAR_LIB": str((stage / "lib/fstar").resolve()),
    })
    rows = []
    for name, cwd in directories.items():
        run = stage / "run"
        if run.exists():
            shutil.rmtree(run)
        cache = run / "cache"
        generated = run / "output"
        cache.mkdir(parents=True)
        generated.mkdir()
        trace = args.output / f"{name}.newfstatat"
        command = [
            "strace", "-f", "-s", "1024", "-e", "trace=newfstatat",
            "-o", str(trace),
            str(binary), "--z3version", "5.3.0",
            "--smt", str(args.z3.resolve()), "--silent",
            "--odir", str(generated), "--cache_dir", str(cache),
            "--already_cached", "Prims,FStar",
            "--warn_error", "-321", "--warn_error", "-240",
            "--dep", "full", *sources,
            "-o", str(run / ".depend"),
        ]
        process = subprocess.run(
            command, cwd=cwd, env=environment,
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            text=True, timeout=300,
        )
        if process.returncode != 0:
            raise RuntimeError(f"{name}: {process.stderr}")
        successes = Counter()
        failures = Counter()
        for line in trace.read_text(errors="replace").splitlines():
            match = PATH_PATTERN.search(line)
            if match is None:
                continue
            path = decode(match.group(1))
            target = successes if match.group(2) == "0" else failures
            target[path] += 1
        failure_parents = Counter()
        failure_parent_paths = {}
        for path, count in failures.items():
            parent = str(Path(path).parent)
            failure_parents[parent] += count
            failure_parent_paths.setdefault(parent, set()).add(path)
        rows.append({
            "fixture": name,
            "cwd": str(cwd),
            "trace_sha256": sha256(trace),
            "trace_bytes": trace.stat().st_size,
            "parsed_successes": sum(successes.values()),
            "parsed_failures": sum(failures.values()),
            "unique_success_paths": len(successes),
            "unique_failure_paths": len(failures),
            "top_success_paths": successes.most_common(30),
            "top_failure_paths": failures.most_common(30),
            "failure_parent_counts": failure_parents.most_common(30),
            "failure_parent_unique_paths": sorted(
                (
                    parent, len(paths)
                )
                for parent, paths in failure_parent_paths.items()
            ),
            "depend_sha256": sha256(run / ".depend"),
        })
    (args.output / "result.json").write_text(json.dumps({
        "provenance": {
            "cpu": args.cpu,
            "binary_sha256": sha256(binary),
            "fstar_lib": environment["FSTAR_LIB"],
            "z3_sha256": sha256(args.z3.resolve()),
            "script_sha256": sha256(Path(__file__)),
        },
        "rows": rows,
    }, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
