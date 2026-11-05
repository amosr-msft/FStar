#!/usr/bin/env python3

import argparse
import hashlib
import importlib.util
import json
import os
import random
import re
import shutil
import subprocess
from pathlib import Path


VARIANTS = {
    "base": {
        "commit": "c68959fe1f070cd66a5ed2e92965185505f109ce",
        "binary": "1ef3f05e975404439063e941236a624cc5dc4d3fd72ec77c4c1ea30b707faa30",
        "ulib": "4017dc355e1bd811d7cd0713de6ba66149e7416251c9e77fae8fac99ade8f84a",
    },
    "head": {
        "commit": "adbf7292f25542a538910711fef79bf4eb8c0bac",
        "binary": "509ac104cde150df8eaf91afc04f849f1e2b426bc92e58aaf50dfe22eaf2eede",
        "ulib": "3431ef516df8f95749d4ad90bffee7b7d3072ce213bf6ca0c82ad48491ebe8f5",
    },
}
CHECKED = {
    "test03": "tests/machine_integers/_cache/Test03.fst.checked.ramon",
    "bug097b": "tests/bug-reports/closed/_cache/Bug097b.fst.checked.ramon",
    "tc-syntax": "tests/micro-benchmarks/_cache/TcSyntax.fst.checked.ramon",
    "bug4287": "tests/bug-reports/closed/_cache/Bug4287.fst.checked.ramon",
    "bug1414": "tests/bug-reports/closed/_cache/Bug1414.fst.checked.ramon",
    "test-sealed": "tests/micro-benchmarks/_cache/TestSealed.fst.checked.ramon",
    "merge-sort2": "examples/algorithms/_cache/MergeSort2.fst.checked.ramon",
    "test-mbqi": "tests/bug-reports/closed/_cache/TestMBQI.fst.checked.ramon",
    "ext-uint-div-rem":
        "tests/extraction/backends/_cache/ExtUIntDivRem.fst.checked.ramon",
    "ext-int-div-rem":
        "tests/extraction/backends/_cache/ExtIntDivRem.fst.checked.ramon",
    "bv-binary-ops":
        "tests/micro-benchmarks/_cache/BvBinaryOps.fst.checked.ramon",
    "canon-semiring":
        "tests/semiring/_cache/CanonCommSemiring.fst.checked.ramon",
    "long": "tests/calc/_cache/Long.fst.checked.ramon",
    "ext-uint-rotate":
        "tests/extraction/backends/_cache/ExtUIntRotate.fst.checked.ramon",
    "rbtree":
        "examples/data_structures/_cache/RBTreeIntrinsic.fst.checked.ramon",
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
    path = Path(__file__).resolve().parent / "run_latest_outliers.py"
    spec = importlib.util.spec_from_file_location("latest_outliers", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.monitor


def parse_ramon(path):
    text = path.read_text(errors="replace")
    argv = [
        match.group(1)
        for match in re.finditer(r"^argv\s+\d+ = (.*)$", text, re.M)
    ]
    cwd = re.search(r"^cwd\s+(.+)$", text, re.M).group(1)
    return {"argv": argv, "cwd": cwd, "sha256": sha256(path)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--head", type=Path, required=True)
    parser.add_argument("--z3", type=Path, required=True)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cpu", type=int, default=16)
    parser.add_argument("--repetitions", type=int, default=5)
    args = parser.parse_args()
    roots = {"base": args.base.resolve(), "head": args.head.resolve()}
    binaries = {
        variant: root / "stage3/out/bin/fstar.exe"
        for variant, root in roots.items()
    }
    heads = {
        variant: subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
        ).strip()
        for variant, root in roots.items()
    }
    for variant, root in roots.items():
        expected = VARIANTS[variant]
        if subprocess.run([
            "git", "-C", str(root), "merge-base", "--is-ancestor",
            expected["commit"], heads[variant],
        ]).returncode != 0:
            raise RuntimeError(f"{variant}: unexpected ancestry")
        if subprocess.run([
            "git", "-C", str(root), "diff", "--quiet",
            expected["commit"], "--", "src", "ulib", "pulse",
        ]).returncode != 0:
            raise RuntimeError(f"{variant}: production sources differ")
        if sha256(binaries[variant]) != expected["binary"]:
            raise RuntimeError(f"{variant}: compiler differs")
        checked = tree_sha256(
            root / "stage3/out/lib/fstar/ulib.checked"
        )
        if checked != {"sha256": expected["ulib"], "files": 379}:
            raise RuntimeError(f"{variant}: dependency tree differs")
    if sha256(args.z3.resolve()) != (
        "4da6a0f78424098b600a9112ebb9d8ce45de248a4913c26dd7d472e6dabef6d3"
    ):
        raise RuntimeError("unexpected Z3")
    artifact = args.artifact.resolve()
    report_rows = {
        row["full"]: row
        for row in json.loads(
            (artifact / "timeData.json").read_text()
        )
    }
    specs = {}
    for workload, relative in CHECKED.items():
        ramon = parse_ramon(
            artifact / "ramon-files/base" / relative
        )
        full = relative.removesuffix(".ramon")
        report = report_rows[full]
        specs[workload] = {
            "kind": "checked",
            "relative": relative,
            "ramon": ramon,
            "ci_base_seconds": report["base"],
            "ci_head_seconds": report["patch"],
        }
    dep_dir = "tests/bug-reports/closed"
    dep_sources = [
        str(path.relative_to(roots["base"] / dep_dir))
        for pattern in ("*.fst", "*.fsti")
        for path in sorted(
            (roots["base"] / dep_dir).glob(pattern)
        )
    ]
    specs["bug-reports-depend"] = {
        "kind": "dependency",
        "directory": dep_dir,
        "sources": dep_sources,
        "ci_base_seconds": report_rows[
            "tests/bug-reports/closed/.depend"
        ]["base"],
        "ci_head_seconds": report_rows[
            "tests/bug-reports/closed/.depend"
        ]["patch"],
    }
    source_hashes = {}
    for workload, details in specs.items():
        if details["kind"] == "checked":
            raw_argv = details["ramon"]["argv"]
            source_arg = raw_argv[raw_argv.index("-c") + 1]
            cwd_suffix = Path(details["ramon"]["cwd"]).parts
            marker = cwd_suffix.index("fstar-base")
            relative_cwd = Path(*cwd_suffix[marker + 1:])
            paths = {
                variant: root / relative_cwd / source_arg
                for variant, root in roots.items()
            }
            if len({sha256(path) for path in paths.values()}) != 1:
                raise RuntimeError(f"{workload}: source differs")
            details["relative_cwd"] = str(relative_cwd)
            details["source_arg"] = source_arg
            source_hashes[workload] = sha256(paths["base"])
        else:
            for source in details["sources"]:
                paths = {
                    variant: root / details["directory"] / source
                    for variant, root in roots.items()
                }
                if len({sha256(path) for path in paths.values()}) != 1:
                    raise RuntimeError(f"{workload}/{source}: differs")
            source_hashes[workload] = hashlib.sha256(
                "\n".join(
                    f"{source}\0{sha256(roots['base'] / details['directory'] / source)}"
                    for source in details["sources"]
                ).encode()
            ).hexdigest()
    args.output.mkdir(parents=True, exist_ok=True)
    if any(args.output.iterdir()):
        raise RuntimeError("output must be empty")
    os.sched_setaffinity(0, {args.cpu})
    environment = os.environ.copy()
    for name in (
        "FSTAR_LIB", "FSTAR_HOME", "OCAMLRUNPARAM", "CAMLRUNPARAM",
        "LD_PRELOAD", "LD_LIBRARY_PATH", "OCAMLPATH",
        "CAML_LD_LIBRARY_PATH", "FSTAR_MEM_REPORT",
    ):
        environment.pop(name, None)
    environment.update({"LC_ALL": "C", "LANG": "C"})
    provenance = {
        "cpu": args.cpu,
        "repetitions": args.repetitions,
        "selection": specs,
        "source_sha256": source_hashes,
        "z3_sha256": sha256(args.z3.resolve()),
        "variants": {
            variant: {
                "root": str(root),
                "worktree_head": heads[variant],
                "source_commit": VARIANTS[variant]["commit"],
                "binary_sha256": sha256(binaries[variant]),
                "ulib_checked": tree_sha256(
                    root / "stage3/out/lib/fstar/ulib.checked"
                ),
            }
            for variant, root in roots.items()
        },
        "script_sha256": sha256(Path(__file__)),
        "monitor_sha256": sha256(
            Path(__file__).resolve().parent / "run_latest_outliers.py"
        ),
    }
    (args.output / "provenance.json").write_text(
        json.dumps(provenance, indent=2) + "\n"
    )
    monitor = load_monitor()
    randomizer = random.Random(4805)
    cells = [
        (workload, repeat)
        for workload in specs
        for repeat in range(1, args.repetitions + 1)
    ]
    randomizer.shuffle(cells)
    measurements = args.output / "measurements.jsonl"
    for workload, repeat in cells:
        details = specs[workload]
        for variant in randomizer.sample(list(roots), len(roots)):
            root = roots[variant]
            run_dir = args.output / f"{repeat}-{workload}-{variant}"
            cache = run_dir / "cache"
            generated = run_dir / "output"
            cache.mkdir(parents=True)
            generated.mkdir()
            heap = run_dir / "fstar.fstarmem"
            env = environment.copy()
            env["FSTAR_MEM_REPORT"] = str(heap)
            common = [
                str(binaries[variant]),
                "--z3version", "5.3.0",
                "--smt", str(args.z3.resolve()),
                "--silent",
                "--odir", str(generated),
                "--cache_dir", str(cache),
                "--already_cached", "Prims,FStar",
                "--warn_error", "-321",
            ]
            if details["kind"] == "checked":
                raw = details["ramon"]["argv"][1:]
                warn_args = []
                index = 0
                while index < len(raw):
                    if raw[index] == "--warn_error":
                        warn_args.extend(raw[index:index + 2])
                        index += 2
                    else:
                        index += 1
                source = (
                    root / details["relative_cwd"] / details["source_arg"]
                ).resolve()
                command = [
                    *common,
                    *warn_args[2:],
                    "-c", str(source),
                    "-o", str(cache / f"{source.name}.checked"),
                ]
                cwd = source.parent
                timeout = max(120, int(details["ci_base_seconds"] * 4 + 60))
            else:
                cwd = (root / details["directory"]).resolve()
                command = [
                    *common,
                    "--warn_error", "-240",
                    "--dep", "full",
                    *[
                        str((cwd / source).resolve())
                        for source in details["sources"]
                    ],
                    "-o", str(run_dir / ".depend"),
                ]
                timeout = 180
            log = run_dir / "run.log"
            measured = monitor(command, cwd, env, log, timeout)
            heap_peak = None
            if heap.is_file():
                match = re.search(
                    r"fstar\.mempeak\s+([0-9]+)", heap.read_text()
                )
                if match is not None:
                    heap_peak = int(match.group(1))
            row = {
                "variant": variant,
                "workload": workload,
                "repeat": repeat,
                "command": command,
                "cwd": str(cwd),
                "log_sha256": sha256(log),
                "fstar_heap_peak_bytes": heap_peak,
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
