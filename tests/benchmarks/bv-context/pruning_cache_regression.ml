module P = FStarC_SMTEncoding_Pruning
module T = FStarC_SMTEncoding_Term

let resolve name = Some (T.Caption name)

let assumption name free kind =
  P.Sum_assume {
    P.asum_name = name;
    P.asum_free_names = free;
    P.asum_pretyping = false;
    P.asum_kind = kind;
  }

let add summaries state =
  P.add_summaries summaries resolve state

let retained state =
  P.prune state []
  |> List.filter_map (function T.Caption name -> Some name | _ -> None)
  |> List.sort String.compare

let expect label expected actual =
  if expected <> actual then
    failwith (
      Printf.sprintf "%s: expected [%s], got [%s]"
        label (String.concat "; " expected) (String.concat "; " actual)
    )

let () =
  let edge =
    P.Sum_triggers [[]; ["a"; "b"]]
    |> assumption "edge_empty_alternative" []
  in
  let state =
    P.init
    |> add [assumption "root_a" ["a"] (P.Sum_ambient true)]
    |> add [edge]
  in
  let empty_alternative = retained state in
  expect "empty alternative" ["edge_empty_alternative"; "root_a"]
    empty_alternative;

  let conjunction =
    P.Sum_triggers [["a"; "b"]]
    |> assumption "edge_conjunction" []
  in
  let state =
    P.init
    |> add [assumption "root_a" ["a"] (P.Sum_ambient true)]
    |> add [conjunction]
  in
  let conjunction_before_b = retained state in
  expect "conjunction before b" ["root_a"] conjunction_before_b;
  let state =
    state
    |> add [assumption "root_b" ["b"] (P.Sum_ambient true)]
  in
  let conjunction_after_b = retained state in
  expect "conjunction after b"
    ["edge_conjunction"; "root_a"; "root_b"] conjunction_after_b;

  let state =
    P.init
    |> add [assumption "root_ab" ["a"; "b"] (P.Sum_ambient true)]
    |> add [conjunction]
  in
  let late_conjunction = retained state in
  expect "late conjunction" ["edge_conjunction"; "root_ab"]
    late_conjunction;

  Printf.printf "empty=%s\nconjunction-before=%s\nconjunction-after=%s\nlate=%s\n"
    (String.concat "," empty_alternative)
    (String.concat "," conjunction_before_b)
    (String.concat "," conjunction_after_b)
    (String.concat "," late_conjunction)
