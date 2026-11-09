#!/usr/bin/env python3

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path


BINARY = "207e478416f8fae3bd3c3b33914f2a5a9504fbcaf2d3d4745d9cc5914e0734b9"
Z3 = "4da6a0f78424098b600a9112ebb9d8ce45de248a4913c26dd7d472e6dabef6d3"


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trie", type=Path, required=True)
    parser.add_argument("--flat", type=Path, required=True)
    parser.add_argument("--controlled", type=Path, required=True)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--z3", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cpu", type=int, default=16)
    args = parser.parse_args()
    trie = args.trie.resolve()
    binary_source = trie / "stage3/out/bin/fstar.exe"
    if sha256(binary_source) != BINARY or sha256(args.z3.resolve()) != Z3:
        raise RuntimeError("unexpected artifact")
    stage = args.stage.resolve()
    if stage.exists():
        raise RuntimeError("stage path must not exist")
    shutil.copytree(trie / "stage3/out", stage)
    binary = stage / "bin/fstar.exe"
    directories = {
        "original_trie": trie / "tests/bug-reports/closed",
        "original_flat":
            args.flat.resolve() / "tests/bug-reports/closed",
        "controlled": args.controlled.resolve(),
    }
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
        "LC_ALL": "C",
        "LANG": "C",
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
        summary = args.output / f"{name}.strace"
        command = [
            "strace", "-c", "-f", "-o", str(summary),
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
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, timeout=300,
        )
        if process.returncode != 0:
            raise RuntimeError(
                f"{name}: strace failed: {process.stderr}"
            )
        rows.append({
            "fixture": name,
            "cwd": str(cwd),
            "cwd_length": len(str(cwd)),
            "summary": summary.read_text(),
            "summary_sha256": sha256(summary),
            "depend_sha256": sha256(run / ".depend"),
        })
    (args.output / "result.json").write_text(json.dumps({
        "provenance": {
            "cpu": args.cpu,
            "binary_sha256": sha256(binary),
            "z3_sha256": sha256(args.z3.resolve()),
            "fstar_lib": environment["FSTAR_LIB"],
            "script_sha256": sha256(Path(__file__)),
        },
        "rows": rows,
    }, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
