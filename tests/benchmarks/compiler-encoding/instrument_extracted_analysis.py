#!/usr/bin/env python3

import argparse
from pathlib import Path


PHASE_HELPER = r'''
let heap_analysis_enabled () =
  match Sys.getenv_opt "FSTAR_HEAP_ANALYSIS" with
  | None -> false
  | Some _ -> true

let heap_force_gc () =
  match Sys.getenv_opt "FSTAR_HEAP_FORCE_GC" with
  | None -> ()
  | Some _ -> Gc.full_major ()

let heap_snapshot name =
  if heap_analysis_enabled () then
    let stat =
      match Sys.getenv_opt "FSTAR_HEAP_FORCE_GC" with
      | None -> Gc.quick_stat ()
      | Some _ -> Gc.stat ()
    in
    Printf.eprintf
      "HEAP_SNAPSHOT,%s,%.0f,%.0f,%.0f,%d,%d,%d,%d,%d,%d,%d,%d,%d\n%!"
      name stat.Gc.minor_words stat.Gc.promoted_words stat.Gc.major_words
      stat.Gc.minor_collections stat.Gc.major_collections
      stat.Gc.heap_words stat.Gc.top_heap_words stat.Gc.live_words
      stat.Gc.live_blocks stat.Gc.free_words stat.Gc.fragments
      stat.Gc.compactions

let heap_boundary name =
  heap_force_gc ();
  heap_snapshot name

let sharing_phase name f =
  match Sys.getenv_opt "FSTAR_SHARING_ANALYSIS" with
  | None -> f ()
  | Some _ ->
      heap_boundary (name ^ ".before");
      let wall0 = Unix.gettimeofday () in
      let cpu0 = Sys.time () in
      let result = f () in
      let cpu_ms = 1000. *. (Sys.time () -. cpu0) in
      let wall_ms = 1000. *. (Unix.gettimeofday () -. wall0) in
      heap_boundary (name ^ ".after");
      Printf.eprintf "SHARING_PHASE,%s,%.3f,%.3f\n%!" name
        wall_ms cpu_ms;
      result

'''

EXIT_SNAPSHOT = r'''
let () =
  if heap_analysis_enabled () then
    let control = Gc.get () in
    Printf.eprintf
      "HEAP_CONTROL,%d,%d,%d,%d,%d,%d,%d\n%!"
      control.Gc.minor_heap_size control.Gc.major_heap_increment
      control.Gc.space_overhead control.Gc.verbose control.Gc.max_overhead
      control.Gc.stack_limit control.Gc.allocation_policy;
  at_exit (fun () -> heap_boundary "process.exit")

'''

