#!/usr/bin/env python3

import argparse
import hashlib
import json
import os
import random
import resource
import subprocess
import time
from pathlib import Path


EXPECTED_COMMITS = {
    "base": "c68959fe1f070cd66a5ed2e92965185505f109ce",
    "head": "e2c45ed0c4099f8d27ef0d78641ca8b626f4cdcb",
}


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def usage():
    current = resource.getrusage(resource.RUSAGE_CHILDREN)
    return {
        "user_seconds": current.ru_utime,
        "system_seconds": current.ru_stime,
        "voluntary_context_switches": current.ru_nvcsw,
        "involuntary_context_switches": current.ru_nivcsw,
    }


def subtract(after, before):
    return {key: after[key] - before[key] for key in after}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--head", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cpu", type=int, default=16)
    parser.add_argument("--batches", type=int, default=5)
    parser.add_argument("--iterations", type=int, default=1000)
    args = parser.parse_args()
    roots = {"base": args.base.resolve(), "head": args.head.resolve()}
    binaries = {
        variant: root / "stage2/out/bin/fstar.exe"
        for variant, root in roots.items()
    }
    commits = {
        variant: subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
        ).strip()
        for variant, root in roots.items()
    }
    if commits != EXPECTED_COMMITS:
        raise RuntimeError("unexpected revisions")
    if any(
        subprocess.run(
            ["git", "-C", str(root), "diff", "--quiet"],
            check=False,
        ).returncode != 0
        or subprocess.run(
            ["git", "-C", str(root), "diff", "--cached", "--quiet"],
            check=False,
        ).returncode != 0
        for root in roots.values()
    ):
        raise RuntimeError("benchmark worktrees have tracked changes")
    os.sched_setaffinity(0, {args.cpu})
    environment = os.environ.copy()
    for name in (
        "FSTAR_LIB",
        "FSTAR_HOME",
        "OCAMLRUNPARAM",
        "CAMLRUNPARAM",
        "LD_PRELOAD",
        "LD_LIBRARY_PATH",
        "OCAMLPATH",
        "CAML_LD_LIBRARY_PATH",
    ):
        environment.pop(name, None)
    environment.update({"LC_ALL": "C", "LANG": "C"})
    for variant in roots:
        for _ in range(10):
            subprocess.run(
                [str(binaries[variant]), "--version"],
                env=environment,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
            )
    randomizer = random.Random(4797)
    order = [
        variant
        for repeat in range(1, args.batches + 1)
        for variant in randomizer.sample(list(roots), len(roots))
    ]
    rows = []
    for index, variant in enumerate(order):
        before = usage()
        started = time.monotonic()
        for _ in range(args.iterations):
            subprocess.run(
                [str(binaries[variant]), "--version"],
                env=environment,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
            )
        elapsed = time.monotonic() - started
        row = {
            "variant": variant,
            "repeat": index // len(roots) + 1,
            "iterations": args.iterations,
            "wall_seconds": elapsed,
            **subtract(usage(), before),
        }
        rows.append(row)
    output = {
        "cpu": args.cpu,
        "batches": args.batches,
        "iterations_per_batch": args.iterations,
        "order": order,
        "rows": rows,
        "variants": {
            variant: {
                "root": str(root),
                "commit": commits[variant],
                "binary_sha256": sha256(binaries[variant]),
                "version": subprocess.check_output(
                    [str(binaries[variant]), "--version"],
                    env=environment,
                    text=True,
                ).strip(),
            }
            for variant, root in roots.items()
        },
        "environment": {"LC_ALL": "C", "LANG": "C"},
        "script_sha256": sha256(Path(__file__)),
    }
    args.output.write_text(json.dumps(output, indent=2) + "\n")


if __name__ == "__main__":
    main()
