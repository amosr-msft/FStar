#!/usr/bin/env python3

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path


PACKAGES = (
    "threads,batteries,dynlink,mtime,mtime.clock,pprint,"
    "ppx_deriving.runtime,ppx_deriving_yojson.runtime,ppxlib,ppxlib.ast,"
    "process,stdint,yojson,zarith,unix"
)
VARIANTS = {
    "cached": {
        "commit": "f4886d2decd874cd0008e31d6ba07c7da43c5ba4",
        "archive":
            "fb9bf78c2753510edbe849c4e7c26214795b862fcc353dfce099a2fee7b0085f",
    },
    "optimized": {
        "commit": "c939875498355d0684b41138b5dbc208e34ef2b4",
        "archive":
            "7a739392b2481cb49e9b744a0ef504d4c2258473b715ebce72c23980840d1a87",
    },
}


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cached", type=Path, required=True)
    parser.add_argument("--optimized", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cpu", type=int, default=16)
    args = parser.parse_args()
    roots = {
        "cached": args.cached.resolve(),
        "optimized": args.optimized.resolve(),
    }
    harness = Path(__file__).resolve().parent / "source_name_miss_scaling.ml"
    args.output.mkdir(parents=True, exist_ok=True)
    os.sched_setaffinity(0, {args.cpu})
    provenance = {
        "cpu": args.cpu,
        "iterations": 5_000,
        "root_counts": [1, 16, 64, 256],
        "harness_sha256": sha256(harness),
        "runner_sha256": sha256(Path(__file__)),
        "variants": {},
    }
    results = {}
    with tempfile.TemporaryDirectory(
        prefix="source-name-misses-", dir=args.output
    ) as directory:
        fixture = Path(directory)
        for variant, root in roots.items():
            spec = VARIANTS[variant]
            head = subprocess.check_output(
                ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
            ).strip()
            if subprocess.run([
                "git", "-C", str(root), "merge-base", "--is-ancestor",
                spec["commit"], head,
            ]).returncode != 0:
                raise RuntimeError(f"{variant}: unexpected revision")
            if subprocess.run([
                "git", "-C", str(root), "diff", "--quiet", spec["commit"],
                "--", "src", "ulib", "pulse",
            ]).returncode != 0:
                raise RuntimeError(f"{variant}: production sources differ")
            build = root / "stage2/dune/_build/default/fstar-guts"
            archive = build / "fstarcompiler.cmxa"
            if sha256(archive) != spec["archive"]:
                raise RuntimeError(f"{variant}: archive differs")
            executable = fixture / f"{variant}.exe"
            command = [
                "ocamlfind", "ocamlopt", "-thread", "-linkpkg",
                "-package", PACKAGES,
                "-I", str(build / ".fstarcompiler.objs/byte"),
                "-I", str(build / ".fstarcompiler.objs/native"),
                str(archive), str(harness), "-o", str(executable),
            ]
            subprocess.run(command, cwd=fixture, check=True)
            observations = []
            for _ in range(5):
                process = subprocess.run(
                    [str(executable), str(fixture)],
                    cwd=fixture,
                    text=True,
                    capture_output=True,
                    check=True,
                )
                observations.append([
                    {
                        "roots": int(line.split()[0]),
                        "seconds": float(line.split()[1]),
                    }
                    for line in process.stdout.splitlines()
                ])
            results[variant] = observations
            provenance["variants"][variant] = {
                "root": str(root),
                "worktree_head": head,
                "source_commit": spec["commit"],
                "archive_sha256": sha256(archive),
                "compile_command": command,
            }
    (args.output / "result.json").write_text(
        json.dumps(
            {"provenance": provenance, "results": results},
            indent=2,
        ) + "\n"
    )


if __name__ == "__main__":
    main()
