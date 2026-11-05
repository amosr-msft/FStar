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
import tempfile
from pathlib import Path


EXPECTED = {
    "master": {
        "commit": "9ccacf4a8a392137d5384f8b39500377ebf53f79",
        "binary":
            "9c24fe8a04f8244948b877bbb4eb1d480b6bfd093d0fabdd8e99c53af4ebe098",
        "archive":
            "7bbe5c51bd111e4e1ba7ce1ce87f60d5c48a6095f22fa40d4ea0c3d71088793b",
        "checked":
            "9c36db327a39edccf01aa6caf78c1e1e1a0fa6390b2454c479b96399eda8e019",
    },
    "current-pr": {
        "commit": "17a249095c2215ca9aea56aa3e8e3c78d4b444ea",
        "binary":
            "70461743a87c84de2ec11bd56afee0e2188563d6a8b7dd2ff94dcf2cc71d7861",
        "archive":
            "85de6fa526ad3740f8fbf21031029ee0952cee1b85ae74c377122f8be580414b",
        "checked":
            "b297d104750fcee70bdb7fc70ee565cd750a6a96ae4f7183f03501b39437d739",
    },
    "no-flat": {
        "commit": "e03d632de7",
        "binary":
            "40788ea35d25ee0926a14f07a2eb3354d37eb74fec16dff7e1e7383849e8fa72",
        "archive":
            "f156d90c77b5acd83df4979b8f6a941543ba2805a55a16167b24d2077a67688a",
        "checked":
            "27ebad034d19f6ab79677da687b12555a9e7367d9d16617bce1cb5a06542ab76",
    },
    "trie": {
        "commit": "0a1c87e8bb",
        "binary":
            "96aec30290e9aab6b876f51cf8e9da5b0875f4aa3ff04b80ae99aa0f7d0a19cd",
        "archive":
            "e4564a2ce59149b8e976b8025bfec09bb5e00ef85c1f5565685c873f1d0662b5",
        "checked":
            "67398b51b3bb4fbd24792bb9c0395b6b6694e691dbde1b4ae357984217bd71e3",
    },
}
COMPARISONS = {
    "flat": {"current-pr", "no-flat"},
    "trie": {"master", "no-flat", "trie"},
}
CHECKED = {
    "test03": "tests/machine_integers/_cache/Test03.fst.checked.ramon",
    "tc-syntax": "tests/micro-benchmarks/_cache/TcSyntax.fst.checked.ramon",
    "merge-sort2": "examples/algorithms/_cache/MergeSort2.fst.checked.ramon",
    "ext-uint-div-rem":
        "tests/extraction/backends/_cache/ExtUIntDivRem.fst.checked.ramon",
    "bv-binary-ops":
        "tests/micro-benchmarks/_cache/BvBinaryOps.fst.checked.ramon",
    "long": "tests/calc/_cache/Long.fst.checked.ramon",
}
PACKAGES = (
    "threads,batteries,dynlink,mtime,mtime.clock,pprint,"
    "ppx_deriving.runtime,ppx_deriving_yojson.runtime,ppxlib,ppxlib.ast,"
    "process,stdint,yojson,zarith,unix"
)


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


def parse_variant(value):
    name, path = value.split("=", 1)
    if name not in EXPECTED:
        raise argparse.ArgumentTypeError(f"unknown variant: {name}")
    return name, Path(path)


def load_helpers():
    here = Path(__file__).resolve().parent
    latest_spec = importlib.util.spec_from_file_location(
        "latest_outliers", here / "run_latest_outliers.py"
    )
    latest = importlib.util.module_from_spec(latest_spec)
    latest_spec.loader.exec_module(latest)
    broad_spec = importlib.util.spec_from_file_location(
        "broad", here / "run_broad_reproduction.py"
    )
    broad = importlib.util.module_from_spec(broad_spec)
    broad_spec.loader.exec_module(broad)
    return latest.monitor, broad.parse_ramon


