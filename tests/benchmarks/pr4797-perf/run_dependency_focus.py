#!/usr/bin/env python3

import argparse
import hashlib
import importlib.util
import json
import os
import random
import subprocess
from pathlib import Path


COMMITS = {
    "base": "c68959fe1f070cd66a5ed2e92965185505f109ce",
    "head": "e2c45ed0c4099f8d27ef0d78641ca8b626f4cdcb",
    "rebuild": "e2c45ed0c4099f8d27ef0d78641ca8b626f4cdcb",
}
BINARIES = {
    "base": "8bd6f882f363ef45734caa875596182229436f1b53b6ea5d8a1584d2d1cedc3f",
    "head": "025429ead58f2b302c5854eca5f4475421f9a0aab1003e8242eb2cab5dbc686a",
    "rebuild":
        "7448b6320e820d027303bfd94d4460e4c55b88425fdb659f4eda15ed5fa40c5b",
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
    return {"sha256": digest.hexdigest(), "files": len(files)}


def load_monitor():
    path = Path(__file__).resolve().parent / "run_source_workloads.py"
    spec = importlib.util.spec_from_file_location("source_workloads", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.monitor


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--head", type=Path, required=True)
    parser.add_argument("--rebuild", type=Path, required=True)
    parser.add_argument("--z3", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cpu", type=int, default=16)
    parser.add_argument("--repetitions", type=int, default=20)
    args = parser.parse_args()
    roots = {
        "base": args.base.resolve(),
        "head": args.head.resolve(),
        "rebuild": args.rebuild.resolve(),
    }
    binaries = {
        variant: root / "stage2/out/bin/fstar.exe"
        for variant, root in roots.items()
    }
    versions = {
        variant: subprocess.check_output(
            [str(binary), "--version"], text=True
        ).strip()
        for variant, binary in binaries.items()
    }
    for variant, binary in binaries.items():
        if (
            f"commit={COMMITS[variant]}" not in versions[variant]
            or sha256(binary) != BINARIES[variant]
        ):
            raise RuntimeError(f"{variant}: unexpected compiler")
    heads = {
        variant: subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
        ).strip()
        for variant, root in roots.items()
    }
    if heads["base"] != COMMITS["base"] or heads["rebuild"] != COMMITS["rebuild"]:
        raise RuntimeError("exact control revisions differ")
    if subprocess.run([
        "git", "-C", str(roots["head"]), "merge-base", "--is-ancestor",
        COMMITS["head"], heads["head"],
    ]).returncode != 0:
        raise RuntimeError("evidence head does not descend from PR head")
    for variant in ("head", "rebuild"):
        if subprocess.run([
            "git", "-C", str(roots[variant]), "diff", "--quiet",
            COMMITS[variant], "--", "src", "ulib", "pulse",
        ]).returncode != 0:
            raise RuntimeError(f"{variant}: production sources differ")
    source_relative = "tests/bug-reports/closed/Bug3207.fst"
    sources = {
        variant: (root / source_relative).resolve()
        for variant, root in roots.items()
    }
    if len({sha256(source) for source in sources.values()}) != 1:
        raise RuntimeError("source differs")
    if sha256(args.z3.resolve()) != (
        "4da6a0f78424098b600a9112ebb9d8ce45de248a4913c26dd7d472e6dabef6d3"
    ):
        raise RuntimeError("unexpected Z3")
    args.output.mkdir(parents=True, exist_ok=True)
    if any(args.output.iterdir()):
        raise RuntimeError("output must be empty")
    os.sched_setaffinity(0, {args.cpu})
    environment = os.environ.copy()
    for name in (
        "FSTAR_LIB",
        "FSTAR_HOME",
        "OCAMLRUNPARAM",
        "CAMLRUNPARAM",
        "LD_PRELOAD",
        "LD_LIBRARY_PATH",
        "OCAMLPATH",
        "CAML_LD_LIBRARY_PATH",
    ):
        environment.pop(name, None)
    environment.update({"LC_ALL": "C", "LANG": "C"})
    provenance = {
        "cpu": args.cpu,
        "repetitions": args.repetitions,
        "source_sha256": sha256(sources["base"]),
        "variants": {
            variant: {
                "root": str(roots[variant]),
                "compiler_commit": COMMITS[variant],
                "binary_sha256": sha256(binaries[variant]),
                "version": versions[variant],
                "worktree_head": heads[variant],
                "checked_tree": tree_sha256(
                    roots[variant] / "stage2/out/lib/fstar/ulib.checked"
                ),
            }
            for variant in roots
        },
        "z3_sha256": sha256(args.z3.resolve()),
        "script_sha256": sha256(Path(__file__)),
        "monitor_script_sha256": sha256(
            Path(__file__).resolve().parent / "run_source_workloads.py"
        ),
    }
    (args.output / "provenance.json").write_text(
        json.dumps(provenance, indent=2) + "\n"
    )
    monitor = load_monitor()
    randomizer = random.Random(4799)
    measurements = args.output / "measurements.jsonl"
    repeats = list(range(1, args.repetitions + 1))
    randomizer.shuffle(repeats)
    for repeat in repeats:
        for variant in randomizer.sample(list(roots), len(roots)):
            root = roots[variant]
            source = sources[variant]
            command = [
                str(binaries[variant]),
                "--z3version", "5.3.0",
                "--smt", str(args.z3.resolve()),
                "--include", str(root / "stage2/out/lib/fstar/ulib"),
                "--include",
                str(root / "stage2/out/lib/fstar/ulib.checked"),
                "--dep", "full", str(source),
            ]
            run_dir = args.output / f"{repeat}-{variant}"
            run_dir.mkdir()
            log = run_dir / "run.log"
            measured = monitor(
                command, source.parent, environment, log, 120
            )
            row = {
                "variant": variant,
                "repeat": repeat,
                "command": command,
                "log_sha256": sha256(log),
                **measured,
            }
            with measurements.open("a") as stream:
                stream.write(json.dumps(row, sort_keys=True) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            if measured["returncode"] != 0 or measured["timed_out"]:
                raise RuntimeError(f"{variant}/{repeat} failed")


if __name__ == "__main__":
    main()
