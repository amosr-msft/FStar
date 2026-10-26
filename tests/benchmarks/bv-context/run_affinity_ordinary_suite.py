#!/usr/bin/env python3

import argparse
import fcntl
import hashlib
import json
import os
import random
import re
import stat
import subprocess
from pathlib import Path


WORKLOADS = {
    "bv-binary-ops": {
        "source": "tests/micro-benchmarks/BvBinaryOps.fst",
        "declarations": 56, "queries": 89,
    },
    "classical-sugar": {
        "source": "tests/micro-benchmarks/ClassicalSugar.fst",
        "declarations": 50, "queries": 89,
    },
    "positivity": {
        "source": "tests/micro-benchmarks/Positivity.fst",
        "declarations": 243, "queries": 41,
    },
    "well-founded-recursion": {
        "source": "tests/micro-benchmarks/TestWellFoundedRecursion.fst",
        "declarations": 80, "queries": 78,
    },
    "normalization": {
        "source": "tests/micro-benchmarks/Normalization.fst",
        "declarations": 20, "queries": 88,
    },
    "norm-vs-smt": {
        "source": "tests/micro-benchmarks/NormVsSMT.fst",
        "declarations": 13, "queries": 3,
    },
    "bug3207": {
        "source": "tests/bug-reports/closed/Bug3207.fst",
        "declarations": 242, "queries": 523,
    },
}

EXPECTED_COMMITS = {
    "baseline": "0e13baff38309523a2074ef8fbc3745b4bc793ad",
    "candidate": "2260651e1f6db17b3d2013664d31e4fcc2c5fbae",
}

EXPECTED_BINARIES = {
    "baseline":
        "92170e8deb7866a34c5ca71989cbb4e0a61b17bf49829ba5f080b02f14b7d012",
    "candidate":
        "83c2f0de76d2915cae3231e1c2621009f4101f25fba45b5046366de538b97208",
}