def checked_specs(artifact, roots, workloads):
    _, parse_ramon = load_helpers()
    specs = {}
    source_hashes = {}
    for workload, relative in CHECKED.items():
        if workloads and workload not in workloads:
            continue
        ramon = parse_ramon(artifact / "ramon-files/base" / relative)
        raw = ramon["argv"]
        source_arg = raw[raw.index("-c") + 1]
        parts = Path(ramon["cwd"]).parts
        marker = parts.index("fstar-base")
        relative_cwd = Path(*parts[marker + 1:])
        paths = {
            variant: root / relative_cwd / source_arg
            for variant, root in roots.items()
        }
        hashes = {variant: sha256(path) for variant, path in paths.items()}
        if len(set(hashes.values())) != 1:
            raise RuntimeError(f"{workload}: source differs")
        warn_args = []
        index = 1
        while index < len(raw):
            if raw[index] == "--warn_error":
                warn_args.extend(raw[index:index + 2])
                index += 2
            else:
                index += 1
        specs[workload] = {
            "relative_cwd": str(relative_cwd),
            "source_arg": source_arg,
            "warn_args": warn_args[2:],
            "ramon_sha256": ramon["sha256"],
        }
        source_hashes[workload] = next(iter(hashes.values()))
    return specs, source_hashes


