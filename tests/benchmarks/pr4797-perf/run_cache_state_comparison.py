#!/usr/bin/env python3

import hashlib
import importlib.util
import json
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
RUNNER = HERE / "run_root_trie_comparison.py"
spec = importlib.util.spec_from_file_location("root_trie_runner", RUNNER)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)

runner.EXPECTED.update({
    "reviewed-trie": {
        "commit": "0a1c87e8bbdcf740ae753c84401c981a14f15c6f",
        "binary":
            "2177f26d889d0a8a028ee323c7404b7915431597ab939be31b4e398b56f5d73b",
        "archive":
            "5d0c148a8231892363ab0b0326add7b3cdbeb24995f22d7f40fec83d552bf613",
        "checked":
            "9976536383898186eb288cb70e104f3ac0350db21c4586846e87fc830e52352d",
    },
    "cache-state": {
        "commit": "2ef0fe554eeca5907db4deb5d9daf4f9e276b97d",
        "binary":
            "84402407c135053ea3bfec747c98b0a0788adedf69acceffca9e8ef5ceb37e69",
        "archive":
            "600fba3706e58db30b5dfde880c7e396200e5902082d7d64e819bd26a46be17d",
        "checked":
            "67398b51b3bb4fbd24792bb9c0395b6b6694e691dbde1b4ae357984217bd71e3",
    },
})
runner.COMPARISONS["cache-state"] = {"reviewed-trie", "cache-state"}


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    output = Path(sys.argv[sys.argv.index("--output") + 1]).resolve()
    runner.main()
    provenance_path = output / "provenance.json"
    provenance = json.loads(provenance_path.read_text())
    provenance["driver_sha256"] = sha256(Path(__file__))
    provenance_path.write_text(json.dumps(provenance, indent=2) + "\n")


if __name__ == "__main__":
    main()
