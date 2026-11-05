#!/usr/bin/env python3

import argparse
import hashlib
import importlib.util
import json
import os
import random
import re
import shutil
import subprocess
from pathlib import Path


VARIANTS = {
    "three": {
        "commit": "7da01c0b4ae5cf447f6951ddb38714b7f1969a35",
        "binary": "495750cf4228d820cec087320b06779aaaa0cd7185a66c654311399f0f9f93ba",
        "checked":
            "ad27f44a3caa142bcfaa3a7d1132bbecfbacc7564169442a8762d78a20408223",
    },
    "two": {
        "commit": "285501627e98a089ee15fe10dec94fcfa0b76f73",
        "builds": [
            (
                "2b58b223b75a70e46f6128d5c3655481db18415f40613a46f4a6583a086531a7",
                "9acbcc1158c442aba661da3f4aea1bed27bbf42dc37a78e87a33bfcda3740851",
            ),
            (
                "29660d4cd685ee35ea48fcea81327a6f7b5f7d85c00602b1b5e5cb83ce2a1eae",
                "ce8100f99545886fab975aa35aa4e6c60609f5f88bc8f0c24bb48b27c4a7b508",
            ),
        ],
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
    parser.add_argument("--three", type=Path, required=True)
    parser.add_argument("--two", type=Path, required=True)
    parser.add_argument("--z3", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cpu", type=int, default=16)
    parser.add_argument("--dependency-repetitions", type=int, default=20)
    parser.add_argument("--source-repetitions", type=int, default=5)
    args = parser.parse_args()
    roots = {"three": args.three.resolve(), "two": args.two.resolve()}
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
    dep_dir = "tests/bug-reports/closed"
    dep_sources = [
        path.name
        for pattern in ("*.fst", "*.fsti")
        for path in sorted(
            (roots["three"] / dep_dir).glob(pattern)
        )
    ]
    source_hashes = {}
    for source in dep_sources:
        hashes = {
            variant: sha256(root / dep_dir / source)
            for variant, root in roots.items()
        }
        if len(set(hashes.values())) != 1:
            raise RuntimeError(f"{source}: source differs")
        source_hashes[f"dependency/{source}"] = hashes["three"]
    for workload, details in WORKLOADS.items():
        hashes = {
            variant: sha256(root / details["source"])
            for variant, root in roots.items()
        }
        if len(set(hashes.values())) != 1:
            raise RuntimeError(f"{workload}: source differs")
        source_hashes[workload] = hashes["three"]
    args.output.mkdir(parents=True, exist_ok=True)
    if any(args.output.iterdir()):
        raise RuntimeError("output must be empty")
    os.sched_setaffinity(0, {args.cpu})
    environment = os.environ.copy()
    for name in (
        "FSTAR_LIB", "FSTAR_HOME", "OCAMLRUNPARAM", "CAMLRUNPARAM",
        "LD_PRELOAD", "LD_LIBRARY_PATH", "OCAMLPATH",
        "CAML_LD_LIBRARY_PATH", "FSTAR_MEM_REPORT",
    ):
        environment.pop(name, None)
    environment.update({"LC_ALL": "C", "LANG": "C"})
    provenance = {
        "cpu": args.cpu,
        "dependency_repetitions": args.dependency_repetitions,
        "source_repetitions": args.source_repetitions,
        "dependency_sources": dep_sources,
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
    randomizer = random.Random(4812)
    cells = [
        ("dependency", repeat)
        for repeat in range(1, args.dependency_repetitions + 1)
    ] + [
        (workload, repeat)
        for workload in WORKLOADS
        for repeat in range(1, args.source_repetitions + 1)
    ]
    randomizer.shuffle(cells)
    measurements = args.output / "measurements.jsonl"
    for workload, repeat in cells:
        for variant in randomizer.sample(list(roots), len(roots)):
            root = roots[variant]
            run_dir = args.output / f"{repeat}-{workload}-{variant}"
            cache = run_dir / "cache"
            generated = run_dir / "output"
            cache.mkdir(parents=True)
            generated.mkdir()
            heap = run_dir / "fstar.fstarmem"
            env = environment.copy()
            env["FSTAR_MEM_REPORT"] = str(heap)
            common = [
                str(binaries[variant]),
                "--z3version", "5.3.0",
                "--smt", str(args.z3.resolve()),
                "--silent",
                "--odir", str(generated),
                "--cache_dir", str(cache),
                "--already_cached", "Prims,FStar",
                "--warn_error", "-321",
            ]
            if workload == "dependency":
                cwd = root / dep_dir
                command = [
                    *common,
                    "--warn_error", "-240",
                    "--dep", "full",
                    *dep_sources,
                    "-o", str(run_dir / ".depend"),
                ]
                timeout = 180
            else:
                details = WORKLOADS[workload]
                source = (root / details["source"]).resolve()
                cwd = source.parent
                command = [
                    *common,
                    "--force",
                    "-c", str(source),
                    "-o", str(cache / f"{source.name}.checked"),
                ]
                timeout = details["timeout"]
            log = run_dir / "run.log"
            measured = monitor(command, cwd, env, log, timeout)
            heap_peak = None
            if heap.is_file():
                match = re.search(
                    r"fstar\.mempeak\s+([0-9]+)", heap.read_text()
                )
                if match is not None:
                    heap_peak = int(match.group(1))
            row = {
                "variant": variant,
                "workload": workload,
                "repeat": repeat,
                "command": command,
                "cwd": str(cwd),
                "log_sha256": sha256(log),
                "fstar_heap_peak_bytes": heap_peak,
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
