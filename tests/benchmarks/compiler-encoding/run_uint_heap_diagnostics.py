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


VARIANTS = ("master", "interning")


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def provenance(
    variant, dependency_variant, module, roots, binaries, cache, generated, z3
):
    child = module.replace("Live500", "Children")
    return {
        "compiler_commit": subprocess.check_output(
            ["git", "-C", str(roots[variant]), "rev-parse", "HEAD"], text=True
        ).strip(),
        "compiler_binary_sha256": sha256(binaries[variant]),
        "dependency_commit": subprocess.check_output(
            ["git", "-C", str(roots[dependency_variant]), "rev-parse", "HEAD"],
            text=True,
        ).strip(),
        "dependency_child_sha256": sha256(cache / f"{child}.fst.checked"),
        "source_sha256": sha256(generated / f"{module}.fst"),
        "z3_sha256": sha256(z3),
        "ocamlrunparam": os.environ.get("OCAMLRUNPARAM"),
    }


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


def parse_heap_log(path):
    text = path.read_text()
    snapshots = []
    for match in re.finditer(
        r"HEAP_SNAPSHOT,([^,]+),([0-9]+),([0-9]+),([0-9]+),"
        r"([0-9]+),([0-9]+),([0-9]+),([0-9]+),([0-9]+),"
        r"([0-9]+),([0-9]+),([0-9]+),([0-9]+)",
        text,
    ):
        values = [int(value) for value in match.groups()[1:]]
        snapshots.append(dict(zip(
            (
                "minor_words", "promoted_words", "major_words",
                "minor_collections", "major_collections", "heap_words",
                "top_heap_words", "live_words", "live_blocks", "free_words",
                "fragments", "compactions",
            ),
            values,
        ), name=match.group(1)))
    reachability = []
    for match in re.finditer(
        r"HEAP_REACHABLE,([^,]+),([0-9]+),([0-9]+),([0-9]+),([0-9]+)",
        text,
    ):
        reachability.append({
            "phase": match.group(1),
            "input_words": int(match.group(2)),
            "output_words": int(match.group(3)),
            "union_words": int(match.group(4)),
            "shared_words": int(match.group(5)),
        })
    control = re.search(
        r"HEAP_CONTROL,([0-9]+),([0-9]+),([0-9]+),([0-9]+),"
        r"([0-9]+),([0-9]+),([0-9]+)",
        text,
    )
    file_events = []
    for match in re.finditer(
        r"HEAP_FILE,([^,]+),([^,]+),([0-9]+),([0-9]+),([0-9]+),([0-9]+)",
        text,
    ):
        file_events.append({
            "phase": match.group(1),
            "file": match.group(2),
            "heap_words": int(match.group(3)),
            "top_heap_words": int(match.group(4)),
            "major_collections": int(match.group(5)),
            "minor_collections": int(match.group(6)),
        })
    declaration_events = []
    for match in re.finditer(
        r"HEAP_DECL,([^,]+),([^,]+),([0-9]+),([0-9]+),([0-9]+),([0-9]+)",
        text,
    ):
        declaration_events.append({
            "phase": match.group(1),
            "declaration": match.group(2),
            "heap_words": int(match.group(3)),
            "top_heap_words": int(match.group(4)),
            "major_collections": int(match.group(5)),
            "minor_collections": int(match.group(6)),
        })
    return {
        "snapshots": snapshots,
        "reachability": reachability,
        "file_events": file_events,
        "declaration_events": declaration_events,
        "gc_control": [int(value) for value in control.groups()] if control else None,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--master-worktree", type=Path, required=True)
    parser.add_argument("--interning-worktree", type=Path, required=True)
    parser.add_argument("--instrumented-dir", type=Path)
    parser.add_argument("--generated", type=Path, required=True)
    parser.add_argument("--cache-root", type=Path, required=True)
    parser.add_argument("--z3", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--analysis-mode",
        choices=("lightweight", "snapshot", "forced", "after-cache-gc"),
        required=True,
    )
    parser.add_argument("--modules", nargs="+", required=True)
    parser.add_argument("--modes", nargs="+", choices=("write", "no-write"), required=True)
    parser.add_argument("--repetitions", type=int, required=True)
    parser.add_argument(
        "--cross-dependencies", action="store_true",
        help="Run each compiler against both variants' library and child caches.",
    )
    args = parser.parse_args()
    roots = {
        "master": args.master_worktree.resolve(),
        "interning": args.interning_worktree.resolve(),
    }
    if args.analysis_mode == "lightweight":
        binaries = {
            variant: root / "stage3/out/bin/fstar.exe"
            for variant, root in roots.items()
        }
    else:
        if args.instrumented_dir is None:
            parser.error("--instrumented-dir is required for heap analysis")
        binaries = {
            "master": args.instrumented_dir / "fstar-no-intern.exe",
            "interning": args.instrumented_dir / "fstar-interning.exe",
        }
    args.output.mkdir(parents=True, exist_ok=True)
    lock = (args.output / "campaign.lock").open("w")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    results = args.output / "measurements.jsonl"
    completed = set()
    if results.exists():
        for line in results.read_text().splitlines():
            row = json.loads(line)
            if "provenance" not in row:
                raise RuntimeError(
                    f"{results} predates provenance validation; use a new output directory"
                )
            dependency_variant = row.get("dependency_variant", row["variant"])
            current = provenance(
                row["variant"], dependency_variant, row["module"], roots,
                binaries, args.cache_root / f"cache-{dependency_variant}",
                args.generated.resolve(), args.z3.resolve(),
            )
            if row["provenance"] != current:
                raise RuntimeError(
                    f"{results} contains incompatible completed observations"
                )
            completed.add((
                row["analysis_mode"], row["variant"],
                row.get("dependency_variant", row["variant"]), row["module"],
                row["mode"], row["repeat"],
            ))
    dependency_variants = VARIANTS if args.cross_dependencies else (None,)
    jobs = [
        (variant, dependency_variant or variant, module, mode, repeat)
        for repeat in range(1, args.repetitions + 1)
        for variant in VARIANTS
        for dependency_variant in dependency_variants
        for module in args.modules
        for mode in args.modes
        if (
            args.analysis_mode, variant, dependency_variant or variant,
            module, mode, repeat,
        ) not in completed
    ]
    random.Random(4771 + len(completed)).shuffle(jobs)
    for variant, dependency_variant, module, mode, repeat in jobs:
        dependency_root = roots[dependency_variant]
        cache = args.cache_root / f"cache-{dependency_variant}"
        run_provenance = provenance(
            variant, dependency_variant, module, roots, binaries, cache,
            args.generated.resolve(), args.z3.resolve(),
        )
        checked = cache / f"{module}.fst.checked"
        checked.unlink(missing_ok=True)
        stem = (
            f"{args.analysis_mode}-{repeat}-{module}-{variant}-"
            f"deps-{dependency_variant}-{mode}"
        )
        log_file = args.output / f"{stem}.log"
        time_file = args.output / f"{stem}.time"
        mem_file = args.output / f"{stem}.fstarmem"
        environment = os.environ.copy()
        environment["FSTAR_MEM_REPORT"] = str(mem_file)
        if args.analysis_mode != "lightweight":
            environment["FSTAR_SHARING_ANALYSIS"] = "1"
            environment["FSTAR_HEAP_ANALYSIS"] = "1"
        if args.analysis_mode == "forced":
            environment["FSTAR_HEAP_FORCE_GC"] = "1"
            environment["FSTAR_HEAP_REACHABLE"] = "1"
        if args.analysis_mode == "after-cache-gc":
            environment["FSTAR_HEAP_FORCE_AFTER_BENCH_CACHE"] = "1"
        command = [
            "/usr/bin/time", "-v", "-o", str(time_file),
            str(binaries[variant]), "--z3version", "5.3.0",
            "--smt", str(args.z3.resolve()), "--smtencoding.elim_box", "true",
            "--include", str(dependency_root / "stage3/out/lib/fstar/ulib"),
            "--include", str(dependency_root / "stage3/out/lib/fstar/ulib.checked"),
            "--include", str(args.generated), "--cache_dir", str(cache),
            "--odir", str(cache), "--already_cached", "Prims,FStar",
        ]
        if mode == "write":
            command.append("--cache_checked_modules")
        command.append(str(args.generated / f"{module}.fst"))
        with log_file.open("w") as log:
            process = subprocess.run(
                command, env=environment, stdout=log, stderr=subprocess.STDOUT
            )
        if process.returncode != 0:
            raise RuntimeError(f"{stem} failed; see {log_file}")
        row = {
            "analysis_mode": args.analysis_mode,
            "variant": variant,
            "dependency_variant": dependency_variant,
            "module": module,
            "mode": mode,
            "repeat": repeat,
            "provenance": run_provenance,
            "command": command,
            **parse_time(time_file),
            "fstar_mempeak_bytes": int(mem_file.read_text().split()[1]),
            "checked_bytes": checked.stat().st_size if checked.exists() else 0,
            **parse_heap_log(log_file),
        }
        with results.open("a") as stream:
            stream.write(json.dumps(row, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())


if __name__ == "__main__":
    main()
