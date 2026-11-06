#!/usr/bin/env python3

import hashlib
import importlib.util
import json
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
DRIVER = HERE / "run_cache_state_comparison.py"
spec = importlib.util.spec_from_file_location("cache_state_driver", DRIVER)
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)

driver.runner.EXPECTED["cache-state-rebuild"] = {
    "commit": "2ef0fe554eeca5907db4deb5d9daf4f9e276b97d",
    "binary":
        "fca8b319b4aaac348a8bed0689bb90043719f9e739f4e13e2a19ca4b10775873",
    "archive":
        "600fba3706e58db30b5dfde880c7e396200e5902082d7d64e819bd26a46be17d",
    "checked":
        "4b9fb485d1d235391e4f23a38129de281b8a754f254867b2ed15f1c233e396ed",
}
driver.runner.COMPARISONS["cache-state-rebuild"] = {
    "reviewed-trie", "cache-state", "cache-state-rebuild"
}


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    output = Path(sys.argv[sys.argv.index("--output") + 1]).resolve()
    driver.runner.main()
    provenance_path = output / "provenance.json"
    provenance = json.loads(provenance_path.read_text())
    provenance["driver_sha256"] = sha256(DRIVER)
    provenance["rebuild_driver_sha256"] = sha256(Path(__file__))
    provenance_path.write_text(json.dumps(provenance, indent=2) + "\n")


if __name__ == "__main__":
    main()
