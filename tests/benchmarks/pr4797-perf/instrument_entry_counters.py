#!/usr/bin/env python3

import argparse
from pathlib import Path


def replace_once(path, old, new):
    text = path.read_text()
    if text.count(old) != 1:
        raise RuntimeError(f"expected one match in {path}")
    path.write_text(text.replace(old, new, 1))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("worktree", type=Path)
    args = parser.parse_args()
    extracted = args.worktree.resolve() / "stage2/fstarc.ml"
    replace_once(
        extracted / "FStarC_Range_Type.ml",
        "let mk_rng (file_name : string) (start_pos : Prims.int) "
        "(end_pos : Prims.int) : rng =\n"
        "  { file_name = file_name; start_pos = start_pos; "
        "end_pos = end_pos }\n",
        "let mk_rng_calls = ref 0\n\n"
        "let () = at_exit (fun () -> Printf.eprintf "
        "\"PR4797_COUNTER mk_rng=%d\\n%!\" !mk_rng_calls)\n\n"
        "let mk_rng (file_name : string) (start_pos : Prims.int) "
        "(end_pos : Prims.int) : rng =\n"
        "  incr mk_rng_calls;\n"
        "  { file_name = file_name; start_pos = start_pos; "
        "end_pos = end_pos }\n",
    )
    replace_once(
        extracted / "FStarC_Find.ml",
        "let source_file_name (filename : string) : string =\n"
        "  (let tmp = (find_file filename) in\n",
        "let source_file_name_calls = ref 0\n\n"
        "let () = at_exit (fun () -> Printf.eprintf "
        "\"PR4797_COUNTER source_file_name=%d\\n%!\" "
        "!source_file_name_calls)\n\n"
        "let source_file_name (filename : string) : string =\n"
        "  (incr source_file_name_calls;\n"
        "  let tmp = (find_file filename) in\n",
    )


if __name__ == "__main__":
    main()
