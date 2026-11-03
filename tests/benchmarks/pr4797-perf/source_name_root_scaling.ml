let iterations = 20_000

let run root source roots =
  let extras =
    List.init (roots - 1) (fun i ->
      Filename.concat root (Printf.sprintf "unused-%04d" i))
  in
  FStarC_Find.set_no_default_includes true;
  FStarC_Find.set_file_list [];
  FStarC_Find.set_include_path (extras @ [root]);
  ignore (FStarC_Find.source_file_name source);
  let started = Sys.time () in
  for _ = 1 to iterations do
    ignore (FStarC_Find.source_file_name source)
  done;
  Printf.printf "%d %.9f\n%!" roots (Sys.time () -. started)

let () =
  let root = Sys.argv.(1) in
  let source = Sys.argv.(2) in
  List.iter (run root source) [1; 16; 64; 256]
