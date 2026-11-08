#!/usr/bin/env python3

import hashlib
import importlib.util
import json
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
RUNNER = HERE / "run_flat_same_binary.py"
spec = importlib.util.spec_from_file_location("flat_same_binary", RUNNER)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)

runner.COMMIT = "850c09bed1b8167e4e91a396d563e20e485ec446"
original_load_helpers = runner.load_helpers


def load_helpers():
    monitor, parse_ramon, checked = original_load_helpers()

    def monitor_with_heap(command, cwd, environment, log, timeout):
        env = environment.copy()
        env["FSTAR_MEM_REPORT"] = str(log.parent / "fstar.fstarmem")
        return monitor(command, cwd, env, log, timeout)

    return monitor_with_heap, parse_ramon, checked


runner.load_helpers = load_helpers


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    output = Path(sys.argv[sys.argv.index("--output") + 1]).resolve()
    runner.main()
    provenance_path = output / "provenance.json"
    provenance = json.loads(provenance_path.read_text())
    provenance["baseline"] = (
        "canonical component trie 7df960b9fb plus diagnostic selector"
    )
    provenance["single_index"] = True
    provenance["dependency_heap_reports"] = True
    provenance["driver_sha256"] = sha256(Path(__file__))
    provenance_path.write_text(json.dumps(provenance, indent=2) + "\n")


if __name__ == "__main__":
    main()
