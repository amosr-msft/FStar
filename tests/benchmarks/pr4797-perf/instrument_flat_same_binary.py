#!/usr/bin/env python3

import argparse
from pathlib import Path


def replace_once(text, old, new, label):
    if text.count(old) != 1:
        raise RuntimeError(f"{label}: expected one occurrence")
    return text.replace(old, new, 1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("worktree", type=Path)
    args = parser.parse_args()
    path = args.worktree.resolve() / "stage3/fstarc.ml/FStarC_Find.ml"
    text = path.read_text()
    marker = "let normalized_module_include_paths "
    counters = """let diagnostic_relative_calls = ref 0
    let diagnostic_relative_seconds = ref 0.0
let diagnostic_filename_chars = ref 0
let diagnostic_flat_probes = ref 0
let diagnostic_flat_dirnames = ref 0
let diagnostic_trie_nodes = ref 0
let diagnostic_trie_hash_probes = ref 0
let diagnostic_index_builds = ref 0
let diagnostic_root_count = ref 0
let diagnostic_gc_start = Gc.quick_stat ()
let diagnostic_allocated_start = Gc.allocated_bytes ()

let () = at_exit (fun () ->
  let gc = Gc.quick_stat () in
  Printf.eprintf
    "PR4797_FLAT_DIAG mode=%s relative_calls=%d relative_seconds=%.9f filename_chars=%d \
flat_probes=%d flat_dirnames=%d trie_nodes=%d trie_hash_probes=%d \
index_builds=%d roots=%d allocated_bytes=%.0f minor_words=%.0f \
promoted_words=%.0f major_words=%.0f minor_collections=%d \
major_collections=%d compactions=%d heap_words=%d top_heap_words=%d\\n%!"
    (if diagnostic_flat_root_mode then "flat" else "trie")
    !diagnostic_relative_calls !diagnostic_relative_seconds
    !diagnostic_filename_chars
    !diagnostic_flat_probes !diagnostic_flat_dirnames
    !diagnostic_trie_nodes !diagnostic_trie_hash_probes
    !diagnostic_index_builds !diagnostic_root_count
    (Gc.allocated_bytes () -. diagnostic_allocated_start)
    (gc.Gc.minor_words -. diagnostic_gc_start.Gc.minor_words)
    (gc.Gc.promoted_words -. diagnostic_gc_start.Gc.promoted_words)
    (gc.Gc.major_words -. diagnostic_gc_start.Gc.major_words)
    (gc.Gc.minor_collections - diagnostic_gc_start.Gc.minor_collections)
    (gc.Gc.major_collections - diagnostic_gc_start.Gc.major_collections)
    (gc.Gc.compactions - diagnostic_gc_start.Gc.compactions)
    gc.Gc.heap_words gc.Gc.top_heap_words)

"""
    text = replace_once(text, marker, counters + marker, "counter marker")
    old_flat = (
        "(directory : string) (immediate : bool) : (string) option =\n"
        "  (let tmp = "
    )
    new_flat = (
        "(directory : string) (immediate : bool) : (string) option =\n"
        "  (incr diagnostic_flat_probes;\n"
        "  let tmp = "
    )
    text = replace_once(text, old_flat, new_flat, "flat entry")
    old_dirname = (
        "| tmp1 -> (let parent = (Filename.dirname directory) in\n"
    )
    new_dirname = (
        "| tmp1 -> (incr diagnostic_flat_dirnames;\n"
        "      let parent = (Filename.dirname directory) in\n"
    )
    text = replace_once(text, old_dirname, new_dirname, "flat dirname")
    old_trie = (
        "(trie : source_root_trie) (best : (string) option) "
        ": (string) option =\n"
        "  (let best1 = "
    )
    new_trie = (
        "(trie : source_root_trie) (best : (string) option) "
        ": (string) option =\n"
        "  (incr diagnostic_trie_nodes;\n"
        "  let best1 = "
    )
    text = replace_once(text, old_trie, new_trie, "trie entry")
    old_probe = (
        "(match components with\n"
        "    | [] -> best1\n"
        "    | (component :: rest) -> (let tmp = "
    )
    new_probe = (
        "(match components with\n"
        "    | [] -> best1\n"
        "    | (component :: rest) -> "
        "(incr diagnostic_trie_hash_probes;\n"
        "      let tmp = "
    )
    text = replace_once(text, old_probe, new_probe, "trie probe")
    old_relative_name = (
        "let relative_source_path_normalized (filename : string) "
        ": (string) option =\n"
    )
    new_relative_name = (
        "let relative_source_path_normalized_original (filename : string) "
        ": (string) option =\n"
    )
    text = replace_once(
        text, old_relative_name, new_relative_name, "relative name"
    )
    old_relative = (
        ": (string) option =\n"
        "  (let roots = (normalized_module_include_paths ()) in\n"
    )
    new_relative = (
        ": (string) option =\n"
        "  (incr diagnostic_relative_calls;\n"
        "  diagnostic_filename_chars := !diagnostic_filename_chars "
        "+ String.length filename;\n"
        "  let roots = (normalized_module_include_paths ()) in\n"
    )
    text = replace_once(text, old_relative, new_relative, "relative entry")
    wrapper_marker = "\nlet relative_source_path (filename : string)"
    wrapper = """
let relative_source_path_normalized (filename : string) : (string) option =
  let started = Sys.time () in
  let result = relative_source_path_normalized_original filename in
  diagnostic_relative_seconds :=
    !diagnostic_relative_seconds +. (Sys.time () -. started);
  result
"""
    text = replace_once(
        text, wrapper_marker, "\n" + wrapper + wrapper_marker,
        "relative wrapper",
    )
    old_build = (
        "| None -> (let tmp2 = (module_include_paths ()) in\n"
        "      let paths = "
    )
    new_build = (
        "| None -> (incr diagnostic_index_builds;\n"
        "      let tmp2 = (module_include_paths ()) in\n"
        "      let paths = "
    )
    text = replace_once(text, old_build, new_build, "index build")
    old_roots = (
        "let flat_source_roots = "
        "(FStarC_HashTable.FStarC_HashTable_hashtbl_make__0.create "
    )
    new_roots = (
        "diagnostic_root_count := BatList.length paths;\n"
        "      let flat_source_roots = "
        "(FStarC_HashTable.FStarC_HashTable_hashtbl_make__0.create "
    )
    text = replace_once(text, old_roots, new_roots, "root count")
    path.write_text(text)


if __name__ == "__main__":
    main()
