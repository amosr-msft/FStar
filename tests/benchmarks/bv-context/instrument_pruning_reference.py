#!/usr/bin/env python3

import argparse
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("worktree", type=Path)
    args = parser.parse_args()
    path = (
        args.worktree.resolve()
        / "stage2/fstarc.ml/FStarC_SMTEncoding_Pruning.ml"
    )
    text = path.read_text()
    old = (
        'let fresh_scan = (if tmp1 then true else '
        '(FStarC_Options_Ext.enabled "pretyping_axioms")) in'
    )
    new = (
        "let fresh_scan = "
        "(match Sys.getenv_opt \"FSTAR_PRUNING_REFERENCE\" with "
        "Some _ -> true | None -> "
        f"(if tmp1 then true else "
        '(FStarC_Options_Ext.enabled "pretyping_axioms"))) in'
    )
    if text.count(old) != 1:
        raise RuntimeError("expected one fresh_scan definition")
    path.write_text(text.replace(old, new, 1))


if __name__ == "__main__":
    main()
