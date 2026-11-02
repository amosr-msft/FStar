#!/usr/bin/env python3

import argparse
import hashlib
import json
import os
import random
import shutil
import subprocess
import time
from pathlib import Path

import psutil


COMPILER_COMMITS = {
    "base": "c68959fe1f070cd66a5ed2e92965185505f109ce",
    "head": "e2c45ed0c4099f8d27ef0d78641ca8b626f4cdcb",
}
BINARIES = {
    "base": "8bd6f882f363ef45734caa875596182229436f1b53b6ea5d8a1584d2d1cedc3f",
    "head": "025429ead58f2b302c5854eca5f4475421f9a0aab1003e8242eb2cab5dbc686a",
}
WORKLOADS = {
    "normalization": "tests/micro-benchmarks/Normalization.fst",
    "bv-binary-ops": "tests/micro-benchmarks/BvBinaryOps.fst",
    "bug3207": "tests/bug-reports/closed/Bug3207.fst",
    "long": "tests/calc/Long.fst",
    "arrow-unfold-limit": "tests/custard/ArrowUnfoldLimit.fst",
    "dependency-bug3207": "tests/bug-reports/closed/Bug3207.fst",
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


def monitor(command, cwd, environment, log_path, timeout):
    with log_path.open("w") as log:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=environment,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        root = psutil.Process(process.pid)
        started = time.monotonic()
        cpu = {}
        peak_rss = 0
        timed_out = False
        while True:
            processes = []
            try:
                processes = [root, *root.children(recursive=True)]
            except psutil.Error:
                pass
            for child in processes:
                try:
                    times = child.cpu_times()
                    cpu[child.pid] = {
                        "user": times.user,
                        "system": times.system,
                        "root": child.pid == process.pid,
                    }
                    peak_rss = max(peak_rss, child.memory_info().rss)
                except psutil.Error:
                    pass
            returncode = process.poll()
            if returncode is not None:
                break
            if time.monotonic() - started > timeout:
                process.kill()
                timed_out = True
                returncode = process.wait()
                break
            time.sleep(0.005)
        wall = time.monotonic() - started
    root_cpu = sum(
        item["user"] + item["system"]
        for item in cpu.values()
        if item["root"]
    )
    child_cpu = sum(
        item["user"] + item["system"]
        for item in cpu.values()
        if not item["root"]
    )
    return {
        "returncode": returncode,
        "timed_out": timed_out,
        "wall_seconds": wall,
        "root_cpu_seconds": root_cpu,
        "child_cpu_seconds": child_cpu,
        "peak_process_rss_bytes": peak_rss,
        "observed_processes": len(cpu),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--head", type=Path, required=True)
    parser.add_argument("--z3", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cpu", type=int, default=16)
    parser.add_argument("--repetitions", type=int, default=5)
    args = parser.parse_args()
    roots = {"base": args.base.resolve(), "head": args.head.resolve()}
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
    if worktree_heads["base"] != COMPILER_COMMITS["base"]:
        raise RuntimeError("unexpected base revision")
    if subprocess.run([
        "git", "-C", str(roots["head"]), "merge-base", "--is-ancestor",
        COMPILER_COMMITS["head"], worktree_heads["head"],
    ]).returncode != 0:
        raise RuntimeError("PR head is not an ancestor of evidence HEAD")
    changed = subprocess.check_output([
        "git", "-C", str(roots["head"]), "diff", "--name-only",
        COMPILER_COMMITS["head"],
    ], text=True).splitlines()
    untracked = subprocess.check_output([
        "git", "-C", str(roots["head"]), "ls-files", "--others",
        "--exclude-standard",
    ], text=True).splitlines()
    if any(
        not path.startswith("tests/benchmarks/pr4797-perf/")
        for path in changed + untracked
    ):
        raise RuntimeError("head worktree contains unrelated evidence changes")
    versions = {
        variant: subprocess.check_output(
            [str(binary), "--version"], text=True
        ).strip()
        for variant, binary in binaries.items()
    }
    for variant, binary in binaries.items():
        if (
            f"commit={COMPILER_COMMITS[variant]}" not in versions[variant]
            or sha256(binary) != BINARIES[variant]
        ):
            raise RuntimeError(f"{variant}: unexpected compiler binary")
    if sha256(args.z3.resolve()) != (
        "4da6a0f78424098b600a9112ebb9d8ce45de248a4913c26dd7d472e6dabef6d3"
    ):
        raise RuntimeError("unexpected Z3")
    source_hashes = {}
    for workload, relative in WORKLOADS.items():
        hashes = {
            variant: sha256(root / relative)
            for variant, root in roots.items()
        }
        if len(set(hashes.values())) != 1:
            raise RuntimeError(f"{workload}: source differs")
        source_hashes[workload] = hashes["base"]
    os.sched_setaffinity(0, {args.cpu})
    environment = os.environ.copy()
    for name in (
        "FSTAR_LIB",
        "FSTAR_HOME",
        "OCAMLRUNPARAM",
        "CAMLRUNPARAM",
        "FSTAR_PRUNING_REFERENCE",
        "LD_PRELOAD",
        "LD_LIBRARY_PATH",
        "OCAMLPATH",
        "CAML_LD_LIBRARY_PATH",
    ):
        environment.pop(name, None)
    environment.update({"LC_ALL": "C", "LANG": "C"})
    args.output.mkdir(parents=True, exist_ok=True)
    if any(args.output.iterdir()):
        raise RuntimeError("output must be empty")
    provenance = {
        "cpu": args.cpu,
        "repetitions": args.repetitions,
        "source_sha256": source_hashes,
        "z3": {
            "path": str(args.z3.resolve()),
            "sha256": sha256(args.z3.resolve()),
            "version": subprocess.check_output(
                [str(args.z3.resolve()), "--version"], text=True
            ).strip(),
        },
        "variants": {
            variant: {
                "root": str(root),
                "worktree_head": worktree_heads[variant],
                "compiler_commit": COMPILER_COMMITS[variant],
                "binary_sha256": sha256(binaries[variant]),
                "checked_tree": tree_sha256(
                    root / "stage2/out/lib/fstar/ulib.checked"
                ),
                "version": versions[variant],
            }
            for variant, root in roots.items()
        },
        "script_sha256": sha256(Path(__file__)),
    }
    (args.output / "provenance.json").write_text(
        json.dumps(provenance, indent=2) + "\n"
    )
    randomizer = random.Random(4797)
    cells = [
        (workload, repeat)
        for workload in WORKLOADS
        for repeat in range(1, args.repetitions + 1)
    ]
    randomizer.shuffle(cells)
    plan = []
    for workload, repeat in cells:
        variants = randomizer.sample(list(roots), len(roots))
        plan.extend((variant, workload, repeat) for variant in variants)
    results_path = args.output / "measurements.jsonl"
    for variant, workload, repeat in plan:
        root = roots[variant]
        source = (root / WORKLOADS[workload]).resolve()
        run_dir = args.output / f"{repeat}-{workload}-{variant}"
        cache = run_dir / "cache"
        generated = run_dir / "output"
        cache.mkdir(parents=True)
        generated.mkdir()
        common = [
            str(binaries[variant]),
            "--z3version",
            "5.3.0",
            "--smt",
            str(args.z3.resolve()),
            "--include",
            str(root / "stage2/out/lib/fstar/ulib"),
            "--include",
            str(root / "stage2/out/lib/fstar/ulib.checked"),
        ]
        if workload == "dependency-bug3207":
            command = [*common, "--dep", "full", str(source)]
            timeout = 120
        else:
            output = cache / f"{source.name}.checked"
            command = [
                *common,
                "--silent",
                "--odir",
                str(generated),
                "--cache_dir",
                str(cache),
                "--already_cached",
                "Prims,FStar",
                "--warn_error",
                "-321",
                "--force",
                "-c",
                str(source),
                "-o",
                str(output),
            ]
            timeout = 360
        log_path = run_dir / "run.log"
        measured = monitor(
            command,
            source.parent,
            environment,
            log_path,
            timeout,
        )
        row = {
            "variant": variant,
            "workload": workload,
            "repeat": repeat,
            "command": command,
            "cwd": str(source.parent),
            "log_sha256": sha256(log_path),
            **measured,
        }
        with results_path.open("a") as stream:
            stream.write(json.dumps(row, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        if measured["returncode"] != 0 or measured["timed_out"]:
            raise RuntimeError(f"{variant}/{workload}/{repeat} failed")
        shutil.rmtree(cache)
        shutil.rmtree(generated)


if __name__ == "__main__":
    main()
