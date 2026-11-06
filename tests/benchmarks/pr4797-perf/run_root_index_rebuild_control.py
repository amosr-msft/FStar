#!/usr/bin/env python3

import hashlib
import importlib.util
import json
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
DRIVER = HERE / "run_root_index_variants.py"
spec = importlib.util.spec_from_file_location("root_index_variants", DRIVER)
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)

driver.runner.EXPECTED.update({
    "incumbent-rebuild": {
        "commit": "2ef0fe554eeca5907db4deb5d9daf4f9e276b97d",
        "binary":
            "fca8b319b4aaac348a8bed0689bb90043719f9e739f4e13e2a19ca4b10775873",
        "archive":
            "600fba3706e58db30b5dfde880c7e396200e5902082d7d64e819bd26a46be17d",
        "checked":
            "4b9fb485d1d235391e4f23a38129de281b8a754f254867b2ed15f1c233e396ed",
    },
    "forest-rebuild": {
        "commit": "3e7d0a0eb1b8",
        "binary":
            "eede4008eeac2c4cee20ce94bcd98707cfaac9efbd3456587abef5177390f6b7",
        "archive":
            "a2d61d3229d959235beaab2b7461315df678309616fb035e91b8f39a18fbd9d6",
        "checked":
            "3c0ab8405f625208747e62d83d819586286788673424c295f814f3671f46b534",
    },
    "flat-rebuild": {
        "commit": "e7403a6164c6",
        "binary":
            "1fc100866a296007072c04a6750ad4100563bdfb5fb8588cbd5370b36996acce",
        "archive":
            "2898ad019b85ac195c08cfd1ae65783385bc8c8ecaf5c38da1031795a55d9d5a",
        "checked":
            "5f03849f512bc9d4654b79bb2d3f0a2a7712a83ad7487f9ed4fc51999868b889",
    },
})
driver.runner.COMPARISONS["trie"] = {
    "incumbent-rebuild", "forest-rebuild", "flat-rebuild"
}


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    output = Path(sys.argv[sys.argv.index("--output") + 1]).resolve()
    driver.runner.main()
    provenance_path = output / "provenance.json"
    provenance = json.loads(provenance_path.read_text())
    provenance["comparison_alias"] = {
        "trie": "incumbent-forest-flat-independent-rebuilds",
    }
    provenance["direction_order"] = (
        "forward/reverse variant order, balanced per workload"
    )
    provenance["driver_sha256"] = sha256(Path(__file__))
    provenance["base_driver_sha256"] = sha256(DRIVER)
    provenance_path.write_text(json.dumps(provenance, indent=2) + "\n")


if __name__ == "__main__":
    main()
