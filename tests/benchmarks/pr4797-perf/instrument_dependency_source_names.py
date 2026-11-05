#!/usr/bin/env python3

import argparse
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("worktree", type=Path)
    args = parser.parse_args()
    path = (
        args.worktree.resolve()
        / "stage3/fstarc.ml/FStarC_Find.ml"
    )
    text = path.read_text()
    relative_old = (
        "let relative_source_path_normalized "
        "(filename : string) : (string) option =\n"
    )
    relative_new = (
        "let relative_source_path_normalized_calls = ref 0\n"
        "let relative_source_path_normalized_seconds = ref 0.0\n\n"
        "let () = at_exit (fun () ->\n"
        "  Printf.eprintf "
        "\"PR4797_RELATIVE_SOURCE calls=%d seconds=%.9f\\n%!\"\n"
        "    !relative_source_path_normalized_calls\n"
        "    !relative_source_path_normalized_seconds)\n\n"
        "let relative_source_path_normalized_original "
        "(filename : string) : (string) option =\n"
    )
    if text.count(relative_old) != 1:
        raise RuntimeError("expected one relative_source_path definition")
    text = text.replace(relative_old, relative_new, 1)
    relative_marker = "\nlet relative_source_path (filename : string)"
    relative_wrapper = (
        "\nlet relative_source_path_normalized "
        "(filename : string) : (string) option =\n"
        "  (incr relative_source_path_normalized_calls;\n"
        "  let started = Sys.time () in\n"
        "  let result = relative_source_path_normalized_original filename in\n"
        "  relative_source_path_normalized_seconds :=\n"
        "    !relative_source_path_normalized_seconds "
        "+. (Sys.time () -. started);\n"
        "  result)\n"
    )
    if text.count(relative_marker) != 1:
        raise RuntimeError("expected one relative insertion point")
    text = text.replace(
        relative_marker, relative_wrapper + relative_marker, 1
    )
    old = (
        "let source_file_name (s : string) : string =\n"
        "  (cached_fun source_file_name_cache "
    )
    new = (
        "let source_file_name_calls = ref 0\n"
        "let source_file_name_seconds = ref 0.0\n\n"
        "let () = at_exit (fun () -> Printf.eprintf "
        "\"PR4797_DEP_SOURCE_NAMES calls=%d seconds=%.9f\\n%!\" "
        "!source_file_name_calls !source_file_name_seconds)\n\n"
        "let source_file_name_original (s : string) : string =\n"
        "  (cached_fun source_file_name_cache "
    )
    if text.count(old) != 1:
        raise RuntimeError("expected one source_file_name definition")
    text = text.replace(old, new, 1)
    marker = "\nlet module_include_paths_normalized"
    wrapper = (
        "\nlet source_file_name (s : string) : string =\n"
        "  (incr source_file_name_calls;\n"
        "  let started = Sys.time () in\n"
        "  let result = source_file_name_original s in\n"
        "  source_file_name_seconds :=\n"
        "    !source_file_name_seconds +. (Sys.time () -. started);\n"
        "  result)\n"
    )
    if text.count(marker) != 1:
        raise RuntimeError("expected one insertion point")
    path.write_text(text.replace(marker, wrapper + marker, 1))


if __name__ == "__main__":
    main()
