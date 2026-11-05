#!/usr/bin/env python3

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
from pathlib import Path


COMMIT = "7da01c0b4ae5cf447f6951ddb38714b7f1969a35"
COMPILER = "1454cca09e8f96f2c8a6fe3aab2812c55dd0d971a49d1cf3a4cb2bb4be3e9377"


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_monitor():
    path = Path(__file__).resolve().parent / "run_latest_outliers.py"
    spec = importlib.util.spec_from_file_location("latest_outliers", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.monitor


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--worktree", type=Path, required=True)
    parser.add_argument("--fstar", type=Path, required=True)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cpu", type=int, default=16)
    parser.add_argument("--repetitions", type=int, default=3)
    args = parser.parse_args()
    worktree = args.worktree.resolve()
    fstar = args.fstar.resolve()
    if subprocess.run([
        "git", "-C", str(worktree), "merge-base", "--is-ancestor",
        COMMIT, "HEAD",
    ]).returncode != 0:
        raise RuntimeError("unexpected worktree ancestry")
    if subprocess.run([
        "git", "-C", str(worktree), "diff", "--quiet", COMMIT,
        "--", "src", "ulib", "pulse",
    ]).returncode != 0:
        raise RuntimeError("production sources differ")
    if sha256(fstar) != COMPILER:
        raise RuntimeError("diagnostic compiler differs")
    campaign = args.campaign.resolve()
    campaign_provenance = json.loads(
        (campaign / "provenance.json").read_text()
    )
    sources = campaign_provenance["source_arguments"]
    source_sha256 = {
        source: sha256(
            worktree / "tests/bug-reports/closed" / source
        )
        for source in sources
    }
    z3 = Path("/workspace/wt11/benchmark-tools/bin/z3-5.3.0")
    if sha256(z3) != (
        "4da6a0f78424098b600a9112ebb9d8ce45de248a4913c26dd7d472e6dabef6d3"
    ):
        raise RuntimeError("unexpected Z3")
    args.output.mkdir(parents=True, exist_ok=True)
    if any(args.output.iterdir()):
        raise RuntimeError("output must be empty")
    os.sched_setaffinity(0, {args.cpu})
    environment = os.environ.copy()
    environment.update({"LC_ALL": "C", "LANG": "C"})
    monitor = load_monitor()
    measurements = args.output / "measurements.jsonl"
    patterns = {
        "module_name":
            r"PR4797_MODULE_NAME calls=([0-9]+) seconds=([0-9.]+)",
        "ownership":
            r"PR4797_OWNERSHIP calls=([0-9]+) misses=([0-9]+) "
            r"source_calls=([0-9]+) source_misses=([0-9]+)",
        "source_time":
            r"PR4797_SOURCE_TIME seconds=([0-9.]+)",
    }
    for repeat in range(1, args.repetitions + 1):
        run_dir = args.output / str(repeat)
        cache = run_dir / "cache"
        generated = run_dir / "output"
        cache.mkdir(parents=True)
        generated.mkdir()
        command = [
            str(fstar),
            "--z3version", "5.3.0",
            "--smt", str(z3),
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
        cwd = worktree / "tests/bug-reports/closed"
        log = run_dir / "run.log"
        measured = monitor(command, cwd, environment, log, 180)
        text = log.read_text()
        counters = {}
        for name, pattern in patterns.items():
            match = re.search(pattern, text)
            if match is None:
                raise RuntimeError(f"{name}: counters missing")
            counters[name] = [float(value) for value in match.groups()]
        row = {
            "repeat": repeat,
            "command": command,
            "cwd": str(cwd),
            "log_sha256": sha256(log),
            "counters": counters,
            **measured,
        }
        with measurements.open("a") as stream:
            stream.write(json.dumps(row, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        if measured["returncode"] != 0 or measured["timed_out"]:
            raise RuntimeError(f"repeat {repeat} failed")
        shutil.rmtree(cache)
        shutil.rmtree(generated)
    result = {
        "cpu": args.cpu,
        "repetitions": args.repetitions,
        "worktree": str(worktree),
        "worktree_head": subprocess.check_output(
            ["git", "-C", str(worktree), "rev-parse", "HEAD"], text=True
        ).strip(),
        "compiler_commit": COMMIT,
        "compiler_path": str(fstar),
        "compiler_sha256": sha256(fstar),
        "source_manifest_sha256": hashlib.sha256(
            "\n".join(sources).encode()
        ).hexdigest(),
        "source_sha256": source_sha256,
        "z3_path": str(z3),
        "z3_sha256": sha256(z3),
        "campaign_provenance_sha256": sha256(
            campaign / "provenance.json"
        ),
        "measurements_sha256": sha256(measurements),
        "script_sha256": sha256(Path(__file__)),
        "instrument_cache_sha256": sha256(
            Path(__file__).resolve().parent
            / "instrument_ownership_cache.py"
        ),
        "instrument_dep_sha256": sha256(
            Path(__file__).resolve().parent
            / "instrument_module_name_path.py"
        ),
    }
    (args.output / "result.json").write_text(
        json.dumps(result, indent=2) + "\n"
    )


if __name__ == "__main__":
    main()
