#!/usr/bin/env python3

import argparse
import hashlib
import json
import os
import random
import resource
import shutil
import subprocess
import time
from pathlib import Path


BINARY = "207e478416f8fae3bd3c3b33914f2a5a9504fbcaf2d3d4745d9cc5914e0734b9"
Z3 = "4da6a0f78424098b600a9112ebb9d8ce45de248a4913c26dd7d472e6dabef6d3"
FIELDS = (
    "ru_utime", "ru_stime", "ru_maxrss", "ru_minflt", "ru_majflt",
    "ru_inblock", "ru_oublock", "ru_nvcsw", "ru_nivcsw",
)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trie", type=Path, required=True)
    parser.add_argument("--flat", type=Path, required=True)
    parser.add_argument("--short", type=Path, required=True)
    parser.add_argument("--long", type=Path, required=True)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--z3", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--cpu", type=int, default=16)
    parser.add_argument("--seed", type=int, default=5063)
    args = parser.parse_args()
    trie = args.trie.resolve()
    binary_source = trie / "stage3/out/bin/fstar.exe"
    if sha256(binary_source) != BINARY or sha256(args.z3.resolve()) != Z3:
        raise RuntimeError("unexpected artifact")
    directories = {
        "original_trie": trie / "tests/bug-reports/closed",
        "original_flat":
            args.flat.resolve() / "tests/bug-reports/closed",
        "controlled_short": args.short.resolve(),
        "controlled_long": args.long.resolve(),
    }
    sources = [
        path.name
        for pattern in ("*.fst", "*.fsti")
        for path in sorted(directories["original_trie"].glob(pattern))
    ]
    source_sha256 = {
        name: {
            source: sha256(path / source) for source in sources
        }
        for name, path in directories.items()
    }
    if len({
        hashlib.sha256(
            json.dumps(value, sort_keys=True).encode()
        ).hexdigest()
        for value in source_sha256.values()
    }) != 1:
        raise RuntimeError("source trees differ")
    stage = args.stage.resolve()
    if stage.exists():
        raise RuntimeError("stage path must not exist")
    shutil.copytree(trie / "stage3/out", stage)
    binary = stage / "bin/fstar.exe"
    args.output.mkdir(parents=True, exist_ok=True)
    if any(args.output.iterdir()):
        raise RuntimeError("output must be empty")
    os.sched_setaffinity(0, {args.cpu})
    environment = os.environ.copy()
    environment.update({
        "LC_ALL": "C", "LANG": "C",
        "FSTAR_LIB": str((stage / "lib/fstar").resolve()),
    })
    cells = [
        (name, repeat)
        for name in directories
        for repeat in range(1, args.repetitions + 1)
    ]
    random.Random(args.seed).shuffle(cells)
    measurements = args.output / "measurements.jsonl"
    fixed_run = stage / "run"
    for name, repeat in cells:
        if fixed_run.exists():
            shutil.rmtree(fixed_run)
        cache = fixed_run / "cache"
        generated = fixed_run / "output"
        cache.mkdir(parents=True)
        generated.mkdir()
        command = [
            str(binary), "--z3version", "5.3.0",
            "--smt", str(args.z3.resolve()), "--silent",
            "--odir", str(generated), "--cache_dir", str(cache),
            "--already_cached", "Prims,FStar",
            "--warn_error", "-321", "--warn_error", "-240",
            "--dep", "full", *sources,
            "-o", str(fixed_run / ".depend"),
        ]
        before = resource.getrusage(resource.RUSAGE_CHILDREN)
        started = time.monotonic()
        process = subprocess.run(
            command, cwd=directories[name], env=environment,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        wall = time.monotonic() - started
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        usage = {
            field: getattr(after, field) - getattr(before, field)
            for field in FIELDS
        }
        with measurements.open("a") as stream:
            stream.write(json.dumps({
                "fixture": name,
                "repeat": repeat,
                "cwd": str(directories[name]),
                "cwd_length": len(str(directories[name])),
                "wall_seconds": wall,
                "returncode": process.returncode,
                "usage": usage,
            }, sort_keys=True) + "\n")
        if process.returncode != 0:
            raise RuntimeError(f"{name}/{repeat} failed")
    (args.output / "provenance.json").write_text(json.dumps({
        "cpu": args.cpu,
        "repetitions": args.repetitions,
        "seed": args.seed,
        "binary_sha256": sha256(binary),
        "fstar_lib": environment["FSTAR_LIB"],
        "directories": {
            name: {
                "path": str(path),
                "length": len(str(path)),
                "device": path.stat().st_dev,
                "inode": path.stat().st_ino,
            }
            for name, path in directories.items()
        },
        "source_sha256": source_sha256["original_trie"],
        "z3_sha256": sha256(args.z3.resolve()),
        "script_sha256": sha256(Path(__file__)),
        "measurements_sha256": sha256(measurements),
    }, indent=2) + "\n")


if __name__ == "__main__":
    main()
