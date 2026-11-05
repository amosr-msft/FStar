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
    cached_old = (
        "let cached_fun (cache : ('a) "
        "FStarC_HashTable.FStarC_HashTable_hashtbl_make__0.t) "
        "(f : (string -> 'a)) (s : string) : 'a =\n"
        "  (let tmp = "
        "(FStarC_HashTable.FStarC_HashTable_hashtbl_make__0.find_opt "
        "cache s) in\n"
    )
    cached_new = (
        "let ownership_calls = ref 0\n"
        "let ownership_misses = ref 0\n"
        "let source_name_calls = ref 0\n"
        "let source_name_misses = ref 0\n\n"
        "let () = at_exit (fun () ->\n"
        "  Printf.eprintf "
        "\"PR4797_OWNERSHIP calls=%d misses=%d source_calls=%d "
        "source_misses=%d\\n%!\"\n"
        "    !ownership_calls !ownership_misses\n"
        "    !source_name_calls !source_name_misses)\n\n"
        "let cached_fun (cache : ('a) "
        "FStarC_HashTable.FStarC_HashTable_hashtbl_make__0.t) "
        "(f : (string -> 'a)) (s : string) : 'a =\n"
        "  (let ownership =\n"
        "     Obj.repr cache == Obj.repr relative_source_path_cache\n"
        "   in\n"
        "  let source_name =\n"
        "     Obj.repr cache == Obj.repr source_file_name_cache\n"
        "   in\n"
        "  if ownership then incr ownership_calls;\n"
        "  if source_name then incr source_name_calls;\n"
        "  let tmp = "
        "(FStarC_HashTable.FStarC_HashTable_hashtbl_make__0.find_opt "
        "cache s) in\n"
    )
    if text.count(cached_old) != 1:
        raise RuntimeError("expected one cached_fun")
    text = text.replace(cached_old, cached_new, 1)
    miss_old = "| None -> (let v = (f s) in\n"
    miss_new = (
        "| None -> (\n"
        "      if ownership then incr ownership_misses;\n"
        "      if source_name then incr source_name_misses;\n"
        "      let v = (f s) in\n"
    )
    if text.count(miss_old) != 1:
        raise RuntimeError("expected one cache miss branch")
    text = text.replace(miss_old, miss_new, 1)
    source_old = "let source_file_name (s : string) : string =\n"
    source_new = (
        "let source_file_name_seconds = ref 0.0\n\n"
        "let () = at_exit (fun () ->\n"
        "  Printf.eprintf \"PR4797_SOURCE_TIME seconds=%.9f\\n%!\"\n"
        "    !source_file_name_seconds)\n\n"
        "let source_file_name_original (s : string) : string =\n"
    )
    if text.count(source_old) != 1:
        raise RuntimeError("expected one source_file_name")
    text = text.replace(source_old, source_new, 1)
    marker = "\nlet module_include_paths_normalized"
    wrapper = (
        "\nlet source_file_name (s : string) : string =\n"
        "  (let started = Sys.time () in\n"
        "  let result = source_file_name_original s in\n"
        "  source_file_name_seconds :=\n"
        "    !source_file_name_seconds +. (Sys.time () -. started);\n"
        "  result)\n"
    )
    if text.count(marker) != 1:
        raise RuntimeError("expected one source insertion point")
    path.write_text(text.replace(marker, wrapper + marker, 1))


if __name__ == "__main__":
    main()
