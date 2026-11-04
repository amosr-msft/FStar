#!/usr/bin/env python3

import argparse
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import time
from pathlib import Path

import psutil


VARIANTS = {
    "base": {
        "commit": "c68959fe1f070cd66a5ed2e92965185505f109ce",
        "binary": "1ef3f05e975404439063e941236a624cc5dc4d3fd72ec77c4c1ea30b707faa30",
        "ulib": "4017dc355e1bd811d7cd0713de6ba66149e7416251c9e77fae8fac99ade8f84a",
        "pulse_common":
            "323da1b69509a38269320f9387f6585fcfa0c0495b24eca097443b9b67ba42a4",
        "pulse": "02fcff3269600101a93cbde95b992fd31d6d081c90c2d1fc4b9de68fef650982",
    },
    "head": {
        "commit": "adbf7292f25542a538910711fef79bf4eb8c0bac",
        "binary": "509ac104cde150df8eaf91afc04f849f1e2b426bc92e58aaf50dfe22eaf2eede",
        "ulib": "3431ef516df8f95749d4ad90bffee7b7d3072ce213bf6ca0c82ad48491ebe8f5",
        "pulse_common":
            "93c1072c157471cfd4e7c9ab698727cc32e0a2dedb14e415d59b15ebc5fb647d",
        "pulse": "e89596fc9b48a70c1d50700d5e21e448e0c289f135e6facda947a882a1603916",
    },
}
WORKLOADS = {
    "ext-uint-mask": {
        "source": "tests/extraction/backends/ExtUIntMask.fst",
        "warn": "-349",
        "timeout": 900,
        "repetitions": 5,
    },
    "bv-model": {
        "source": "tests/micro-benchmarks/BvModelAgreesWithZ3.fst",
        "warn": "+240",
        "timeout": 900,
        "repetitions": 5,
    },
    "ext-uint-unsigned": {
        "source": "tests/extraction/backends/ExtUIntUnsigned.fst",
        "warn": "-349",
        "timeout": 600,
        "repetitions": 5,
    },
    "calc-protocol": {
        "source":
            "pulse/share/pulse/examples/protocol/calc/spec/Calc.Protocol.fst",
        "pulse": True,
        "timeout": 180,
        "repetitions": 10,
    },
    "tftp-client-log": {
        "source":
            "pulse/share/pulse/examples/protocol/tftp/impl/"
            "TFTP.Impl.Client.Log.fst",
        "pulse": True,
        "timeout": 300,
        "repetitions": 5,
    },
    "calc-log": {
        "source":
            "pulse/share/pulse/examples/protocol/calc/spec/Calc.Log.fst",
        "pulse": True,
        "timeout": 300,
        "repetitions": 5,
    },
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
        peak_root_rss = 0
        peak_group_rss = 0
        timed_out = False
        while True:
            processes = []
            try:
                processes = [root, *root.children(recursive=True)]
            except psutil.Error:
                pass
            group_rss = 0
            for child in processes:
                try:
                    times = child.cpu_times()
                    rss = child.memory_info().rss
                    cpu[child.pid] = {
                        "user": times.user,
                        "system": times.system,
                        "root": child.pid == process.pid,
                    }
                    group_rss += rss
                    if child.pid == process.pid:
                        peak_root_rss = max(peak_root_rss, rss)
                except psutil.Error:
                    pass
            peak_group_rss = max(peak_group_rss, group_rss)
            returncode = process.poll()
            if returncode is not None:
                break
            if time.monotonic() - started > timeout:
                process.kill()
                timed_out = True
                returncode = process.wait()
                break
            time.sleep(0.01)
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
        "peak_root_rss_bytes": peak_root_rss,
        "peak_group_rss_bytes": peak_group_rss,
        "observed_processes": len(cpu),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--head", type=Path, required=True)
    parser.add_argument("--z3", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cpu", type=int, default=16)
    parser.add_argument(
        "--workloads",
        nargs="+",
        choices=tuple(WORKLOADS),
    )
    args = parser.parse_args()
    roots = {"base": args.base.resolve(), "head": args.head.resolve()}
    workloads = (
        {name: WORKLOADS[name] for name in args.workloads}
        if args.workloads is not None
        else WORKLOADS
    )
    binaries = {
        variant: root / "stage3/out/bin/fstar.exe"
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
        if sha256(binaries[variant]) != spec["binary"]:
            raise RuntimeError(f"{variant}: binary differs")
        trees = {
            "ulib": tree_sha256(
                root / "stage3/out/lib/fstar/ulib.checked"
            ),
            "pulse_common": tree_sha256(
                root / "stage3/out/lib/fstar/pulse/common.checked"
            ),
            "pulse": tree_sha256(
                root / "stage3/out/lib/fstar/pulse/pulse.checked"
            ),
        }
        for name, tree in trees.items():
            if tree["sha256"] != spec[name]:
                raise RuntimeError(f"{variant}/{name}: tree differs")
    if sha256(args.z3.resolve()) != (
        "4da6a0f78424098b600a9112ebb9d8ce45de248a4913c26dd7d472e6dabef6d3"
    ):
        raise RuntimeError("unexpected Z3")
    source_hashes = {}
    for workload, details in workloads.items():
        hashes = {
            variant: sha256(root / details["source"])
            for variant, root in roots.items()
        }
        if len(set(hashes.values())) != 1:
            raise RuntimeError(f"{workload}: source differs")
        source_hashes[workload] = hashes["base"]
    args.output.mkdir(parents=True, exist_ok=True)
    if any(args.output.iterdir()):
        raise RuntimeError("output must be empty")
    os.sched_setaffinity(0, {args.cpu})
    base_environment = os.environ.copy()
    for name in (
        "FSTAR_LIB", "FSTAR_HOME", "OCAMLRUNPARAM", "CAMLRUNPARAM",
        "LD_PRELOAD", "LD_LIBRARY_PATH", "OCAMLPATH",
        "CAML_LD_LIBRARY_PATH", "FSTAR_MEM_REPORT",
    ):
        base_environment.pop(name, None)
    base_environment.update({"LC_ALL": "C", "LANG": "C"})
    provenance = {
        "cpu": args.cpu,
        "workloads": workloads,
        "source_sha256": source_hashes,
        "z3_sha256": sha256(args.z3.resolve()),
        "variants": {
            variant: {
                "root": str(root),
                "worktree_head": worktree_heads[variant],
                "source_commit": VARIANTS[variant]["commit"],
                "binary_sha256": sha256(binaries[variant]),
                "ulib_checked": tree_sha256(
                    root / "stage3/out/lib/fstar/ulib.checked"
                ),
                "pulse_common_checked": tree_sha256(
                    root / "stage3/out/lib/fstar/pulse/common.checked"
                ),
                "pulse_checked": tree_sha256(
                    root / "stage3/out/lib/fstar/pulse/pulse.checked"
                ),
                "pulse_suite_caches": {
                    suite: tree_sha256(root / suite / "_cache")
                    for suite in (
                        "pulse/share/pulse/examples/protocol/calc",
                        "pulse/share/pulse/examples/protocol/tftp",
                    )
                },
            }
            for variant, root in roots.items()
        },
        "script_sha256": sha256(Path(__file__)),
    }
    (args.output / "provenance.json").write_text(
        json.dumps(provenance, indent=2) + "\n"
    )
    randomizer = random.Random(4804)
    cells = [
        (workload, repeat)
        for workload, details in workloads.items()
        for repeat in range(1, details["repetitions"] + 1)
    ]
    randomizer.shuffle(cells)
    measurements = args.output / "measurements.jsonl"
    for workload, repeat in cells:
        details = WORKLOADS[workload]
        for variant in randomizer.sample(list(roots), len(roots)):
            root = roots[variant]
            source = (root / details["source"]).resolve()
            run_dir = args.output / f"{repeat}-{workload}-{variant}"
            isolated_cache = run_dir / "cache"
            isolated_output = run_dir / "output"
            isolated_cache.mkdir(parents=True)
            isolated_output.mkdir()
            mem_report = run_dir / "fstar.fstarmem"
            environment = base_environment.copy()
            environment["FSTAR_MEM_REPORT"] = str(mem_report)
            command = [
                str(binaries[variant]),
                "--z3version", "5.3.0",
                "--smt", str(args.z3.resolve()),
                "--silent",
            ]
            if details.get("pulse"):
                suite_root = source.parents[1]
                cache = suite_root / "_cache"
                generated = suite_root / "_output"
                (cache / (source.name + ".checked")).unlink(missing_ok=True)
                command.extend([
                    "--cache_checked_modules",
                    "--odir", str(generated),
                    "--cache_dir", str(cache),
                    "--already_cached",
                    "Prims,FStar,Pulse.Nolib,Pulse.Lib,Pulse.Class,PulseCore",
                    "--include", str(suite_root / "spec"),
                    "--include", str(suite_root / "impl"),
                    "--warn_error", "-321",
                    "--warn_error", "@247",
                    "--ext", "optimize_let_vc",
                    "--ext", "fly_deps",
                    str(source),
                ])
            else:
                cache = isolated_cache
                generated = isolated_output
                command.extend([
                    "--odir", str(generated),
                    "--cache_dir", str(cache),
                    "--already_cached", "Prims,FStar",
                    "--warn_error", "-321",
                    "--warn_error", details["warn"],
                    "-c", str(source),
                    "-o", str(cache / f"{source.name}.checked"),
                ])
            log = run_dir / "run.log"
            measured = monitor(
                command,
                suite_root if details.get("pulse") else source.parent,
                environment,
                log,
                details["timeout"],
            )
            fstar_heap = None
            if mem_report.is_file():
                match = re.search(
                    r"fstar\.mempeak\s+([0-9]+)",
                    mem_report.read_text(),
                )
                if match is not None:
                    fstar_heap = int(match.group(1))
            row = {
                "variant": variant,
                "workload": workload,
                "repeat": repeat,
                "command": command,
                "cwd": str(
                    suite_root if details.get("pulse") else source.parent
                ),
                "log_sha256": sha256(log),
                "fstar_heap_peak_bytes": fstar_heap,
                "fstarmem_sha256":
                    sha256(mem_report) if mem_report.is_file() else None,
                **measured,
            }
            with measurements.open("a") as stream:
                stream.write(json.dumps(row, sort_keys=True) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            if measured["returncode"] != 0 or measured["timed_out"]:
                raise RuntimeError(f"{variant}/{workload}/{repeat} failed")
            if not details.get("pulse"):
                shutil.rmtree(cache)
                shutil.rmtree(generated)


if __name__ == "__main__":
    main()
