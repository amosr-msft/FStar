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
    "incumbent": {
        "commit": "2ef0fe554eeca5907db4deb5d9daf4f9e276b97d",
        "binary":
            "84402407c135053ea3bfec747c98b0a0788adedf69acceffca9e8ef5ceb37e69",
        "archive":
            "600fba3706e58db30b5dfde880c7e396200e5902082d7d64e819bd26a46be17d",
        "checked":
            "67398b51b3bb4fbd24792bb9c0395b6b6694e691dbde1b4ae357984217bd71e3",
    },
    "forest": {
        "commit": "3e7d0a0eb1b8",
        "binary":
            "4ca29f690621d0775648d2216524168e1340491f9a5e149798d87a958f7bdeda",
        "archive":
            "8af7e15b4db082d70f9c8c77101ddde11936c75dfc1459316891d9d8484ec895",
        "checked":
            "57f0b2739ed3be72038a0d50e43f585e8e09fe6763e67318d3428afde289445c",
    },
    "flat": {
        "commit": "e7403a6164c6",
        "binary":
            "4385f92ce929a0298c4b391f694ffc6e094ad1839a317067d798854d1e4ba659",
        "archive":
            "8007f1de15be55de8c81537f55c354820122bf2e72a5f6183ba710a750c6fbb0",
        "checked":
            "b0fb71a579282a76446e4db2e32943ac0fec64a02efa11d5bd52cd4cb60f6c26",
    },
})
runner.COMPARISONS["trie"] = {"incumbent", "forest", "flat"}

OriginalRandom = runner.random.Random


class BalancedRandom(OriginalRandom):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.order_index = 0

    def shuffle(self, values):
        if (
            values
            and isinstance(values[0], tuple)
            and len(values[0]) == 2
        ):
            by_group = {}
            for value in values:
                by_group.setdefault(value[0], []).append(value)
            even = []
            odd = []
            for group_values in by_group.values():
                super().shuffle(group_values)
                midpoint = len(group_values) // 2
                even.extend(group_values[:midpoint])
                odd.extend(group_values[midpoint:])
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
        if k == 3 and len(population) == 3 and counts is None:
            ordered = list(population)
            if self.order_index % 2:
                ordered.reverse()
            self.order_index += 1
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
    provenance["comparison_alias"] = {
        "trie": "incumbent-forest-flat",
    }
    provenance["direction_order"] = (
        "forward/reverse variant order, balanced per workload/root count"
    )
    provenance["driver_sha256"] = sha256(Path(__file__))
    provenance_path.write_text(json.dumps(provenance, indent=2) + "\n")


if __name__ == "__main__":
    main()
