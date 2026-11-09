let kind = function
  | FStarC_Find.Flat -> "Flat"
  | FStarC_Find.Recursive -> "Recursive"

let () =
  let files = Array.to_list Sys.argv |> List.tl in
  List.iter (fun file ->
    let path = FStarC_Filepath.normalize_file_path file in
    Printf.printf "FILE\t%s\t%d\t%d\n"
      path (String.length path) (Hashtbl.hash path)) files;
  FStarC_Find.set_file_list files;
  FStarC_Find.module_include_paths_normalized ()
  |> List.iter (fun root ->
    Printf.printf "ROOT-%s\t%s\t%d\t%d\n"
      (kind root.FStarC_Find.kind)
      root.FStarC_Find.dir
      (String.length root.FStarC_Find.dir)
      (Hashtbl.hash root.FStarC_Find.dir))
