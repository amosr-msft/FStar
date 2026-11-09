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
    "trie": {
        "commit": "7df960b9fbbeed8c599361d9660f40f2e2f85f9c",
        "binary":
            "207e478416f8fae3bd3c3b33914f2a5a9504fbcaf2d3d4745d9cc5914e0734b9",
    },
    "flat": {
        "commit": "1b61ce6d3b2d0cead2f5174d931b042961529193",
        "binary":
            "667968b8748df177213e2ae45faa5156e507469c9b4cf9771cabc7c9e19d0641",
    },
}
Z3 = "4da6a0f78424098b600a9112ebb9d8ce45de248a4913c26dd7d472e6dabef6d3"


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_variant(value):
    name, path = value.split("=", 1)
    if name not in VARIANTS:
        raise argparse.ArgumentTypeError(f"unknown variant: {name}")
    return name, Path(path)


def load_monitor():
    path = Path(__file__).resolve().parent / "run_latest_outliers.py"
    spec = importlib.util.spec_from_file_location("latest", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.monitor


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--variant", action="append", type=parse_variant, required=True
    )
    parser.add_argument("--z3", type=Path, required=True)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, default=20)
    parser.add_argument("--cpu", type=int, default=16)
    parser.add_argument("--seed", type=int, default=5071)
    args = parser.parse_args()
    roots = {name: path.resolve() for name, path in args.variant}
    if set(roots) != set(VARIANTS):
        raise RuntimeError("trie and flat variants required")
    for name, root in roots.items():
        spec = VARIANTS[name]
        if (
            subprocess.check_output(
                ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
            ).strip() != spec["commit"]
            or sha256(root / "stage3/out/bin/fstar.exe") != spec["binary"]
        ):
            raise RuntimeError(f"{name}: artifact differs")
    if sha256(args.z3.resolve()) != Z3:
        raise RuntimeError("unexpected Z3")
    stage = args.stage.resolve()
    if stage.exists():
        raise RuntimeError("stage path must not exist")
    shutil.copytree(roots["trie"] / "stage3/out", stage)
    binary = stage / "bin/fstar.exe"
    cwd = roots["trie"] / "tests/bug-reports/closed"
    sources = [
        path.name
        for pattern in ("*.fst", "*.fsti")
        for path in sorted(cwd.glob(pattern))
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
    monitor = load_monitor()
    randomizer = random.Random(args.seed)
    repeats = list(range(1, args.repetitions + 1))
    randomizer.shuffle(repeats)
    measurements = args.output / "measurements.jsonl"
    run = stage / "run"
    for repeat in repeats:
        order = ["trie", "flat"]
        if repeat % 2:
            order.reverse()
        for variant in order:
            shutil.copy2(
                roots[variant] / "stage3/out/bin/fstar.exe", binary
            )
            if run.exists():
                shutil.rmtree(run)
            cache = run / "cache"
            generated = run / "output"
            cache.mkdir(parents=True)
            generated.mkdir()
            command = [
                str(binary), "--z3version", "5.3.0",
                "--smt", str(args.z3.resolve()), "--silent",
                "--odir", str(generated), "--cache_dir", str(cache),
                "--already_cached", "Prims,FStar",
                "--warn_error", "-321", "--warn_error", "-240",
                "--dep", "full", *sources,
                "-o", str(run / ".depend"),
            ]
            log = args.output / f"{repeat}-{variant}.log"
            measured = monitor(command, cwd, environment, log, 180)
            with measurements.open("a") as stream:
                stream.write(json.dumps({
                    "repeat": repeat,
                    "variant": variant,
                    "runtime_binary_sha256": sha256(binary),
                    "depend_sha256": sha256(run / ".depend"),
                    "log_sha256": sha256(log),
                    **measured,
                }, sort_keys=True) + "\n")
            if measured["returncode"] != 0 or measured["timed_out"]:
                raise RuntimeError(f"{repeat}/{variant} failed")
    (args.output / "provenance.json").write_text(json.dumps({
        "cpu": args.cpu,
        "repetitions": args.repetitions,
        "seed": args.seed,
        "runtime_binary_path": str(binary),
        "runtime_cwd": str(cwd),
        "runtime_fstar_lib": environment["FSTAR_LIB"],
        "runtime_run_path": str(run),
        "variants": VARIANTS,
        "source_manifest_sha256": hashlib.sha256(
            "\n".join(sources).encode()
        ).hexdigest(),
        "z3_sha256": sha256(args.z3.resolve()),
        "script_sha256": sha256(Path(__file__)),
        "monitor_sha256": sha256(
            Path(__file__).resolve().parent / "run_latest_outliers.py"
        ),
    }, indent=2) + "\n")


if __name__ == "__main__":
    main()
