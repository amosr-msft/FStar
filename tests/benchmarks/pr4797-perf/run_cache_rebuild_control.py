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


COMMIT = "f4886d2decd874cd0008e31d6ba07c7da43c5ba4"
BINARIES = {
    "original": "e45671b08968de1ac22b3081f8b074c6966713ec577f147e4f686796b99fa17e",
    "rebuild": "8578fcb8034b2330dc2b8f74c352ed702fe93905da582b3a7076a781e9ea963d",
}
CHECKED = {
    "original": "3431ef516df8f95749d4ad90bffee7b7d3072ce213bf6ca0c82ad48491ebe8f5",
    "rebuild": "639c909d38045bff7f8751040bf4bda7d832cc77f7da072e91f6f0c85dacbb0a",
}
OPTIMIZED_COMMIT = "c939875498355d0684b41138b5dbc208e34ef2b4"
OPTIMIZED_BINARIES = {
    "original": "35e1c8f97bd7557e37723d2d0f8dec9b05dd29664037ab5312ca6ce4a5e469e3",
    "rebuild": "bb9a39e97ca2ed702551d466fac52cefcfb1855d49375a2b5f0cad789d3c432d",
}
OPTIMIZED_CHECKED = {
    "original": "3431ef516df8f95749d4ad90bffee7b7d3072ce213bf6ca0c82ad48491ebe8f5",
    "rebuild": "75b9926e13e4dac9552050e5099ecda300e11e333122b3b65a380691a5dfb680",
}
WORKLOADS = {
    "normalization": "tests/micro-benchmarks/Normalization.fst",
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
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--optimized", action="store_true")
    args = parser.parse_args()
    roots = {
        "original": args.original.resolve(),
        "rebuild": args.rebuild.resolve(),
    }
    binaries = {
        variant: root / "stage2/out/bin/fstar.exe"
        for variant, root in roots.items()
    }
    commit = OPTIMIZED_COMMIT if args.optimized else COMMIT
    expected_binaries = OPTIMIZED_BINARIES if args.optimized else BINARIES
    expected_checked = OPTIMIZED_CHECKED if args.optimized else CHECKED
    for variant, root in roots.items():
        head = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
        ).strip()
        if (
            variant == "rebuild" and head != commit
            or variant == "original" and subprocess.run([
                "git", "-C", str(root), "merge-base", "--is-ancestor",
                commit, head,
            ]).returncode != 0
        ):
            raise RuntimeError(f"{variant}: revision differs")
        if subprocess.run([
            "git", "-C", str(root), "diff", "--quiet", commit,
            "--", "src", "ulib", "pulse",
        ]).returncode != 0:
            raise RuntimeError(f"{variant}: production sources differ")
        if sha256(binaries[variant]) != expected_binaries[variant]:
            raise RuntimeError(f"{variant}: binary differs")
        if tree_sha256(
            root / "stage2/out/lib/fstar/ulib.checked"
        ) != {"sha256": expected_checked[variant], "files": 379}:
            raise RuntimeError(f"{variant}: checked tree differs")
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
        "FSTAR_LIB", "FSTAR_HOME", "OCAMLRUNPARAM", "CAMLRUNPARAM",
        "LD_PRELOAD", "LD_LIBRARY_PATH", "OCAMLPATH",
        "CAML_LD_LIBRARY_PATH",
    ):
        environment.pop(name, None)
    environment.update({"LC_ALL": "C", "LANG": "C"})
    provenance = {
        "cpu": args.cpu,
        "repetitions": args.repetitions,
        "commit": commit,
        "variants": {
            variant: {
                "root": str(root),
                "worktree_head": subprocess.check_output(
                    ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
                ).strip(),
                "binary_sha256": sha256(binaries[variant]),
                "checked_tree": tree_sha256(
                    root / "stage2/out/lib/fstar/ulib.checked"
                ),
            }
            for variant, root in roots.items()
        },
        "z3_sha256": sha256(args.z3.resolve()),
        "script_sha256": sha256(Path(__file__)),
    }
    (args.output / "provenance.json").write_text(
        json.dumps(provenance, indent=2) + "\n"
    )
    monitor = load_monitor()
    randomizer = random.Random(4803)
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
            command = [
                str(binaries[variant]),
                "--z3version", "5.3.0",
                "--smt", str(args.z3.resolve()),
                "--include", str(root / "stage2/out/lib/fstar/ulib"),
                "--include",
                str(root / "stage2/out/lib/fstar/ulib.checked"),
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
                command, source.parent, environment, log, 360
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