SHARING_WRAPPER = r'''

let sharing_heap_analysis_enabled () =
  match Sys.getenv_opt "FSTAR_HEAP_ANALYSIS" with
  | None -> false
  | Some _ -> true

let sharing_heap_force_gc () =
  match Sys.getenv_opt "FSTAR_HEAP_FORCE_GC" with
  | None -> ()
  | Some _ -> Gc.full_major ()

let sharing_heap_snapshot name =
  if sharing_heap_analysis_enabled () then
    let stat =
      match Sys.getenv_opt "FSTAR_HEAP_FORCE_GC" with
      | None -> Gc.quick_stat ()
      | Some _ -> Gc.stat ()
    in
    Printf.eprintf
      "HEAP_SNAPSHOT,%s,%.0f,%.0f,%.0f,%d,%d,%d,%d,%d,%d,%d,%d,%d\n%!"
      name stat.Gc.minor_words stat.Gc.promoted_words stat.Gc.major_words
      stat.Gc.minor_collections stat.Gc.major_collections
      stat.Gc.heap_words stat.Gc.top_heap_words stat.Gc.live_words
      stat.Gc.live_blocks stat.Gc.free_words stat.Gc.fragments
      stat.Gc.compactions

let sharing_reachable phase input output =
  match Sys.getenv_opt "FSTAR_HEAP_REACHABLE" with
  | None -> ()
  | Some _ ->
      let input_words = Obj.reachable_words (Obj.repr input) in
      let output_words = Obj.reachable_words (Obj.repr output) in
      let union_words = Obj.reachable_words (Obj.repr (input, output)) in
      Printf.eprintf "HEAP_REACHABLE,%s,%d,%d,%d,%d\n%!"
        phase input_words output_words union_words
        (input_words + output_words - union_words)

let sharing_analysis phase f x =
  match Sys.getenv_opt "FSTAR_SHARING_ANALYSIS" with
  | None -> f x
  | Some _ ->
      sharing_heap_force_gc ();
      sharing_heap_snapshot (phase ^ ".before");
      let before = Gc.quick_stat () in
      let allocated0 = Gc.allocated_bytes () in
      let wall0 = Unix.gettimeofday () in
      let cpu0 = Sys.time () in
      let output = f x in
      let cpu_ms = 1000. *. (Sys.time () -. cpu0) in
      let wall_ms = 1000. *. (Unix.gettimeofday () -. wall0) in
      sharing_reachable phase x output;
      sharing_heap_force_gc ();
      sharing_heap_snapshot (phase ^ ".after");
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

FILE_HEAP_HELPER = r'''let file_heap_snapshot phase fn =
    match Sys.getenv_opt "FSTAR_HEAP_ANALYSIS" with
    | None -> ()
    | Some _ ->
        let basename = Filename.basename fn in
        (match Sys.getenv_opt "FSTAR_HEAP_FORCE_AFTER_BENCH_CACHE" with
         | Some _ when phase = "cache.after" &&
             (basename = "BenchUIntChildren.fst" ||
              basename = "BenchBvChildren.fst") -> Gc.full_major ()
         | _ -> ());
        let stat = Gc.quick_stat () in
        Printf.eprintf "HEAP_FILE,%s,%s,%d,%d,%d,%d\n%!"
          phase basename stat.Gc.heap_words
          stat.Gc.top_heap_words stat.Gc.major_collections
          stat.Gc.minor_collections in
  '''

DECL_HEAP_HELPER = r'''
let decl_heap_snapshot phase declaration =
  match Sys.getenv_opt "FSTAR_HEAP_ANALYSIS" with
  | None -> ()
  | Some _ ->
      let stat = Gc.quick_stat () in
      Printf.eprintf "HEAP_DECL,%s,%s,%d,%d,%d,%d\n%!"
        phase declaration stat.Gc.heap_words stat.Gc.top_heap_words
        stat.Gc.major_collections stat.Gc.minor_collections

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
        has_index_interner = "let intern_index (index :" in text
        if has_index_interner:
            text = replace_once(
                text, "let intern_index (index :",
                "let intern_index_impl (index :"
            )
        wrapper = SHARING_WRAPPER
        if not has_index_interner:
            wrapper = wrapper.replace(
                '\nlet intern_index x = sharing_analysis "index" intern_index_impl x',
                "",
            )
        sharing.write_text(text + wrapper)
    if sharing_only:
        return

    encoding = extracted / "FStarC_SMTEncoding_Encode.ml"
    text = encoding.read_text()
    position = text.index("let encode_modul_aux ")
    text = text[:position] + PHASE_HELPER + text[position:]
    text = text[:position + len(PHASE_HELPER)] + EXIT_SNAPSHOT + text[position + len(PHASE_HELPER):]
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
    if sharing.exists() and "let index1 =" in text:
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
        decls_name = "decls1" if sharing.exists() else "decls"
        text = replace_once(
            text,
            f"let index = (FStarC_SMTEncoding_Pruning.summarize_elts {decls_name}) in",
            'let index = (sharing_phase "summarize_elts" '
            f"(fun () -> FStarC_SMTEncoding_Pruning.summarize_elts {decls_name})) in"
        )
        text = replace_once(
            text,
            "(if give_to_z3 then (give_index_to_z3_and_set_env env2 name index "
            f"(fun tmp6 -> {decls_name})) else ());",
            '(if give_to_z3 then (sharing_phase "give_index_to_z3" '
            "(fun () -> give_index_to_z3_and_set_env env2 name index "
            f"(fun tmp6 -> {decls_name}))) else ());"
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

    universal = extracted / "FStarC_Universal.ml"
    text = universal.read_text()
    text = replace_once(
        text,
        "  let tc_source_file = (fun tmp1 ->",
        "  " + FILE_HEAP_HELPER + "let tc_source_file = (fun tmp1 ->"
    )
    text = replace_once(
        text,
        "(FStarC_Profiling.profile (fun tmp4 -> (parse fly_deps env fn)) "
        'tmp3 "FStarC.Universal.tc_source_file.parse")',
        "(FStarC_Profiling.profile (fun tmp4 -> "
        '(file_heap_snapshot "parse.before" fn; '
        "let result = (parse fly_deps env fn) in "
        'file_heap_snapshot "parse.after" fn; result)) '
        'tmp3 "FStarC.Universal.tc_source_file.parse")'
    )
    text = replace_once(
        text,
        "(FStarC_Profiling.profile (fun tmp6 -> (check env1)) "
        '(Some ((FStarC_Ident.string_of_lid mname))) '
        '"FStarC.Universal.tc_source_file.check")',
        "(FStarC_Profiling.profile (fun tmp6 -> "
        '(file_heap_snapshot "check.before" fn; '
        "let result = (check env1) in "
        'file_heap_snapshot "check.after" fn; result)) '
        "(Some ((FStarC_Ident.string_of_lid mname))) "
        '"FStarC.Universal.tc_source_file.check")'
    )
    text = replace_once(
        text,
        "let r = (if tmp3 then None else "
        "(FStarC_CheckedFiles.load_module_from_cache env fn)) in",
        "let r = (if tmp3 then None else "
        '(file_heap_snapshot "cache.before" fn; '
        "let result = (FStarC_CheckedFiles.load_module_from_cache env fn) in "
        'file_heap_snapshot "cache.after" fn; result)) in'
    )
    universal.write_text(text)

    typechecker = extracted / "FStarC_TypeChecker_Tc.ml"
    text = typechecker.read_text()
    position = text.index("let tc_decls__process_one_decl ")
    text = text[:position] + DECL_HEAP_HELPER + text[position:]
    text = replace_once(
        text,
        "let tmp8 = (FStarC_Errors.with_ctx tmp7 "
        "(fun tmp8 -> (tc_decl env1 se))) in",
        'let tmp8 = (decl_heap_snapshot "tc_decl.before" tmp6; '
        "let result = (FStarC_Errors.with_ctx tmp7 "
        "(fun tmp8 -> (tc_decl env1 se))) in "
        'decl_heap_snapshot "tc_decl.after" tmp6; result) in'
    )
    text = replace_once(
        text,
        '(FStarC_Profiling.profile (fun tmp12 -> (BatList.iter '
        "(fun se1 -> (((env3).FStarC_TypeChecker_Env.solver)."
        "FStarC_TypeChecker_Env.encode_sig env3 se1)) ses'3)) "
        "(Some ((FStarC_Ident.string_of_lid "
        "(FStarC_TypeChecker_Env.current_module env3)))) "
        '"FStarC.TypeChecker.Tc.encode_sig");',
        '(decl_heap_snapshot "encode_sig.before" tmp6; '
        "(FStarC_Profiling.profile (fun tmp12 -> (BatList.iter "
        "(fun se1 -> (((env3).FStarC_TypeChecker_Env.solver)."
        "FStarC_TypeChecker_Env.encode_sig env3 se1)) ses'3)) "
        "(Some ((FStarC_Ident.string_of_lid "
        "(FStarC_TypeChecker_Env.current_module env3)))) "
        '"FStarC.TypeChecker.Tc.encode_sig"); '
        'decl_heap_snapshot "encode_sig.after" tmp6);'
    )
    typechecker.write_text(text)


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
