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
    "incumbent": {
        "commit": "2ef0fe554eeca5907db4deb5d9daf4f9e276b97d",
        "archive":
            "600fba3706e58db30b5dfde880c7e396200e5902082d7d64e819bd26a46be17d",
    },
    "canonical": {
        "commit": "7df960b9fbbeed8c599361d9660f40f2e2f85f9c",
        "archive":
            "422cfed886c9e4a12baf6d0b49d67b66fafd33f93d7c351e0f22a420bedef6cd",
    },
}
SCENARIOS = {
    "recursive-outer": "A/B.fst",
    "nested-outer-first": "A.fst",
    "nested-inner-first": "A.fst",
    "sibling": "A/B.fst",
    "boundary": "NONE",
    "flat-immediate": "A.fst",
    "flat-outer-fallback": "flat/deeper/A.fst",
    "nested-flat-outer-fallback": "flat/nested/deeper/A.fst",
    "duplicate-flat-recursive": "A/B.fst",
    "duplicate-recursive-flat": "A/B.fst",
    "duplicate-recursive": "A/B.fst",
    "filesystem-root": {
        "incumbent": "NONE",
        "canonical": "A/B.fst",
    },
}


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_variant(value):
    name, path = value.split("=", 1)
    if name not in VARIANTS:
        raise argparse.ArgumentTypeError(f"unknown variant: {name}")
    return name, Path(path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--variant", action="append", type=parse_variant, required=True
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cpu", type=int, default=16)
    args = parser.parse_args()
    roots = {name: path.resolve() for name, path in args.variant}
    if set(roots) != set(VARIANTS):
        raise RuntimeError("all variants are required")
    os.sched_setaffinity(0, {args.cpu})
    harness = (
        Path(__file__).resolve().parent / "canonical_trie_differential.ml"
    )
    provenance = {
        "cpu": args.cpu,
        "harness_sha256": sha256(harness),
        "runner_sha256": sha256(Path(__file__)),
        "scenarios": SCENARIOS,
        "variants": {},
    }
    results = {}
    with tempfile.TemporaryDirectory(
        prefix="canonical-trie-differential-", dir=args.output.parent
    ) as directory:
        fixture = Path(directory)
        for relative in (
            "outer", "outer/flat", "outer/flat/nested", "sibling",
            "outer-suffix",
        ):
            (fixture / relative).mkdir(parents=True)
        (fixture / "outer/flat/fstar.include").write_text("")
        (fixture / "outer/flat/nested/fstar.include").write_text("")
        executables = {}
        for variant, root in roots.items():
            spec = VARIANTS[variant]
            head = subprocess.check_output(
                ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
            ).strip()
            if not head.startswith(spec["commit"]):
                raise RuntimeError(f"{variant}: unexpected revision {head}")
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
            executables[variant] = executable
            provenance["variants"][variant] = {
                "root": str(root),
                "head": head,
                "archive_sha256": sha256(archive),
                "executable_sha256": sha256(executable),
                "compile_command": command,
            }
        for scenario, expected in SCENARIOS.items():
            observed = {}
            for variant, executable in executables.items():
                process = subprocess.run(
                    [str(executable), str(fixture), scenario],
                    cwd=fixture,
                    text=True,
                    capture_output=True,
                    check=True,
                )
                observed[variant] = process.stdout.strip()
            expected_by_variant = (
                expected if isinstance(expected, dict)
                else {variant: expected for variant in VARIANTS}
            )
            if observed != expected_by_variant:
                raise RuntimeError(
                    f"{scenario}: expected {expected}, observed {observed}"
                )
            results[scenario] = observed
    args.output.write_text(json.dumps({
        "provenance": provenance,
        "results": results,
    }, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
