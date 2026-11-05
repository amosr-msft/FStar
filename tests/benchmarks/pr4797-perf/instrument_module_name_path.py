#!/usr/bin/env python3

import argparse
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("worktree", type=Path)
    args = parser.parse_args()
    path = (
        args.worktree.resolve()
        / "stage3/fstarc.ml/FStarC_Parser_Dep.ml"
    )
    text = path.read_text()
    old = (
        "let module_name_from_include_path "
        "(f : string) : (string) option =\n"
    )
    new = (
        "let module_name_from_include_path_calls = ref 0\n"
        "let module_name_from_include_path_seconds = ref 0.0\n\n"
        "let () = at_exit (fun () ->\n"
        "  Printf.eprintf "
        "\"PR4797_MODULE_NAME calls=%d seconds=%.9f\\n%!\"\n"
        "    !module_name_from_include_path_calls\n"
        "    !module_name_from_include_path_seconds)\n\n"
        "let module_name_from_include_path_original "
        "(f : string) : (string) option =\n"
    )
    if text.count(old) != 1:
        raise RuntimeError("expected one module_name_from_include_path")
    text = text.replace(old, new, 1)
    marker = "\nlet maybe_module_key_of_file"
    wrapper = (
        "\nlet module_name_from_include_path "
        "(f : string) : (string) option =\n"
        "  (incr module_name_from_include_path_calls;\n"
        "  let started = Sys.time () in\n"
        "  let result = module_name_from_include_path_original f in\n"
        "  module_name_from_include_path_seconds :=\n"
        "    !module_name_from_include_path_seconds "
        "+. (Sys.time () -. started);\n"
        "  result)\n"
    )
    if text.count(marker) != 1:
        raise RuntimeError("expected one insertion point")
    path.write_text(text.replace(marker, wrapper + marker, 1))


if __name__ == "__main__":
    main()
