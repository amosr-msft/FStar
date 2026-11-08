#!/usr/bin/env python3

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path


COMMIT = "850c09bed1b8167e4e91a396d563e20e485ec446"
ARCHIVE = "f95f3a38cb038d8c34339c144dce787707a0c5ebf7fcf9564e95ccadcb6f777d"
PACKAGES = (
    "threads,batteries,dynlink,mtime,mtime.clock,pprint,"
    "ppx_deriving.runtime,ppx_deriving_yojson.runtime,ppxlib,ppxlib.ast,"
    "process,stdint,yojson,zarith,unix"
)
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
    "filesystem-root": "A/B.fst",
    "rebuild": "A/B.fst|C/D.fst|E/F.fst",
}


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--worktree", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cpu", type=int, default=16)
    args = parser.parse_args()
    root = args.worktree.resolve()
    head = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
    ).strip()
    if head != COMMIT:
        raise RuntimeError(f"unexpected revision: {head}")
    build = root / "stage2/dune/_build/default/fstar-guts"
    archive = build / "fstarcompiler.cmxa"
    if sha256(archive) != ARCHIVE:
        raise RuntimeError("archive differs")
    os.sched_setaffinity(0, {args.cpu})
    harness = Path(__file__).resolve().parent / "single_index_differential.ml"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment.pop("FSTAR_FLAT_ROOT_DIAGNOSTIC", None)
    with tempfile.TemporaryDirectory(
        prefix="single-index-differential-", dir=args.output.parent
    ) as directory:
        fixture = Path(directory)
        for relative in (
            "outer", "outer/flat", "outer/flat/nested", "sibling",
            "outer-suffix",
        ):
            (fixture / relative).mkdir(parents=True)
        (fixture / "outer/flat/fstar.include").write_text("")
        (fixture / "outer/flat/nested/fstar.include").write_text("")
        executable = fixture / "differential.exe"
        command = [
            "ocamlfind", "ocamlopt", "-thread", "-linkpkg",
            "-package", PACKAGES,
            "-I", str(build / ".fstarcompiler.objs/byte"),
            "-I", str(build / ".fstarcompiler.objs/native"),
            str(archive), str(harness), "-o", str(executable),
        ]
        subprocess.run(command, cwd=fixture, check=True)
        results = {}
        for scenario, expected in SCENARIOS.items():
            observed = {}
            for mode in ("trie", "flat"):
                env = environment.copy()
                if mode == "flat":
                    env["FSTAR_FLAT_ROOT_DIAGNOSTIC"] = "1"
                process = subprocess.run(
                    [str(executable), str(fixture), scenario],
                    cwd=fixture,
                    env=env,
                    text=True,
                    capture_output=True,
                    check=True,
                )
                observed[mode] = process.stdout.strip()
            if set(observed.values()) != {expected}:
                raise RuntimeError(
                    f"{scenario}: expected {expected}, observed {observed}"
                )
            results[scenario] = observed
        args.output.write_text(json.dumps({
            "provenance": {
                "cpu": args.cpu,
                "head": head,
                "archive_sha256": sha256(archive),
                "harness_sha256": sha256(harness),
                "runner_sha256": sha256(Path(__file__)),
                "executable_sha256": sha256(executable),
                "compile_command": command,
            },
            "results": results,
        }, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
