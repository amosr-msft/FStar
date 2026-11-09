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


def write_row(path, row):
    with path.open("a") as stream:
        stream.write(json.dumps(row, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--variant", action="append", type=parse_variant, required=True
    )
    parser.add_argument("--z3", type=Path, required=True)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, default=10)
    parser.add_argument("--cpu", type=int, default=16)
    parser.add_argument("--seed", type=int, default=5031)
    args = parser.parse_args()
    roots = {name: path.resolve() for name, path in args.variant}
    if set(roots) != set(VARIANTS):
        raise RuntimeError("trie and flat variants required")
    for name, root in roots.items():
        spec = VARIANTS[name]
        head = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
        ).strip()
        if (
            head != spec["commit"]
            or sha256(root / "stage3/out/bin/fstar.exe") != spec["binary"]
        ):
            raise RuntimeError(f"{name}: artifact differs")
    if sha256(args.z3.resolve()) != Z3:
        raise RuntimeError("unexpected Z3")
    stage = args.stage.resolve()
    if stage.exists():
        raise RuntimeError("stage path must not exist")
    shutil.copytree(roots["trie"] / "stage3/out", stage)
    binary_path = stage / "bin/fstar.exe"
    sources_by_cwd = {}
    hashes = {}
    for cwd_name, root in roots.items():
        directory = root / "tests/bug-reports/closed"
        sources = [
            path.name
            for pattern in ("*.fst", "*.fsti")
            for path in sorted(directory.glob(pattern))
        ]
        sources_by_cwd[cwd_name] = sources
        hashes[cwd_name] = {
            source: sha256(directory / source) for source in sources
        }
    if (
        sources_by_cwd["trie"] != sources_by_cwd["flat"]
        or hashes["trie"] != hashes["flat"]
    ):
        raise RuntimeError("input trees differ")
    sources = sources_by_cwd["trie"]
    args.output.mkdir(parents=True, exist_ok=True)
    if any(args.output.iterdir()):
        raise RuntimeError("output must be empty")
    os.sched_setaffinity(0, {args.cpu})
    environment = os.environ.copy()
    for name in (
        "FSTAR_HOME", "OCAMLRUNPARAM", "CAMLRUNPARAM", "LD_PRELOAD",
        "LD_LIBRARY_PATH", "OCAMLPATH", "CAML_LD_LIBRARY_PATH",
        "FSTAR_MEM_REPORT",
    ):
        environment.pop(name, None)
    environment.update({
        "LC_ALL": "C",
        "LANG": "C",
        "FSTAR_LIB": str((stage / "lib/fstar").resolve()),
    })
    cells = [
        (binary_name, cwd_name)
        for binary_name in VARIANTS
        for cwd_name in VARIANTS
    ]
    randomizer = random.Random(args.seed)
    repeats = list(range(1, args.repetitions + 1))
    randomizer.shuffle(repeats)
    monitor = load_monitor()
    measurements = args.output / "measurements.jsonl"
    fixed_run = stage / "run"
    for repeat in repeats:
        for binary_name, cwd_name in randomizer.sample(cells, len(cells)):
            shutil.copy2(
                roots[binary_name] / "stage3/out/bin/fstar.exe",
                binary_path,
            )
            if fixed_run.exists():
                shutil.rmtree(fixed_run)
            cache = fixed_run / "cache"
            generated = fixed_run / "output"
            cache.mkdir(parents=True)
            generated.mkdir()
            cwd = roots[cwd_name] / "tests/bug-reports/closed"
            command = [
                str(binary_path), "--z3version", "5.3.0",
                "--smt", str(args.z3.resolve()), "--silent",
                "--odir", str(generated), "--cache_dir", str(cache),
                "--already_cached", "Prims,FStar",
                "--warn_error", "-321", "--warn_error", "-240",
                "--dep", "full", *sources,
                "-o", str(fixed_run / ".depend"),
            ]
            log = args.output / (
                f"{repeat}-{binary_name}-binary-{cwd_name}-cwd.log"
            )
            measured = monitor(command, cwd, environment, log, 180)
            row = {
                "repeat": repeat,
                "binary": binary_name,
                "cwd_variant": cwd_name,
                "command": command,
                "cwd": str(cwd),
                "runtime_binary_sha256": sha256(binary_path),
                "depend_sha256": sha256(fixed_run / ".depend"),
                "log_sha256": sha256(log),
                **measured,
            }
            write_row(measurements, row)
            if measured["returncode"] != 0 or measured["timed_out"]:
                raise RuntimeError(
                    f"{repeat}/{binary_name}/{cwd_name} failed"
                )
    (args.output / "provenance.json").write_text(json.dumps({
        "cpu": args.cpu,
        "repetitions": args.repetitions,
        "seed": args.seed,
        "stage": str(stage),
        "runtime_binary_path": str(binary_path),
        "fixed_run_path": str(fixed_run),
        "fstar_lib": environment["FSTAR_LIB"],
        "variants": {
            name: {
                "root": str(root),
                "head": VARIANTS[name]["commit"],
                "binary_sha256": VARIANTS[name]["binary"],
            }
            for name, root in roots.items()
        },
        "sources": sources,
        "source_sha256": hashes["trie"],
        "z3_sha256": sha256(args.z3.resolve()),
        "script_sha256": sha256(Path(__file__)),
        "monitor_sha256": sha256(
            Path(__file__).resolve().parent / "run_latest_outliers.py"
        ),
    }, indent=2) + "\n")


if __name__ == "__main__":
    main()
