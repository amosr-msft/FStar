#!/usr/bin/env python3

import argparse
from pathlib import Path


PHASE_HELPER = r'''
let sharing_phase name f =
  match Sys.getenv_opt "FSTAR_SHARING_ANALYSIS" with
  | None -> f ()
  | Some _ ->
      let wall0 = Unix.gettimeofday () in
      let cpu0 = Sys.time () in
      let result = f () in
      Printf.eprintf "SHARING_PHASE,%s,%.3f,%.3f\n%!" name
        (1000. *. (Unix.gettimeofday () -. wall0))
        (1000. *. (Sys.time () -. cpu0));
      result

'''

SHARING_WRAPPER = r'''

let sharing_analysis phase f x =
  match Sys.getenv_opt "FSTAR_SHARING_ANALYSIS" with
  | None -> f x
  | Some _ ->
      let before = Gc.quick_stat () in
      let allocated0 = Gc.allocated_bytes () in
      let wall0 = Unix.gettimeofday () in
      let cpu0 = Sys.time () in
      let output = f x in
      let cpu_ms = 1000. *. (Sys.time () -. cpu0) in
      let wall_ms = 1000. *. (Unix.gettimeofday () -. wall0) in
      let after = Gc.quick_stat () in
      Printf.eprintf
        "SHARING_ANALYSIS,%s,%.3f,%.3f,%.0f,%.0f,%.0f,%d,%d,%d,%d\n%!"
        phase wall_ms cpu_ms
        ((Gc.allocated_bytes () -. allocated0) /. float_of_int (Sys.word_size / 8))
        (after.Gc.promoted_words -. before.Gc.promoted_words)
        (after.Gc.major_words -. before.Gc.major_words)
        (after.Gc.minor_collections - before.Gc.minor_collections)
        (after.Gc.major_collections - before.Gc.major_collections)
        after.Gc.heap_words after.Gc.top_heap_words;
      output

let intern_decls x = sharing_analysis "decls" intern_decls_impl x
let intern_index x = sharing_analysis "index" intern_index_impl x
'''


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError(f"expected one occurrence of {old!r}")
    return text.replace(old, new, 1)


def instrument(root, sharing_only):
    extracted = root / "stage2/fstarc.ml"
    sharing = extracted / "FStarC_SMTEncoding_Sharing.ml"
    if sharing.exists():
        text = sharing.read_text()
        text = replace_once(
            text, "let intern_decls (declarations :",
            "let intern_decls_impl (declarations :"
        )
        text = replace_once(
            text, "let intern_index (index :", "let intern_index_impl (index :"
        )
        sharing.write_text(text + SHARING_WRAPPER)
    if sharing_only:
        return

    encoding = extracted / "FStarC_SMTEncoding_Encode.ml"
    text = encoding.read_text()
    position = text.index("let encode_modul_aux ")
    text = text[:position] + PHASE_HELPER + text[position:]
    text = replace_once(
        text, "let tmp5 = (encode_signature {",
        'let tmp5 = (sharing_phase "encode_signature" (fun () -> encode_signature {'
    )
    start = text.index('let tmp5 = (sharing_phase "encode_signature"')
    end = text.index("(modul).FStarC_Syntax_Syntax.declarations) in", start)
    text = text[:end] + text[end:].replace(
        "(modul).FStarC_Syntax_Syntax.declarations) in",
        "(modul).FStarC_Syntax_Syntax.declarations)) in", 1
    )
    if sharing.exists():
        text = replace_once(
            text,
            "let index = (FStarC_SMTEncoding_Pruning.summarize_elts decls1) in",
            'let index = (sharing_phase "summarize_elts" '
            "(fun () -> FStarC_SMTEncoding_Pruning.summarize_elts decls1)) in"
        )
        text = replace_once(
            text,
            "(if give_to_z3 then (give_index_to_z3_and_set_env env2 name index1 "
            "(fun tmp6 -> decls1)) else ());",
            '(if give_to_z3 then (sharing_phase "give_index_to_z3" '
            "(fun () -> give_index_to_z3_and_set_env env2 name index1 "
            "(fun tmp6 -> decls1))) else ());"
        )
    else:
        text = replace_once(
            text,
            "let index = (FStarC_SMTEncoding_Pruning.summarize_elts decls) in",
            'let index = (sharing_phase "summarize_elts" '
            "(fun () -> FStarC_SMTEncoding_Pruning.summarize_elts decls)) in"
        )
        text = replace_once(
            text,
            "(if give_to_z3 then (give_index_to_z3_and_set_env env2 name index "
            "(fun tmp6 -> decls)) else ());",
            '(if give_to_z3 then (sharing_phase "give_index_to_z3" '
            "(fun () -> give_index_to_z3_and_set_env env2 name index "
            "(fun tmp6 -> decls))) else ());"
        )
    encoding.write_text(text)

    checked = extracted / "FStarC_CheckedFiles.ml"
    text = checked.read_text()
    position = text.index("let store_module_to_cache ")
    text = text[:position] + PHASE_HELPER + text[position:]
    text = replace_once(
        text,
        "let checked_digest = (store_values_to_cache cache_file stage1 stage2 tmp8) in",
        'let checked_digest = (sharing_phase "store_values_to_cache" '
        "(fun () -> store_values_to_cache cache_file stage1 stage2 tmp8)) in"
    )
    checked.write_text(text)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("worktree", type=Path)
    parser.add_argument(
        "--sharing-only", action="store_true",
        help="Instrument only intern_decls/intern_index for broad profiles",
    )
    args = parser.parse_args()
    instrument(args.worktree.resolve(), args.sharing_only)


if __name__ == "__main__":
    main()
