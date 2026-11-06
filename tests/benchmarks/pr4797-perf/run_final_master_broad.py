#!/usr/bin/env python3

import hashlib
import importlib.util
import json
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
RUNNER = HERE / "run_pr_fixed_broad.py"
spec = importlib.util.spec_from_file_location("pr_fixed_broad", RUNNER)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)

runner.VARIANTS.update({
    "pr": {
        "commit": "9ccacf4a8a392137d5384f8b39500377ebf53f79",
        "binary":
            "9c24fe8a04f8244948b877bbb4eb1d480b6bfd093d0fabdd8e99c53af4ebe098",
        "checked":
            "9c36db327a39edccf01aa6caf78c1e1e1a0fa6390b2454c479b96399eda8e019",
    },
    "fixed": {
        "commit": "2ef0fe554eeca5907db4deb5d9daf4f9e276b97d",
        "binary":
            "84402407c135053ea3bfec747c98b0a0788adedf69acceffca9e8ef5ceb37e69",
        "checked":
            "67398b51b3bb4fbd24792bb9c0395b6b6694e691dbde1b4ae357984217bd71e3",
    },
})

OriginalRandom = runner.random.Random


class BalancedRandom(OriginalRandom):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.pair_index = 0

    def shuffle(self, values):
        if (
            values
            and isinstance(values[0], tuple)
            and len(values[0]) == 2
        ):
            by_workload = {}
            for value in values:
                by_workload.setdefault(value[0], []).append(value)
            even = []
            odd = []
            for workload_values in by_workload.values():
                super().shuffle(workload_values)
                midpoint = len(workload_values) // 2
                even.extend(workload_values[:midpoint])
                odd.extend(workload_values[midpoint:])
            super().shuffle(even)
            super().shuffle(odd)
            values[:] = [
                value
                for pair in zip(even, odd)
                for value in pair
            ]
            return
        super().shuffle(values)

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
    provenance["variant_aliases"] = {
        "pr": "master",
        "fixed": "final-grouped-trie",
    }
    provenance["direction_order"] = (
        "randomized cells with exactly 10 pairs in each direction per workload"
    )
    provenance["driver_sha256"] = sha256(Path(__file__))
    provenance_path.write_text(json.dumps(provenance, indent=2) + "\n")


if __name__ == "__main__":
    main()
