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


Z3_SHA256 = "4da6a0f78424098b600a9112ebb9d8ce45de248a4913c26dd7d472e6dabef6d3"
TARGETS = {
    "long": {
        "ramon": "tests/calc/_cache/Long.fst.checked.ramon",
        "repetitions": 5,
        "timeout": 180,
    },
    "lib-vec": {
        "ramon": "tests/hacl/_cache/Lib.Vec.Lemmas.fst.checked.ramon",
        "repetitions": 5,
        "timeout": 180,
    },
    "cbor-boundary": {
        "ramon":
            "tests/custard/pulse/_cache/CborBoundarySlice.fst.checked.ramon",
        "repetitions": 5,
        "timeout": 300,
    },
    "calc-endpoint": {
        "ramon": (
            "pulse/share/pulse/examples/protocol/calc/_cache/"
            "Calc.Server.Endpoint.fst.checked.ramon"
        ),
        "repetitions": 5,
        "timeout": 180,
    },
    "bool-refinement": {
        "ramon": (
            "examples/dsls/bool_refinement/_cache/"
            "BoolRefinement.fst.checked.ramon"
        ),
        "repetitions": 3,
        "timeout": 300,
    },
    "float-extract": {
        "ramon": "tests/floats/_output/FloatExtract.krml.ramon",
        "repetitions": 10,
        "timeout": 120,
    },
    "ext-uint-div-rem": {
        "ramon": (
            "tests/extraction/backends/_cache/"
            "ExtUIntDivRem.fst.checked.ramon"
        ),
        "repetitions": 5,
        "timeout": 120,
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
    return {"files": len(files), "sha256": digest.hexdigest()}


def parse_ramon(path):
    text = path.read_text(errors="replace")
    argv = [
        match.group(1)
        for match in re.finditer(r"^argv\s+\d+ = (.*)$", text, re.M)
    ]
    cwd = re.search(r"^cwd\s+(.+)$", text, re.M).group(1)
    values = {}
    for key in (
        "root.utime", "root.stime", "group.total", "group.utime",
        "group.stime", "group.mempeak", "walltime",
    ):
        match = re.search(rf"^{re.escape(key)}\s+(.+)$", text, re.M)
        values[key] = match.group(1) if match else None
    return {
        "argv": argv,
        "cwd": cwd,
        "values": values,
        "sha256": sha256(path),
    }


def load_monitor():
    path = Path(__file__).resolve().parent / "run_latest_outliers.py"
    spec = importlib.util.spec_from_file_location("latest", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.monitor


def activate(prepared, stage, variant):
    selected = prepared / "installs" / variant
    if stage.exists() or not selected.is_dir():
        raise RuntimeError("invalid stage activation state")
    selected.rename(stage)


def deactivate(prepared, stage, variant):
    selected = prepared / "installs" / variant
    if selected.exists() or not stage.is_dir():
        raise RuntimeError("invalid stage deactivation state")
    stage.rename(selected)


def write_row(path, row):
    with path.open("a") as stream:
        stream.write(json.dumps(row, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--z3-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cpu", type=int, default=16)
    parser.add_argument("--seed", type=int, default=5101)
    parser.add_argument(
        "--target", action="append", choices=tuple(TARGETS)
    )
    parser.add_argument("--repetitions", type=int)
    args = parser.parse_args()
    source = args.source.resolve()
    prepared = args.prepared.resolve()
    artifact = args.artifact.resolve()
    stage = args.stage.resolve()
    if stage.exists():
        raise RuntimeError("stage path must not exist")
    if args.output.exists():
        raise RuntimeError("output must not exist")
    z3 = args.z3_dir.resolve() / "z3-5.3.0"
    if sha256(z3) != Z3_SHA256:
        raise RuntimeError("unexpected Z3 artifact")
    args.output.mkdir(parents=True)
    prepared_provenance = json.loads(
        (prepared / "provenance.json").read_text()
    )
    selected_targets = (
        set(args.target) if args.target else set(TARGETS)
    )
    specs = {}
    for target, details in TARGETS.items():
        if target not in selected_targets:
            continue
        base = parse_ramon(
            artifact / "ramon-files/base" / details["ramon"]
        )
        head = parse_ramon(
            artifact / "ramon-files/head" / details["ramon"]
        )
        parts = Path(base["cwd"]).parts
        marker = parts.index("fstar-base")
        relative_cwd = Path(*parts[marker + 1:])
        if relative_cwd != Path(*Path(head["cwd"]).parts[
            Path(head["cwd"]).parts.index("fstar-head") + 1:
        ]):
            raise RuntimeError(f"{target}: cwd differs")
        if base["argv"][1:] != head["argv"][1:]:
            raise RuntimeError(f"{target}: argv differs")
        specs[target] = {
            **details,
            "repetitions": (
                args.repetitions
                if args.repetitions is not None
                else details["repetitions"]
            ),
            "relative_cwd": str(relative_cwd),
            "argv": base["argv"][1:],
            "ci": {"base": base, "head": head},
        }
    os.sched_setaffinity(0, {args.cpu})
    environment = os.environ.copy()
    for name in (
        "FSTAR_LIB", "FSTAR_HOME", "OCAMLRUNPARAM", "CAMLRUNPARAM",
        "LD_PRELOAD", "LD_LIBRARY_PATH", "OCAMLPATH",
        "CAML_LD_LIBRARY_PATH", "FSTAR_MEM_REPORT",
    ):
        environment.pop(name, None)
    environment.update({
        "LC_ALL": "C",
        "LANG": "C",
        "PATH": (
            str(args.z3_dir.resolve())
            + os.pathsep + environment["PATH"]
        ),
    })
    monitor = load_monitor()
    randomizer = random.Random(args.seed)
    cells = [
        (target, repeat)
        for target, details in specs.items()
        for repeat in range(1, details["repetitions"] + 1)
    ]
    randomizer.shuffle(cells)
    measurements = args.output / "measurements.jsonl"
    for target, repeat in cells:
        details = specs[target]
        cwd = source / details["relative_cwd"]
        for variant in (
            ("base", "head") if repeat % 2 == 0 else ("head", "base")
        ):
            activate(prepared, stage, variant)
            try:
                cache = cwd / "_cache"
                generated = cwd / "_output"
                if cache.exists():
                    shutil.rmtree(cache)
                if generated.exists():
                    shutil.rmtree(generated)
                shutil.copytree(
                    prepared / "caches" / target / variant, cache
                )
                generated.mkdir()
                heap = args.output / (
                    f"{target}-{repeat}-{variant}.fstarmem"
                )
                env = environment.copy()
                env["FSTAR_MEM_REPORT"] = str(heap)
                command = [
                    str(stage / "bin/fstar.exe"),
                    *details["argv"],
                ]
                log = args.output / f"{target}-{repeat}-{variant}.log"
                measured = monitor(
                    command, cwd, env, log, details["timeout"]
                )
                heap_match = re.search(
                    r"fstar\.mempeak\s+([0-9]+)",
                    heap.read_text(),
                )
                if heap_match is None:
                    raise RuntimeError("heap report missing")
                output_relative = Path(
                    details["argv"][details["argv"].index("-o") + 1]
                ) if "-o" in details["argv"] else (
                    Path("_cache") / (
                        Path(details["argv"][-1]).name + ".checked"
                    )
                )
                output_path = cwd / output_relative
                if not output_path.exists():
                    candidates = [
                        path for path in (cache, generated)
                        if path.exists()
                    ]
                    output_hash = {
                        str(path.relative_to(cwd)): tree_sha256(path)
                        for path in candidates
                    }
                elif output_path.is_file():
                    output_hash = {
                        str(output_relative): sha256(output_path)
                    }
                else:
                    output_hash = {
                        str(output_relative): tree_sha256(output_path)
                    }
                row = {
                    "target": target,
                    "repeat": repeat,
                    "variant": variant,
                    "command": command,
                    "cwd": str(cwd),
                    "runtime_binary_sha256":
                        sha256(stage / "bin/fstar.exe"),
                    "runtime_install_tree": tree_sha256(stage),
                    "input_cache_tree": prepared_provenance[
                        "targets"
                    ][target][variant]["cache_tree"],
                    "fstar_heap_peak_bytes":
                        int(heap_match.group(1)),
                    "log_sha256": sha256(log),
                    "output_hash": output_hash,
                    **measured,
                }
                write_row(measurements, row)
                if measured["returncode"] != 0 or measured["timed_out"]:
                    raise RuntimeError(
                        f"{target}/{repeat}/{variant} failed"
                    )
            finally:
                for path in (cwd / "_cache", cwd / "_output"):
                    if path.exists():
                        shutil.rmtree(path)
                deactivate(prepared, stage, variant)
    (args.output / "provenance.json").write_text(json.dumps({
        "cpu": args.cpu,
        "seed": args.seed,
        "source": str(source),
        "source_head": subprocess.check_output(
            ["git", "-C", str(source), "rev-parse", "HEAD"], text=True
        ).strip(),
        "stage": str(stage),
        "z3": {"path": str(z3), "sha256": sha256(z3)},
        "prepared_provenance_sha256":
            sha256(prepared / "provenance.json"),
        "artifact_report_sha256": sha256(artifact / "report.html"),
        "targets": specs,
        "script_sha256": sha256(Path(__file__)),
        "monitor_sha256": sha256(
            Path(__file__).resolve().parent / "run_latest_outliers.py"
        ),
    }, indent=2) + "\n")


if __name__ == "__main__":
    main()
