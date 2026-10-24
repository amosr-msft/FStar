#!/usr/bin/env python3

import argparse
import fcntl
import hashlib
import json
import os
import random
import re
import subprocess
from pathlib import Path


VARIANTS = ("master", "interning", "candidate")
MODULES = ("BenchBvLive500", "BenchUIntLive500")


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_time(path):
    text = path.read_text()
    elapsed = re.search(r"Elapsed \(wall clock\) time.*: ([0-9:.]+)$", text, re.M)
    fields = elapsed.group(1).split(":")
    seconds = float(fields[-1])
    if len(fields) >= 2:
        seconds += 60 * int(fields[-2])
    if len(fields) == 3:
        seconds += 3600 * int(fields[-3])
    value = lambda pattern: re.search(pattern, text, re.M).group(1)
    return {
        "wall_seconds": seconds,
        "user_seconds": float(value(r"User time \(seconds\): ([0-9.]+)$")),
        "system_seconds": float(value(r"System time \(seconds\): ([0-9.]+)$")),
        "max_rss_kb": int(value(r"Maximum resident set size \(kbytes\): (\d+)$")),
    }


def parse_profile(path):
    text = path.read_text()
    result = {}
    for phase, values in re.findall(
        r"SHARING_ANALYSIS,([^,]+),([0-9.,]+)", text
    ):
        fields = values.split(",")
        result[f"{phase}_wall_ms"] = float(fields[0])
        result[f"{phase}_cpu_ms"] = float(fields[1])
        result[f"{phase}_allocated_words"] = int(float(fields[2]))
    for name in (
        "allocated_words", "promoted_words", "major_words",
        "minor_collections", "major_collections", "top_heap_words",
    ):
        match = re.search(rf"^{name}: ([0-9]+)$", text, re.M)
        if match:
            result[name] = int(match.group(1))
    return result


def provenance(roots, binaries, generated, z3, caches):
    result = {"z3_sha256": sha256(z3)}
    for variant in VARIANTS:
        child_hashes = {}
        for module in MODULES:
            child = module.replace("Live500", "Children")
            child_hashes[child] = sha256(caches[variant] / f"{child}.fst.checked")
        result[variant] = {
            "commit": subprocess.check_output(
                ["git", "-C", str(roots[variant]), "rev-parse", "HEAD"],
                text=True,
            ).strip(),
            "binary_sha256": sha256(binaries[variant]),
            "child_sha256": child_hashes,
        }
    result["sources"] = {
        module: sha256(generated / f"{module}.fst") for module in MODULES
    }
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--master", type=Path, required=True)
    parser.add_argument("--interning", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--instrumented-dir", type=Path)
    parser.add_argument("--generated", type=Path, required=True)
    parser.add_argument("--cache-root", type=Path, required=True)
    parser.add_argument("--z3", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--profile", action="store_true")
    parser.add_argument("--modules", nargs="+", choices=MODULES, default=MODULES)
    parser.add_argument("--variants", nargs="+", choices=VARIANTS, default=VARIANTS)
    parser.add_argument(
        "--modes", nargs="+", choices=("write", "no-write"),
        default=("write", "no-write"),
    )
    args = parser.parse_args()
    roots = {
        "master": args.master.resolve(),
        "interning": args.interning.resolve(),
        "candidate": args.candidate.resolve(),
    }
    if args.profile:
        if args.instrumented_dir is None:
            parser.error("--instrumented-dir is required with --profile")
        binaries = {
            variant: args.instrumented_dir / f"fstar-{variant}.exe"
            for variant in VARIANTS
        }
    else:
        binaries = {
            variant: root / "stage3/out/bin/fstar.exe"
            for variant, root in roots.items()
        }
    caches = {
        variant: args.cache_root / f"cache-{variant}" for variant in VARIANTS
    }
    args.output.mkdir(parents=True, exist_ok=True)
    lock = (args.output / "campaign.lock").open("w")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    campaign_provenance = provenance(
        roots, binaries, args.generated.resolve(), args.z3.resolve(), caches
    )
    provenance_file = args.output / "provenance.json"
    if provenance_file.exists():
        if json.loads(provenance_file.read_text()) != campaign_provenance:
            raise RuntimeError("output directory contains incompatible provenance")
    else:
        provenance_file.write_text(json.dumps(campaign_provenance, indent=2) + "\n")

    results = args.output / "measurements.jsonl"
    completed = set()
    if results.exists():
        for line in results.read_text().splitlines():
            row = json.loads(line)
            completed.add(
                (row["variant"], row["module"], row["mode"], row["repeat"])
            )
    jobs = [
        (variant, module, mode, repeat)
        for repeat in range(1, args.repetitions + 1)
        for variant in args.variants
        for module in args.modules
        for mode in args.modes
        if (variant, module, mode, repeat) not in completed
    ]
    random.Random(4772 if args.profile else 4773).shuffle(jobs)
    environment = os.environ.copy()
    if args.profile:
        environment["FSTAR_SHARING_ANALYSIS"] = "1"
        environment["OCAMLRUNPARAM"] = "v=0x400"
    for variant, module, mode, repeat in jobs:
        cache = caches[variant]
        checked = cache / f"{module}.fst.checked"
        checked.unlink(missing_ok=True)
        stem = f"{repeat}-{module}-{variant}-{mode}"
        log_file = args.output / f"{stem}.log"
        time_file = args.output / f"{stem}.time"
        mem_file = args.output / f"{stem}.fstarmem"
        command = [
            "/usr/bin/time", "-v", "-o", str(time_file),
            str(binaries[variant]), "--z3version", "5.3.0",
            "--smt", str(args.z3.resolve()), "--smtencoding.elim_box", "true",
            "--include", str(roots[variant] / "stage3/out/lib/fstar/ulib"),
            "--include", str(roots[variant] / "stage3/out/lib/fstar/ulib.checked"),
            "--include", str(args.generated.resolve()),
            "--cache_dir", str(cache), "--odir", str(cache),
            "--already_cached", "Prims,FStar",
        ]
        if args.profile:
            command += [
                "--profile", module,
                "--profile_component", "FStarC.SMTEncoding.Sharing",
            ]
        if mode == "write":
            command.append("--cache_checked_modules")
        command.append(str(args.generated.resolve() / f"{module}.fst"))
        environment["FSTAR_MEM_REPORT"] = str(mem_file)
        with log_file.open("w") as log:
            process = subprocess.run(
                command, env=environment, stdout=log, stderr=subprocess.STDOUT
            )
        if process.returncode != 0:
            raise RuntimeError(f"{stem} failed; see {log_file}")
        row = {
            "variant": variant,
            "module": module,
            "mode": mode,
            "repeat": repeat,
            "command": command,
            **parse_time(time_file),
            "fstar_mempeak_bytes": int(mem_file.read_text().split()[1]),
            "checked_bytes": checked.stat().st_size if checked.exists() else 0,
            **(parse_profile(log_file) if args.profile else {}),
        }
        with results.open("a") as stream:
            stream.write(json.dumps(row, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())


if __name__ == "__main__":
    main()
