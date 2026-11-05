let root_counts = [1; 16; 64; 256]

let roots fixture count =
  List.init (count - 1) (fun i ->
    Filename.concat fixture (Printf.sprintf "unused-%04d" i))
  @ [Filename.concat fixture "owned"]

let time f =
  let started = Sys.time () in
  let value = f () in
  Sys.time () -. started, value

let is_module expected filename =
  FStarC_Parser_Dep.maybe_module_name_of_file filename = Some expected

let run fixture count =
  let include_paths = roots fixture count in
  let owned = Filename.concat fixture "owned" in
  let repeated = Filename.concat owned "A/B/C.fst" in
  FStarC_Find.set_no_default_includes true;
  FStarC_Find.set_file_list [];
  FStarC_Find.set_include_path include_paths;
  let distinct_seconds, distinct_matches =
    time (fun () ->
      let matches = ref 0 in
      for i = 1 to 5_000 do
        let filename =
          Filename.concat owned (Printf.sprintf "A/B/C%06d.fst" i)
        in
        let expected = Printf.sprintf "A.B.C%06d" i in
        if is_module expected filename
        then incr matches
      done;
      !matches)
  in
  let repeated_seconds, repeated_matches =
    time (fun () ->
      let matches = ref 0 in
      for _ = 1 to 20_000 do
        if is_module "A.B.C" repeated
        then incr matches
      done;
      !matches)
  in
  let cold_seconds, cold_matches =
    time (fun () ->
      let matches = ref 0 in
      for i = 1 to 500 do
        FStarC_Find.set_include_path include_paths;
        let filename =
          Filename.concat owned (Printf.sprintf "Cold/C%06d.fst" i)
        in
        let expected = Printf.sprintf "Cold.C%06d" i in
        if is_module expected filename
        then incr matches
      done;
      !matches)
  in
  Printf.printf "%d %.9f %d %.9f %d %.9f %d\n%!"
    count
    distinct_seconds distinct_matches
    repeated_seconds repeated_matches
    cold_seconds cold_matches

let () =
  let fixture = Sys.argv.(1) in
  run fixture (int_of_string Sys.argv.(2))
