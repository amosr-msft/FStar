module T = FStarC_SMTEncoding_Term
module P = FStarC_SMTEncoding_Pruning
module C = FStarC_CheckedFiles
module U = FStarC_Util

module TermTable = Hashtbl.Make (struct
  type t = T.term
  let equal = ( = )
  let hash = Hashtbl.hash
end)

module DeclTable = Hashtbl.Make (struct
  type t = T.decl
  let equal = ( = )
  let hash = Hashtbl.hash
end)

module EltTable = Hashtbl.Make (struct
  type t = T.decls_elt
  let equal = ( = )
  let hash = Hashtbl.hash
end)

module SummaryTable = Hashtbl.Make (struct
  type t = P.decl_summary
  let equal = ( = )
  let hash = Hashtbl.hash
end)

module EltSummaryTable = Hashtbl.Make (struct
  type t = P.elt_summary
  let equal = ( = )
  let hash = Hashtbl.hash
end)

type stats = {
  mutable term_seen: int;
  mutable term_hits: int;
  mutable decl_seen: int;
  mutable decl_hits: int;
  mutable elt_seen: int;
  mutable elt_hits: int;
  mutable summary_seen: int;
  mutable summary_hits: int;
  mutable elt_summary_seen: int;
  mutable elt_summary_hits: int;
}

let recover_sharing smt_index smt_decls =
  let terms = TermTable.create 100_003 in
  let decls = DeclTable.create 50_021 in
  let elts = EltTable.create 20_011 in
  let summaries = SummaryTable.create 10_007 in
  let elt_summaries = EltSummaryTable.create 10_007 in
  let stats = {
    term_seen = 0; term_hits = 0; decl_seen = 0; decl_hits = 0;
    elt_seen = 0; elt_hits = 0; summary_seen = 0; summary_hits = 0;
    elt_summary_seen = 0; elt_summary_hits = 0;
  } in
  let rec term value =
    let rebuilt =
      match value with
      | T.App (op, args, range) -> T.App (op, List.map term args, range)
      | T.Quant (op, patterns, weight, sorts, body, range) ->
          T.Quant (op, List.map (List.map term) patterns, weight, sorts, term body, range)
      | T.Let (values, body) -> T.Let (List.map term values, term body)
      | T.Labeled (body, label, range) -> T.Labeled (term body, label, range)
      | leaf -> leaf
    in
    stats.term_seen <- stats.term_seen + 1;
    match TermTable.find_opt terms rebuilt with
    | Some existing -> stats.term_hits <- stats.term_hits + 1; existing
    | None -> TermTable.add terms rebuilt rebuilt; rebuilt
  and decl value =
    let rebuilt =
      match value with
      | T.DefineFun (name, args, result, body, caption) ->
          T.DefineFun (name, args, result, term body, caption)
      | T.Assume assumption ->
          T.Assume { assumption with T.assumption_term = term assumption.T.assumption_term }
      | T.Module (name, declarations) -> T.Module (name, List.map decl declarations)
      | T.Eval value -> T.Eval (term value)
      | other -> other
    in
    stats.decl_seen <- stats.decl_seen + 1;
    match DeclTable.find_opt decls rebuilt with
    | Some existing -> stats.decl_hits <- stats.decl_hits + 1; existing
    | None -> DeclTable.add decls rebuilt rebuilt; rebuilt
  and elt value =
    let rebuilt = { value with T.decls = List.map decl value.T.decls } in
    stats.elt_seen <- stats.elt_seen + 1;
    match EltTable.find_opt elts rebuilt with
    | Some existing -> stats.elt_hits <- stats.elt_hits + 1; existing
    | None -> EltTable.add elts rebuilt rebuilt; rebuilt
  in
  let summary value =
    let rebuilt =
      match value with
      | P.Sum_other declaration -> P.Sum_other (decl declaration)
      | other -> other
    in
    stats.summary_seen <- stats.summary_seen + 1;
    match SummaryTable.find_opt summaries rebuilt with
    | Some existing -> stats.summary_hits <- stats.summary_hits + 1; existing
    | None -> SummaryTable.add summaries rebuilt rebuilt; rebuilt
  in
  let elt_summary value =
    let rebuilt = { value with P.elts_sums = List.map summary value.P.elts_sums } in
    stats.elt_summary_seen <- stats.elt_summary_seen + 1;
    match EltSummaryTable.find_opt elt_summaries rebuilt with
    | Some existing -> stats.elt_summary_hits <- stats.elt_summary_hits + 1; existing
    | None -> EltSummaryTable.add elt_summaries rebuilt rebuilt; rebuilt
  in
  List.map elt_summary smt_index, List.map elt smt_decls, stats

let load path =
  let header :
    (string * C.checked_file_entry_stage1 * C.checked_file_entry_stage2) option =
    U.load_2values_from_file3 path
  in
  let declarations : T.decls_elt list option = U.load_3rd_value_from_file3 path in
  match header, declarations with
  | Some (digest, stage1, stage2), Some declarations -> digest, stage1, stage2, declarations
  | _ -> failwith ("cannot load " ^ path)

let verify_equal name expected actual =
  if expected <> actual then failwith (name ^ " changed structurally")

