#!/usr/bin/env python3

import argparse
from pathlib import Path


def replace_once(text, old, new, label):
    if text.count(old) != 1:
        raise RuntimeError(f"{label}: expected one occurrence")
    return text.replace(old, new, 1)


def replace_once_after(text, marker, old, new, label):
    start = text.find(marker)
    if start < 0:
        raise RuntimeError(f"{label}: marker missing")
    prefix = text[:start]
    suffix = text[start:]
    return prefix + replace_once(suffix, old, new, label)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("worktree", type=Path)
    args = parser.parse_args()
    path = args.worktree.resolve() / "stage3/fstarc.ml/FStarC_Find.ml"
    text = path.read_text()
    marker = "let normalized_module_include_paths "
    counters = """let diagnostic_index_builds = ref 0
let diagnostic_trie_builds = ref 0
let diagnostic_flat_builds = ref 0
let diagnostic_roots_total = ref 0
let diagnostic_gc_start = Gc.quick_stat ()
let diagnostic_allocated_start = Gc.allocated_bytes ()

let () = at_exit (fun () ->
  let gc = Gc.quick_stat () in
  Printf.eprintf
    "PR4797_SINGLE_INDEX mode=%s index_builds=%d trie_builds=%d \
flat_builds=%d roots_total=%d allocated_bytes=%.0f minor_words=%.0f \
promoted_words=%.0f major_words=%.0f minor_collections=%d \
major_collections=%d compactions=%d heap_words=%d top_heap_words=%d\\n%!"
    (if use_flat_source_root_index then "flat" else "trie")
    !diagnostic_index_builds !diagnostic_trie_builds
    !diagnostic_flat_builds !diagnostic_roots_total
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
    text = replace_once_after(
        text,
        marker,
        "(match tmp1 with\n"
        "    | (Some (paths)) -> paths\n"
        "    | None -> (let tmp2 = (module_include_paths ()) in\n",
        "(match tmp1 with\n"
        "    | (Some (paths)) -> paths\n"
        "    | None -> (incr diagnostic_index_builds;\n"
        "      let tmp2 = (module_include_paths ()) in\n",
        "index build",
    )
    text = replace_once(
        text,
        "let source_roots = (if use_flat_source_root_index "
        "then (let roots = ",
        "diagnostic_roots_total := "
        "!diagnostic_roots_total + BatList.length paths;\n"
        "      let source_roots = "
        "(if use_flat_source_root_index then "
        "(incr diagnostic_flat_builds;\n"
        "        let roots = ",
        "flat build",
    )
    text = replace_once(
        text,
        "(FlatRootMap (roots))) else (let tmp3 = ",
        "(FlatRootMap (roots))) else "
        "(incr diagnostic_trie_builds;\n"
        "        let tmp3 = ",
        "trie build",
    )
    path.write_text(text)


if __name__ == "__main__":
    main()
