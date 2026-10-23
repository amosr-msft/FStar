#!/usr/bin/env python3

import argparse
import json
import os
import random
import re
import subprocess
import time
from pathlib import Path


VARIANTS = ("original-a", "original-b", "fusion", "combined")
MODULES = ("BenchBvLive500", "BenchUIntLive500")


def external_fstar_running(own):
    own = own.resolve()
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            executable = (entry / "exe").resolve()
        except OSError:
            continue
        if (
            executable != own
            and executable.name.startswith("fstar")
            and executable.name.endswith(".exe")
        ):
            return True
    return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--worktree-prefix", type=Path, required=True)
    parser.add_argument("--instrumented-dir", type=Path, required=True)
    parser.add_argument("--generated", type=Path, required=True)
    parser.add_argument("--cache-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--z3-bin-dir", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, default=2)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment["PATH"] = f"{args.z3_bin_dir.resolve()}:{environment['PATH']}"
    environment["FSTAR_SHARING_ANALYSIS"] = "1"
    jobs = [
        (variant, module, mode, repeat)
        for repeat in range(1, args.repetitions + 1)
        for variant in VARIANTS
        for module in MODULES
        for mode in ("write", "no-write")
    ]
    random.Random(4768).shuffle(jobs)
    rows = []
    for variant, module, mode, repeat in jobs:
        compiler = args.instrumented_dir / f"fstar-{variant}.exe"
        worktree = Path(f"{args.worktree_prefix}-{variant}")
        cache = args.cache_root / f"cache-{variant}"
        (cache / f"{module}.fst.checked").unlink(missing_ok=True)
        while external_fstar_running(compiler):
            time.sleep(5)
        stem = f"{repeat}-{module}-{variant}-{mode}"
        log_file = args.output / f"{stem}.log"
        time_file = args.output / f"{stem}.time"
        command = [
            "/usr/bin/time", "-v", "-o", str(time_file),
            "env", "OCAMLRUNPARAM=v=0x400", "FSTAR_SHARING_ANALYSIS=1",
            str(compiler), "--z3version", "5.3.0",
            "--smt", str(args.z3_bin_dir.resolve() / "z3-5.3.0"),
            "--smtencoding.elim_box", "true",
            "--include", str(worktree / "stage3/out/lib/fstar/ulib"),
            "--include", str(worktree / "stage3/out/lib/fstar/ulib.checked"),
            "--include", str(args.generated),
            "--cache_dir", str(cache), "--odir", str(cache),
            "--already_cached", "Prims,FStar",
        ]
        if mode == "write":
            command.append("--cache_checked_modules")
        command.append(str(args.generated / f"{module}.fst"))
        with log_file.open("w") as log:
            completed = subprocess.run(
                command, env=environment, stdout=log, stderr=subprocess.STDOUT
            )
        if completed.returncode != 0:
            raise RuntimeError(f"{stem} failed; see {log_file}")
        text = log_file.read_text()
        phases = {}
        for name, wall, cpu in re.findall(
            r"SHARING_PHASE,([^,]+),([0-9.]+),([0-9.]+)", text
        ):
            phases[f"{name}_wall_ms"] = float(wall)
            phases[f"{name}_cpu_ms"] = float(cpu)
        for values in re.findall(
            r"SHARING_ANALYSIS,(decls|index),([0-9.]+),([0-9.]+),"
            r"([0-9.]+),([0-9.]+),([0-9.]+),(\d+),(\d+),(\d+),(\d+)",
            text,
        ):
            phase, wall, cpu, allocated, promoted, major, minor_gc, major_gc, heap, peak = values
            phases[f"{phase}_wall_ms"] = float(wall)
            phases[f"{phase}_allocated_words"] = int(float(allocated))
            phases[f"{phase}_heap_words_after"] = int(heap)
            phases[f"{phase}_top_heap_words_after"] = int(peak)
        timing = time_file.read_text()
        elapsed = re.search(r"Elapsed.*: (?:(\d+):)?(\d+):([0-9.]+)", timing)
        wall = (
            3600 * int(elapsed.group(1) or 0)
            + 60 * int(elapsed.group(2))
            + float(elapsed.group(3))
        )
        value = lambda pattern: int(re.search(pattern, text, re.M).group(1))
        rows.append({
            "variant": variant, "module": module, "mode": mode, "repeat": repeat,
            "command": command, "wall_seconds": wall,
            "allocated_words": value(r"^allocated_words: (\d+)$"),
            "promoted_words": value(r"^promoted_words: (\d+)$"),
            "major_words": value(r"^major_words: (\d+)$"),
            "minor_collections": value(r"^minor_collections: (\d+)$"),
            "major_collections": value(r"^major_collections: (\d+)$"),
            "top_heap_words": value(r"^top_heap_words: (\d+)$"),
            **phases,
        })
    (args.output / "measurements.json").write_text(json.dumps(rows, indent=2))


if __name__ == "__main__":
    main()
