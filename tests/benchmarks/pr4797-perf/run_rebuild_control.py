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


COMPILER_COMMIT = "e2c45ed0c4099f8d27ef0d78641ca8b626f4cdcb"
WORKLOADS = {
    "normalization": "tests/micro-benchmarks/Normalization.fst",
    "dependency-bug3207": "tests/bug-reports/closed/Bug3207.fst",
    "long": "tests/calc/Long.fst",
    "arrow-unfold-limit": "tests/custard/ArrowUnfoldLimit.fst",
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
    path = Path(__file__).resolve().parent / "run_source_workloads.py"
    spec = importlib.util.spec_from_file_location("source_workloads", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.monitor


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--original", type=Path, required=True)
    parser.add_argument("--rebuild", type=Path, required=True)
    parser.add_argument("--z3", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cpu", type=int, default=16)
    parser.add_argument("--repetitions", type=int, default=3)
    args = parser.parse_args()
    roots = {
        "original": args.original.resolve(),
        "rebuild": args.rebuild.resolve(),
    }
    binaries = {
        variant: root / "stage2/out/bin/fstar.exe"
        for variant, root in roots.items()
    }
    versions = {
        variant: subprocess.check_output(
            [str(binary), "--version"], text=True
        ).strip()
        for variant, binary in binaries.items()
    }
    if any(
        f"commit={COMPILER_COMMIT}" not in version
        for version in versions.values()
    ):
        raise RuntimeError("unexpected compiler source revision")
    heads = {
        variant: subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
        ).strip()
        for variant, root in roots.items()
    }
    if heads["rebuild"] != COMPILER_COMMIT:
        raise RuntimeError("rebuild worktree is not the exact PR head")
    if subprocess.run([
        "git", "-C", str(roots["original"]), "merge-base", "--is-ancestor",
        COMPILER_COMMIT, heads["original"],
    ]).returncode != 0:
        raise RuntimeError("original worktree does not descend from PR head")
    for root in roots.values():
        if subprocess.run([
            "git", "-C", str(root), "diff", "--quiet", COMPILER_COMMIT,
            "--", "src", "ulib", "pulse",
        ]).returncode != 0:
            raise RuntimeError("production sources differ from PR head")
    if sha256(args.z3.resolve()) != (
        "4da6a0f78424098b600a9112ebb9d8ce45de248a4913c26dd7d472e6dabef6d3"
    ):
        raise RuntimeError("unexpected Z3")
    for workload, relative in WORKLOADS.items():
        if len({
            sha256(root / relative) for root in roots.values()
        }) != 1:
            raise RuntimeError(f"{workload}: source differs")
    args.output.mkdir(parents=True, exist_ok=True)
    if any(args.output.iterdir()):
        raise RuntimeError("output must be empty")
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
    provenance = {
        "cpu": args.cpu,
        "repetitions": args.repetitions,
        "compiler_commit": COMPILER_COMMIT,
        "variants": {
            variant: {
                "root": str(root),
                "binary_sha256": sha256(binaries[variant]),
                "version": versions[variant],
                "worktree_head": heads[variant],
                "checked_tree": tree_sha256(
                    root / "stage2/out/lib/fstar/ulib.checked"
                ),
            }
            for variant, root in roots.items()
        },
        "z3_sha256": sha256(args.z3.resolve()),
        "script_sha256": sha256(Path(__file__)),
        "monitor_script_sha256": sha256(
            Path(__file__).resolve().parent / "run_source_workloads.py"
        ),
    }
    (args.output / "provenance.json").write_text(
        json.dumps(provenance, indent=2) + "\n"
    )
    monitor = load_monitor()
    randomizer = random.Random(4798)
    cells = [
        (workload, repeat)
        for workload in WORKLOADS
        for repeat in range(1, args.repetitions + 1)
    ]
    randomizer.shuffle(cells)
    measurements = args.output / "measurements.jsonl"
    for workload, repeat in cells:
        for variant in randomizer.sample(list(roots), len(roots)):
            root = roots[variant]
            source = (root / WORKLOADS[workload]).resolve()
            run_dir = args.output / f"{repeat}-{workload}-{variant}"
            cache = run_dir / "cache"
            generated = run_dir / "output"
            cache.mkdir(parents=True)
            generated.mkdir()
            common = [
                str(binaries[variant]),
                "--z3version", "5.3.0",
                "--smt", str(args.z3.resolve()),
                "--include", str(root / "stage2/out/lib/fstar/ulib"),
                "--include",
                str(root / "stage2/out/lib/fstar/ulib.checked"),
            ]
            if workload == "dependency-bug3207":
                command = [*common, "--dep", "full", str(source)]
                timeout = 120
            else:
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
                timeout = 360
            log = run_dir / "run.log"
            measured = monitor(
                command, source.parent, environment, log, timeout
            )
            row = {
                "variant": variant,
                "workload": workload,
                "repeat": repeat,
                "command": command,
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
