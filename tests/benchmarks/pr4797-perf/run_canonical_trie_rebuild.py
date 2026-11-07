#!/usr/bin/env python3

import hashlib
import importlib.util
import json
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
DRIVER = HERE / "run_canonical_trie_comparison.py"
spec = importlib.util.spec_from_file_location("canonical_driver", DRIVER)
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)

driver.runner.EXPECTED["canonical-rebuild"] = {
    "commit": "7df960b9fbbeed8c599361d9660f40f2e2f85f9c",
    "binary":
        "2e1c3ba0905e0c57c2411cbd07f33bf82106e9de7f24b4c182797286e98566f7",
    "archive":
        "b458b65f5192863a524f8b3f4be199af7fdff06ac7f2bf0206c593e1a1466961",
    "checked":
        "6dbdd24b661fbdee157f50fefa2264f7ca18429a7eb13889041328eda1d1a9a2",
}
driver.runner.COMPARISONS["canonical-rebuild"] = {
    "incumbent", "canonical", "canonical-rebuild"
}


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    output = Path(sys.argv[sys.argv.index("--output") + 1]).resolve()
    driver.runner.main()
    provenance_path = output / "provenance.json"
    provenance = json.loads(provenance_path.read_text())
    provenance["direction_order"] = "forward/reverse triple order"
    provenance["driver_sha256"] = sha256(Path(__file__))
    provenance["base_driver_sha256"] = sha256(DRIVER)
    provenance_path.write_text(json.dumps(provenance, indent=2) + "\n")


if __name__ == "__main__":
    main()
