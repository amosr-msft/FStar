#!/usr/bin/env python3

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path


COMMIT = "850c09bed1b8167e4e91a396d563e20e485ec446"
FSTAR = "acd01bedf88b61cc0ee5d37c1592305fd0b5b4d4af9910e708a2edb6856a07e1"
ARCHIVE = "3269489fbdd6c30c0326bf3eef6dfc14b458484674164662841d2a071d0ceb5c"
Z3 = "4da6a0f78424098b600a9112ebb9d8ce45de248a4913c26dd7d472e6dabef6d3"
PACKAGES = (
    "threads,batteries,dynlink,mtime,mtime.clock,pprint,"
    "ppx_deriving.runtime,ppx_deriving_yojson.runtime,ppxlib,ppxlib.ast,"
    "process,stdint,yojson,zarith,unix"
)
PATTERN = re.compile(
    r"PR4797_SINGLE_INDEX mode=(\w+) index_builds=(\d+) "
    r"trie_builds=(\d+) flat_builds=(\d+) roots_total=(\d+) "
    r"allocated_bytes=([0-9.]+) minor_words=([0-9.]+) "
    r"promoted_words=([0-9.]+) major_words=([0-9.]+) "
    r"minor_collections=(\d+) major_collections=(\d+) "
    r"compactions=(\d+) heap_words=(\d+) top_heap_words=(\d+)"
)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_monitor():
    path = Path(__file__).resolve().parent / "run_latest_outliers.py"
    spec = importlib.util.spec_from_file_location("latest", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.monitor


def parse_trace(text):
    match = PATTERN.search(text)
    if match is None:
        raise RuntimeError("single-index trace missing")
    names = (
        "mode", "index_builds", "trie_builds", "flat_builds",
        "roots_total", "allocated_bytes", "minor_words",
        "promoted_words", "major_words", "minor_collections",
        "major_collections", "compactions", "heap_words",
        "top_heap_words",
    )
    result = dict(zip(names, match.groups()))
    for name in names[1:]:
        result[name] = float(result[name])
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--worktree", type=Path, required=True)
    parser.add_argument("--fstar", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--z3", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cpu", type=int, default=16)
    parser.add_argument("--repetitions", type=int, default=3)
    args = parser.parse_args()
    root = args.worktree.resolve()
    fstar = args.fstar.resolve()
    archive = args.archive.resolve()
    head = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
    ).strip()
    if (
        head != COMMIT or sha256(fstar) != FSTAR
        or sha256(archive) != ARCHIVE or sha256(args.z3.resolve()) != Z3
    ):
        raise RuntimeError("unexpected diagnostic artifact")
    args.output.mkdir(parents=True, exist_ok=True)
    if any(args.output.iterdir()):
        raise RuntimeError("output must be empty")
    os.sched_setaffinity(0, {args.cpu})
    environment = os.environ.copy()
    environment.update({"LC_ALL": "C", "LANG": "C"})
    environment.pop("FSTAR_FLAT_ROOT_DIAGNOSTIC", None)
    directory = root / "tests/bug-reports/closed"
    sources = [
        path.name
        for pattern in ("*.fst", "*.fsti")
        for path in sorted(directory.glob(pattern))
    ]
    monitor = load_monitor()
    rows = []
    for repeat in range(1, args.repetitions + 1):
        order = ("trie", "flat") if repeat % 2 else ("flat", "trie")
        for mode in order:
            run_dir = args.output / f"{repeat}-{mode}"
            cache = run_dir / "cache"
            generated = run_dir / "output"
            cache.mkdir(parents=True)
            generated.mkdir()
            heap = run_dir / "fstar.fstarmem"
            env = environment.copy()
            env["FSTAR_MEM_REPORT"] = str(heap)
            if mode == "flat":
                env["FSTAR_FLAT_ROOT_DIAGNOSTIC"] = "1"
            command = [
                str(fstar), "--z3version", "5.3.0",
                "--smt", str(args.z3.resolve()), "--silent",
                "--odir", str(generated), "--cache_dir", str(cache),
                "--already_cached", "Prims,FStar",
                "--warn_error", "-321", "--warn_error", "-240",
                "--dep", "full", *sources,
                "-o", str(run_dir / ".depend"),
            ]
            log = run_dir / "run.log"
            measured = monitor(command, directory, env, log, 180)
            trace = parse_trace(log.read_text())
            heap_match = re.search(
                r"fstar\.mempeak\s+([0-9]+)", heap.read_text()
            )
            row = {
                "repeat": repeat,
                "mode": mode,
                "trace": trace,
                "fstar_heap_peak_bytes": int(heap_match.group(1)),
                "log_sha256": sha256(log),
                **measured,
            }
            rows.append(row)
            if measured["returncode"] != 0 or measured["timed_out"]:
                raise RuntimeError(f"{repeat}/{mode} failed")
            shutil.rmtree(cache)
            shutil.rmtree(generated)
    harness = (
        Path(__file__).resolve().parent / "single_index_differential.ml"
    )
    build = root / "stage3/dune/_build/default/fstar-guts"
    lifecycle = {}
    with tempfile.TemporaryDirectory(
        prefix="single-index-lifecycle-", dir=args.output
    ) as temporary:
        fixture = Path(temporary)
        for relative in (
            "outer", "outer/flat", "outer/flat/nested", "sibling",
            "outer-suffix",
        ):
            (fixture / relative).mkdir(parents=True)
        executable = fixture / "lifecycle.exe"
        compile_command = [
            "ocamlfind", "ocamlopt", "-thread", "-linkpkg",
            "-package", PACKAGES,
            "-I", str(build / ".fstarcompiler.objs/byte"),
            "-I", str(build / ".fstarcompiler.objs/native"),
            str(archive), str(harness), "-o", str(executable),
        ]
        subprocess.run(compile_command, cwd=fixture, check=True)
        for mode in ("trie", "flat"):
            env = environment.copy()
            if mode == "flat":
                env["FSTAR_FLAT_ROOT_DIAGNOSTIC"] = "1"
            process = subprocess.run(
                [str(executable), str(fixture), "rebuild"],
                cwd=fixture,
                env=env,
                text=True,
                capture_output=True,
                check=True,
            )
            trace = parse_trace(process.stderr)
            if (
                trace["index_builds"] != 3
                or trace["trie_builds"] != (0 if mode == "flat" else 3)
                or trace["flat_builds"] != (3 if mode == "flat" else 0)
            ):
                raise RuntimeError(f"{mode}: invalid construction trace")
            lifecycle[mode] = {
                "stdout": process.stdout.strip(),
                "trace": trace,
            }
    extracted = root / "stage2/fstarc.ml/FStarC_Find.ml"
    extracted_text = extracted.read_text()
    invariant = {
        "tagged_index": "type source_root_index =" in extracted_text,
        "flat_constructor": "FlatRootMap" in extracted_text,
        "trie_constructor": "ComponentTrie" in extracted_text,
        "branch_local_flat_allocation": (
            "if use_flat_source_root_index then "
            "(incr diagnostic_flat_builds;\n"
            "        let roots =" in extracted_text
        ),
        "branch_local_trie_allocation": (
            "else (incr diagnostic_trie_builds;\n"
            "        let tmp3 = (empty_source_root_trie ())" in extracted_text
        ),
    }
    if not all(invariant.values()):
        raise RuntimeError(f"extracted invariant failed: {invariant}")
    (args.output / "result.json").write_text(json.dumps({
        "provenance": {
            "cpu": args.cpu,
            "repetitions": args.repetitions,
            "head": head,
            "fstar_sha256": sha256(fstar),
            "archive_sha256": sha256(archive),
            "z3_sha256": sha256(args.z3.resolve()),
            "runner_sha256": sha256(Path(__file__)),
            "instrument_sha256": sha256(
                Path(__file__).resolve().parent
                / "instrument_single_index.py"
            ),
            "harness_sha256": sha256(harness),
            "extracted_find_sha256": sha256(extracted),
            "source_manifest_sha256": hashlib.sha256(
                "\n".join(sources).encode()
            ).hexdigest(),
        },
        "extracted_invariant": invariant,
        "dependency_rows": rows,
        "lifecycle": lifecycle,
    }, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
