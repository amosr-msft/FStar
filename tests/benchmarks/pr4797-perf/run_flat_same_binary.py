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


COMMIT = "896a237eae"
Z3 = "4da6a0f78424098b600a9112ebb9d8ce45de248a4913c26dd7d472e6dabef6d3"


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_helpers():
    here = Path(__file__).resolve().parent
    latest_spec = importlib.util.spec_from_file_location(
        "latest", here / "run_latest_outliers.py"
    )
    latest = importlib.util.module_from_spec(latest_spec)
    latest_spec.loader.exec_module(latest)
    broad_spec = importlib.util.spec_from_file_location(
        "broad", here / "run_broad_reproduction.py"
    )
    broad = importlib.util.module_from_spec(broad_spec)
    broad_spec.loader.exec_module(broad)
    return latest.monitor, broad.parse_ramon, broad.CHECKED


def write_row(path, row):
    with path.open("a") as stream:
        stream.write(json.dumps(row, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--worktree", type=Path, required=True)
    parser.add_argument("--z3", type=Path, required=True)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--binary-sha256", required=True)
    parser.add_argument("--instrumented", action="store_true")
    parser.add_argument("--kind", choices=("dependency", "long"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, required=True)
    parser.add_argument("--cpu", type=int, default=16)
    parser.add_argument("--seed", type=int, default=4963)
    args = parser.parse_args()
    root = args.worktree.resolve()
    head = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
    ).strip()
    if not head.startswith(COMMIT):
        raise RuntimeError(f"unexpected revision: {head}")
    binary = root / "stage3/out/bin/fstar.exe"
    if (
        sha256(binary) != args.binary_sha256
        or sha256(args.z3.resolve()) != Z3
    ):
        raise RuntimeError("unexpected binary or Z3")
    args.output.mkdir(parents=True, exist_ok=True)
    if any(args.output.iterdir()):
        raise RuntimeError("output must be empty")
    os.sched_setaffinity(0, {args.cpu})
    monitor, parse_ramon, checked = load_helpers()
    environment = os.environ.copy()
    for name in (
        "FSTAR_LIB", "FSTAR_HOME", "OCAMLRUNPARAM", "CAMLRUNPARAM",
        "LD_PRELOAD", "LD_LIBRARY_PATH", "OCAMLPATH",
        "CAML_LD_LIBRARY_PATH", "FSTAR_MEM_REPORT",
        "FSTAR_FLAT_ROOT_DIAGNOSTIC",
    ):
        environment.pop(name, None)
    environment.update({"LC_ALL": "C", "LANG": "C"})
    modes = ("trie", "flat")
    randomizer = random.Random(args.seed)
    repeats = list(range(1, args.repetitions + 1))
    randomizer.shuffle(repeats)
    measurements = args.output / "measurements.jsonl"
    workload = {}
    if args.kind == "dependency":
        directory = root / "tests/bug-reports/closed"
        sources = [
            path.name
            for pattern in ("*.fst", "*.fsti")
            for path in sorted(directory.glob(pattern))
        ]
        workload = {
            "directory": str(directory.relative_to(root)),
            "sources": sources,
            "source_sha256": {
                source: sha256(directory / source) for source in sources
            },
        }
    else:
        ramon = parse_ramon(
            args.artifact.resolve() / "ramon-files/base" / checked["long"]
        )
        raw = ramon["argv"]
        source_arg = raw[raw.index("-c") + 1]
        parts = Path(ramon["cwd"]).parts
        marker = parts.index("fstar-base")
        relative_cwd = Path(*parts[marker + 1:])
        warn_args = []
        index = 1
        while index < len(raw):
            if raw[index] == "--warn_error":
                warn_args.extend(raw[index:index + 2])
                index += 2
            else:
                index += 1
        workload = {
            "relative_cwd": str(relative_cwd),
            "source_arg": source_arg,
            "source_sha256": sha256(root / relative_cwd / source_arg),
            "warn_args": warn_args[2:],
            "ramon_sha256": ramon["sha256"],
        }
    for repeat in repeats:
        order = list(modes)
        if repeat % 2:
            order.reverse()
        for mode in order:
            run_dir = args.output / f"{repeat}-{mode}"
            cache = run_dir / "cache"
            generated = run_dir / "output"
            cache.mkdir(parents=True)
            generated.mkdir()
            env = environment.copy()
            if mode == "flat":
                env["FSTAR_FLAT_ROOT_DIAGNOSTIC"] = "1"
            if args.kind == "dependency":
                cwd = root / workload["directory"]
                command = [
                    str(binary), "--z3version", "5.3.0",
                    "--smt", str(args.z3.resolve()), "--silent",
                    "--odir", str(generated), "--cache_dir", str(cache),
                    "--already_cached", "Prims,FStar",
                    "--warn_error", "-321", "--warn_error", "-240",
                    "--dep", "full", *workload["sources"],
                    "-o", str(run_dir / ".depend"),
                ]
            else:
                cwd = root / workload["relative_cwd"]
                source = (cwd / workload["source_arg"]).resolve()
                heap = run_dir / "fstar.fstarmem"
                env["FSTAR_MEM_REPORT"] = str(heap)
                command = [
                    str(binary), "--z3version", "5.3.0",
                    "--smt", str(args.z3.resolve()), "--silent",
                    "--odir", str(generated), "--cache_dir", str(cache),
                    "--already_cached", "Prims,FStar",
                    "--warn_error", "-321", *workload["warn_args"],
                    "-c", str(source),
                    "-o", str(cache / f"{source.name}.checked"),
                ]
            log = run_dir / "run.log"
            measured = monitor(command, cwd, env, log, 600)
            row = {
                "mode": mode,
                "repeat": repeat,
                "kind": args.kind,
                "command": command,
                "cwd": str(cwd),
                "log_sha256": sha256(log),
                **measured,
            }
            if args.instrumented:
                match = re.search(
                    r"PR4797_FLAT_DIAG mode=(\w+) relative_calls=(\d+) "
                    r"relative_seconds=([0-9.]+) filename_chars=(\d+) "
                    r"flat_probes=(\d+) "
                    r"flat_dirnames=(\d+) trie_nodes=(\d+) "
                    r"trie_hash_probes=(\d+) index_builds=(\d+) "
                    r"roots=(\d+) allocated_bytes=([0-9.]+) "
                    r"minor_words=([0-9.]+) promoted_words=([0-9.]+) "
                    r"major_words=([0-9.]+) minor_collections=(\d+) "
                    r"major_collections=(\d+) compactions=(\d+) "
                    r"heap_words=(\d+) top_heap_words=(\d+)",
                    log.read_text(),
                )
                if match is None:
                    raise RuntimeError("diagnostic counters missing")
                names = (
                    "reported_mode", "relative_calls", "relative_seconds",
                    "filename_chars",
                    "flat_probes", "flat_dirnames", "trie_nodes",
                    "trie_hash_probes", "index_builds", "roots",
                    "allocated_bytes", "minor_words", "promoted_words",
                    "major_words", "minor_collections",
                    "major_collections", "compactions", "heap_words",
                    "top_heap_words",
                )
                row["diagnostic"] = dict(zip(names, match.groups()))
            if args.kind == "long":
                match = re.search(
                    r"fstar\.mempeak\s+([0-9]+)",
                    (run_dir / "fstar.fstarmem").read_text(),
                )
                row["fstar_heap_peak_bytes"] = int(match.group(1))
            write_row(measurements, row)
            if measured["returncode"] != 0 or measured["timed_out"]:
                raise RuntimeError(f"{repeat}/{mode} failed")
            shutil.rmtree(cache)
            shutil.rmtree(generated)
    provenance = {
        "kind": args.kind,
        "cpu": args.cpu,
        "repetitions": args.repetitions,
        "seed": args.seed,
        "worktree": str(root),
        "head": head,
        "binary_sha256": sha256(binary),
        "instrumented": args.instrumented,
        "z3_sha256": sha256(args.z3.resolve()),
        "workload": workload,
        "script_sha256": sha256(Path(__file__)),
        "monitor_sha256": sha256(
            Path(__file__).resolve().parent / "run_latest_outliers.py"
        ),
    }
    if args.instrumented:
        provenance["instrument_script_sha256"] = sha256(
            Path(__file__).resolve().parent
            / "instrument_flat_same_binary.py"
        )
    (args.output / "provenance.json").write_text(
        json.dumps(provenance, indent=2) + "\n"
    )


if __name__ == "__main__":
    main()
