#!/usr/bin/env python3

import argparse
import hashlib
import importlib.util
import json
import os
import random
import shutil
import subprocess
from pathlib import Path


VARIANTS = {
    "base": {
        "commit": "c68959fe1f070cd66a5ed2e92965185505f109ce",
        "binary": "1ef3f05e975404439063e941236a624cc5dc4d3fd72ec77c4c1ea30b707faa30",
        "checked":
            "4017dc355e1bd811d7cd0713de6ba66149e7416251c9e77fae8fac99ade8f84a",
    },
    "pr": {
        "commit": "adbf7292f25542a538910711fef79bf4eb8c0bac",
        "binary": "21c17ebd430d1679a6ecf63696a9f389c6635163c6ac35e45757307fdbdf4c4b",
        "checked":
            "5e40a2f86a2324f1ad48bcde59e3e73fb8aff974f81c0b7feb3a6cf86d8b0b95",
    },
    "fixed": {
        "commit": "7da01c0b4ae5cf447f6951ddb38714b7f1969a35",
        "binary": "495750cf4228d820cec087320b06779aaaa0cd7185a66c654311399f0f9f93ba",
        "checked":
            "ad27f44a3caa142bcfaa3a7d1132bbecfbacc7564169442a8762d78a20408223",
    },
}
WORKLOADS = {
    "normalization": {
        "source": "tests/micro-benchmarks/Normalization.fst",
        "timeout": 120,
    },
    "bv-binary-ops": {
        "source": "tests/micro-benchmarks/BvBinaryOps.fst",
        "timeout": 180,
    },
    "long": {
        "source": "tests/calc/Long.fst",
        "timeout": 300,
    },
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


def load_monitor():
    path = Path(__file__).resolve().parent / "run_latest_outliers.py"
    spec = importlib.util.spec_from_file_location("latest_outliers", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.monitor


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--pr", type=Path, required=True)
    parser.add_argument("--fixed", type=Path, required=True)
    parser.add_argument("--z3", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cpu", type=int, default=16)
    parser.add_argument("--repetitions", type=int, default=5)
    args = parser.parse_args()
    roots = {
        "base": args.base.resolve(),
        "pr": args.pr.resolve(),
        "fixed": args.fixed.resolve(),
    }
    binaries = {
        variant: root / "stage3/out/bin/fstar.exe"
        for variant, root in roots.items()
    }
    heads = {
        variant: subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
        ).strip()
        for variant, root in roots.items()
    }
    for variant, root in roots.items():
        spec = VARIANTS[variant]
        if subprocess.run([
            "git", "-C", str(root), "merge-base", "--is-ancestor",
            spec["commit"], heads[variant],
        ]).returncode != 0:
            raise RuntimeError(f"{variant}: unexpected ancestry")
        if sha256(binaries[variant]) != spec["binary"]:
            raise RuntimeError(f"{variant}: binary differs")
        if tree_sha256(
            root / "stage3/out/lib/fstar/ulib.checked"
        ) != {"sha256": spec["checked"], "files": 379}:
            raise RuntimeError(f"{variant}: checked tree differs")
    source_hashes = {}
    for workload, details in WORKLOADS.items():
        hashes = {
            variant: sha256(root / details["source"])
            for variant, root in roots.items()
        }
        if len(set(hashes.values())) != 1:
            raise RuntimeError(f"{workload}: source differs")
        source_hashes[workload] = hashes["base"]
    args.output.mkdir(parents=True, exist_ok=True)
    if any(args.output.iterdir()):
        raise RuntimeError("output must be empty")
    os.sched_setaffinity(0, {args.cpu})
    environment = os.environ.copy()
    environment.update({"LC_ALL": "C", "LANG": "C"})
    provenance = {
        "cpu": args.cpu,
        "repetitions": args.repetitions,
        "workloads": WORKLOADS,
        "source_sha256": source_hashes,
        "z3_sha256": sha256(args.z3.resolve()),
        "variants": {
            variant: {
                "root": str(root),
                "worktree_head": heads[variant],
                "source_commit": VARIANTS[variant]["commit"],
                "binary_sha256": sha256(binaries[variant]),
                "checked_tree": tree_sha256(
                    root / "stage3/out/lib/fstar/ulib.checked"
                ),
            }
            for variant, root in roots.items()
        },
        "script_sha256": sha256(Path(__file__)),
        "monitor_sha256": sha256(
            Path(__file__).resolve().parent / "run_latest_outliers.py"
        ),
    }
    (args.output / "provenance.json").write_text(
        json.dumps(provenance, indent=2) + "\n"
    )
    monitor = load_monitor()
    randomizer = random.Random(4810)
    cells = [
        (workload, repeat)
        for workload in WORKLOADS
        for repeat in range(1, args.repetitions + 1)
    ]
    randomizer.shuffle(cells)
    measurements = args.output / "measurements.jsonl"
    for workload, repeat in cells:
        details = WORKLOADS[workload]
        for variant in randomizer.sample(list(roots), len(roots)):
            root = roots[variant]
            source = (root / details["source"]).resolve()
            run_dir = args.output / f"{repeat}-{workload}-{variant}"
            cache = run_dir / "cache"
            generated = run_dir / "output"
            cache.mkdir(parents=True)
            generated.mkdir()
            command = [
                str(binaries[variant]),
                "--z3version", "5.3.0",
                "--smt", str(args.z3.resolve()),
                "--silent",
                "--odir", str(generated),
                "--cache_dir", str(cache),
                "--already_cached", "Prims,FStar",
                "--warn_error", "-321",
                "--force",
                "-c", str(source),
                "-o", str(cache / f"{source.name}.checked"),
            ]
            log = run_dir / "run.log"
            measured = monitor(
                command,
                source.parent,
                environment,
                log,
                details["timeout"],
            )
            row = {
                "variant": variant,
                "workload": workload,
                "repeat": repeat,
                "command": command,
                "cwd": str(source.parent),
                "log_sha256": sha256(log),
                **measured,
            }
            with measurements.open("a") as stream:
                stream.write(json.dumps(row, sort_keys=True) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            if measured["returncode"] != 0 or measured["timed_out"]:
                raise RuntimeError(f"{variant}/{workload}/{repeat} failed")
            shutil.rmtree(cache)
            shutil.rmtree(generated)


if __name__ == "__main__":
    main()
