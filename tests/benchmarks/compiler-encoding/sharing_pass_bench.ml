module C = FStarC_CheckedFiles
module T = FStarC_SMTEncoding_Term
module P = FStarC_SMTEncoding_Pruning

type variant = {
  name: string;
  decls: T.decls_elt list -> T.decls_elt list;
  index: P.elt_summary list -> P.elt_summary list;
}

let variants = [|
  { name = "original"; decls = Sharing_original.intern_decls;
    index = Sharing_original.intern_index };
  { name = "fusion"; decls = Sharing_fusion.intern_decls;
    index = Sharing_fusion.intern_index };
  { name = "combined"; decls = Sharing_combined.intern_decls;
    index = Sharing_combined.intern_index };
|]

let load path =
  let header :
    (string * C.checked_file_entry_stage1 * C.checked_file_entry_stage2) option =
    FStarC_Util.load_2values_from_file3 path in
  let declarations : T.decls_elt list option =
    FStarC_Util.load_3rd_value_from_file3 path in
  match header, declarations with
  | Some (_, _, stage2), Some declarations ->
      stage2.C.tc_res.C.stored_smt_index, declarations
  | _ -> failwith ("cannot load " ^ path)

let delta before after field = field after -. field before

let measure variant phase f input =
  Gc.full_major ();
  let before = Gc.quick_stat () in
  let allocated0 = Gc.allocated_bytes () in
  let wall0 = Unix.gettimeofday () in
  let cpu0 = Sys.time () in
  let output = Sys.opaque_identity (f input) in
  let cpu_ms = 1000. *. (Sys.time () -. cpu0) in
  let wall_ms = 1000. *. (Unix.gettimeofday () -. wall0) in
  let after = Gc.quick_stat () in
  Printf.printf
    "%s,%s,%.3f,%.3f,%.0f,%.0f,%.0f,%d,%d,%d\n%!"
    variant.name phase wall_ms cpu_ms
    ((Gc.allocated_bytes () -. allocated0) /. float_of_int (Sys.word_size / 8))
    (delta before after (fun x -> x.Gc.promoted_words))
    (delta before after (fun x -> x.Gc.major_words))
    (after.Gc.minor_collections - before.Gc.minor_collections)
    (after.Gc.major_collections - before.Gc.major_collections)
    (Obj.reachable_words (Obj.repr output));
  output

let shuffle state values =
  let a = Array.copy values in
  for i = Array.length a - 1 downto 1 do
    let j = Random.State.int state (i + 1) in
    let x = a.(i) in
    a.(i) <- a.(j);
    a.(j) <- x
  done;
  a

let () =
  if Array.length Sys.argv <> 3 then
    failwith "usage: sharing_pass_bench FILE REPEATS";
  let index, declarations = load Sys.argv.(1) in
  let repeats = int_of_string Sys.argv.(2) in
  let expected_decls = variants.(0).decls declarations in
  let expected_index = variants.(0).index index in
  Array.iter (fun variant ->
    if variant.decls declarations <> expected_decls then
      failwith (variant.name ^ " decls differ");
    if variant.index index <> expected_index then
      failwith (variant.name ^ " index differs")) variants;
  Printf.printf
    "variant,phase,wall_ms,cpu_ms,allocated_words,promoted_words,major_words,\
minor_collections,major_collections,reachable_words\n%!";
  let state = Random.State.make [|4764|] in
  for _repeat = 1 to repeats do
    Array.iter
      (fun variant ->
        ignore (measure variant "decls" variant.decls declarations))
      (shuffle state variants);
    Array.iter
      (fun variant ->
        ignore (measure variant "index" variant.index index))
      (shuffle state variants)
  done
