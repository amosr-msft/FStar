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
        "builds": [
            (
                "85d8872e8791d7113a09c40646327a6a9a6e19645b8730b6478f910465932208",
                "3431ef516df8f95749d4ad90bffee7b7d3072ce213bf6ca0c82ad48491ebe8f5",
            ),
            (
                "495750cf4228d820cec087320b06779aaaa0cd7185a66c654311399f0f9f93ba",
                "ad27f44a3caa142bcfaa3a7d1132bbecfbacc7564169442a8762d78a20408223",
            ),
        ],
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
    parser.add_argument("--repetitions", type=int, default=20)
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
        if subprocess.run([
            "git", "-C", str(root), "diff", "--quiet", spec["commit"],
            "--", "src", "ulib", "pulse",
        ]).returncode != 0:
            raise RuntimeError(f"{variant}: production sources differ")
        binary_hash = sha256(binaries[variant])
        checked = tree_sha256(
            root / "stage3/out/lib/fstar/ulib.checked"
        )
        builds = (
            spec["builds"]
            if "builds" in spec
            else [(spec["binary"], spec["checked"])]
        )
        if checked["files"] != 379 or (
            binary_hash, checked["sha256"]
        ) not in builds:
            raise RuntimeError(f"{variant}: compiler/dependency build differs")
    if sha256(args.z3.resolve()) != (
        "4da6a0f78424098b600a9112ebb9d8ce45de248a4913c26dd7d472e6dabef6d3"
    ):
        raise RuntimeError("unexpected Z3")
    directory = "tests/bug-reports/closed"
    sources = [
        path.name
        for pattern in ("*.fst", "*.fsti")
        for path in sorted(
            (roots["base"] / directory).glob(pattern)
        )
    ]
    source_sha256 = {}
    for source in sources:
        hashes = {
            variant: sha256(root / directory / source)
            for variant, root in roots.items()
        }
        if len(set(hashes.values())) != 1:
            raise RuntimeError(f"{source}: source differs")
        source_sha256[source] = hashes["base"]
    args.output.mkdir(parents=True, exist_ok=True)
    if any(args.output.iterdir()):
        raise RuntimeError("output must be empty")
    os.sched_setaffinity(0, {args.cpu})
    environment = os.environ.copy()
    environment.update({"LC_ALL": "C", "LANG": "C"})
    provenance = {
        "cpu": args.cpu,
        "repetitions": args.repetitions,
        "source_arguments": sources,
        "source_sha256": source_sha256,
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
    randomizer = random.Random(4809)
    repeats = list(range(1, args.repetitions + 1))
    randomizer.shuffle(repeats)
    measurements = args.output / "measurements.jsonl"
    for repeat in repeats:
        for variant in randomizer.sample(list(roots), len(roots)):
            root = roots[variant]
            cwd = root / directory
            run_dir = args.output / f"{repeat}-{variant}"
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
                "--warn_error", "-240",
                "--dep", "full",
                *sources,
                "-o", str(run_dir / ".depend"),
            ]
            log = run_dir / "run.log"
            measured = monitor(command, cwd, environment, log, 180)
            row = {
                "variant": variant,
                "repeat": repeat,
                "command": command,
                "cwd": str(cwd),
                "log_sha256": sha256(log),
                **measured,
            }
            with measurements.open("a") as stream:
                stream.write(json.dumps(row, sort_keys=True) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            if measured["returncode"] != 0 or measured["timed_out"]:
                raise RuntimeError(f"{variant}/{repeat} failed")
            shutil.rmtree(cache)
            shutil.rmtree(generated)


if __name__ == "__main__":
    main()
