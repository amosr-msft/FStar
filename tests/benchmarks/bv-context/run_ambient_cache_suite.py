#!/usr/bin/env python3

import argparse
import fcntl
import hashlib
import json
import os
import random
import re
import subprocess
from pathlib import Path


WORKLOADS = {
    "simple-1024": {
        "kind": "generated",
        "source": "SimpleAgreement1024.fst",
        "count": 1024,
        "repetitions": 3,
        "timeout": 300,
        "category": "context-heavy",
    },
    "simple-2048": {
        "kind": "generated",
        "source": "SimpleAgreement2048.fst",
        "count": 2048,
        "repetitions": 2,
        "timeout": 600,
        "category": "context-heavy-large",
    },
    "full-bv-width3": {
        "kind": "source",
        "source": "tests/micro-benchmarks/BvModelAgreesWithZ3.fst",
        "repetitions": 1,
        "timeout": 1200,
        "category": "context-heavy-bv",
    },
    "classical-sugar": {
        "kind": "source",
        "source": "tests/micro-benchmarks/ClassicalSugar.fst",
        "repetitions": 3,
        "timeout": 120,
        "category": "small-ordinary",
    },
    "positivity": {
        "kind": "source",
        "source": "tests/micro-benchmarks/Positivity.fst",
        "repetitions": 3,
        "timeout": 120,
        "category": "small-ordinary",
    },
    "well-founded-recursion": {
        "kind": "source",
        "source": "tests/micro-benchmarks/TestWellFoundedRecursion.fst",
        "repetitions": 3,
        "timeout": 120,
        "category": "ordinary-regression",
    },
    "normalization": {
        "kind": "source",
        "source": "tests/micro-benchmarks/Normalization.fst",
        "repetitions": 3,
        "timeout": 300,
        "category": "normalization-heavy",
    },
    "norm-vs-smt": {
        "kind": "source",
        "source": "tests/micro-benchmarks/NormVsSMT.fst",
        "repetitions": 3,
        "timeout": 300,
        "category": "normalization-smt",
    },
    "bv-binary-ops": {
        "kind": "source",
        "source": "tests/micro-benchmarks/BvBinaryOps.fst",
        "repetitions": 3,
        "timeout": 300,
        "category": "bv-ordinary",
    },
    "list-tot-properties": {
        "kind": "source",
        "source": "ulib/FStar.List.Tot.Properties.fst",
        "repetitions": 1,
        "timeout": 900,
        "category": "large-library",
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


def parse_elapsed(text):
    match = re.search(
        r"Elapsed \(wall clock\) time.*: ([0-9:.]+)$", text, re.M
    )
    fields = match.group(1).split(":")
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
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    roots = {
        "baseline": args.baseline.resolve(),
        "candidate": args.candidate.resolve(),
    }
    binaries = {
        variant: root / "stage2/out/bin/fstar.exe"
        for variant, root in roots.items()
    }
    args.output.mkdir(parents=True, exist_ok=True)
    lock = (args.output / "campaign.lock").open("w")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    generated = args.output / "generated"
    generated.mkdir(exist_ok=True)
    script_root = Path(__file__).resolve().parent
    generator = script_root / "generate_simple.py"
    generator_hash = sha256(generator)
    if generator_hash != (
        "b80798e1ab39085d2ff9cc7d5093d2f58902129455ef1fb05a2c963aa8373d73"
    ):
        raise RuntimeError("unexpected simple generator")
    for spec in WORKLOADS.values():
        if spec["kind"] == "generated":
            subprocess.run([
                "python", str(generator),
                "--output", str(generated),
                "--count", str(spec["count"]),
            ], check=True)

    source_hashes = {}
    for workload, spec in WORKLOADS.items():
        hashes = {}
        if spec["kind"] == "generated":
            source = generated / spec["source"]
            hashes["shared"] = sha256(source)
        else:
            for variant, root in roots.items():
                hashes[variant] = sha256(root / spec["source"])
            if hashes["baseline"] != hashes["candidate"]:
                raise RuntimeError(f"{workload}: variant sources differ")
        source_hashes[workload] = hashes
    baseline_status = subprocess.check_output(
        ["git", "-C", str(roots["baseline"]), "status", "--porcelain"],
        text=True,
    )
    candidate_status = subprocess.check_output(
        ["git", "-C", str(roots["candidate"]), "status", "--porcelain"],
        text=True,
    )
    if baseline_status or candidate_status:
        raise RuntimeError("benchmark worktrees must be clean")
    commits = {
        variant: subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
        ).strip()
        for variant, root in roots.items()
    }
    if commits != {
        "baseline": "0e13baff38309523a2074ef8fbc3745b4bc793ad",
        "candidate": "2260651e1f6db17b3d2013664d31e4fcc2c5fbae",
    }:
        raise RuntimeError(f"unexpected benchmark commits: {commits}")
    candidate_diff = subprocess.check_output([
        "git", "-C", str(roots["candidate"]), "diff", "--name-status",
        "0e13baff38309523a2074ef8fbc3745b4bc793ad..HEAD",
    ], text=True).splitlines()
    if candidate_diff != [
        "M\tsrc/smtencoding/FStarC.SMTEncoding.Pruning.fst"
    ]:
        raise RuntimeError(f"unexpected candidate diff: {candidate_diff}")
    ocaml_version = subprocess.check_output(
        ["ocamlc", "-version"], text=True
    ).strip()
    if ocaml_version != "4.14.2":
        raise RuntimeError(f"unexpected OCaml version: {ocaml_version}")
    binary_hashes = {
        variant: sha256(binary) for variant, binary in binaries.items()
    }
    if binary_hashes != {
        "baseline":
            "92170e8deb7866a34c5ca71989cbb4e0a61b17bf49829ba5f080b02f14b7d012",
        "candidate":
            "83c2f0de76d2915cae3231e1c2621009f4101f25fba45b5046366de538b97208",
    }:
        raise RuntimeError(f"unexpected benchmark binaries: {binary_hashes}")
    checked_dependency_trees = {
        variant: tree_sha256(
            root / "stage2/out/lib/fstar/ulib.checked"
        )
        for variant, root in roots.items()
    }
    approved_dependency_trees = {
        "baseline": {
            "sha256":
                "6e3fb8cfb46662026444bbd4404ccfd3961c6f76384b57135f56fcedea397a0f",
            "files": 379,
        },
        "candidate": {
            "sha256":
                "77d114652ff5051c773738765ef31b3d4047706f46f2728a80055d15cb2436c3",
            "files": 379,
        },
    }
    if checked_dependency_trees != approved_dependency_trees:
        raise RuntimeError(
            f"unexpected checked dependency trees: {checked_dependency_trees}"
        )
    z3_hash = sha256(args.z3.resolve())
    if z3_hash != (
        "4da6a0f78424098b600a9112ebb9d8ce45de248a4913c26dd7d472e6dabef6d3"
    ):
        raise RuntimeError(f"unexpected Z3 binary: {z3_hash}")
    fstar_versions = {
        variant: subprocess.check_output(
            [str(binary), "--version"], text=True
        ).strip()
        for variant, binary in binaries.items()
    }
    if any("compiler=OCaml 4.14.2" not in value for value in fstar_versions.values()):
        raise RuntimeError(f"unexpected compiler toolchain: {fstar_versions}")
    provenance = {
        "runner_sha256": sha256(Path(__file__)),
        "generator_sha256": generator_hash,
        "z3_sha256": z3_hash,
        "variants": {
            variant: {
                "commit": commits[variant],
                "binary_sha256": binary_hashes[variant],
                "version": fstar_versions[variant],
                "checked_dependency_tree":
                    checked_dependency_trees[variant],
                "pruning_source_sha256": sha256(
                    root
                    / "src/smtencoding/FStarC.SMTEncoding.Pruning.fst"
                ),
            }
            for variant, root in roots.items()
        },
        "ocaml_version": ocaml_version,
        "cleared_environment": [
            "FSTAR_LIB", "FSTAR_HOME", "OCAMLRUNPARAM",
            "CAMLRUNPARAM", "FSTAR_PRUNING_REFERENCE",
            "FSTAR_NO_DEDUP_VC",
        ],
        "candidate_diff": candidate_diff,
        "workloads": WORKLOADS,
        "source_sha256": source_hashes,
    }
    provenance_file = args.output / "provenance.json"
    if provenance_file.exists():
        if json.loads(provenance_file.read_text()) != provenance:
            raise RuntimeError("output directory has incompatible provenance")
    else:
        provenance_file.write_text(json.dumps(provenance, indent=2) + "\n")

    results = args.output / "measurements.jsonl"
    completed = set()
    prior_rows = []
    if results.exists():
        for line in results.read_text().splitlines():
            row = json.loads(line)
            prior_rows.append(row)
            completed.add((row["variant"], row["workload"], row["repeat"]))
    pairs = [
        (workload, repeat)
        for workload, spec in WORKLOADS.items()
        for repeat in range(1, spec["repetitions"] + 1)
    ]
    randomizer = random.Random(4775)
    randomizer.shuffle(pairs)
    all_jobs = []
    for workload, repeat in pairs:
        variants = list(roots)
        randomizer.shuffle(variants)
        all_jobs.extend(
            (variant, workload, repeat) for variant in variants
        )
    jobs = [
        job for job in all_jobs if job not in completed
    ]
    new_rows = []
    for variant, workload, repeat in jobs:
        root = roots[variant]
        spec = WORKLOADS[workload]
        source = (
            generated / spec["source"]
            if spec["kind"] == "generated"
            else root / spec["source"]
        )
        stem = f"{repeat}-{workload}-{variant}"
        log_file = args.output / f"{stem}.log"
        time_file = args.output / f"{stem}.time"
        command = [
            "/usr/bin/time", "-v", "-o", str(time_file),
            "timeout", "--kill-after=5s", f"{spec['timeout']}s",
            str(binaries[variant]), "--z3version", "5.3.0",
            "--smt", str(args.z3.resolve()),
            "--include", str(root / "stage2/out/lib/fstar/ulib"),
            "--include", str(root / "stage2/out/lib/fstar/ulib.checked"),
            "--force", "--timing", "--query_stats",
        ]
        command.append(str(source))
        environment = os.environ.copy()
        for name in provenance["cleared_environment"]:
            environment.pop(name, None)
        with log_file.open("w") as log:
            process = subprocess.run(
                command, env=environment,
                stdout=log, stderr=subprocess.STDOUT,
            )
        time_text = time_file.read_text()
        status = (
            "success" if process.returncode == 0
            else "timeout" if process.returncode in (124, 137)
            else "failure"
        )
        text = log_file.read_text()
        row = {
            "variant": variant,
            "workload": workload,
            "category": spec["category"],
            "repeat": repeat,
            "status": status,
            "returncode": process.returncode,
            "wall_seconds": parse_elapsed(time_text),
            "user_seconds": float(re.search(
                r"User time \(seconds\): ([0-9.]+)$", time_text, re.M
            ).group(1)),
            "system_seconds": float(re.search(
                r"System time \(seconds\): ([0-9.]+)$", time_text, re.M
            ).group(1)),
            "max_rss_kb": int(re.search(
                r"Maximum resident set size \(kbytes\): ([0-9]+)$",
                time_text, re.M,
            ).group(1)),
            "profiled_declaration_ms": sum(
                int(value)
                for value in re.findall(
                    r"profiled FStarC\.TypeChecker\.Tc\.process_one_decl:"
                    r"\s+([0-9]+) ms",
                    text,
                )
            ),
            "profiled_declaration_count": len(re.findall(
                r"profiled FStarC\.TypeChecker\.Tc\.process_one_decl:", text
            )),
            "query_count": len(re.findall(r"Query-stats \(", text)),
            "z3_reported_seconds": sum(
                float(value)
                for value in re.findall(
                    r"Query-stats .*? succeeded in ([0-9.]+) seconds",
                    text,
                )
            ),
            "source_sha256": sha256(source),
            "command": command,
        }
        with results.open("a") as stream:
            stream.write(json.dumps(row, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        new_rows.append(row)
    all_rows = prior_rows + new_rows
    unsuccessful = [
        row for row in all_rows if row["status"] != "success"
    ]
    matched = {}
    for row in all_rows:
        matched.setdefault(
            (row["workload"], row["repeat"]), {}
        )[row["variant"]] = row
    for key, variants in matched.items():
        if set(variants) != {"baseline", "candidate"}:
            raise RuntimeError(f"incomplete matched pair: {key}")
        left = variants["baseline"]
        right = variants["candidate"]
        if (
            left["status"] == right["status"] == "success"
            and (
                left["profiled_declaration_count"]
                != right["profiled_declaration_count"]
                or left["query_count"] != right["query_count"]
            )
        ):
            raise RuntimeError(f"matched work differs: {key}")
    if unsuccessful:
        names = [
            (
                f"{row['workload']}/{row['variant']}#{row['repeat']}"
                f"={row['status']}"
            )
            for row in unsuccessful
        ]
        raise RuntimeError("suite unsuccessful rows: " + ", ".join(names))


if __name__ == "__main__":
    main()
