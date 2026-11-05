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
    "three": {
        "commit": "7da01c0b4ae5cf447f6951ddb38714b7f1969a35",
        "archive":
            "2037dcf943e9eafabc6cf554867cc710158fb010192aaa3090457fb8bc5d59e6",
    },
    "two": {
        "commit": "285501627e98a089ee15fe10dec94fcfa0b76f73",
        "archive":
            "7e8c55dba4abeacc08a557411e7923aac3ff1feaa8fa053472d73ddb83bfee19",
    },
}


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--three", type=Path, required=True)
    parser.add_argument("--two", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cpu", type=int, default=16)
    args = parser.parse_args()
    roots = {"three": args.three.resolve(), "two": args.two.resolve()}
    harness = (
        Path(__file__).resolve().parent / "source_name_root_scaling.ml"
    )
    args.output.mkdir(parents=True, exist_ok=True)
    os.sched_setaffinity(0, {args.cpu})
    provenance = {
        "cpu": args.cpu,
        "iterations": 20_000,
        "root_counts": [1, 16, 64, 256],
        "harness_sha256": sha256(harness),
        "runner_sha256": sha256(Path(__file__)),
        "variants": {},
    }
    results = {}
    with tempfile.TemporaryDirectory(
        prefix="two-cache-hot-", dir=args.output
    ) as directory:
        temporary = Path(directory)
        source = temporary / "A/B/C.fst"
        source.parent.mkdir(parents=True)
        source.write_text("module A.B.C\n")
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
            build = root / "stage2/dune/_build/default/fstar-guts"
            archive = build / "fstarcompiler.cmxa"
            if sha256(archive) != spec["archive"]:
                raise RuntimeError(f"{variant}: archive differs")
            executable = temporary / f"{variant}.exe"
            build_harness = temporary / f"{variant}-{harness.name}"
            build_harness.write_bytes(harness.read_bytes())
            command = [
                "ocamlfind", "ocamlopt", "-thread", "-linkpkg",
                "-package", PACKAGES,
                "-I", str(build / ".fstarcompiler.objs/byte"),
                "-I", str(build / ".fstarcompiler.objs/native"),
                str(archive), str(build_harness), "-o", str(executable),
            ]
            subprocess.run(command, cwd=temporary, check=True)
            observations = []
            for _ in range(5):
                process = subprocess.run(
                    [str(executable), str(temporary), str(source)],
                    cwd=temporary,
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
                "compile_command": [
                    item.replace(str(temporary), "<temporary>")
                    for item in command
                ],
            }
    (args.output / "result.json").write_text(
        json.dumps(
            {"provenance": provenance, "results": results},
            indent=2,
        ) + "\n"
    )


if __name__ == "__main__":
    main()
