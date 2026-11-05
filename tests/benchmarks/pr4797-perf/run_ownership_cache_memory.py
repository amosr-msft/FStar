#!/usr/bin/env python3

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path


PACKAGES = (
    "threads,batteries,dynlink,mtime,mtime.clock,pprint,"
    "ppx_deriving.runtime,ppx_deriving_yojson.runtime,ppxlib,ppxlib.ast,"
    "process,stdint,yojson,zarith,unix"
)
COMMIT = "7da01c0b4ae5cf447f6951ddb38714b7f1969a35"
ARCHIVE = "707e85bc97e65c687659acafb4e710455530c5092dd594003d8357fc86b97912"


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--worktree", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cpu", type=int, default=16)
    args = parser.parse_args()
    worktree = args.worktree.resolve()
    head = subprocess.check_output(
        ["git", "-C", str(worktree), "rev-parse", "HEAD"], text=True
    ).strip()
    if subprocess.run([
        "git", "-C", str(worktree), "merge-base", "--is-ancestor",
        COMMIT, head,
    ]).returncode != 0:
        raise RuntimeError("unexpected worktree ancestry")
    if subprocess.run([
        "git", "-C", str(worktree), "diff", "--quiet", COMMIT,
        "--", "src", "ulib", "pulse",
    ]).returncode != 0:
        raise RuntimeError("production sources differ")
    source_dir = worktree / "tests/bug-reports/closed"
    sources = [
        path.name
        for pattern in ("*.fst", "*.fsti")
        for path in sorted(source_dir.glob(pattern))
    ]
    source_hashes = {
        source: sha256(source_dir / source) for source in sources
    }
    root = Path(__file__).resolve().parent
    harness = root / "ownership_cache_memory.ml"
    build = worktree / "stage2/dune/_build/default/fstar-guts"
    archive = build / "fstarcompiler.cmxa"
    if sha256(archive) != ARCHIVE:
        raise RuntimeError("unexpected compiler archive")
    args.output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="ownership-memory-", dir=args.output
    ) as directory:
        temporary = Path(directory)
        build_harness = temporary / harness.name
        build_harness.write_bytes(harness.read_bytes())
        executable = temporary / "ownership-cache-memory.exe"
        command = [
            "ocamlfind", "ocamlopt", "-thread", "-linkpkg",
            "-package", PACKAGES,
            "-I", str(build / ".fstarcompiler.objs/byte"),
            "-I", str(build / ".fstarcompiler.objs/native"),
            str(archive), str(build_harness), "-o", str(executable),
        ]
        subprocess.run(command, cwd=temporary, check=True)
        run = subprocess.run(
            [
                "/usr/bin/taskset", "-c", str(args.cpu),
                str(executable), str(source_dir), *sources,
            ],
            text=True,
            capture_output=True,
            check=True,
        )
    snapshots = {}
    cache = {}
    for line in run.stdout.splitlines():
        snapshot = re.match(
            r"(inputs|populated|cleared) "
            r"live_words=(\d+) heap_words=(\d+) free_words=(\d+) "
            r"top_heap_words=(\d+) rss_kb=(\d+)",
            line,
        )
        if snapshot:
            snapshots[snapshot.group(1)] = {
                "live_words": int(snapshot.group(2)),
                "heap_words": int(snapshot.group(3)),
                "free_words": int(snapshot.group(4)),
                "top_heap_words": int(snapshot.group(5)),
                "rss_kb": int(snapshot.group(6)),
            }
        cache_line = re.match(
            r"(cache|cleared_cache) entries=(\d+) key_chars=(\d+) "
            r"value_chars=(\d+) negative=(\d+)",
            line,
        )
        if cache_line:
            cache[cache_line.group(1)] = {
                "entries": int(cache_line.group(2)),
                "key_chars": int(cache_line.group(3)),
                "value_chars": int(cache_line.group(4)),
                "negative": int(cache_line.group(5)),
            }
    if set(snapshots) != {"inputs", "populated", "cleared"}:
        raise RuntimeError("snapshot output differs")
    if cache.get("cleared_cache", {}).get("entries") != 0:
        raise RuntimeError("cache did not clear")
    output = {
        "cpu": args.cpu,
        "worktree": str(worktree),
        "worktree_head": head,
        "source_commit": COMMIT,
        "sources": sources,
        "source_sha256": source_hashes,
        "compiler_archive_sha256": sha256(archive),
        "harness_sha256": sha256(harness),
        "runner_sha256": sha256(Path(__file__)),
        "compile_command": [
            item.replace(str(temporary), "<temporary>")
            for item in command
        ],
        "stdout": run.stdout,
        "snapshots": snapshots,
        "cache": cache,
        "diagnostic_deltas": {
            "populated_minus_inputs_live_words":
                snapshots["populated"]["live_words"]
                - snapshots["inputs"]["live_words"],
            "cleared_minus_inputs_live_words":
                snapshots["cleared"]["live_words"]
                - snapshots["inputs"]["live_words"],
            "populated_minus_inputs_heap_words":
                snapshots["populated"]["heap_words"]
                - snapshots["inputs"]["heap_words"],
            "cleared_minus_inputs_heap_words":
                snapshots["cleared"]["heap_words"]
                - snapshots["inputs"]["heap_words"],
            "populated_minus_inputs_rss_kb":
                snapshots["populated"]["rss_kb"]
                - snapshots["inputs"]["rss_kb"],
            "cleared_minus_inputs_rss_kb":
                snapshots["cleared"]["rss_kb"]
                - snapshots["inputs"]["rss_kb"],
        },
        "limitations": [
            "Forced major GC snapshots are diagnostic, not normal timings.",
            "The same process and binary provide the no-cache baseline.",
            "RSS and heap capacity may not shrink after objects become unreachable.",
        ],
    }
    (args.output / "result.json").write_text(
        json.dumps(output, indent=2) + "\n"
    )


if __name__ == "__main__":
    main()
