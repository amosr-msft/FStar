module H = FStarC_HashTable.FStarC_HashTable_hashtbl_make__0

let rss_kb () =
  let input = open_in "/proc/self/status" in
  let rec loop () =
    match input_line input with
    | line ->
      if String.length line >= 6 && String.sub line 0 6 = "VmRSS:" then
        Scanf.sscanf line "VmRSS: %d kB" (fun value -> value)
      else loop ()
    | exception End_of_file -> 0
  in
  let result = loop () in
  close_in input;
  result

let snapshot label =
  Gc.full_major ();
  let stat = Gc.stat () in
  Printf.printf "%s live_words=%d heap_words=%d rss_kb=%d\n%!"
    label stat.Gc.live_words stat.Gc.heap_words (rss_kb ())

let option_stats table =
  H.fold (fun key value (entries, key_chars, value_chars) ->
    entries + 1, key_chars + String.length key,
    value_chars + (match value with None -> 0 | Some s -> String.length s)
  ) table (0, 0, 0)

let print_stats label (entries, key_chars, value_chars) =
  Printf.printf "%s entries=%d key_chars=%d value_chars=%d\n%!"
    label entries key_chars value_chars

let () =
  let root = Sys.argv.(1) in
  let files =
    Array.to_list (Array.sub Sys.argv 2 (Array.length Sys.argv - 2))
    |> List.map (Filename.concat root)
  in
  FStarC_Find.set_no_default_includes true;
  FStarC_Find.set_file_list files;
  snapshot "inputs";
  List.iter (fun file ->
    ignore (FStarC_Find.relative_source_path file)
  ) files;
  snapshot "ownership";
  List.iter (fun file ->
    ignore (FStarC_Find.source_file_name file)
  ) files;
  print_stats "find" (option_stats FStarC_Find.find_file_cache);
  print_stats "ownership_cache"
    (option_stats FStarC_Find.relative_source_path_cache);
  snapshot "source";
  FStarC_Find.clear ();
  snapshot "cleared";
  ignore files
