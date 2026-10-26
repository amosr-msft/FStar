#!/usr/bin/env python3

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path


PACKAGES = (
    "threads,batteries,dynlink,mtime,mtime.clock,pprint,"
    "ppx_deriving.runtime,ppx_deriving_yojson.runtime,ppxlib,ppxlib.ast,"
    "process,stdint,yojson,zarith,unix"
)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--worktree", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    worktree = args.worktree.resolve()
    build = worktree / "stage3/dune/_build/default/fstar-guts"
    archive = build / "fstarcompiler.cmxa"
    harness = root / "pruning_cache_regression.ml"
    args.output.mkdir(parents=True, exist_ok=True)
    executable = args.output / "pruning-cache-regression.exe"
    command = [
        "ocamlfind", "ocamlopt", "-thread", "-linkpkg",
        "-package", PACKAGES,
        "-I", str(build / ".fstarcompiler.objs/byte"),
        "-I", str(build / ".fstarcompiler.objs/native"),
        str(archive), str(harness), "-o", str(executable),
    ]
    subprocess.run(command, check=True)
    outputs = {}
    environments = {}
    for mode in ("cached", "reference"):
        environment = os.environ.copy()
        selected = {}
        if mode == "reference":
            selected["FSTAR_PRUNING_REFERENCE"] = "1"
            environment.update(selected)
        process = subprocess.run(
            [str(executable)], env=environment,
            text=True, capture_output=True, check=True,
        )
        outputs[mode] = process.stdout
        environments[mode] = selected
        (args.output / f"{mode}.out").write_text(process.stdout)
    if outputs["cached"] != outputs["reference"]:
        raise RuntimeError("cached/reference retained assumptions differ")
    expected = (
        "empty=edge_empty_alternative,root_a\n"
        "conjunction-before=root_a\n"
        "conjunction-after=edge_conjunction,root_a,root_b\n"
        "late=edge_conjunction,root_ab\n"
    )
    if outputs["cached"] != expected:
        raise RuntimeError("retained assumptions differ from expected output")
    result = {
        "compile_command": command,
        "run_command": [str(executable)],
        "environments": environments,
        "output": outputs["cached"],
        "output_sha256":
            hashlib.sha256(outputs["cached"].encode()).hexdigest(),
        "provenance": {
            "worktree_commit": subprocess.check_output(
                ["git", "-C", str(worktree), "rev-parse", "HEAD"], text=True
            ).strip(),
            "compiler_archive_sha256": sha256(archive),
            "harness_sha256": sha256(harness),
            "instrumenter_sha256":
                sha256(root / "instrument_pruning_reference.py"),
            "runner_sha256": sha256(Path(__file__)),
        },
    }
    (args.output / "result.json").write_text(
        json.dumps(result, indent=2) + "\n"
    )


if __name__ == "__main__":
    main()
