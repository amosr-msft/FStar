#!/usr/bin/env python3

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fstar", type=Path, required=True)
    parser.add_argument("--worktree", type=Path, required=True)
    parser.add_argument("--z3", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--count", type=int, default=1024)
    parser.add_argument("--no-ambients", action="store_true")
    parser.add_argument("--debug-pruning", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    worktree = args.worktree.resolve()
    ulib = worktree / "stage2/out/lib/fstar/ulib"
    checked = worktree / "stage2/out/lib/fstar/ulib.checked"
    if not ulib.is_dir() or not checked.is_dir():
        parser.error("--worktree lacks matching stage2 ulib directories")
    generated = args.output / "generated"
    generated.mkdir(parents=True, exist_ok=True)
    source = generated / f"SimpleAgreement{args.count}.fst"
    if not source.exists():
        subprocess.run([
            "python", str(root / "generate_simple.py"),
            "--output", str(generated), "--count", str(args.count),
        ], check=True)
    provenance = {
        "fstar_sha256": sha256(args.fstar),
        "z3_sha256": sha256(args.z3),
        "source_sha256": sha256(source),
        "instrumenter_sha256": sha256(root / "instrument_context.py"),
        "runner_sha256": sha256(Path(__file__)),
        "worktree_commit": subprocess.check_output(
            ["git", "-C", str(worktree), "rev-parse", "HEAD"], text=True
        ).strip(),
        "prims_checked_sha256": sha256(checked / "Prims.fst.checked"),
        "no_ambients": args.no_ambients,
        "debug_pruning": args.debug_pruning,
    }
    provenance_file = args.output / "provenance.json"
    if provenance_file.exists():
        if json.loads(provenance_file.read_text()) != provenance:
            raise RuntimeError("incompatible provenance")
    else:
        provenance_file.write_text(json.dumps(provenance, indent=2) + "\n")
    log_file = args.output / "trace.log"
    time_file = args.output / "trace.time"
    environment = os.environ.copy()
    environment["FSTAR_CONTEXT_TRACE"] = "1"
    command = [
        "/usr/bin/time", "-v", "-o", str(time_file),
        str(args.fstar), "--z3version", "5.3.0", "--smt", str(args.z3),
        "--include", str(ulib), "--include", str(checked),
        "--timing", "--query_stats", str(source),
    ]
    if args.no_ambients:
        command[-1:-1] = ["--ext", "context_pruning_no_ambients"]
    if args.debug_pruning:
        command[-1:-1] = ["--ext", "debug_context_pruning"]
    with log_file.open("w") as log:
        process = subprocess.run(
            command, env=environment, stdout=log, stderr=subprocess.STDOUT
        )
    if process.returncode != 0:
        raise RuntimeError(f"trace failed; see {log_file}")
    text = log_file.read_text()
    events = []
    for line in text.splitlines():
        if line.startswith("CONTEXT_"):
            events.append(line)
    if not events:
        raise RuntimeError("instrumented compiler emitted no context events")
    (args.output / "events.json").write_text(
        json.dumps({"command": command, "events": events}, indent=2) + "\n"
    )


if __name__ == "__main__":
    main()
