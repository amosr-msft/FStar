#!/usr/bin/env python3

import argparse
import hashlib
import importlib.util
import json
import os
import random
import shutil
import subprocess
from pathlib import Path


VARIANTS = {
    "base": {
        "commit": "c68959fe1f070cd66a5ed2e92965185505f109ce",
        "binary": "8bd6f882f363ef45734caa875596182229436f1b53b6ea5d8a1584d2d1cedc3f",
        "checked":
            "4017dc355e1bd811d7cd0713de6ba66149e7416251c9e77fae8fac99ade8f84a",
    },
    "pr": {
        "commit": "e2c45ed0c4099f8d27ef0d78641ca8b626f4cdcb",
        "binary": "025429ead58f2b302c5854eca5f4475421f9a0aab1003e8242eb2cab5dbc686a",
        "checked":
            "59bf4cada8ec7bd5e9a06576354483ad86c23932d4386ab5311e57a778f549b7",
    },
    "cached": {
        "commit": "f4886d2decd874cd0008e31d6ba07c7da43c5ba4",
        "binary": [
            "e45671b08968de1ac22b3081f8b074c6966713ec577f147e4f686796b99fa17e",
            "8578fcb8034b2330dc2b8f74c352ed702fe93905da582b3a7076a781e9ea963d",
        ],
        "checked": [
            "3431ef516df8f95749d4ad90bffee7b7d3072ce213bf6ca0c82ad48491ebe8f5",
            "639c909d38045bff7f8751040bf4bda7d832cc77f7da072e91f6f0c85dacbb0a",
        ],
    },
    "optimized": {
        "commit": "c939875498355d0684b41138b5dbc208e34ef2b4",
        "binary": [
            "35e1c8f97bd7557e37723d2d0f8dec9b05dd29664037ab5312ca6ce4a5e469e3",
            "bb9a39e97ca2ed702551d466fac52cefcfb1855d49375a2b5f0cad789d3c432d",
        ],
        "checked": [
            "3431ef516df8f95749d4ad90bffee7b7d3072ce213bf6ca0c82ad48491ebe8f5",
            "75b9926e13e4dac9552050e5099ecda300e11e333122b3b65a380691a5dfb680",
        ],
    },
}
WORKLOADS = {
    "normalization": "tests/micro-benchmarks/Normalization.fst",
    "bv-binary-ops": "tests/micro-benchmarks/BvBinaryOps.fst",
    "bug3207": "tests/bug-reports/closed/Bug3207.fst",
    "long": "tests/calc/Long.fst",
    "arrow-unfold-limit": "tests/custard/ArrowUnfoldLimit.fst",
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
    parser.add_argument("--base", type=Path)
    parser.add_argument("--pr", type=Path)
    parser.add_argument("--cached", type=Path, required=True)
    parser.add_argument("--optimized", type=Path)
    parser.add_argument("--z3", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cpu", type=int, default=16)
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--dependency-only", action="store_true")
    args = parser.parse_args()
    if args.optimized is None:
        if args.base is None or args.pr is None:
            parser.error("--base and --pr are required without --optimized")
        roots = {
            "base": args.base.resolve(),
            "pr": args.pr.resolve(),
            "cached": args.cached.resolve(),
        }
    else:
        roots = {
            "cached": args.cached.resolve(),
            "optimized": args.optimized.resolve(),
        }
    binaries = {
        variant: root / "stage2/out/bin/fstar.exe"
        for variant, root in roots.items()
    }
    worktree_heads = {
        variant: subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
        ).strip()
        for variant, root in roots.items()
    }
    for variant, root in roots.items():
        spec = VARIANTS[variant]
        if subprocess.run([
            "git", "-C", str(root), "merge-base", "--is-ancestor",
            spec["commit"], worktree_heads[variant],
        ]).returncode != 0:
            raise RuntimeError(f"{variant}: unexpected ancestry")
        if subprocess.run([
            "git", "-C", str(root), "diff", "--quiet", spec["commit"],
            "--", "src", "ulib", "pulse",
        ]).returncode != 0:
            raise RuntimeError(f"{variant}: production sources differ")
        expected_binaries = (
            spec["binary"] if isinstance(spec["binary"], list)
            else [spec["binary"]]
        )
        checked = tree_sha256(
            roots[variant] / "stage2/out/lib/fstar/ulib.checked"
        )
        expected_checked = (
            spec["checked"] if isinstance(spec["checked"], list)
            else [spec["checked"]]
        )
        actual = sha256(binaries[variant]), checked["sha256"]
        allowed = set(zip(expected_binaries, expected_checked))
        if checked["files"] != 379 or actual not in allowed:
            raise RuntimeError(f"{variant}: compiler/dependency build differs")
    if sha256(args.z3.resolve()) != (
        "4da6a0f78424098b600a9112ebb9d8ce45de248a4913c26dd7d472e6dabef6d3"
    ):
        raise RuntimeError("unexpected Z3")
    workloads = (
        {"dependency-bug3207": WORKLOADS["bug3207"]}
        if args.dependency_only
        else WORKLOADS
    )
    source_hashes = {}
    for workload, relative in workloads.items():
        hashes = {
            variant: sha256(root / relative)
            for variant, root in roots.items()
        }
        if len(set(hashes.values())) != 1:
            raise RuntimeError(f"{workload}: source differs")
        source_hashes[workload] = next(iter(hashes.values()))
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
        "dependency_only": args.dependency_only,
        "source_sha256": source_hashes,
        "z3_sha256": sha256(args.z3.resolve()),
        "variants": {
            variant: {
                "root": str(root),
                "worktree_head": worktree_heads[variant],
                "source_commit": VARIANTS[variant]["commit"],
                "binary_sha256": sha256(binaries[variant]),
                "checked_tree": tree_sha256(
                    root / "stage2/out/lib/fstar/ulib.checked"
                ),
            }
            for variant, root in roots.items()
        },
        "script_sha256": sha256(Path(__file__)),
        "monitor_sha256": sha256(
            Path(__file__).resolve().parent / "run_source_workloads.py"
        ),
    }
    (args.output / "provenance.json").write_text(
        json.dumps(provenance, indent=2) + "\n"
    )
    monitor = load_monitor()
    randomizer = random.Random(4801 if args.dependency_only else 4802)
    cells = [
        (workload, repeat)
        for workload in workloads
        for repeat in range(1, args.repetitions + 1)
    ]
    randomizer.shuffle(cells)
    measurements = args.output / "measurements.jsonl"
    for workload, repeat in cells:
        for variant in randomizer.sample(list(roots), len(roots)):
            root = roots[variant]
            source = (root / workloads[workload]).resolve()
            run_dir = args.output / f"{repeat}-{workload}-{variant}"
            cache = run_dir / "cache"
            generated = run_dir / "output"
            cache.mkdir(parents=True)
            generated.mkdir()
            common = [
                str(binaries[variant]),
                "--z3version", "5.3.0",
                "--smt", str(args.z3.resolve()),
                "--include", str(root / "stage2/out/lib/fstar/ulib"),
                "--include",
                str(root / "stage2/out/lib/fstar/ulib.checked"),
            ]
            if args.dependency_only:
                command = [*common, "--dep", "full", str(source)]
                timeout = 120
            else:
                command = [
                    *common,
                    "--silent",
                    "--odir", str(generated),
                    "--cache_dir", str(cache),
                    "--already_cached", "Prims,FStar",
                    "--warn_error", "-321",
                    "--force",
                    "-c", str(source),
                    "-o", str(cache / f"{source.name}.checked"),
                ]
                timeout = 360
            log = run_dir / "run.log"
            measured = monitor(
                command, source.parent, environment, log, timeout
            )
            row = {
                "variant": variant,
                "workload": workload,
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
                raise RuntimeError(f"{variant}/{workload}/{repeat} failed")
            shutil.rmtree(cache)
            shutil.rmtree(generated)


if __name__ == "__main__":
    main()