def write_row(path, row):
    with path.open("a") as stream:
        stream.write(json.dumps(row, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def run_dependency(args, roots, binaries, environment, monitor):
    directory = "tests/bug-reports/closed"
    sources = [
        path.name
        for pattern in ("*.fst", "*.fsti")
        for path in sorted((next(iter(roots.values())) / directory).glob(pattern))
    ]
    source_hashes = {}
    for source in sources:
        hashes = {
            variant: sha256(root / directory / source)
            for variant, root in roots.items()
        }
        if len(set(hashes.values())) != 1:
            raise RuntimeError(f"{source}: source differs")
        source_hashes[source] = next(iter(hashes.values()))
    randomizer = random.Random(args.seed)
    repeats = list(range(1, args.repetitions + 1))
    randomizer.shuffle(repeats)
    measurements = args.output / "measurements.jsonl"
    for repeat in repeats:
        for variant in randomizer.sample(list(roots), len(roots)):
            root = roots[variant]
            run_dir = args.output / f"{repeat}-{variant}"
            cache = run_dir / "cache"
            generated = run_dir / "output"
            cache.mkdir(parents=True)
            generated.mkdir()
            command = [
                str(binaries[variant]),
                "--z3version", "5.3.0",
                "--smt", str(args.z3.resolve()),
                "--silent",
                "--odir", str(generated),
                "--cache_dir", str(cache),
                "--already_cached", "Prims,FStar",
                "--warn_error", "-321",
                "--warn_error", "-240",
                "--dep", "full",
                *sources,
                "-o", str(run_dir / ".depend"),
            ]
            log = run_dir / "run.log"
            measured = monitor(
                command, root / directory, environment, log, args.timeout
            )
            write_row(measurements, {
                "variant": variant,
                "repeat": repeat,
                "workload": "bug-reports-depend",
                "command": command,
                "cwd": str(root / directory),
                "log_sha256": sha256(log),
                **measured,
            })
            if measured["returncode"] != 0 or measured["timed_out"]:
                raise RuntimeError(f"{variant}/{repeat} failed")
            shutil.rmtree(cache)
            shutil.rmtree(generated)
    return {"source_arguments": sources, "source_sha256": source_hashes}


def run_checked(args, roots, binaries, environment, monitor):
    specs, source_hashes = checked_specs(
        args.artifact.resolve(), roots, args.workload
    )
    randomizer = random.Random(args.seed)
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
            source = (
                root / details["relative_cwd"] / details["source_arg"]
            ).resolve()
            run_dir = args.output / f"{repeat}-{workload}-{variant}"
            cache = run_dir / "cache"
            generated = run_dir / "output"
            cache.mkdir(parents=True)
            generated.mkdir()
            heap = run_dir / "fstar.fstarmem"
            env = environment.copy()
            env["FSTAR_MEM_REPORT"] = str(heap)
            command = [
                str(binaries[variant]),
                "--z3version", "5.3.0",
                "--smt", str(args.z3.resolve()),
                "--silent",
                "--odir", str(generated),
                "--cache_dir", str(cache),
                "--already_cached", "Prims,FStar",
                "--warn_error", "-321",
                *details["warn_args"],
                "-c", str(source),
                "-o", str(cache / f"{source.name}.checked"),
            ]
            log = run_dir / "run.log"
            measured = monitor(command, source.parent, env, log, args.timeout)
            heap_peak = None
            if heap.is_file():
                match = re.search(
                    r"fstar\.mempeak\s+([0-9]+)", heap.read_text()
                )
                if match is not None:
                    heap_peak = int(match.group(1))
            write_row(measurements, {
                "variant": variant,
                "repeat": repeat,
                "workload": workload,
                "command": command,
                "cwd": str(source.parent),
                "log_sha256": sha256(log),
                "fstar_heap_peak_bytes": heap_peak,
                **measured,
            })
            if measured["returncode"] != 0 or measured["timed_out"]:
                raise RuntimeError(f"{variant}/{workload}/{repeat} failed")
            shutil.rmtree(cache)
            shutil.rmtree(generated)
    return {"selection": specs, "source_sha256": source_hashes}


def run_structural(args, roots, environment, monitor):
    harness = Path(__file__).resolve().parent / "source_root_index_bench.ml"
    measurements = args.output / "measurements.jsonl"
    provenance = {
        "harness_sha256": sha256(harness),
        "root_counts": [1, 16, 64, 256],
        "distinct_iterations": 5_000,
        "repeated_iterations": 20_000,
        "cold_iterations": 500,
    }
    with tempfile.TemporaryDirectory(
        prefix="source-root-index-", dir=args.output
    ) as directory:
        fixture = Path(directory)
        (fixture / "owned/A/B").mkdir(parents=True)
        (fixture / "owned/A/B/C.fst").write_text("module A.B.C\n")
        executables = {}
        for variant, root in roots.items():
            build = root / "stage2/dune/_build/default/fstar-guts"
            archive = build / "fstarcompiler.cmxa"
            executable = fixture / f"{variant}.exe"
            command = [
                "ocamlfind", "ocamlopt", "-thread", "-linkpkg",
                "-package", PACKAGES,
                "-I", str(build / ".fstarcompiler.objs/byte"),
                "-I", str(build / ".fstarcompiler.objs/native"),
                str(archive), str(harness), "-o", str(executable),
            ]
            subprocess.run(
                command, cwd=fixture, env=environment, check=True
            )
            executables[variant] = executable
            provenance[variant] = {
                "archive_sha256": sha256(archive),
                "executable_sha256": sha256(executable),
                "compile_command": command,
            }
        randomizer = random.Random(args.seed)
        cells = [
            (root_count, repeat)
            for root_count in provenance["root_counts"]
            for repeat in range(1, args.repetitions + 1)
        ]
        randomizer.shuffle(cells)
        for root_count, repeat in cells:
            for variant in randomizer.sample(list(roots), len(roots)):
                log = args.output / f"{repeat}-{variant}.log"
                log = (
                    args.output
                    / f"{root_count}-{repeat}-{variant}.log"
                )
                command = [
                    str(executables[variant]), str(fixture), str(root_count)
                ]
                measured = monitor(
                    command, fixture, environment, log, args.timeout
                )
                parsed = []
                for line in log.read_text().splitlines():
                    fields = line.split()
                    if len(fields) == 7 and fields[0].isdigit():
                        parsed.append({
                            "roots": int(fields[0]),
                            "distinct_seconds": float(fields[1]),
                            "distinct_matches": int(fields[2]),
                            "repeated_seconds": float(fields[3]),
                            "repeated_matches": int(fields[4]),
                            "cold_seconds": float(fields[5]),
                            "cold_matches": int(fields[6]),
                        })
                if len(parsed) != 1 or any(
                    row["roots"] != root_count
                    or
                    row["distinct_matches"] != 5_000
                    or row["repeated_matches"] != 20_000
                    or row["cold_matches"] != 500
                    for row in parsed
                ):
                    raise RuntimeError(f"{variant}/{repeat}: bad output")
                write_row(measurements, {
                    "variant": variant,
                    "repeat": repeat,
                    "roots": root_count,
                    "workload": "source-root-index",
                    "command": command,
                    "log_sha256": sha256(log),
                    "internal": parsed,
                    **measured,
                })
                if measured["returncode"] != 0 or measured["timed_out"]:
                    raise RuntimeError(f"{variant}/{repeat} failed")
    return provenance


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--variant", action="append", type=parse_variant, required=True
    )
    parser.add_argument(
        "--kind", choices=("dependency", "checked", "structural"),
        required=True,
    )
    parser.add_argument(
        "--comparison", choices=tuple(COMPARISONS), required=True
    )
    parser.add_argument("--z3", type=Path)
    parser.add_argument("--artifact", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cpu", type=int, default=16)
    parser.add_argument("--repetitions", type=int, required=True)
    parser.add_argument("--seed", type=int, default=4817)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument(
        "--workload", action="append", choices=tuple(CHECKED)
    )
    args = parser.parse_args()
    roots = {name: path.resolve() for name, path in args.variant}
    if len(roots) != len(args.variant):
        raise RuntimeError("duplicate variant")
    if set(roots) != COMPARISONS[args.comparison]:
        raise RuntimeError(
            f"{args.comparison} requires {sorted(COMPARISONS[args.comparison])}"
        )
    if args.kind == "structural" and args.comparison != "trie":
        raise RuntimeError("structural measurements require trie comparison")
    if args.kind != "structural" and args.z3 is None:
        parser.error("--z3 is required")
    if args.kind == "checked" and args.artifact is None:
        parser.error("--artifact is required")
    args.output.mkdir(parents=True, exist_ok=True)
    if any(args.output.iterdir()):
        raise RuntimeError("output must be empty")
    binaries = {
        variant: root / "stage3/out/bin/fstar.exe"
        for variant, root in roots.items()
    }
    variants = {}
    for variant, root in roots.items():
        head = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
        ).strip()
        expected = EXPECTED[variant]
        if not head.startswith(expected["commit"]):
            raise RuntimeError(
                f"{variant}: {head} != {expected['commit']}"
            )
        status = subprocess.check_output([
            "git", "-C", str(root), "status", "--porcelain",
            "--untracked-files=all", "--", "src", "ulib", "pulse",
        ], text=True)
        if status:
            raise RuntimeError(f"{variant}: production sources dirty")
        binary_hash = sha256(binaries[variant])
        archive_hash = sha256(
            root / "stage2/dune/_build/default/fstar-guts/fstarcompiler.cmxa"
        )
        checked = tree_sha256(
            root / "stage3/out/lib/fstar/ulib.checked"
        )
        if (
            binary_hash != expected["binary"]
            or archive_hash != expected["archive"]
            or checked != {"sha256": expected["checked"], "files": 379}
        ):
            raise RuntimeError(f"{variant}: build artifacts differ")
        variants[variant] = {
            "root": str(root),
            "head": head,
            "binary_sha256": binary_hash,
            "archive_sha256": archive_hash,
            "checked_tree": checked,
            "submodules": subprocess.check_output(
                ["git", "-C", str(root), "submodule", "status"],
                text=True,
            ).splitlines(),
        }
    if args.z3 is not None and sha256(args.z3.resolve()) != (
        "4da6a0f78424098b600a9112ebb9d8ce45de248a4913c26dd7d472e6dabef6d3"
    ):
        raise RuntimeError("unexpected Z3")
    os.sched_setaffinity(0, {args.cpu})
    environment = os.environ.copy()
    for name in (
        "FSTAR_LIB", "FSTAR_HOME", "OCAMLRUNPARAM", "CAMLRUNPARAM",
        "LD_PRELOAD", "LD_LIBRARY_PATH", "OCAMLPATH",
        "CAML_LD_LIBRARY_PATH", "FSTAR_MEM_REPORT",
    ):
        environment.pop(name, None)
    environment.update({"LC_ALL": "C", "LANG": "C"})
    ocamlopt = Path(shutil.which("ocamlopt")).resolve()
    ocamlfind = Path(shutil.which("ocamlfind")).resolve()
    monitor, _ = load_helpers()
    if args.kind == "dependency":
        workload = run_dependency(
            args, roots, binaries, environment, monitor
        )
    elif args.kind == "checked":
        workload = run_checked(
            args, roots, binaries, environment, monitor
        )
    else:
        workload = run_structural(args, roots, environment, monitor)
    provenance = {
        "kind": args.kind,
        "comparison": args.comparison,
        "cpu": args.cpu,
        "repetitions": args.repetitions,
        "seed": args.seed,
        "variants": variants,
        "z3_sha256": sha256(args.z3.resolve()) if args.z3 else None,
        "script_sha256": sha256(Path(__file__)),
        "monitor_sha256": sha256(
            Path(__file__).resolve().parent / "run_latest_outliers.py"
        ),
        "ocaml": {
            "version": subprocess.check_output(
                [str(ocamlopt), "-version"], text=True
            ).strip(),
            "ocamlopt": str(ocamlopt),
            "ocamlopt_sha256": sha256(ocamlopt),
            "ocamlfind": str(ocamlfind),
            "ocamlfind_sha256": sha256(ocamlfind),
        },
        "workload": workload,
    }
    (args.output / "provenance.json").write_text(
        json.dumps(provenance, indent=2) + "\n"
    )


if __name__ == "__main__":
    main()
