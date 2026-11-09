#!/usr/bin/env python3

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


BINARY = "207e478416f8fae3bd3c3b33914f2a5a9504fbcaf2d3d4745d9cc5914e0734b9"
ARCHIVE = "422cfed886c9e4a12baf6d0b49d67b66fafd33f93d7c351e0f22a420bedef6cd"
Z3 = "4da6a0f78424098b600a9112ebb9d8ce45de248a4913c26dd7d472e6dabef6d3"
PACKAGES = (
    "threads,batteries,dynlink,mtime,mtime.clock,pprint,"
    "ppx_deriving.runtime,ppx_deriving_yojson.runtime,ppxlib,ppxlib.ast,"
    "process,stdint,yojson,zarith,unix"
)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_monitor():
    path = Path(__file__).resolve().parent / "run_latest_outliers.py"
    spec = importlib.util.spec_from_file_location("latest", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.monitor


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trie", type=Path, required=True)
    parser.add_argument("--flat", type=Path, required=True)
    parser.add_argument("--controlled", type=Path, required=True)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--z3", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cpu", type=int, default=16)
    args = parser.parse_args()
    trie = args.trie.resolve()
    binary_source = trie / "stage3/out/bin/fstar.exe"
    archive = (
        trie / "stage2/dune/_build/default/fstar-guts/fstarcompiler.cmxa"
    )
    if (
        sha256(binary_source) != BINARY or sha256(archive) != ARCHIVE
        or sha256(args.z3.resolve()) != Z3
    ):
        raise RuntimeError("unexpected artifact")
    directories = {
        "original_trie": trie / "tests/bug-reports/closed",
        "original_flat":
            args.flat.resolve() / "tests/bug-reports/closed",
        "controlled": args.controlled.resolve(),
    }
    sources = [
        path.name
        for pattern in ("*.fst", "*.fsti")
        for path in sorted(directories["original_trie"].glob(pattern))
    ]
    stage = args.stage.resolve()
    if stage.exists():
        raise RuntimeError("stage path must not exist")
    shutil.copytree(trie / "stage3/out", stage)
    binary = stage / "bin/fstar.exe"
    args.output.mkdir(parents=True, exist_ok=True)
    if any(args.output.iterdir()):
        raise RuntimeError("output must be empty")
    os.sched_setaffinity(0, {args.cpu})
    environment = os.environ.copy()
    environment.update({
        "LC_ALL": "C",
        "LANG": "C",
        "FSTAR_LIB": str((stage / "lib/fstar").resolve()),
    })
    monitor = load_monitor()
    rows = []
    for name, cwd in directories.items():
        run_dir = args.output / name
        cache = run_dir / "cache"
        generated = run_dir / "output"
        cache.mkdir(parents=True)
        generated.mkdir()
        command = [
            str(binary), "--z3version", "5.3.0",
            "--smt", str(args.z3.resolve()),
            "--profile_component", "FStarC.Parser.Dep",
            "--odir", str(generated), "--cache_dir", str(cache),
            "--already_cached", "Prims,FStar",
            "--warn_error", "-321", "--warn_error", "-240",
            "--dep", "full", *sources,
            "-o", str(run_dir / ".depend"),
        ]
        log = run_dir / "run.log"
        measured = monitor(command, cwd, environment, log, 180)
        text = log.read_text()
        profiles = [
            line for line in text.splitlines()
            if "FStarC.Parser.Dep" in line
        ]
        rows.append({
            "fixture": name,
            "cwd": str(cwd),
            "cwd_length": len(str(cwd)),
            "profiles": profiles,
            "log_sha256": sha256(log),
            **measured,
        })
        if measured["returncode"] != 0 or measured["timed_out"]:
            raise RuntimeError(f"{name} failed")
    harness = Path(__file__).resolve().parent / "root_manifest.ml"
    build = trie / "stage2/dune/_build/default/fstar-guts"
    with tempfile.TemporaryDirectory(
        prefix="root-manifest-", dir=args.output
    ) as temporary:
        executable = Path(temporary) / "manifest.exe"
        compile_command = [
            "ocamlfind", "ocamlopt", "-thread", "-linkpkg",
            "-package", PACKAGES,
            "-I", str(build / ".fstarcompiler.objs/byte"),
            "-I", str(build / ".fstarcompiler.objs/native"),
            str(archive), str(harness), "-o", str(executable),
        ]
        subprocess.run(compile_command, check=True)
        manifests = {}
        for name, cwd in directories.items():
            process = subprocess.run(
                [str(executable), *sources],
                cwd=cwd,
                env=environment,
                text=True,
                capture_output=True,
                check=True,
            )
            path = args.output / f"{name}.roots"
            path.write_text(process.stdout)
            manifests[name] = {
                "sha256": sha256(path),
                "lines": len(process.stdout.splitlines()),
                "total_characters": sum(
                    len(line.split("\t")[1])
                    for line in process.stdout.splitlines()
                ),
            }
    (args.output / "result.json").write_text(json.dumps({
        "provenance": {
            "cpu": args.cpu,
            "binary_sha256": sha256(binary),
            "archive_sha256": sha256(archive),
            "z3_sha256": sha256(args.z3.resolve()),
            "script_sha256": sha256(Path(__file__)),
            "harness_sha256": sha256(harness),
            "compile_command": compile_command,
            "sources_sha256": hashlib.sha256(
                "\n".join(sources).encode()
            ).hexdigest(),
        },
        "rows": rows,
        "manifests": manifests,
    }, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