EXPECTED_DEPENDENCIES = {
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

CLEARED_ENVIRONMENT = (
    "FSTAR_LIB", "FSTAR_HOME", "OCAMLRUNPARAM", "CAMLRUNPARAM",
    "FSTAR_PRUNING_REFERENCE", "FSTAR_NO_DEDUP_VC",
    "LD_PRELOAD", "LD_LIBRARY_PATH", "LD_AUDIT",
    "OCAMLPATH", "CAML_LD_LIBRARY_PATH",
    "MALLOC_CONF", "GLIBC_TUNABLES", "MALLOC_ARENA_MAX",
    "MALLOC_ARENA_TEST", "MALLOC_CHECK_", "MALLOC_PERTURB_",
    "MALLOC_MMAP_MAX_", "MALLOC_MMAP_THRESHOLD_", "MALLOC_TOP_PAD_",
    "MALLOC_TRIM_THRESHOLD_",
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


def parse_time(path):
    text = path.read_text()
    fields = re.search(
        r"Elapsed \(wall clock\) time.*: ([0-9:.]+)$", text, re.M
    ).group(1).split(":")
    wall = float(fields[-1])
    if len(fields) >= 2:
        wall += 60 * int(fields[-2])
    if len(fields) == 3:
        wall += 3600 * int(fields[-3])
    return {
        "wall_seconds": wall,
        "user_seconds": float(re.search(
            r"User time \(seconds\): ([0-9.]+)$", text, re.M
        ).group(1)),
        "system_seconds": float(re.search(
            r"System time \(seconds\): ([0-9.]+)$", text, re.M
        ).group(1)),
        "max_rss_kb": int(re.search(
            r"Maximum resident set size \(kbytes\): ([0-9]+)$", text, re.M
        ).group(1)),
        "voluntary_context_switches": int(re.search(
            r"Voluntary context switches: ([0-9]+)$", text, re.M
        ).group(1)),
        "involuntary_context_switches": int(re.search(
            r"Involuntary context switches: ([0-9]+)$", text, re.M
        ).group(1)),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--z3", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cpu", type=int, default=16)
    args = parser.parse_args()
    if args.cpu != 16:
        parser.error("this protocol is pinned to CPU 16")
    roots = {
        "baseline": args.baseline.resolve(),
        "candidate": args.candidate.resolve(),
    }
    if roots["baseline"] == roots["candidate"]:
        raise RuntimeError("baseline and candidate roots must differ")
    binaries = {
        variant: root / "stage2/out/bin/fstar.exe"
        for variant, root in roots.items()
    }
    git = Path("/usr/bin/git")
    timeout = Path("/usr/bin/timeout")
    taskset = Path("/usr/bin/taskset")
    time = Path("/usr/bin/time")
    if any(subprocess.check_output(
        [str(git), "-C", str(root), "status", "--porcelain"], text=True
    ) for root in roots.values()):
        raise RuntimeError("benchmark worktrees must be clean")
    commits = {
        variant: subprocess.check_output(
            [str(git), "-C", str(root), "rev-parse", "HEAD"], text=True
        ).strip()
        for variant, root in roots.items()
    }
    binary_hashes = {
        variant: sha256(binary) for variant, binary in binaries.items()
    }
    dependencies = {
        variant: tree_sha256(
            root / "stage2/out/lib/fstar/ulib.checked"
        )
        for variant, root in roots.items()
    }
    if (
        commits != EXPECTED_COMMITS
        or binary_hashes != EXPECTED_BINARIES
        or dependencies != EXPECTED_DEPENDENCIES
    ):
        raise RuntimeError("unexpected matched compiler inputs")
    z3_hash = sha256(args.z3.resolve())
    if z3_hash != (
        "4da6a0f78424098b600a9112ebb9d8ce45de248a4913c26dd7d472e6dabef6d3"
    ):
        raise RuntimeError("unexpected Z3 binary")
    if subprocess.check_output(
        ["ocamlc", "-version"], text=True
    ).strip() != "4.14.2":
        raise RuntimeError("unexpected OCaml version")
    if subprocess.run(
        [str(taskset), "-c", str(args.cpu), "true"]
    ).returncode != 0:
        raise RuntimeError("CPU 16 is not permitted")
    fstar_versions = {
        variant: subprocess.check_output(
            [str(binary), "--version"], text=True
        ).strip()
        for variant, binary in binaries.items()
    }
    if any(
        "compiler=OCaml 4.14.2" not in version
        for version in fstar_versions.values()
    ):
        raise RuntimeError("unexpected embedded F* compiler toolchain")
    source_hashes = {}
    for workload, spec in WORKLOADS.items():
        hashes = {
            variant: sha256(root / spec["source"])
            for variant, root in roots.items()
        }
        if len(set(hashes.values())) != 1:
            raise RuntimeError(f"{workload}: source differs")
        source_hashes[workload] = hashes["baseline"]
    args.output.mkdir(parents=True, exist_ok=True)
    if args.output.is_symlink():
        raise RuntimeError("output must not be a symlink")
    lock_path = args.output / "campaign.lock"
    lock_fd = os.open(
        lock_path,
        os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW,
        0o600,
    )
    if not stat.S_ISREG(os.fstat(lock_fd).st_mode):
        os.close(lock_fd)
        raise RuntimeError("campaign lock must be a regular file")
    lock = os.fdopen(lock_fd, "w")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    provenance = {
        "runner_sha256": sha256(Path(__file__)),
        "cpu": args.cpu,
        "pairs_per_workload": 5,
        "workloads": WORKLOADS,
        "source_sha256": source_hashes,
        "z3_sha256": z3_hash,
        "ocaml_version": "4.14.2",
        "cleared_environment": list(CLEARED_ENVIRONMENT),
        "set_environment": {"LC_ALL": "C", "LANG": "C"},
        "tools": {
            "git": {"path": str(git), "sha256": sha256(git)},
            "timeout": {"path": str(timeout), "sha256": sha256(timeout)},
            "taskset": {"path": str(taskset), "sha256": sha256(taskset)},
            "time": {"path": str(time), "sha256": sha256(time)},
        },
        "variants": {
            variant: {
                "commit": commits[variant],
                "binary_sha256": binary_hashes[variant],
                "checked_dependency_tree": dependencies[variant],
                "version": fstar_versions[variant],
            }
            for variant in roots
        },
    }
    provenance_file = args.output / "provenance.json"
    results = args.output / "measurements.jsonl"
    for path in (provenance_file, results):
        if path.is_symlink():
            raise RuntimeError(f"output file must not be a symlink: {path}")
    if provenance_file.exists():
        if json.loads(provenance_file.read_text()) != provenance:
            raise RuntimeError("incompatible output provenance")
    else:
        provenance_file.write_text(json.dumps(provenance, indent=2) + "\n")
    completed = set()
    prior = []
    if results.exists():
        for line in results.read_text().splitlines():
            row = json.loads(line)
            stem = f"{row['repeat']}-{row['workload']}-{row['variant']}"
            for path in (
                args.output / f"{stem}.time",
                args.output / f"{stem}.log",
            ):
                if path.is_symlink() or not path.is_file():
                    raise RuntimeError(f"existing raw evidence invalid: {path}")
            time_path = args.output / f"{stem}.time"
            log_path = args.output / f"{stem}.log"
            timing = parse_time(time_path)
            text = log_path.read_text()
            raw_declarations = len(re.findall(
                r"profiled FStarC\.TypeChecker\.Tc\.process_one_decl:", text
            ))
            raw_queries = len(re.findall(r"Query-stats \(", text))
            raw_z3 = sum(
                float(value) for value in re.findall(
                    r"Query-stats .*? succeeded in ([0-9.]+) seconds", text
                )
            )
            if (
                any(row[key] != value for key, value in timing.items())
                or row["profiled_declaration_count"] != raw_declarations
                or row["query_count"] != raw_queries
                or row["z3_reported_seconds"] != raw_z3
                or
                row["profiled_declaration_count"]
                != WORKLOADS[row["workload"]]["declarations"]
                or row["query_count"] != WORKLOADS[row["workload"]]["queries"]
            ):
                raise RuntimeError("existing row work count differs")
            prior.append(row)
            completed.add((row["variant"], row["workload"], row["repeat"]))
    randomizer = random.Random(4781)
    pairs = [
        (workload, repeat)
        for workload in WORKLOADS
        for repeat in range(1, 6)
    ]
    randomizer.shuffle(pairs)
    plan = []
    for workload, repeat in pairs:
        variants = list(roots)
        randomizer.shuffle(variants)
        plan.extend((variant, workload, repeat) for variant in variants)
    if prior:
        prior_keys = [
            (row["variant"], row["workload"], row["repeat"])
            for row in prior
        ]
        if prior_keys != plan[:len(prior_keys)]:
            raise RuntimeError("existing rows are not a deterministic plan prefix")
    environment = os.environ.copy()
    for name in CLEARED_ENVIRONMENT:
        environment.pop(name, None)
    environment.update({"LC_ALL": "C", "LANG": "C"})
    new_rows = []
    for variant, workload, repeat in plan:
        key = (variant, workload, repeat)
        if key in completed:
            continue
        root = roots[variant]
        source = root / WORKLOADS[workload]["source"]
        stem = f"{repeat}-{workload}-{variant}"
        time_file = args.output / f"{stem}.time"
        log_file = args.output / f"{stem}.log"
        for path in (time_file, log_file):
            if path.is_symlink():
                raise RuntimeError(f"output file must not be a symlink: {path}")
        command = [
            str(time), "-v", "-o", str(time_file),
            str(timeout), "--kill-after=5s", "300s",
            str(taskset), "-c", str(args.cpu),
            str(binaries[variant]), "--z3version", "5.3.0",
            "--smt", str(args.z3.resolve()),
            "--include", str(root / "stage2/out/lib/fstar/ulib"),
            "--include", str(root / "stage2/out/lib/fstar/ulib.checked"),
            "--force", "--timing", "--query_stats", str(source),
        ]
        with log_file.open("w") as log:
            process = subprocess.run(
                command, env=environment,
                stdout=log, stderr=subprocess.STDOUT,
            )
        if process.returncode != 0:
            raise RuntimeError(f"{stem} failed")
        text = log_file.read_text()
        row = {
            "variant": variant,
            "workload": workload,
            "repeat": repeat,
            **parse_time(time_file),
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
        if (
            row["profiled_declaration_count"]
            != WORKLOADS[workload]["declarations"]
            or row["query_count"] != WORKLOADS[workload]["queries"]
        ):
            raise RuntimeError(f"{workload}: pinned work count differs")
        with results.open("a") as stream:
            stream.write(json.dumps(row, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        new_rows.append(row)
    all_rows = prior + new_rows
    expected = {
        (variant, workload, repeat)
        for variant in roots
        for workload in WORKLOADS
        for repeat in range(1, 6)
    }
    actual = {
        (row["variant"], row["workload"], row["repeat"])
        for row in all_rows
    }
    if len(all_rows) != len(actual) or actual != expected:
        raise RuntimeError("ordinary affinity cells differ")
    for workload in WORKLOADS:
        for repeat in range(1, 6):
            pair = [
                row for row in all_rows
                if row["workload"] == workload and row["repeat"] == repeat
            ]
            if (
                len(pair) != 2
                or len({
                    (
                        row["profiled_declaration_count"],
                        row["query_count"],
                    )
                    for row in pair
                }) != 1
                or pair[0]["profiled_declaration_count"]
                != WORKLOADS[workload]["declarations"]
                or pair[0]["query_count"] != WORKLOADS[workload]["queries"]
            ):
                raise RuntimeError(f"{workload}#{repeat}: work differs")


if __name__ == "__main__":
    main()
