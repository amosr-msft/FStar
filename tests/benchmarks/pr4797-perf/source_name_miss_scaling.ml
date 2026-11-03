let iterations = 5_000

let run root roots =
  let extras =
    List.init (roots - 1) (fun i ->
      Filename.concat root (Printf.sprintf "unused-%04d" i))
  in
  FStarC_Find.set_no_default_includes true;
  FStarC_Find.set_file_list [];
  FStarC_Find.set_include_path (extras @ [root]);
  let started = Sys.time () in
  for i = 1 to iterations do
    let source =
      Filename.concat root (Printf.sprintf "A/B/C%06d.fst" i)
    in
    ignore (FStarC_Find.source_file_name source)
  done;
  Printf.printf "%d %.9f\n%!" roots (Sys.time () -. started)

let () =
  let root = Sys.argv.(1) in
  List.iter (run root) [1; 16; 64; 256]
