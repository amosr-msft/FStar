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
    "master-rebuild": {
        "commit": "9ccacf4a8a392137d5384f8b39500377ebf53f79",
        "binary":
            "a58c72c24bf74ba34fed24b7f303e6ac61d9fbf35f3eace617f79574192b595b",
        "archive":
            "fc1af98be5fbfdeed7a30f2ad8d43a3b762878bafb0f42cc2ea06c9cd308e5d9",
        "checked":
            "3132dbcf8dd83b6b198c4f882645bca1b6498f1a558d193860aad302eda079fe",
    },
    "final-rebuild": {
        "commit": "2ef0fe554eeca5907db4deb5d9daf4f9e276b97d",
        "binary":
            "fca8b319b4aaac348a8bed0689bb90043719f9e739f4e13e2a19ca4b10775873",
        "archive":
            "600fba3706e58db30b5dfde880c7e396200e5902082d7d64e819bd26a46be17d",
        "checked":
            "4b9fb485d1d235391e4f23a38129de281b8a754f254867b2ed15f1c233e396ed",
    },
})
runner.COMPARISONS["final-master-rebuild"] = {
    "master-rebuild", "final-rebuild"
}

OriginalRandom = runner.random.Random


class BalancedRandom(OriginalRandom):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.pair_index = 0

    def sample(self, population, k, *, counts=None):
        if k == 2 and len(population) == 2 and counts is None:
            ordered = list(population)
            if self.pair_index % 2:
                ordered.reverse()
            self.pair_index += 1
            return ordered
        return super().sample(population, k, counts=counts)


runner.random.Random = BalancedRandom


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    output = Path(sys.argv[sys.argv.index("--output") + 1]).resolve()
    runner.main()
    provenance_path = output / "provenance.json"
    provenance = json.loads(provenance_path.read_text())
    provenance["direction_order"] = "exactly alternating"
    provenance["driver_sha256"] = sha256(Path(__file__))
    provenance_path.write_text(json.dumps(provenance, indent=2) + "\n")


if __name__ == "__main__":
    main()
