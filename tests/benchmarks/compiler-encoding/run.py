#!/usr/bin/env python3

import argparse
import json
import re
import subprocess
from pathlib import Path


def parse_time(path):
    fields = {}
    patterns = {
        "wall_seconds": r"Elapsed \(wall clock\) time.*: (?:(\d+):)?(\d+):([0-9.]+)",
        "user_seconds": r"User time \(seconds\): ([0-9.]+)",
        "system_seconds": r"System time \(seconds\): ([0-9.]+)",
        "peak_rss_kb": r"Maximum resident set size \(kbytes\): (\d+)",
    }
    text = path.read_text()
    for key, pattern in patterns.items():
        match = re.search(pattern, text)
        if match is None:
            raise RuntimeError(f"missing {key} in {path}")
        if key == "wall_seconds":
            hours = int(match.group(1) or 0)
            fields[key] = hours * 3600 + int(match.group(2)) * 60 + float(match.group(3))
        elif key == "peak_rss_kb":
            fields[key] = int(match.group(1))
        else:
            fields[key] = float(match.group(1))
    return fields


def run_one(args, source, mode, repeat, generated, cache, results):
    module = source.stem
    checked = cache / f"{source.name}.checked"
    checked.unlink(missing_ok=True)
    time_file = results / f"{module}.{mode}.{repeat}.time"
    log_file = results / f"{module}.{mode}.{repeat}.log"
    command = [
        "/usr/bin/time", "-v", "-o", str(time_file),
        "timeout", "--kill-after=10s", f"{args.timeout}s",
        str(args.fstar),
        "--z3version", args.z3version,
        "--smtencoding.elim_box", "true",
        "--timing",
        "--include", str(generated),
        "--cache_dir", str(cache),
        "--odir", str(cache),
        "--already_cached", "Prims,FStar",
        str(source),
    ]
    if mode == "write":
        command.insert(-1, "--cache_checked_modules")
    with log_file.open("w") as log:
        completed = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
    if completed.returncode != 0:
        raise RuntimeError(f"{module} failed with exit {completed.returncode}; see {log_file}")
    row = {
        "module": module,
        "mode": mode,
        "repeat": repeat,
        "source_bytes": source.stat().st_size,
        "checked_bytes": checked.stat().st_size if checked.exists() else 0,
        "command": command,
    }
    row.update(parse_time(time_file))
    return row


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fstar", type=Path, required=True)
    parser.add_argument("--z3version", default="4.13.3")
    parser.add_argument("--bindings", type=int, nargs="+", default=[100, 250, 500, 1000])
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--modes", nargs="+", choices=["write", "no-write"], default=["write", "no-write"])
    parser.add_argument("--only", nargs="*", default=[])
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    generated = root / "_generated"
    cache = root / "_cache"
    results = root / "_results"
    generated.mkdir(exist_ok=True)
    cache.mkdir(exist_ok=True)
    results.mkdir(exist_ok=True)
    subprocess.run(
        [str(root / "generate.py"), "--out-dir", str(generated), "--bindings", *map(str, args.bindings)],
        check=True,
    )

    child_sources = [generated / "BenchBvChildren.fst", generated / "BenchUIntChildren.fst"]
    for child in child_sources:
        subprocess.run([
            str(args.fstar), "--z3version", args.z3version,
            "--include", str(generated), "--cache_dir", str(cache), "--odir", str(cache),
            "--cache_checked_modules", "--already_cached", "Prims,FStar", str(child),
        ], check=True)

    sources = []
    for count in args.bindings:
        sources += [
            generated / f"BenchBvDirect{count}.fst",
            generated / f"BenchUIntDirect{count}.fst",
        ]
    largest = max(args.bindings)
    sources += [
        generated / f"BenchBvRefined{largest}.fst",
        generated / f"BenchBvAssert{largest}.fst",
        generated / "BenchIsolationAssertions400.fst",
        generated / "BenchIsolationRefinedAssert400.fst",
        generated / "BenchIsolationRefined400.fst",
        generated / "BenchIsolationBv400.fst",
    ]
    if args.only:
        sources = [source for source in sources if any(token in source.stem for token in args.only)]

    output = results / "measurements.jsonl"
    output.unlink(missing_ok=True)
    for source in sources:
        for repeat in range(1, args.repeats + 1):
            modes = args.modes if repeat % 2 else list(reversed(args.modes))
            for mode in modes:
                row = run_one(args, source, mode, repeat, generated, cache, results)
                with output.open("a") as stream:
                    stream.write(json.dumps(row, sort_keys=True) + "\n")
                print(
                    f"{row['module']} {mode} #{repeat}: "
                    f"{row['wall_seconds']:.2f}s, {row['peak_rss_kb'] / 1024:.1f} MiB, "
                    f"{row['checked_bytes'] / 1048576:.2f} MiB checked"
                )


if __name__ == "__main__":
    main()
