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


COMMIT = "e2c45ed0c4099f8d27ef0d78641ca8b626f4cdcb"
BINARIES = {
    "original": "025429ead58f2b302c5854eca5f4475421f9a0aab1003e8242eb2cab5dbc686a",
    "rebuild": "7448b6320e820d027303bfd94d4460e4c55b88425fdb659f4eda15ed5fa40c5b",
}


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def usage():
    current = resource.getrusage(resource.RUSAGE_CHILDREN)
    return current.ru_utime, current.ru_stime


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--original", type=Path, required=True)
    parser.add_argument("--rebuild", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cpu", type=int, default=16)
    parser.add_argument("--batches", type=int, default=5)
    parser.add_argument("--iterations", type=int, default=1000)
    args = parser.parse_args()
    roots = {
        "original": args.original.resolve(),
        "rebuild": args.rebuild.resolve(),
    }
    binaries = {
        variant: root / "stage2/out/bin/fstar.exe"
        for variant, root in roots.items()
    }
    versions = {
        variant: subprocess.check_output(
            [str(binary), "--version"], text=True
        ).strip()
        for variant, binary in binaries.items()
    }
    for variant, binary in binaries.items():
        if (
            f"commit={COMMIT}" not in versions[variant]
            or sha256(binary) != BINARIES[variant]
        ):
            raise RuntimeError(f"{variant}: unexpected compiler")
    heads = {
        variant: subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
        ).strip()
        for variant, root in roots.items()
    }
    if heads["rebuild"] != COMMIT:
        raise RuntimeError("rebuild worktree is not the exact PR head")
    if subprocess.run([
        "git", "-C", str(roots["original"]), "merge-base", "--is-ancestor",
        COMMIT, heads["original"],
    ]).returncode != 0:
        raise RuntimeError("original worktree does not descend from PR head")
    for root in roots.values():
        if subprocess.run([
            "git", "-C", str(root), "diff", "--quiet", COMMIT,
            "--", "src", "ulib", "pulse",
        ]).returncode != 0:
            raise RuntimeError("production sources differ from PR head")
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
    for binary in binaries.values():
        for _ in range(10):
            subprocess.run(
                [str(binary), "--version"],
                env=environment,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
            )
    randomizer = random.Random(4800)
    rows = []
    for repeat in range(1, args.batches + 1):
        for variant in randomizer.sample(list(roots), len(roots)):
            before_user, before_system = usage()
            started = time.monotonic()
            for _ in range(args.iterations):
                subprocess.run(
                    [str(binaries[variant]), "--version"],
                    env=environment,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=True,
                )
            wall = time.monotonic() - started
            after_user, after_system = usage()
            rows.append({
                "variant": variant,
                "repeat": repeat,
                "iterations": args.iterations,
                "user_seconds": after_user - before_user,
                "system_seconds": after_system - before_system,
                "wall_seconds": wall,
            })
    output = {
        "cpu": args.cpu,
        "batches": args.batches,
        "iterations_per_batch": args.iterations,
        "rows": rows,
        "compiler_commit": COMMIT,
        "variants": {
            variant: {
                "root": str(root),
                "binary_sha256": sha256(binaries[variant]),
                "version": versions[variant],
                "worktree_head": heads[variant],
            }
            for variant, root in roots.items()
        },
        "script_sha256": sha256(Path(__file__)),
    }
    args.output.write_text(json.dumps(output, indent=2) + "\n")


if __name__ == "__main__":
    main()
