#!/usr/bin/env python3

import hashlib
import importlib.util
import json
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
RUNNER = HERE / "run_flat_staged_pair.py"
spec = importlib.util.spec_from_file_location("staged_pair", RUNNER)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)

runner.VARIANTS.update({
    "trie": {
        "commit": "1b61ce6d3b2d0cead2f5174d931b042961529193",
        "binary":
            "667968b8748df177213e2ae45faa5156e507469c9b4cf9771cabc7c9e19d0641",
    },
    "flat": {
        "commit": "31a521edd9ca47c547204cb0609a852206e4342a",
        "binary":
            "4fe1e790fc77782c38c3afdbf1f2f003143db58f539f65a78c07f8b9fb86a508",
    },
})


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    output = Path(sys.argv[sys.argv.index("--output") + 1]).resolve()
    runner.main()
    provenance_path = output / "provenance.json"
    provenance = json.loads(provenance_path.read_text())
    provenance["variant_aliases"] = {
        "trie": "pre-dedup-flat",
        "flat": "deduplicated-flat",
    }
    provenance["driver_sha256"] = sha256(Path(__file__))
    provenance_path.write_text(json.dumps(provenance, indent=2) + "\n")


if __name__ == "__main__":
    main()
