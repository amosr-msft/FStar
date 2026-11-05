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
  let stat = Gc.stat () in
  Printf.printf
    "%s live_words=%d heap_words=%d free_words=%d top_heap_words=%d rss_kb=%d\n%!"
    label stat.Gc.live_words stat.Gc.heap_words stat.Gc.free_words
    stat.Gc.top_heap_words (rss_kb ())

let cache_stats () =
  H.fold (fun key value (entries, key_chars, value_chars, negative) ->
    match value with
    | None ->
      entries + 1, key_chars + String.length key, value_chars, negative + 1
    | Some relative ->
      entries + 1, key_chars + String.length key,
      value_chars + String.length relative, negative
  ) FStarC_Find.relative_source_path_cache (0, 0, 0, 0)

let () =
  let root = Sys.argv.(1) in
  let files =
    Array.to_list (Array.sub Sys.argv 2 (Array.length Sys.argv - 2))
    |> List.map (Filename.concat root)
  in
  FStarC_Find.set_no_default_includes true;
  FStarC_Find.set_file_list files;
  Gc.full_major ();
  snapshot "inputs";
  List.iter (fun file ->
    ignore (FStarC_Find.relative_source_path file)
  ) files;
  let entries, key_chars, value_chars, negative = cache_stats () in
  Printf.printf
    "cache entries=%d key_chars=%d value_chars=%d negative=%d\n%!"
    entries key_chars value_chars negative;
  Gc.full_major ();
  snapshot "populated";
  FStarC_Find.clear ();
  let entries, key_chars, value_chars, negative = cache_stats () in
  Printf.printf
    "cleared_cache entries=%d key_chars=%d value_chars=%d negative=%d\n%!"
    entries key_chars value_chars negative;
  Gc.full_major ();
  snapshot "cleared";
  ignore files
