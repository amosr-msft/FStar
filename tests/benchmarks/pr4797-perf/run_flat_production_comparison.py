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
    "canonical": {
        "commit": "7df960b9fbbeed8c599361d9660f40f2e2f85f9c",
        "binary":
            "207e478416f8fae3bd3c3b33914f2a5a9504fbcaf2d3d4745d9cc5914e0734b9",
        "archive":
            "422cfed886c9e4a12baf6d0b49d67b66fafd33f93d7c351e0f22a420bedef6cd",
        "checked":
            "67398b51b3bb4fbd24792bb9c0395b6b6694e691dbde1b4ae357984217bd71e3",
    },
    "flat-production": {
        "commit": "1b61ce6d3b2d0cead2f5174d931b042961529193",
        "binary":
            "667968b8748df177213e2ae45faa5156e507469c9b4cf9771cabc7c9e19d0641",
        "archive":
            "4fd4a63679976618a7e340e7ff5b3d600597d41542fc70e2dbc23f876e199f50",
        "checked":
            "7ecbd36e330e8513e9d2ff389c57272769b94f951ef44edcb34c1d1d92634d8d",
    },
})
runner.COMPARISONS["flat-production"] = {"canonical", "flat-production"}

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
