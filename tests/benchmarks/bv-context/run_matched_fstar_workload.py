#!/usr/bin/env python3

import argparse
import hashlib
import json
import os
import random
import re
import subprocess
from pathlib import Path


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


def elapsed(text):
    fields = re.search(
        r"Elapsed \(wall clock\) time.*: ([0-9:.]+)$", text, re.M
    ).group(1).split(":")
    seconds = float(fields[-1])
    if len(fields) >= 2:
        seconds += 60 * int(fields[-2])
    if len(fields) == 3:
        seconds += 3600 * int(fields[-3])
    return seconds


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--z3", type=Path, required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()
    roots = {
        "baseline": args.baseline.resolve(),
        "candidate": args.candidate.resolve(),
    }
    binaries = {
        variant: root / "stage2/out/bin/fstar.exe"
        for variant, root in roots.items()
    }
    sources = {
        variant: root / args.source for variant, root in roots.items()
    }
    if any(subprocess.check_output(
        ["git", "-C", str(root), "status", "--porcelain"], text=True
    ) for root in roots.values()):
        raise RuntimeError("matched worktrees must be clean")
    if sha256(sources["baseline"]) != sha256(sources["candidate"]):
        raise RuntimeError("variant sources differ")
    commits = {
        variant: subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
        ).strip()
        for variant, root in roots.items()
    }
    binaries_sha256 = {
        variant: sha256(binary) for variant, binary in binaries.items()
    }
    if commits != {
        "baseline": "0e13baff38309523a2074ef8fbc3745b4bc793ad",
        "candidate": "2260651e1f6db17b3d2013664d31e4fcc2c5fbae",
    } or binaries_sha256 != {
        "baseline":
            "92170e8deb7866a34c5ca71989cbb4e0a61b17bf49829ba5f080b02f14b7d012",
        "candidate":
            "83c2f0de76d2915cae3231e1c2621009f4101f25fba45b5046366de538b97208",
    }:
        raise RuntimeError("unexpected matched variants")
    z3_hash = sha256(args.z3.resolve())
    if z3_hash != (
        "4da6a0f78424098b600a9112ebb9d8ce45de248a4913c26dd7d472e6dabef6d3"
    ):
        raise RuntimeError("unexpected Z3 binary")
    ocaml_version = subprocess.check_output(
        ["ocamlc", "-version"], text=True
    ).strip()
    if ocaml_version != "4.14.2":
        raise RuntimeError(f"unexpected OCaml version: {ocaml_version}")
    args.output.mkdir(parents=True, exist_ok=True)
    cleared = (
        "FSTAR_LIB", "FSTAR_HOME", "OCAMLRUNPARAM", "CAMLRUNPARAM",
        "FSTAR_PRUNING_REFERENCE", "FSTAR_NO_DEDUP_VC",
    )
    provenance = {
        "runner_sha256": sha256(Path(__file__)),
        "z3_sha256": z3_hash,
        "ocaml_version": ocaml_version,
        "source": args.source,
        "source_sha256": sha256(sources["baseline"]),
        "repetitions": args.repetitions,
        "timeout": args.timeout,
        "cleared_environment": list(cleared),
        "variants": {
            variant: {
                "commit": commits[variant],
                "binary_sha256": binaries_sha256[variant],
                "checked_dependency_tree": tree_sha256(
                    root / "stage2/out/lib/fstar/ulib.checked"
                ),
            }
            for variant, root in roots.items()
        },
    }
    provenance_file = args.output / "provenance.json"
    if provenance_file.exists():
        if json.loads(provenance_file.read_text()) != provenance:
            raise RuntimeError("incompatible provenance")
    else:
        provenance_file.write_text(json.dumps(provenance, indent=2) + "\n")
    results = args.output / "measurements.jsonl"
    completed = set()
    if results.exists():
        for line in results.read_text().splitlines():
            row = json.loads(line)
            completed.add((row["variant"], row["repeat"]))
    randomizer = random.Random(4776)
    plan = []
    for repeat in range(1, args.repetitions + 1):
        variants = list(roots)
        randomizer.shuffle(variants)
        plan.extend((variant, repeat) for variant in variants)
    environment = os.environ.copy()
    for name in cleared:
        environment.pop(name, None)
    for variant, repeat in plan:
        if (variant, repeat) in completed:
            continue
        root = roots[variant]
        stem = f"{repeat}-{variant}"
        time_file = args.output / f"{stem}.time"
        log_file = args.output / f"{stem}.log"
        command = [
            "/usr/bin/time", "-v", "-o", str(time_file),
            "timeout", "--kill-after=5s", f"{args.timeout}s",
            str(binaries[variant]), "--z3version", "5.3.0",
            "--smt", str(args.z3.resolve()),
            "--include", str(root / "stage2/out/lib/fstar/ulib"),
            "--include", str(root / "stage2/out/lib/fstar/ulib.checked"),
            "--force", "--timing", "--query_stats", str(sources[variant]),
        ]
        with log_file.open("w") as log:
            process = subprocess.run(
                command, env=environment,
                stdout=log, stderr=subprocess.STDOUT,
            )
        if process.returncode != 0:
            raise RuntimeError(f"{stem} failed")
        text = log_file.read_text()
        timing = time_file.read_text()
        row = {
            "variant": variant,
            "repeat": repeat,
            "wall_seconds": elapsed(timing),
            "max_rss_kb": int(re.search(
                r"Maximum resident set size \(kbytes\): ([0-9]+)$",
                timing, re.M,
            ).group(1)),
            "profiled_declaration_count": len(re.findall(
                r"profiled FStarC\.TypeChecker\.Tc\.process_one_decl:", text
            )),
            "query_count": len(re.findall(r"Query-stats \(", text)),
            "z3_reported_seconds": sum(
                float(value) for value in re.findall(
                    r"Query-stats .*? succeeded in ([0-9.]+) seconds", text
                )
            ),
            "command": command,
        }
        with results.open("a") as stream:
            stream.write(json.dumps(row, sort_keys=True) + "\n")
    rows = [
        json.loads(line) for line in results.read_text().splitlines()
    ]
    expected_cells = {
        (variant, repeat)
        for repeat in range(1, args.repetitions + 1)
        for variant in roots
    }
    actual_cells = {(row["variant"], row["repeat"]) for row in rows}
    if len(rows) != len(actual_cells) or actual_cells != expected_cells:
        raise RuntimeError("supplemental cells differ")
    for repeat in range(1, args.repetitions + 1):
        pair = [row for row in rows if row["repeat"] == repeat]
        if len(pair) != 2 or len({
            (row["profiled_declaration_count"], row["query_count"])
            for row in pair
        }) != 1:
            raise RuntimeError(f"repeat {repeat}: matched work differs")


if __name__ == "__main__":
    main()
