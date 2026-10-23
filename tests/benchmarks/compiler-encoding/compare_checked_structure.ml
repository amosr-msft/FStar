let load path =
  let channel = open_in_bin path in
  let _digest : string = input_value channel in
  let _length = input_binary_int channel in
  let stage1 : Obj.t = input_value channel in
  let stage2 : Obj.t = input_value channel in
  let declarations : Obj.t = input_value channel in
  close_in channel;
  stage1, stage2, declarations

let () =
  if Array.length Sys.argv <> 3 then
    failwith "usage: compare_checked_structure LEFT.checked RIGHT.checked";
  let left1, left2, left3 = load Sys.argv.(1) in
  let right1, right2, right3 = load Sys.argv.(2) in
  if left1 <> right1 then failwith "stage 1 differs";
  (* [checked_file_entry_stage2] is [deps_dig * tc_res]. Compiler-specific
     checked dependencies legitimately change [deps_dig]; compare [tc_res]. *)
  if Obj.field left2 1 <> Obj.field right2 1 then
    failwith "stage 2 typechecking result differs";
  if left3 <> right3 then failwith "SMT declarations differ";
  print_endline "stage1, tc_result/index, and declarations structurally equal"
