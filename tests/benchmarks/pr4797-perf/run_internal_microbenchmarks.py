#!/usr/bin/env python3

import argparse
import hashlib
import json
import os
import statistics
import subprocess
import tempfile
from pathlib import Path


PACKAGES = (
    "threads,batteries,dynlink,mtime,mtime.clock,pprint,"
    "ppx_deriving.runtime,ppx_deriving_yojson.runtime,ppxlib,ppxlib.ast,"
    "process,stdint,yojson,zarith,unix"
)
EXPECTED_COMMITS = {
    "base": "c68959fe1f070cd66a5ed2e92965185505f109ce",
    "head": "e2c45ed0c4099f8d27ef0d78641ca8b626f4cdcb",
}


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compile_harness(root, source, output):
    build = root / "stage2/dune/_build/default/fstar-guts"
    command = [
        "ocamlfind",
        "ocamlopt",
        "-thread",
        "-linkpkg",
        "-package",
        PACKAGES,
        "-I",
        str(build / ".fstarcompiler.objs/byte"),
        "-I",
        str(build / ".fstarcompiler.objs/native"),
        str(build / "fstarcompiler.cmxa"),
        str(source),
        "-o",
        str(output),
    ]
    subprocess.run(command, check=True)
    return build / "fstarcompiler.cmxa"


def run(executable, arguments=()):
    process = subprocess.run(
        [str(executable), *map(str, arguments)],
        text=True,
        capture_output=True,
        check=True,
    )
    label, value = process.stdout.strip().split()
    return label, float(value)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--head", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cpu", type=int, default=16)
    args = parser.parse_args()
    roots = {"base": args.base.resolve(), "head": args.head.resolve()}
    commits = {
        variant: subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
        ).strip()
        for variant, root in roots.items()
    }
    if commits != EXPECTED_COMMITS:
        raise RuntimeError("unexpected revisions")
    os.sched_setaffinity(0, {args.cpu})
    source_root = Path(__file__).resolve().parent
    with tempfile.TemporaryDirectory(prefix="pr4797-perf-") as directory:
        temporary = Path(directory)
        archives = {}
        range_executables = {}
        for variant, root in roots.items():
            executable = temporary / f"range-{variant}.exe"
            archive = compile_harness(
                root,
                source_root / "range_constructor_bench.ml",
                executable,
            )
            archives[variant] = {
                "path": str(archive),
                "sha256": sha256(archive),
            }
            range_executables[variant] = executable
        source_executable = temporary / "source-file-name.exe"
        compile_harness(
            roots["head"],
            source_root / "source_file_name_bench.ml",
            source_executable,
        )
        source_observations = {"absolute": [], "relative": []}
        for _ in range(3):
            process = subprocess.run(
                [
                    str(source_executable),
                    str(source_root),
                ],
                text=True,
                capture_output=True,
                check=True,
            )
            for line in process.stdout.splitlines():
                label, value = line.split()
                source_observations[label].append(float(value))
        range_observations = {"base": [], "head": []}
        for _ in range(5):
            for variant in ("base", "head"):
                label, value = run(range_executables[variant])
                if label != "mk_rng":
                    raise RuntimeError("unexpected range benchmark output")
                range_observations[variant].append(value)
    output = {
        "cpu": args.cpu,
        "source_file_name": {
            "iterations_per_form": 1_000_000,
            **{
                f"{label}_seconds": values
                for label, values in source_observations.items()
            },
            **{
                f"{label}_median_microseconds_per_call":
                    statistics.median(values)
                for label, values in source_observations.items()
            },
            "compiler_commit": commits["head"],
        },
        "mk_rng": {
            "iterations": 10_000_000,
            **{
                f"{variant}_seconds": values
                for variant, values in range_observations.items()
            },
            **{
                f"{variant}_median_seconds": statistics.median(values)
                for variant, values in range_observations.items()
            },
            "base_commit": commits["base"],
            "head_commit": commits["head"],
        },
        "compiler_archives": archives,
        "harness_sha256": {
            "source_file_name": sha256(
                source_root / "source_file_name_bench.ml"
            ),
            "mk_rng": sha256(source_root / "range_constructor_bench.ml"),
        },
        "script_sha256": sha256(Path(__file__)),
        "limitations": [
            "These isolate helper cost and do not replace end-to-end workloads.",
            "The range constructor harness discards each result.",
            "The source filename harness measures a hot find-file cache.",
        ],
    }
    args.output.write_text(json.dumps(output, indent=2) + "\n")


if __name__ == "__main__":
    main()
