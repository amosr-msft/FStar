#!/usr/bin/env python3

import argparse
import hashlib
import json
import os
import shutil
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--z3", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--module", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    roots = {
        "baseline": args.baseline.resolve(),
        "candidate": args.candidate.resolve(),
    }
    if args.output.exists():
        shutil.rmtree(args.output)
    args.output.mkdir(parents=True)
    environment = os.environ.copy()
    cleared = (
        "FSTAR_LIB", "FSTAR_HOME", "OCAMLRUNPARAM", "CAMLRUNPARAM",
        "FSTAR_PRUNING_REFERENCE", "FSTAR_NO_DEDUP_VC",
    )
    for name in cleared:
        environment.pop(name, None)
    commands = {}
    files = {}
    provenance = {
        "source_sha256": sha256(args.source.resolve()),
        "z3_sha256": sha256(args.z3.resolve()),
        "runner_sha256": sha256(Path(__file__)),
        "cleared_environment": list(cleared),
        "variants": {},
    }
    for variant, root in roots.items():
        directory = args.output / variant
        directory.mkdir()
        binary = root / "stage2/out/bin/fstar.exe"
        command = [
            str(binary), "--z3version", "5.3.0",
            "--smt", str(args.z3.resolve()),
            "--include", str(root / "stage2/out/lib/fstar/ulib"),
            "--include", str(root / "stage2/out/lib/fstar/ulib.checked"),
            "--force", "--query_stats", "--log_queries",
            str(args.source.resolve()),
        ]
        with (directory / "run.log").open("w") as log:
            process = subprocess.run(
                command, cwd=directory, env=environment,
                stdout=log, stderr=subprocess.STDOUT,
            )
        if process.returncode != 0:
            raise RuntimeError(f"{variant} failed")
        queries = directory / f"queries-{args.module}.smt2"
        if not queries.exists():
            raise RuntimeError(f"{variant} produced no query stream")
        commands[variant] = command
        files[variant] = queries
        provenance["variants"][variant] = {
            "commit": subprocess.check_output(
                ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
            ).strip(),
            "binary_sha256": sha256(binary),
            "checked_dependency_tree": tree_sha256(
                root / "stage2/out/lib/fstar/ulib.checked"
            ),
        }
    if files["baseline"].read_bytes() != files["candidate"].read_bytes():
        raise RuntimeError("baseline/candidate query streams differ")
    result = {
        "commands": commands,
        "query_stream_sha256": sha256(files["baseline"]),
        "baseline_query_stream_sha256": sha256(files["baseline"]),
        "candidate_query_stream_sha256": sha256(files["candidate"]),
        "query_stream_bytes": files["baseline"].stat().st_size,
        "provenance": provenance,
    }
    (args.output / "result.json").write_text(
        json.dumps(result, indent=2) + "\n"
    )


if __name__ == "__main__":
    main()
