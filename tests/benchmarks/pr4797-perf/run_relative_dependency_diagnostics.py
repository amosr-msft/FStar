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


BINARIES = {
    "base":
        "b99ab180501a80e7032a38413ad8798dbc9693a864947bd1820efe980914ae3b",
    "head":
        "07ff02fe863e59a2937908d79c3b5c8da5e5d04b566731b75719c3a38726c421",
}


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_monitor():
    path = Path(__file__).resolve().parent / "run_latest_outliers.py"
    spec = importlib.util.spec_from_file_location("latest_outliers", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.monitor


def counters(path):
    text = path.read_text()
    patterns = {
        "module_name":
            r"PR4797_MODULE_NAME calls=([0-9]+) seconds=([0-9.]+)",
        "source_file_name":
            r"PR4797_DEP_SOURCE_NAMES calls=([0-9]+) seconds=([0-9.]+)",
        "relative_source":
            r"PR4797_RELATIVE_SOURCE calls=([0-9]+) seconds=([0-9.]+)",
    }
    result = {}
    for name, pattern in patterns.items():
        match = re.search(pattern, text)
        if match is not None:
            result[name] = {
                "calls": int(match.group(1)),
                "seconds": float(match.group(2)),
            }
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--head", type=Path, required=True)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cpu", type=int, default=16)
    parser.add_argument("--repetitions", type=int, default=3)
    args = parser.parse_args()
    roots = {"base": args.base.resolve(), "head": args.head.resolve()}
    binaries = {
        variant:
            root / "stage3/dune/_build/default/fstarc-full/fstarc3_full.exe"
        for variant, root in roots.items()
    }
    for variant, binary in binaries.items():
        if sha256(binary) != BINARIES[variant]:
            raise RuntimeError(f"{variant}: diagnostic binary differs")
    campaign = args.campaign.resolve()
    provenance = json.loads((campaign / "provenance.json").read_text())
    sources = provenance["source_arguments"]
    args.output.mkdir(parents=True, exist_ok=True)
    if any(args.output.iterdir()):
        raise RuntimeError("output must be empty")
    os.sched_setaffinity(0, {args.cpu})
    environment = os.environ.copy()
    environment.update({"LC_ALL": "C", "LANG": "C"})
    monitor = load_monitor()
    randomizer = random.Random(4808)
    measurements = args.output / "measurements.jsonl"
    repeats = list(range(1, args.repetitions + 1))
    randomizer.shuffle(repeats)
    for repeat in repeats:
        for variant in randomizer.sample(list(roots), len(roots)):
            root = roots[variant]
            cwd = root / "tests/bug-reports/closed"
            run_dir = args.output / f"{repeat}-{variant}"
            cache = run_dir / "cache"
            generated = run_dir / "output"
            cache.mkdir(parents=True)
            generated.mkdir()
            command = [
                str(binaries[variant]),
                "--z3version", "5.3.0",
                "--smt",
                "/workspace/wt11/benchmark-tools/bin/z3-5.3.0",
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
                "counters": counters(log),
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
    result = {
        "cpu": args.cpu,
        "repetitions": args.repetitions,
        "campaign_provenance_sha256": sha256(
            campaign / "provenance.json"
        ),
        "source_manifest_sha256": hashlib.sha256(
            "\n".join(sources).encode()
        ).hexdigest(),
        "variants": {
            variant: {
                "root": str(root),
                "binary_sha256": sha256(binaries[variant]),
            }
            for variant, root in roots.items()
        },
        "measurements_sha256": sha256(measurements),
        "script_sha256": sha256(Path(__file__)),
        "instrument_find_sha256": sha256(
            Path(__file__).resolve().parent
            / "instrument_dependency_source_names.py"
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
