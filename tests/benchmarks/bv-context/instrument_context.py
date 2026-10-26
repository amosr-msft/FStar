#!/usr/bin/env python3

import argparse
from pathlib import Path


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError(f"expected one occurrence of {old!r}")
    return text.replace(old, new, 1)


SAMPLE = r'''
let context_trace_enabled () =
  match Sys.getenv_opt "FSTAR_CONTEXT_TRACE" with
  | None -> false
  | Some _ -> true

let context_sample n =
  n <= 8 || n land (n - 1) = 0 || n mod 256 = 0
'''


PRUNING = r'''
let context_map_size map =
  FStarC_PSMap.fold map (fun _ _ n -> n + 1) 0

let context_trigger_edges map =
  FStarC_PSMap.fold map (fun _ assumptions n ->
    n + List.length assumptions) 0

let context_add_count = ref 0
let context_prune_count = ref 0

let context_print_state event n elapsed_ms input_count output_count p =
  Printf.eprintf
    "CONTEXT_%s,%d,%.3f,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d\n%!"
    event n elapsed_ms input_count output_count
    (context_map_size p.defs_and_decls_map)
    (context_map_size p.macro_freenames)
    (context_map_size p.trigger_to_assumption)
    (context_trigger_edges p.trigger_to_assumption)
    (context_map_size p.assumption_to_triggers)
    (context_map_size p.assumption_name_map)
    (List.length p.ambients)
    (List.length p.extra_roots)
    (List.length p.pruned_ambients)

let add_decls ds p =
  let started = Unix.gettimeofday () in
  let result = add_decls_impl ds p in
  incr context_add_count;
  (if context_trace_enabled () && context_sample !context_add_count then
    context_print_state "ADD" !context_add_count
      (1000. *. (Unix.gettimeofday () -. started))
      (List.length ds) 0 result);
  result

let prune p roots =
  let started = Unix.gettimeofday () in
  let result = prune_impl p roots in
  incr context_prune_count;
  (if context_trace_enabled () && context_sample !context_prune_count then
    context_print_state "PRUNE" !context_prune_count
      (1000. *. (Unix.gettimeofday () -. started))
      (List.length roots) (List.length result) p);
  result
'''


TC_WRAPPER = r'''
let context_tc_count = ref 0

let tc_decls__process_one_decl input se =
  let _, env = input in
  let gamma_cache_before =
    FStarC_HashTable.FStarC_HashTable_hashtbl_make__0.length
      env.FStarC_TypeChecker_Env.gamma_cache in
  let started = Unix.gettimeofday () in
  let result = tc_decls__process_one_decl_impl input se in
  incr context_tc_count;
  (if context_trace_enabled () && context_sample !context_tc_count then
    let (_, env_after), _ = result in
    Printf.eprintf "CONTEXT_TC,%d,%.3f,%d,%d,%d,%d\n%!"
      !context_tc_count
      (1000. *. (Unix.gettimeofday () -. started))
      (List.length env.FStarC_TypeChecker_Env.gamma_sig)
      (List.length env_after.FStarC_TypeChecker_Env.gamma_sig)
      gamma_cache_before
      (FStarC_HashTable.FStarC_HashTable_hashtbl_make__0.length
        env_after.FStarC_TypeChecker_Env.gamma_cache));
  result

'''


Z3_WRAPPER = r'''
let context_ask_count = ref 0

let ask r qry queryid fresh =
  let started = Unix.gettimeofday () in
  let result = ask_impl r qry queryid fresh in
  incr context_ask_count;
  (if context_trace_enabled () && context_sample !context_ask_count then
    let z3_ms =
      List.fold_left (fun total item ->
        max total (Z.to_int item.z3result_time)) 0 result in
    Printf.eprintf "CONTEXT_ASK,%d,%.3f,%d,%d\n%!"
      !context_ask_count
      (1000. *. (Unix.gettimeofday () -. started))
      z3_ms (List.length qry));
  result

'''


