let show = function
  | None -> "NONE"
  | Some path -> path

let path root suffix = Filename.concat root suffix

let () =
  let fixture = Sys.argv.(1) in
  let scenario = Sys.argv.(2) in
  let outer = path fixture "outer" in
  let nested = path outer "flat" in
  let deep = path nested "nested" in
  let sibling = path fixture "sibling" in
  FStarC_Find.set_no_default_includes true;
  FStarC_Find.set_file_list [];
  FStarC_Find.set_include_path [];
  if scenario = "rebuild" then (
    FStarC_Find.set_include_path [outer];
    let first =
      FStarC_Find.relative_source_path (path outer "A/B.fst")
    in
    FStarC_Find.set_include_path [sibling];
    let second =
      FStarC_Find.relative_source_path (path sibling "C/D.fst")
    in
    FStarC_Find.set_include_path [outer];
    let third =
      FStarC_Find.relative_source_path (path outer "E/F.fst")
    in
    Printf.printf "%s|%s|%s\n"
      (show first) (show second) (show third)
  ) else (
    let target =
      match scenario with
      | "recursive-outer" ->
        FStarC_Find.set_include_path [outer];
        path outer "A/B.fst"
      | "nested-outer-first" ->
        FStarC_Find.set_include_path [outer; deep];
        path deep "A.fst"
      | "nested-inner-first" ->
        FStarC_Find.set_include_path [deep; outer];
        path deep "A.fst"
      | "sibling" ->
        FStarC_Find.set_include_path [outer; sibling];
        path sibling "A/B.fst"
      | "boundary" ->
        FStarC_Find.set_include_path [outer];
        path (outer ^ "-suffix") "A.fst"
      | "flat-immediate" ->
        FStarC_Find.set_include_path [outer; nested];
        path nested "A.fst"
      | "flat-outer-fallback" ->
        FStarC_Find.set_include_path [outer; nested];
        path nested "deeper/A.fst"
      | "nested-flat-outer-fallback" ->
        FStarC_Find.set_include_path [outer; nested; deep];
        path deep "deeper/A.fst"
      | "duplicate-flat-recursive" ->
        FStarC_Find.set_cache_dir outer;
        FStarC_Find.set_include_path [outer; outer];
        path outer "A/B.fst"
      | "duplicate-recursive-flat" ->
        FStarC_Find.set_include_path [fixture];
        path fixture "A/B.fst"
      | "duplicate-recursive" ->
        FStarC_Find.set_include_path [outer; outer];
        path outer "A/B.fst"
      | "filesystem-root" ->
        FStarC_Find.set_include_path [Filename.dir_sep];
        path Filename.dir_sep "A/B.fst"
      | "unix-backslash" ->
        let backslash = path fixture "back\\slash" in
        FStarC_Find.set_include_path [backslash];
        path backslash "A/B.fst"
      | _ -> failwith ("unknown scenario: " ^ scenario)
    in
    print_endline (show (FStarC_Find.relative_source_path target))
  )
