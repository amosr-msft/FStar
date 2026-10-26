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
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--z3", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--stream", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cpu", type=int, default=0)
    parser.add_argument("--replay-repetitions", type=int, default=10)
    parser.add_argument("--matched-repetitions", type=int, default=5)
    args = parser.parse_args()
    if args.replay_repetitions != 10 or args.matched_repetitions != 5:
        parser.error("this control requires exactly 10 replay and 5 matched runs")
    if args.output.exists():
        raise RuntimeError("output must not already exist")
    args.output.mkdir(parents=True)
    roots = {
        "baseline": args.baseline.resolve(),
        "candidate": args.candidate.resolve(),
    }
    binaries = {
        variant: root / "stage2/out/bin/fstar.exe"
        for variant, root in roots.items()
    }
    if roots["baseline"] == roots["candidate"]:
        raise RuntimeError("baseline and candidate roots must differ")
    git = Path("/usr/bin/git")
    timeout = Path("/usr/bin/timeout")
    if any(subprocess.check_output(
        [str(git), "-C", str(root), "status", "--porcelain"], text=True
    ) for root in roots.values()):
        raise RuntimeError("worktrees must be clean")
    commits = {
        variant: subprocess.check_output(
            [str(git), "-C", str(root), "rev-parse", "HEAD"], text=True
        ).strip()
        for variant, root in roots.items()
    }
    binary_hashes = {
        variant: sha256(binary) for variant, binary in binaries.items()
    }
    if commits != {
        "baseline": "0e13baff38309523a2074ef8fbc3745b4bc793ad",
        "candidate": "2260651e1f6db17b3d2013664d31e4fcc2c5fbae",
    } or binary_hashes != {
        "baseline":
            "92170e8deb7866a34c5ca71989cbb4e0a61b17bf49829ba5f080b02f14b7d012",
        "candidate":
            "83c2f0de76d2915cae3231e1c2621009f4101f25fba45b5046366de538b97208",
    }:
        raise RuntimeError("unexpected baseline/candidate builds")
    dependency_trees = {
        variant: tree_sha256(
            root / "stage2/out/lib/fstar/ulib.checked"
        )
        for variant, root in roots.items()
    }
    expected_trees = {
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
    if dependency_trees != expected_trees:
        raise RuntimeError("unexpected checked dependency trees")
    source_hash = sha256(args.source.resolve())
    if source_hash != (
        "a7ed060cd18539f684343ea6afd677effa8fa18bdea2dc12500ff68878c67c05"
    ):
        raise RuntimeError("unexpected SimpleAgreement1024 source")
    z3_hash = sha256(args.z3.resolve())
    if z3_hash != (
        "4da6a0f78424098b600a9112ebb9d8ce45de248a4913c26dd7d472e6dabef6d3"
    ):
        raise RuntimeError("unexpected Z3 binary")
    taskset = Path("/usr/bin/taskset")
    time = Path("/usr/bin/time")
    cleared = (
        "FSTAR_LIB", "FSTAR_HOME", "OCAMLRUNPARAM", "CAMLRUNPARAM",
        "FSTAR_PRUNING_REFERENCE", "FSTAR_NO_DEDUP_VC",
        "LD_PRELOAD", "LD_LIBRARY_PATH", "OCAMLPATH", "CAML_LD_LIBRARY_PATH",
        "LD_AUDIT", "MALLOC_CONF", "GLIBC_TUNABLES",
        "MALLOC_ARENA_MAX", "MALLOC_PERTURB_", "MALLOC_MMAP_THRESHOLD_",
        "MALLOC_TRIM_THRESHOLD_", "MALLOC_ARENA_TEST", "MALLOC_CHECK_",
        "MALLOC_MMAP_MAX_", "MALLOC_TOP_PAD_",
    )
    environment = os.environ.copy()
    for name in cleared:
        environment.pop(name, None)
    environment["LC_ALL"] = "C"
    environment["LANG"] = "C"
    affinity = subprocess.check_output(
        [str(taskset), "-pc", str(os.getpid())], text=True
    ).strip()
    probe = subprocess.run(
        [str(taskset), "-c", str(args.cpu), "true"]
    )
    if probe.returncode != 0:
        raise RuntimeError(f"CPU {args.cpu} is not permitted")
    provenance = {
        "runner_sha256": sha256(Path(__file__)),
        "taskset_sha256": sha256(taskset),
        "time_sha256": sha256(time),
        "timeout_sha256": sha256(timeout),
        "git_sha256": sha256(git),
        "cpu": args.cpu,
        "parent_affinity": affinity,
        "z3_sha256": z3_hash,
        "source_sha256": source_hash,
        "stream_sha256": sha256(args.stream.resolve()),
        "stream_bytes": args.stream.stat().st_size,
        "cleared_environment": list(cleared),
        "set_environment": {"LC_ALL": "C", "LANG": "C"},
        "replay_repetitions": args.replay_repetitions,
        "matched_repetitions": args.matched_repetitions,
        "variants": {
            variant: {
                "commit": commits[variant],
                "binary_sha256": binary_hashes[variant],
                "checked_dependency_tree": dependency_trees[variant],
            }
            for variant, root in roots.items()
        },
    }
    (args.output / "provenance.json").write_text(
        json.dumps(provenance, indent=2) + "\n"
    )

    replay_path = args.output / "replay.jsonl"
    replay_order = list(range(1, args.replay_repetitions + 1))
    random.Random(4779).shuffle(replay_order)
    for repeat in replay_order:
        time_file = args.output / f"replay-{repeat}.time"
        output_file = args.output / f"replay-{repeat}.out"
        command = [
            str(time), "-v", "-o", str(time_file),
            str(timeout), "--kill-after=5s", "120s",
            str(taskset), "-c", str(args.cpu),
            str(args.z3.resolve()), "-smt2", str(args.stream.resolve()),
        ]
        with output_file.open("w") as stream:
            process = subprocess.run(
                command, env=environment,
                stdout=stream, stderr=subprocess.STDOUT,
            )
        if process.returncode != 0:
            raise RuntimeError(f"replay {repeat} failed")
        output = output_file.read_text()
        row = {
            "repeat": repeat,
            **parse_time(time_file),
            "unsat_count": len(re.findall(r"^unsat$", output, re.M)),
            "final_rlimit_count": int(re.findall(
                r":rlimit-count\s+([0-9]+)", output
            )[-1]),
            "final_num_allocs": int(re.findall(
                r":num-allocs\s+([0-9]+)", output
            )[-1]),
            "command": command,
        }
        if (
            row["unsat_count"] != 1025
            or row["final_rlimit_count"] != 77059486
        ):
            raise RuntimeError(f"replay {repeat} work differs")
        with replay_path.open("a") as stream:
            stream.write(json.dumps(row, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    randomizer = random.Random(4780)
    pairs = list(range(1, args.matched_repetitions + 1))
    randomizer.shuffle(pairs)
    plan = []
    for repeat in pairs:
        variants = list(roots)
        randomizer.shuffle(variants)
        plan.extend((variant, repeat) for variant in variants)
    matched_path = args.output / "matched.jsonl"
    for variant, repeat in plan:
        root = roots[variant]
        time_file = args.output / f"matched-{repeat}-{variant}.time"
        log_file = args.output / f"matched-{repeat}-{variant}.log"
        command = [
            str(time), "-v", "-o", str(time_file),
            str(timeout), "--kill-after=5s", "180s",
            str(taskset), "-c", str(args.cpu),
            str(binaries[variant]), "--z3version", "5.3.0",
            "--smt", str(args.z3.resolve()),
            "--include", str(root / "stage2/out/lib/fstar/ulib"),
            "--include", str(root / "stage2/out/lib/fstar/ulib.checked"),
            "--force", "--timing", "--query_stats",
            str(args.source.resolve()),
        ]
        with log_file.open("w") as log:
            process = subprocess.run(
                command, env=environment,
                stdout=log, stderr=subprocess.STDOUT,
            )
        if process.returncode != 0:
            raise RuntimeError(f"matched {repeat}/{variant} failed")
        text = log_file.read_text()
        row = {
            "variant": variant,
            "repeat": repeat,
            **parse_time(time_file),
            "query_count": len(re.findall(r"Query-stats \(", text)),
            "profiled_declaration_count": len(re.findall(
                r"profiled FStarC\.TypeChecker\.Tc\.process_one_decl:", text
            )),
            "profiled_declaration_ms": sum(
                int(value) for value in re.findall(
                    r"profiled FStarC\.TypeChecker\.Tc\.process_one_decl:"
                    r"\s+([0-9]+) ms",
                    text,
                )
            ),
            "z3_reported_seconds": sum(
                float(value) for value in re.findall(
                    r"Query-stats .*? succeeded in ([0-9.]+) seconds", text
                )
            ),
            "command": command,
        }
        if (
            row["query_count"] != 1025
            or row["profiled_declaration_count"] != 1025
        ):
            raise RuntimeError(f"matched {repeat}/{variant} work differs")
        with matched_path.open("a") as stream:
            stream.write(json.dumps(row, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
    matched_rows = [
        json.loads(line) for line in matched_path.read_text().splitlines()
    ]
    for repeat in range(1, args.matched_repetitions + 1):
        pair = [row for row in matched_rows if row["repeat"] == repeat]
        if (
            len(pair) != 2
            or {row["variant"] for row in pair}
            != {"baseline", "candidate"}
            or len({row["query_count"] for row in pair}) != 1
        ):
            raise RuntimeError(f"matched pair {repeat} differs")


if __name__ == "__main__":
    main()
