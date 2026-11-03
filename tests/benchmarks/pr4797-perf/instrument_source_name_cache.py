#!/usr/bin/env python3

import argparse
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("worktree", type=Path)
    args = parser.parse_args()
    path = (
        args.worktree.resolve()
        / "stage2/fstarc.ml/FStarC_Find.ml"
    )
    text = path.read_text()
    old = (
        "let cached_fun (cache : ('a) "
        "FStarC_HashTable.FStarC_HashTable_hashtbl_make__0.t) "
        "(f : (string -> 'a)) (s : string) : 'a =\n"
        "  (let tmp = "
        "(FStarC_HashTable.FStarC_HashTable_hashtbl_make__0.find_opt "
        "cache s) in\n"
    )
    new = (
        "let source_name_cache_calls = ref 0\n"
        "let source_name_cache_misses = ref 0\n\n"
        "let () = at_exit (fun () ->\n"
        "  Printf.eprintf "
        "\"PR4797_SOURCE_CACHE calls=%d misses=%d\\n%!\"\n"
        "    !source_name_cache_calls !source_name_cache_misses)\n\n"
        "let cached_fun (cache : ('a) "
        "FStarC_HashTable.FStarC_HashTable_hashtbl_make__0.t) "
        "(f : (string -> 'a)) (s : string) : 'a =\n"
        "  (let is_source_name =\n"
        "     Obj.repr cache == Obj.repr source_file_name_cache\n"
        "   in\n"
        "  if is_source_name then incr source_name_cache_calls;\n"
        "  let tmp = "
        "(FStarC_HashTable.FStarC_HashTable_hashtbl_make__0.find_opt "
        "cache s) in\n"
    )
    if text.count(old) != 1:
        raise RuntimeError("expected one cached_fun definition")
    text = text.replace(old, new, 1)
    old_none = "| None -> (let v = (f s) in\n"
    new_none = (
        "| None -> (\n"
        "      if is_source_name then incr source_name_cache_misses;\n"
        "      let v = (f s) in\n"
    )
    if text.count(old_none) != 1:
        raise RuntimeError("expected one cached_fun miss branch")
    path.write_text(text.replace(old_none, new_none, 1))


if __name__ == "__main__":
    main()
