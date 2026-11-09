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
        "checked":
            "67398b51b3bb4fbd24792bb9c0395b6b6694e691dbde1b4ae357984217bd71e3",
    },
    "flat": {
        "commit": "1b61ce6d3b2d0cead2f5174d931b042961529193",
        "binary":
            "667968b8748df177213e2ae45faa5156e507469c9b4cf9771cabc7c9e19d0641",
        "checked":
            "7ecbd36e330e8513e9d2ff389c57272769b94f951ef44edcb34c1d1d92634d8d",
    },
}
Z3 = "4da6a0f78424098b600a9112ebb9d8ce45de248a4913c26dd7d472e6dabef6d3"


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
    return {"files": len(files), "sha256": digest.hexdigest()}


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
    parser.add_argument("--seed", type=int, default=5021)
    args = parser.parse_args()
    roots = {name: path.resolve() for name, path in args.variant}
    if set(roots) != set(VARIANTS):
        raise RuntimeError("trie and flat variants required")
    provenance_variants = {}
    for name, root in roots.items():
        spec = VARIANTS[name]
        head = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
        ).strip()
        binary = root / "stage3/out/bin/fstar.exe"
        checked = root / "stage3/out/lib/fstar/ulib.checked"
        if (
            head != spec["commit"] or sha256(binary) != spec["binary"]
            or tree_sha256(checked)
            != {"files": 379, "sha256": spec["checked"]}
        ):
            raise RuntimeError(f"{name}: artifact differs")
        provenance_variants[name] = {
            "root": str(root),
            "head": head,
            "binary_sha256": sha256(binary),
            "checked_tree": tree_sha256(checked),
        }
    if sha256(args.z3.resolve()) != Z3:
        raise RuntimeError("unexpected Z3")
    stage = args.stage.resolve()
    if stage.exists():
        raise RuntimeError("stage path must not exist")
    shutil.copytree(
        roots["trie"] / "stage3/out", stage, symlinks=False
    )
    binary_path = stage / "bin/fstar.exe"
    checked_path = stage / "lib/fstar/ulib.checked"
    source_dir = roots["trie"] / "tests/bug-reports/closed"
    sources = [
        path.name
        for pattern in ("*.fst", "*.fsti")
        for path in sorted(source_dir.glob(pattern))
    ]
    source_sha256 = {
        source: sha256(source_dir / source) for source in sources
    }
    for source in sources:
        if sha256(roots["flat"] / "tests/bug-reports/closed" / source) != (
            source_sha256[source]
        ):
            raise RuntimeError(f"{source}: source differs")
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
    monitor = load_monitor()
    cells = [
        (binary_name, checked_name)
        for binary_name in VARIANTS
        for checked_name in VARIANTS
    ]
    randomizer = random.Random(args.seed)
    repeats = list(range(1, args.repetitions + 1))
    randomizer.shuffle(repeats)
    measurements = args.output / "measurements.jsonl"
    fixed_run = stage / "run"
    for repeat in repeats:
        for binary_name, checked_name in randomizer.sample(cells, len(cells)):
            shutil.copy2(
                roots[binary_name] / "stage3/out/bin/fstar.exe",
                binary_path,
            )
            shutil.rmtree(checked_path)
            shutil.copytree(
                roots[checked_name] / "stage3/out/lib/fstar/ulib.checked",
                checked_path,
            )
            if fixed_run.exists():
                shutil.rmtree(fixed_run)
            cache = fixed_run / "cache"
            generated = fixed_run / "output"
            cache.mkdir(parents=True)
            generated.mkdir()
            heap = fixed_run / "fstar.fstarmem"
            env = environment.copy()
            env["FSTAR_MEM_REPORT"] = str(heap)
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
                f"{repeat}-{binary_name}-binary-{checked_name}-checked.log"
            )
            measured = monitor(command, source_dir, env, log, 180)
            depend = fixed_run / ".depend"
            depend_copy = args.output / (
                f"{repeat}-{binary_name}-binary-{checked_name}-checked.depend"
            )
            shutil.copy2(depend, depend_copy)
            row = {
                "repeat": repeat,
                "binary": binary_name,
                "checked": checked_name,
                "command": command,
                "cwd": str(source_dir),
                "environment": {
                    "FSTAR_LIB": env["FSTAR_LIB"],
                    "LC_ALL": env["LC_ALL"],
                    "LANG": env["LANG"],
                },
                "runtime_binary_sha256": sha256(binary_path),
                "runtime_checked_tree": tree_sha256(checked_path),
                "depend_sha256": sha256(depend),
                "log_sha256": sha256(log),
                "fstar_heap_sha256": sha256(heap),
                **measured,
            }
            write_row(measurements, row)
            if measured["returncode"] != 0 or measured["timed_out"]:
                raise RuntimeError(
                    f"{repeat}/{binary_name}/{checked_name} failed"
                )
    rows = [
        json.loads(line) for line in measurements.read_text().splitlines()
    ]
    output_hashes = sorted({row["depend_sha256"] for row in rows})
    (args.output / "provenance.json").write_text(json.dumps({
        "cpu": args.cpu,
        "repetitions": args.repetitions,
        "seed": args.seed,
        "stage": str(stage),
        "runtime_binary_path": str(binary_path),
        "runtime_checked_path": str(checked_path),
        "runtime_cwd": str(source_dir),
        "fixed_run_path": str(fixed_run),
        "variants": provenance_variants,
        "sources": sources,
        "source_sha256": source_sha256,
        "z3_sha256": sha256(args.z3.resolve()),
        "script_sha256": sha256(Path(__file__)),
        "monitor_sha256": sha256(
            Path(__file__).resolve().parent / "run_latest_outliers.py"
        ),
        "depend_sha256": output_hashes,
    }, indent=2) + "\n")


if __name__ == "__main__":
    main()
