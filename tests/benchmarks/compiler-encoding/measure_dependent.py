#!/usr/bin/env python3

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import time
from pathlib import Path


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fstar", type=Path, required=True)
    parser.add_argument("--z3version", default="5.3.0")
    parser.add_argument("--smt", type=Path, required=True)
    parser.add_argument("--dependency", type=Path, required=True)
    parser.add_argument("--child", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--module", required=True)
    parser.add_argument("--child-module", required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--mode", choices=["metadata", "rooted"], required=True)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()
    if re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9_.-]*[A-Za-z0-9])?", args.label) is None:
        parser.error("--label must be one safe path component")
    for option, module in (("--module", args.module), ("--child-module", args.child_module)):
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)*", module) is None:
            parser.error(f"{option} is not a valid F* module name")

    root = Path(__file__).resolve().parent
    generated = root / "_generated"
    results_root = root / "_results" / "dependent-load"
    label_dir = results_root / args.label
    results = label_dir / args.mode
    for path in (root / "_results", results_root, label_dir, results):
        if path.is_symlink():
            parser.error(f"results path must not contain symlinks: {path}")
    cache = results / "cache"
    for input_path in (args.dependency, args.child, args.target, args.fstar, args.smt):
        if input_path.resolve().is_relative_to(results.resolve()):
            parser.error(f"input path must be outside the recreated results directory: {input_path}")
    if results.exists():
        shutil.rmtree(results)
    cache.mkdir(parents=True)
    dependency_cache = cache / f"{args.module}.fst.checked"
    child_cache = cache / f"{args.child_module}.fst.checked"
    for destination in (dependency_cache, child_cache):
        if not destination.resolve().is_relative_to(cache.resolve()):
            parser.error(f"cache destination escapes isolated cache: {destination}")
    shutil.copyfile(args.dependency, dependency_cache)
    shutil.copyfile(args.child, child_cache)
    provenance = {
        "dependency_sha256": sha256(dependency_cache),
        "child_sha256": sha256(child_cache),
        "target_sha256": sha256(args.target),
        "fstar_sha256": sha256(args.fstar),
        "smt_sha256": sha256(args.smt),
    }

    command = [
        str(args.fstar),
        "--z3version", args.z3version,
        "--smtencoding.elim_box", "true",
        "--include", str(generated),
        "--include", str(root),
        "--cache_dir", str(cache),
        "--odir", str(cache),
        "--already_cached", f"Prims,FStar,{args.child_module},{args.module}",
        "--debug", "CheckedFiles",
        "--query_stats",
    ]
    if args.smt:
        command += ["--smt", str(args.smt)]
    if args.mode == "metadata":
        command += ["--admit_smt_queries", "true"]
    command.append(str(args.target))
    fstar_version = subprocess.run(
        [str(args.fstar), "--version"], text=True, capture_output=True, check=True
    ).stdout.strip()
    smt_version = subprocess.run(
        [str(args.smt), "--version"], text=True, capture_output=True, check=True
    ).stdout.strip()

    measurements = results / "measurements.jsonl"
    measurements.unlink(missing_ok=True)
    for repeat in range(1, args.repeats + 1):
        target_cache = cache / f"{args.target.name}.checked"
        target_cache.unlink(missing_ok=True)
        time_file = results / f"repeat-{repeat}.time"
        timed_command = [
            "/usr/bin/time", "-v", "-o", str(time_file),
            "timeout", "--kill-after=5s", f"{args.timeout}s",
        ] + command
        started = time.monotonic()
        completed = subprocess.run(timed_command, text=True, capture_output=True)
        elapsed = time.monotonic() - started
        log = results / f"repeat-{repeat}.log"
        log.write_text(completed.stdout + completed.stderr)
        if completed.returncode != 0:
            raise RuntimeError(f"repeat {repeat} failed; see {log}")
        time_text = time_file.read_text()
        rss_match = re.search(r"Maximum resident set size \(kbytes\): (\d+)", time_text)
        if rss_match is None:
            raise RuntimeError(f"missing peak RSS in {time_file}")
        row = {
            "repeat": repeat,
            "wall_seconds": elapsed,
            "peak_rss_kb": int(rss_match.group(1)),
            **provenance,
            "fstar_version": fstar_version,
            "smt_version": smt_version,
            "command": command,
        }
        with measurements.open("a") as stream:
            stream.write(json.dumps(row, sort_keys=True) + "\n")
        print(f"{args.label} {args.mode} #{repeat}: {elapsed:.3f}s, {row['peak_rss_kb'] / 1024:.1f} MiB")


if __name__ == "__main__":
    main()
