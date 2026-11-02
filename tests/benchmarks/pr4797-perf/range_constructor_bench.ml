let iterations = 10_000_000

let () =
  let filename = "/workspace/source/A/B/C.fst" in
  let started = Sys.time () in
  for _ = 1 to iterations do
    ignore (
      FStarC_Range_Type.mk_rng filename Prims.int_zero Prims.int_one
    )
  done;
  Printf.printf "mk_rng %.6f\n%!" (Sys.time () -. started)
