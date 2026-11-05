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
VARIANTS = {
    "three": {
        "commit": "7da01c0b4ae5cf447f6951ddb38714b7f1969a35",
        "archive":
            "2037dcf943e9eafabc6cf554867cc710158fb010192aaa3090457fb8bc5d59e6",
        "harness": "source_name_memory_three.ml",
    },
    "two": {
        "commit": "285501627e98a089ee15fe10dec94fcfa0b76f73",
        "archive":
            "7e8c55dba4abeacc08a557411e7923aac3ff1feaa8fa053472d73ddb83bfee19",
        "harness": "source_name_memory_two.ml",
    },
}


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--three", type=Path, required=True)
    parser.add_argument("--two", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cpu", type=int, default=16)
    args = parser.parse_args()
    roots = {"three": args.three.resolve(), "two": args.two.resolve()}
    source_dir = roots["three"] / "tests/bug-reports/closed"
    sources = [
        path.name
        for pattern in ("*.fst", "*.fsti")
        for path in sorted(source_dir.glob(pattern))
    ]
    source_hashes = {
        source: sha256(source_dir / source) for source in sources
    }
    script_root = Path(__file__).resolve().parent
    args.output.mkdir(parents=True, exist_ok=True)
    results = {}
    with tempfile.TemporaryDirectory(
        prefix="two-cache-memory-", dir=args.output
    ) as directory:
        temporary = Path(directory)
        for variant, root in roots.items():
            spec = VARIANTS[variant]
            head = subprocess.check_output(
                ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
            ).strip()
            if subprocess.run([
                "git", "-C", str(root), "merge-base", "--is-ancestor",
                spec["commit"], head,
            ]).returncode != 0:
                raise RuntimeError(f"{variant}: unexpected revision")
            build = root / "stage2/dune/_build/default/fstar-guts"
            archive = build / "fstarcompiler.cmxa"
            if sha256(archive) != spec["archive"]:
                raise RuntimeError(f"{variant}: archive differs")
            harness = script_root / spec["harness"]
            build_harness = temporary / harness.name
            build_harness.write_bytes(harness.read_bytes())
            executable = temporary / f"{variant}.exe"
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
            tables = {}
            for line in run.stdout.splitlines():
                snapshot = re.match(
                    r"(inputs|ownership|source|cleared) "
                    r"live_words=(\d+) heap_words=(\d+) rss_kb=(\d+)",
                    line,
                )
                if snapshot:
                    snapshots[snapshot.group(1)] = {
                        "live_words": int(snapshot.group(2)),
                        "heap_words": int(snapshot.group(3)),
                        "rss_kb": int(snapshot.group(4)),
                    }
                table = re.match(
                    r"(find|ownership_cache|source_cache) "
                    r"entries=(\d+) key_chars=(\d+) value_chars=(\d+)",
                    line,
                )
                if table:
                    tables[table.group(1)] = {
                        "entries": int(table.group(2)),
                        "key_chars": int(table.group(3)),
                        "value_chars": int(table.group(4)),
                    }
            results[variant] = {
                "root": str(root),
                "worktree_head": head,
                "source_commit": spec["commit"],
                "archive_sha256": sha256(archive),
                "harness_sha256": sha256(harness),
                "compile_command": [
                    item.replace(str(temporary), "<temporary>")
                    for item in command
                ],
                "stdout": run.stdout,
                "snapshots": snapshots,
                "tables": tables,
            }
    output = {
        "cpu": args.cpu,
        "sources": sources,
        "source_sha256": source_hashes,
        "results": results,
        "runner_sha256": sha256(Path(__file__)),
        "limitations": [
            "Forced major GC snapshots are diagnostic only.",
            "The variants are separate native builds.",
            "RSS need not shrink when objects become unreachable.",
        ],
    }
    (args.output / "result.json").write_text(
        json.dumps(output, indent=2) + "\n"
    )


if __name__ == "__main__":
    main()
