#!/usr/bin/env python3

import argparse
import json
import os
import random
import re
import subprocess
from pathlib import Path


VARIANTS = ("master", "interning")
MODULES = ("BenchBvLive500", "BenchUIntLive500")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--master-worktree", type=Path, required=True)
    parser.add_argument("--interning-worktree", type=Path, required=True)
    parser.add_argument("--instrumented-dir", type=Path, required=True)
    parser.add_argument("--generated", type=Path, required=True)
    parser.add_argument("--cache-root", type=Path, required=True)
    parser.add_argument("--z3", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, default=3)
    args = parser.parse_args()
    roots = {
        "master": args.master_worktree.resolve(),
        "interning": args.interning_worktree.resolve(),
    }
    binaries = {
        "master": args.instrumented_dir / "fstar-no-intern.exe",
        "interning": args.instrumented_dir / "fstar-interning.exe",
    }
    args.output.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment["FSTAR_SHARING_ANALYSIS"] = "1"
    jobs = [
        (variant, module, mode, repeat)
        for repeat in range(1, args.repetitions + 1)
        for variant in VARIANTS for module in MODULES
        for mode in ("write", "no-write")
    ]
    random.Random(4770).shuffle(jobs)
    rows = []
    for variant, module, mode, repeat in jobs:
        root = roots[variant]
        cache = args.cache_root / f"cache-{variant}"
        (cache / f"{module}.fst.checked").unlink(missing_ok=True)
        stem = f"{repeat}-{module}-{variant}-{mode}"
        log_file = args.output / f"{stem}.log"
        time_file = args.output / f"{stem}.time"
        command = [
            "/usr/bin/time", "-v", "-o", str(time_file),
            "env", "OCAMLRUNPARAM=v=0x400", "FSTAR_SHARING_ANALYSIS=1",
            str(binaries[variant]), "--z3version", "5.3.0",
            "--smt", str(args.z3.resolve()), "--smtencoding.elim_box", "true",
            "--query_stats", "--profile", module,
            "--profile_component", "FStarC.CheckedFiles",
            "--profile_component", "FStarC.TypeChecker",
            "--profile_component", "FStarC.SMTEncoding",
            "--include", str(root / "stage3/out/lib/fstar/ulib"),
            "--include", str(root / "stage3/out/lib/fstar/ulib.checked"),
            "--include", str(args.generated), "--cache_dir", str(cache),
            "--odir", str(cache), "--already_cached", "Prims,FStar",
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
        phase_values = {}
        for name, wall, cpu in re.findall(
            r"SHARING_PHASE,([^,]+),([0-9.]+),([0-9.]+)", text
        ):
            phase_values[f"{name}_wall_ms"] = float(wall)
            phase_values[f"{name}_cpu_ms"] = float(cpu)
        sharing = re.search(
            r"SHARING_ANALYSIS,decls,([0-9.]+),([0-9.]+),([0-9.]+),"
            r"([0-9.]+),([0-9.]+),(\d+),(\d+),(\d+),(\d+)", text
        )
        if sharing:
            phase_values["intern_decls_wall_ms"] = float(sharing.group(1))
            phase_values["intern_decls_allocated_words"] = int(float(sharing.group(3)))
        value = lambda pattern: int(re.search(pattern, text, re.M).group(1))
        counter = lambda name: int(re.search(
            re.escape(module) + r", profiled " + re.escape(name) + r":\s+(\d+) ms",
            text,
        ).group(1))
        timing = time_file.read_text()
        elapsed = re.search(r"Elapsed.*: (?:(\d+):)?(\d+):([0-9.]+)", timing)
        wall = (
            3600 * int(elapsed.group(1) or 0)
            + 60 * int(elapsed.group(2))
            + float(elapsed.group(3))
        )
        rows.append({
            "variant": variant, "module": module, "mode": mode, "repeat": repeat,
            "command": command, "wall_seconds": wall,
            "process_one_decl_ms":
                counter("FStarC.TypeChecker.Tc.process_one_decl"),
            "simplify_vc_ms": counter("FStarC.TypeChecker.Rel.simplify_vc"),
            "encode_sig_ms": counter("FStarC.TypeChecker.Tc.encode_sig"),
            "z3_aggregate_ms": sum(int(x) for x in re.findall(
                r"Z3 \(aggregate query time\):\s+(\d+) ms", text
            )),
            "checked_files_ms": sum(int(x) for x in re.findall(
                r"profiled FStarC.CheckedFiles:\s+(\d+) ms", text
            )),
            "allocated_words": value(r"^allocated_words: (\d+)$"),
            "promoted_words": value(r"^promoted_words: (\d+)$"),
            "major_words": value(r"^major_words: (\d+)$"),
            "minor_collections": value(r"^minor_collections: (\d+)$"),
            "major_collections": value(r"^major_collections: (\d+)$"),
            "top_heap_words": value(r"^top_heap_words: (\d+)$"),
            **phase_values,
        })
    (args.output / "measurements.json").write_text(json.dumps(rows, indent=2))


if __name__ == "__main__":
    main()
