let () =
  let include_root = Sys.argv.(1) in
  let outside = Sys.argv.(2) in
  FStarC_Find.set_no_default_includes true;
  FStarC_Find.set_file_list [];
  FStarC_Find.set_include_path [include_root];
  List.iter (fun suffix ->
    let input = Filename.concat outside suffix in
    Printf.printf "%s=%s\n%!" suffix
      (FStarC_Find.source_file_name input)
  ) ["."; ".."; "missing.fst"]
