let iterations = 1_000_000

let run label filename =
  let started = Sys.time () in
  for _ = 1 to iterations do
    ignore (FStarC_Find.source_file_name filename)
  done;
  Printf.printf "%s %.6f\n%!" label (Sys.time () -. started)

let () =
  let root = Sys.argv.(1) in
  let absolute = Filename.concat root "GeneratedSmoke.fst" in
  FStarC_Find.set_include_path [root];
  run "absolute" absolute;
  run "relative" "GeneratedSmoke.fst"
