#!/usr/bin/env python3

import argparse
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
from pathlib import Path


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare_output(path, expected):
    if path.is_symlink():
        raise RuntimeError("output must not be a symlink")
    if path.exists():
        marker = path / "provenance.json"
        if not path.is_dir() or not marker.is_file():
            raise RuntimeError("refusing to replace unmarked output")
        previous = json.loads(marker.read_text())
        if previous != expected:
            raise RuntimeError("existing output provenance differs")
        shutil.rmtree(path)
    path.mkdir(parents=True)


def elapsed(text):
    fields = re.search(
        r"Elapsed \(wall clock\) time.*: ([0-9:.]+)$", text, re.M
    ).group(1).split(":")
    seconds = float(fields[-1])
    if len(fields) >= 2:
        seconds += 60 * int(fields[-2])
    if len(fields) == 3:
        seconds += 3600 * int(fields[-3])
    return seconds


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fstar", type=Path, required=True)
    parser.add_argument("--worktree", type=Path, required=True)
    parser.add_argument("--z3", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, default=5)
    args = parser.parse_args()
    worktree = args.worktree.resolve()
    cleared = (
        "FSTAR_LIB", "FSTAR_HOME", "OCAMLRUNPARAM", "CAMLRUNPARAM",
        "FSTAR_NO_DEDUP_VC", "FSTAR_PRUNING_REFERENCE",
    )
    z3_hash = sha256(args.z3.resolve())
    if z3_hash != (
        "4da6a0f78424098b600a9112ebb9d8ce45de248a4913c26dd7d472e6dabef6d3"
    ):
        raise RuntimeError("unexpected Z3 binary")
    provenance = {
        "runner_sha256": sha256(Path(__file__)),
        "fstar_sha256": sha256(args.fstar.resolve()),
        "fstar_path": str(args.fstar.resolve()),
        "worktree_path": str(worktree),
        "worktree_commit": subprocess.check_output(
            ["git", "-C", str(worktree), "rev-parse", "HEAD"], text=True
        ).strip(),
        "z3_sha256": z3_hash,
        "z3_path": str(args.z3.resolve()),
        "source_sha256": sha256(args.source.resolve()),
        "source_path": str(args.source.resolve()),
        "repetitions": args.repetitions,
        "cleared_environment": list(cleared),
        "prims_checked_sha256": sha256(
            worktree / "stage2/out/lib/fstar/ulib.checked/Prims.fst.checked"
        ),
        "instrumenter_sha256": sha256(
            Path(__file__).resolve().parent
            / "instrument_pruning_reference.py"
        ),
        "extracted_pruning_sha256": sha256(
            worktree / "stage2/fstarc.ml/FStarC_SMTEncoding_Pruning.ml"
        ),
    }
    prepare_output(args.output, provenance)
    (args.output / "provenance.json").write_text(
        json.dumps(provenance, indent=2) + "\n"
    )
    pairs = list(range(1, args.repetitions + 1))
    randomizer = random.Random(4778)
    randomizer.shuffle(pairs)
    plan = []
    for repeat in pairs:
        modes = ["cached", "reference"]
        randomizer.shuffle(modes)
        plan.extend((mode, repeat) for mode in modes)
    results = []
    for mode, repeat in plan:
        stem = f"{repeat}-{mode}"
        time_file = args.output / f"{stem}.time"
        log_file = args.output / f"{stem}.log"
        environment = os.environ.copy()
        for name in cleared:
            environment.pop(name, None)
        selected_environment = {}
        if mode == "reference":
            selected_environment["FSTAR_PRUNING_REFERENCE"] = "1"
            environment.update(selected_environment)
        command = [
            "/usr/bin/time", "-v", "-o", str(time_file),
            str(args.fstar.resolve()), "--z3version", "5.3.0",
            "--smt", str(args.z3.resolve()),
            "--include", str(worktree / "stage2/out/lib/fstar/ulib"),
            "--include", str(worktree / "stage2/out/lib/fstar/ulib.checked"),
            "--force", "--timing", "--query_stats",
            str(args.source.resolve()),
        ]
        with log_file.open("w") as log:
            process = subprocess.run(
                command, env=environment,
                stdout=log, stderr=subprocess.STDOUT,
            )
        if process.returncode != 0:
            raise RuntimeError(f"{stem} failed")
        text = log_file.read_text()
        timing = time_file.read_text()
        results.append({
            "mode": mode,
            "repeat": repeat,
            "wall_seconds": elapsed(timing),
            "user_seconds": float(re.search(
                r"User time \(seconds\): ([0-9.]+)$", timing, re.M
            ).group(1)),
            "system_seconds": float(re.search(
                r"System time \(seconds\): ([0-9.]+)$", timing, re.M
            ).group(1)),
            "max_rss_kb": int(re.search(
                r"Maximum resident set size \(kbytes\): ([0-9]+)$",
                timing, re.M,
            ).group(1)),
            "profiled_declaration_ms": sum(
                int(value) for value in re.findall(
                    r"profiled FStarC\.TypeChecker\.Tc\.process_one_decl:"
                    r"\s+([0-9]+) ms",
                    text,
                )
            ),
            "query_count": len(re.findall(r"Query-stats \(", text)),
            "z3_reported_seconds": sum(
                float(value) for value in re.findall(
                    r"Query-stats .*? succeeded in ([0-9.]+) seconds", text
                )
            ),
            "environment": selected_environment,
            "command": command,
        })
    (args.output / "measurements.json").write_text(
        json.dumps(results, indent=2) + "\n"
    )


if __name__ == "__main__":
    main()