let canonical_path path =
  if Sys.file_exists path then Unix.realpath path
  else Filename.concat (Unix.realpath (Filename.dirname path)) (Filename.basename path)

let same_file input output =
  canonical_path input = canonical_path output ||
  (Sys.file_exists output &&
   let input_stat = Unix.stat input in
   let output_stat = Unix.stat output in
   input_stat.Unix.st_dev = output_stat.Unix.st_dev &&
   input_stat.Unix.st_ino = output_stat.Unix.st_ino)

let run input output =
  if same_file input output then
    failwith "input and output paths must differ";
  let started = Unix.gettimeofday () in
  let original_digest, stage1, stage2, declarations = load input in
  let loaded = Unix.gettimeofday () in
  let stored = stage2.C.tc_res in
  let index, declarations', stats =
    recover_sharing stored.C.stored_smt_index declarations
  in
  verify_equal "SMT index" stored.C.stored_smt_index index;
  verify_equal "SMT declarations" declarations declarations';
  let stored' = { stored with C.stored_smt_index = index } in
  let stage2' = { stage2 with C.tc_res = stored' } in
  let recovered = Unix.gettimeofday () in
  ignore (U.save_3values_to_file output stage1 stage2' declarations');
  let saved = Unix.gettimeofday () in
  let shared_digest, stage1'', stage2'', declarations'' = load output in
  verify_equal "round-trip stage 1" stage1 stage1'';
  verify_equal "round-trip stage 2" stage2 stage2'';
  verify_equal "round-trip declarations" declarations declarations'';
  let verified = Unix.gettimeofday () in
  Printf.printf
    "input=%s output=%s input_bytes=%d output_bytes=%d load_s=%.3f recover_s=%.3f save_s=%.3f verify_s=%.3f\n"
    input output (Unix.stat input).Unix.st_size (Unix.stat output).Unix.st_size
    (loaded -. started) (recovered -. loaded) (saved -. recovered) (verified -. saved);
  Printf.printf "input_digest=%s output_digest=%s\n" original_digest shared_digest;
  Printf.printf
    "terms=%d term_hits=%d decls=%d decl_hits=%d elts=%d elt_hits=%d summaries=%d summary_hits=%d elt_summaries=%d elt_summary_hits=%d\n"
    stats.term_seen stats.term_hits stats.decl_seen stats.decl_hits
    stats.elt_seen stats.elt_hits stats.summary_seen stats.summary_hits
    stats.elt_summary_seen stats.elt_summary_hits

let load_only input =
  let started = Unix.gettimeofday () in
  let _, _, stage2, declarations = load input in
  let elapsed = Unix.gettimeofday () -. started in
  Printf.printf "input=%s load_s=%.3f index_entries=%d declaration_blocks=%d\n"
    input elapsed
    (List.length stage2.C.tc_res.C.stored_smt_index)
    (List.length declarations)

let persistence_profile input output =
  if same_file input output then
    failwith "input and output paths must differ";
  let _, stage1, stage2, declarations = load input in
  let started = Unix.gettimeofday () in
  let stage12 =
    Marshal.to_string stage1 [] ^ Marshal.to_string stage2 [] in
  let metadata_serialized = Unix.gettimeofday () in
  let stage3 = Marshal.to_string declarations [] in
  let smt_serialized = Unix.gettimeofday () in
  let digest =
    BatDigest.to_hex
      (BatDigest.string
        (BatDigest.string stage12 ^ BatDigest.string stage3)) in
  let hashed = Unix.gettimeofday () in
  let temporary =
    output ^ ".tmp." ^ string_of_int (Unix.getpid ()) in
  let channel =
    open_out_gen
      [Open_wronly; Open_creat; Open_excl; Open_binary]
      0o600 temporary in
  (try
     Marshal.to_channel channel digest [];
     output_binary_int channel (String.length stage12);
     output_string channel stage12;
     output_string channel stage3;
     close_out channel;
     Unix.rename temporary output
   with error ->
     close_out_noerr channel;
     (try Sys.remove temporary with _ -> ());
     raise error);
  let written = Unix.gettimeofday () in
  let _, stage1', stage2', declarations' = load output in
  verify_equal "profiled stage 1" stage1 stage1';
  verify_equal "profiled stage 2" stage2 stage2';
  verify_equal "profiled declarations" declarations declarations';
  Printf.printf
    "input=%s bytes=%d stage12_bytes=%d stage3_bytes=%d metadata_serialize_s=%.6f smt_serialize_s=%.6f hash_s=%.6f buffered_write_s=%.6f\n"
    input (Unix.stat input).Unix.st_size
    (String.length stage12) (String.length stage3)
    (metadata_serialized -. started)
    (smt_serialized -. metadata_serialized)
    (hashed -. smt_serialized)
    (written -. hashed)

let () =
  match Array.to_list Sys.argv with
  | [_; "--load"; input] -> load_only input
  | [_; "--persistence-profile"; input; output] ->
      persistence_profile input output
  | [_; input; output] -> run input output
  | _ ->
      failwith
        "usage: sharing_experiment INPUT.checked OUTPUT.checked | \
         --load INPUT.checked | \
         --persistence-profile INPUT.checked OUTPUT.checked"
