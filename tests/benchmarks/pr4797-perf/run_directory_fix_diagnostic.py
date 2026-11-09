#!/usr/bin/env python3

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path


VARIANTS = {
    "flat": {
        "commit": "1b61ce6d3b2d0cead2f5174d931b042961529193",
        "binary":
            "667968b8748df177213e2ae45faa5156e507469c9b4cf9771cabc7c9e19d0641",
        "archive":
            "4fd4a63679976618a7e340e7ff5b3d600597d41542fc70e2dbc23f876e199f50",
    },
    "dedup": {
        "commit": "8fcec04cf3",
        "binary":
            "4e91f2c5e292227e0234c89c5fe7009b2688f635f2d4e2dbd590c1c680291d48",
        "archive":
            "065a3a0dfb0f21a959760fc15c9c239171acdb2508135c1898d5da369d3d51f0",
    },
}
Z3 = "4da6a0f78424098b600a9112ebb9d8ce45de248a4913c26dd7d472e6dabef6d3"
PACKAGES = (
    "threads,batteries,dynlink,mtime,mtime.clock,pprint,"
    "ppx_deriving.runtime,ppx_deriving_yojson.runtime,ppxlib,ppxlib.ast,"
    "process,stdint,yojson,zarith,unix"
)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalized_depend(path, roots, run):
    text = "\n".join(
        line for line in path.read_text().splitlines()
        if not line.startswith("#")
    )
    text = text.replace(str(run), "<RUN>")
    for root in roots.values():
        text = text.replace(str(root), "<WORKTREE>")
    return hashlib.sha256(text.encode()).hexdigest()


def parse_variant(value):
    name, path = value.split("=", 1)
    if name not in VARIANTS:
        raise argparse.ArgumentTypeError(name)
    return name, Path(path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--variant", action="append", type=parse_variant, required=True
    )
    parser.add_argument("--z3", type=Path, required=True)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cpu", type=int, default=16)
    args = parser.parse_args()
    roots = {name: path.resolve() for name, path in args.variant}
    if set(roots) != set(VARIANTS):
        raise RuntimeError("flat and dedup required")
    for name, root in roots.items():
        spec = VARIANTS[name]
        if (
            not subprocess.check_output(
                ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
            ).strip().startswith(spec["commit"])
            or sha256(root / "stage3/out/bin/fstar.exe") != spec["binary"]
            or sha256(
                root
                / "stage2/dune/_build/default/fstar-guts/fstarcompiler.cmxa"
            ) != spec["archive"]
        ):
            raise RuntimeError(f"{name}: artifact differs")
    if sha256(args.z3.resolve()) != Z3:
        raise RuntimeError("unexpected Z3")
    args.output.mkdir(parents=True, exist_ok=True)
    if any(args.output.iterdir()):
        raise RuntimeError("output must be empty")
    os.sched_setaffinity(0, {args.cpu})
    cwd = roots["flat"] / "tests/bug-reports/closed"
    sources = [
        path.name
        for pattern in ("*.fst", "*.fsti")
        for path in sorted(cwd.glob(pattern))
    ]
    harness = Path(__file__).resolve().parent / "root_manifest.ml"
    rows = {}
    stage = args.stage.resolve()
    if stage.exists():
        raise RuntimeError("stage path must not exist")
    shutil.copytree(roots["flat"] / "stage3/out", stage)
    binary_path = stage / "bin/fstar.exe"
    environment = os.environ.copy()
    environment.update({
        "LC_ALL": "C",
        "LANG": "C",
        "FSTAR_LIB": str((stage / "lib/fstar").resolve()),
    })
    with tempfile.TemporaryDirectory(
        prefix="directory-fix-", dir=args.output
    ) as temporary:
        temporary = Path(temporary)
        for name, root in roots.items():
            shutil.copy2(
                root / "stage3/out/bin/fstar.exe", binary_path
            )
            run = temporary / name
            cache = run / "cache"
            generated = run / "output"
            cache.mkdir(parents=True)
            generated.mkdir()
            trace = args.output / f"{name}.strace"
            depend = run / ".depend"
            command = [
                "strace", "-c", "-f", "-o", str(trace),
                str(binary_path),
                "--z3version", "5.3.0",
                "--smt", str(args.z3.resolve()), "--silent",
                "--odir", str(generated), "--cache_dir", str(cache),
                "--already_cached", "Prims,FStar",
                "--warn_error", "-321", "--warn_error", "-240",
                "--dep", "full", *sources, "-o", str(depend),
            ]
            process = subprocess.run(
                command, cwd=cwd, env=environment,
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                text=True, timeout=300,
            )
            if process.returncode != 0:
                raise RuntimeError(f"{name}: {process.stderr}")
            depend_copy = args.output / f"{name}.depend"
            shutil.copy2(depend, depend_copy)
            archive = (
                root
                / "stage2/dune/_build/default/fstar-guts/fstarcompiler.cmxa"
            )
            build = archive.parent
            manifest_exe = temporary / f"{name}-manifest.exe"
            compile_command = [
                "ocamlfind", "ocamlopt", "-thread", "-linkpkg",
                "-package", PACKAGES,
                "-I", str(build / ".fstarcompiler.objs/byte"),
                "-I", str(build / ".fstarcompiler.objs/native"),
                str(archive), str(harness), "-o", str(manifest_exe),
            ]
            subprocess.run(compile_command, check=True)
            manifest = subprocess.run(
                [str(manifest_exe), *sources], cwd=cwd,
                env=environment,
                text=True, capture_output=True, check=True,
            ).stdout
            manifest_path = args.output / f"{name}.roots"
            manifest_path.write_text(manifest)
            strace_text = trace.read_text()
            match = re.search(
                r"^\s*[\d.]+\s+[\d.]+\s+\d+\s+(\d+)\s+"
                r"(\d+)\s+newfstatat$",
                strace_text,
                re.M,
            )
            rows[name] = {
                "depend_sha256": sha256(depend_copy),
                "normalized_depend_sha256":
                    normalized_depend(depend_copy, roots, run),
                "strace_sha256": sha256(trace),
                "newfstatat_calls": int(match.group(1)),
                "newfstatat_errors": int(match.group(2)),
                "root_manifest_sha256": sha256(manifest_path),
                "root_manifest_lines": sum(
                    line.startswith("ROOT-")
                    for line in manifest.splitlines()
                ),
                "file_manifest_lines": sum(
                    line.startswith("FILE\t")
                    for line in manifest.splitlines()
                ),
                "compile_command": compile_command,
            }
    if len({
        row["normalized_depend_sha256"] for row in rows.values()
    }) != 1:
        raise RuntimeError("semantic dependency output differs")
    (args.output / "result.json").write_text(json.dumps({
        "provenance": {
            "cpu": args.cpu,
            "variants": VARIANTS,
            "z3_sha256": sha256(args.z3.resolve()),
            "runtime_binary_path": str(binary_path),
            "runtime_fstar_lib": environment["FSTAR_LIB"],
            "source_manifest_sha256": hashlib.sha256(
                "\n".join(sources).encode()
            ).hexdigest(),
            "runner_sha256": sha256(Path(__file__)),
            "harness_sha256": sha256(harness),
        },
        "rows": rows,
    }, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
