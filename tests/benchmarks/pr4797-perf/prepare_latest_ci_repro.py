#!/usr/bin/env python3

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path


Z3_SHA256 = "4da6a0f78424098b600a9112ebb9d8ce45de248a4913c26dd7d472e6dabef6d3"
VARIANTS = {
    "base": {
        "commit": "9ccacf4a8a392137d5384f8b39500377ebf53f79",
        "binary":
            "9c24fe8a04f8244948b877bbb4eb1d480b6bfd093d0fabdd8e99c53af4ebe098",
    },
    "head": {
        "commit": "31a521edd9ca47c547204cb0609a852206e4342a",
        "binary":
            "633eb53e40a84c75dc85ecd77593a97fd179683265644053f70ba49612e694e1",
    },
}
TARGETS = {
    "long": ("tests/calc", "_cache/Long.fst.checked", False),
    "lib-vec": (
        "tests/hacl", "_cache/Lib.Vec.Lemmas.fst.checked", False
    ),
    "cbor-boundary": (
        "tests/custard/pulse",
        "_cache/CborBoundarySlice.fst.checked",
        False,
    ),
    "calc-endpoint": (
        "pulse/share/pulse/examples/protocol/calc",
        "_cache/Calc.Server.Endpoint.fst.checked",
        False,
    ),
    "bool-refinement": (
        "examples/dsls/bool_refinement",
        "_cache/BoolRefinement.fst.checked",
        False,
    ),
    "float-extract": (
        "tests/floats", "_cache/FloatExtract.fst.checked", True
    ),
    "ext-uint-div-rem": (
        "tests/extraction/backends",
        "_cache/ExtUIntDivRem.fst.checked",
        False,
    ),
}


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_sha256(path):
    digest = hashlib.sha256()
    files = sorted(item for item in path.rglob("*") if item.is_file())
    for item in files:
        digest.update(str(item.relative_to(path)).encode())
        digest.update(b"\0")
        digest.update(item.read_bytes())
        digest.update(b"\0")
    return {"files": len(files), "sha256": digest.hexdigest()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--variant", action="append", required=True)
    parser.add_argument("--z3-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = args.source.resolve()
    variants = {}
    for value in args.variant:
        name, path = value.split("=", 1)
        variants[name] = Path(path).resolve()
    if set(variants) != set(VARIANTS):
        raise RuntimeError("base and head variants required")
    if args.output.exists():
        raise RuntimeError("output must not exist")
    z3 = args.z3_dir.resolve() / "z3-5.3.0"
    if sha256(z3) != Z3_SHA256:
        raise RuntimeError("unexpected Z3 artifact")
    args.output.mkdir(parents=True)
    environment = os.environ.copy()
    environment["PATH"] = (
        str(args.z3_dir.resolve()) + os.pathsep + environment["PATH"]
    )
    provenance = {
        "source": str(source),
        "source_head": subprocess.check_output(
            ["git", "-C", str(source), "rev-parse", "HEAD"], text=True
        ).strip(),
        "z3": {"path": str(z3), "sha256": sha256(z3)},
        "variants": {},
        "targets": {},
        "script_sha256": sha256(Path(__file__)),
    }
    for name, root in variants.items():
        spec = VARIANTS[name]
        head = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
        ).strip()
        binary = root / "stage3/out/bin/fstar.exe"
        version = subprocess.check_output(
            [str(binary), "--version"], text=True
        )
        embedded_commit = next(
            line.removeprefix("commit=")
            for line in version.splitlines()
            if line.startswith("commit=")
        )
        if (
            head != spec["commit"]
            or embedded_commit != spec["commit"]
            or sha256(binary) != spec["binary"]
        ):
            raise RuntimeError(f"{name}: unexpected artifact")
        install = args.output / "installs" / name
        install.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(root / "stage3/out", install)
        provenance["variants"][name] = {
            "root": str(root),
            "head": head,
            "embedded_commit": embedded_commit,
            "binary_sha256": sha256(binary),
            "install_tree": tree_sha256(install),
        }
    for target, (relative, make_target, keep_target) in TARGETS.items():
        target_provenance = {}
        directory = source / relative
        for variant, root in variants.items():
            cache = directory / "_cache"
            generated = directory / "_output"
            if cache.exists():
                shutil.rmtree(cache)
            if generated.exists():
                shutil.rmtree(generated)
            command = [
                "make", "-C", str(directory), make_target,
                f"FSTAR_EXE={root / 'stage3/out/bin/fstar.exe'}",
            ]
            log = args.output / "logs" / f"{target}-{variant}.log"
            log.parent.mkdir(parents=True, exist_ok=True)
            with log.open("w") as stream:
                subprocess.run(
                    command, env=environment,
                    stdout=stream, stderr=subprocess.STDOUT, check=True,
                )
            target_file = directory / make_target
            if not target_file.is_file():
                raise RuntimeError(f"{target}/{variant}: target missing")
            snapshot = args.output / "caches" / target / variant
            snapshot.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(cache, snapshot)
            if not keep_target:
                (snapshot / Path(make_target).name).unlink()
            target_provenance[variant] = {
                "command": command,
                "log_sha256": sha256(log),
                "cache_tree": tree_sha256(snapshot),
                "target_sha256": sha256(target_file),
                "target_kept": keep_target,
            }
        provenance["targets"][target] = target_provenance
    for relative, _, _ in TARGETS.values():
        directory = source / relative
        for name in ("_cache", "_output"):
            path = directory / name
            if path.exists():
                shutil.rmtree(path)
    (args.output / "provenance.json").write_text(
        json.dumps(provenance, indent=2) + "\n"
    )


if __name__ == "__main__":
    main()