SOLVER_WRAPPER = r'''
let context_solve_count = ref 0

let encode_and_ask use_env_msg tcenv q =
  let started = Unix.gettimeofday () in
  let result = encode_and_ask_impl use_env_msg tcenv q in
  incr context_solve_count;
  (if context_trace_enabled () && context_sample !context_solve_count then
    Printf.eprintf "CONTEXT_SOLVE,%d,%.3f\n%!"
      !context_solve_count
      (1000. *. (Unix.gettimeofday () -. started)));
  result

'''

FLUSH_WRAPPER = r'''
let context_flush_count = ref 0

let prune_level roots hd s =
  let started = Unix.gettimeofday () in
  let result = prune_level_impl roots hd s in
  incr context_flush_count;
  (if context_trace_enabled () && context_sample !context_flush_count then
    let newly_flushed =
      match result.to_flush_rev with
      | declarations :: _ -> List.length declarations
      | [] -> 0 in
    Printf.eprintf "CONTEXT_FLUSH,%d,%.3f,%d,%d,%d\n%!"
      !context_flush_count
      (1000. *. (Unix.gettimeofday () -. started))
      (List.length roots) newly_flushed
      (FStarC_PSMap.fold result.given_decl_names
        (fun _ _ count -> count + 1) 0));
  result

'''


ENCODE_WRAPPER = r'''
let context_encode_count = ref 0

let encode_sig tcenv se =
  let started = Unix.gettimeofday () in
  let result = encode_sig_impl tcenv se in
  incr context_encode_count;
  (if context_trace_enabled () && context_sample !context_encode_count then
    Printf.eprintf "CONTEXT_ENCODE,%d,%.3f\n%!"
      !context_encode_count
      (1000. *. (Unix.gettimeofday () -. started)));
  result
'''


def instrument(root):
    extracted = root / "stage2/fstarc.ml"

    pruning = extracted / "FStarC_SMTEncoding_Pruning.ml"
    text = pruning.read_text()
    text = replace_once(text, "let add_decls (ds :", "let add_decls_impl (ds :")
    text = replace_once(text, "let prune (p :", "let prune_impl (p :")
    pruning.write_text(text + SAMPLE + PRUNING)

    tc = extracted / "FStarC_TypeChecker_Tc.ml"
    text = tc.read_text()
    text = replace_once(
        text,
        "let tc_decls__process_one_decl (ses_env :",
        "let tc_decls__process_one_decl_impl (ses_env :",
    )
    marker = "let tc_decls (env :"
    position = text.index(marker)
    tc.write_text(text[:position] + SAMPLE + TC_WRAPPER + text[position:])

    z3 = extracted / "FStarC_SMTEncoding_Z3.ml"
    text = z3.read_text()
    text = replace_once(
        text,
        "let ask (r : FStarC_Range_Type.range)",
        "let ask_impl (r : FStarC_Range_Type.range)",
    )
    marker = "let ask_text "
    position = text.index(marker)
    z3.write_text(text[:position] + SAMPLE + Z3_WRAPPER + text[position:])

    solver = extracted / "FStarC_SMTEncoding_Solver.ml"
    text = solver.read_text()
    text = replace_once(
        text,
        "let encode_and_ask (use_env_msg :",
        "let encode_and_ask_impl (use_env_msg :",
    )
    marker = "let do_solve "
    position = text.index(marker)
    solver.write_text(text[:position] + SAMPLE + SOLVER_WRAPPER + text[position:])

    solver_state = extracted / "FStarC_SMTEncoding_SolverState.ml"
    text = solver_state.read_text()
    text = replace_once(
        text,
        "let prune_level (roots :",
        "let prune_level_impl (roots :",
    )
    marker = "let rec flush__aux "
    if text.count(marker) != 1:
        raise RuntimeError(f"expected one occurrence of {marker!r}")
    position = text.index(marker)
    solver_state.write_text(
        text[:position] + SAMPLE + FLUSH_WRAPPER + text[position:]
    )

    encoding = extracted / "FStarC_SMTEncoding_Encode.ml"
    text = encoding.read_text()
    text = replace_once(
        text, "let encode_sig (tcenv :", "let encode_sig_impl (tcenv :"
    )
    encoding.write_text(text + SAMPLE + ENCODE_WRAPPER)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("worktree", type=Path)
    args = parser.parse_args()
    instrument(args.worktree.resolve())


if __name__ == "__main__":
    main()
