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
    "pr": {
        "commit": "e2c45ed0c4099f8d27ef0d78641ca8b626f4cdcb",
        "archive":
            "209a3d5d66528ab5e6bdf3b43db4ae98fc31b10bc4ed26ce8c9e8a13907a1fc1",
    },
    "cached": {
        "commit": "f4886d2decd874cd0008e31d6ba07c7da43c5ba4",
        "archive":
            "4abc50b7dd12cd467a05f16658ad4fe864d7332868482e0725ab2ae895c69ee1",
    },
}


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pr", type=Path, required=True)
    parser.add_argument("--cached", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cpu", type=int, default=16)
    args = parser.parse_args()
    roots = {"pr": args.pr.resolve(), "cached": args.cached.resolve()}
    source_root = Path(__file__).resolve().parent
    harness = source_root / "source_name_root_scaling.ml"
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
        prefix="source-name-roots-", dir=args.output
    ) as directory:
        fixture = Path(directory)
        source = fixture / "A/B/C.fst"
        source.parent.mkdir(parents=True)
        source.write_text("module A.B.C\n")
        for variant, root in roots.items():
            head = subprocess.check_output(
                ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
            ).strip()
            if subprocess.run([
                "git", "-C", str(root), "merge-base", "--is-ancestor",
                VARIANTS[variant]["commit"], head,
            ]).returncode != 0:
                raise RuntimeError(f"{variant}: unexpected revision")
            build = root / "stage2/dune/_build/default/fstar-guts"
            archive = build / "fstarcompiler.cmxa"
            if (
                VARIANTS[variant]["archive"] is not None
                and sha256(archive) != VARIANTS[variant]["archive"]
            ):
                raise RuntimeError(f"{variant}: archive differs")
            executable = fixture / f"{variant}.exe"
            command = [
                "ocamlfind", "ocamlopt", "-thread", "-linkpkg",
                "-package", PACKAGES,
                "-I", str(build / ".fstarcompiler.objs/byte"),
                "-I", str(build / ".fstarcompiler.objs/native"),
                str(archive), str(harness), "-o", str(executable),
            ]
            subprocess.run(command, check=True)
            observations = []
            for _ in range(5):
                process = subprocess.run(
                    [str(executable), str(fixture), str(source)],
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
                "source_commit": VARIANTS[variant]["commit"],
                "archive_sha256": sha256(archive),
                "compile_command": command,
            }
    output = {"provenance": provenance, "results": results}
    (args.output / "result.json").write_text(
        json.dumps(output, indent=2) + "\n"
    )


if __name__ == "__main__":
    main()
