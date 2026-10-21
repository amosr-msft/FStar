module T = FStarC_SMTEncoding_Term
module P = FStarC_SMTEncoding_Pruning

let exact_equal left right =
  left == right ||
  try left = right with Invalid_argument _ -> false

(* Tables are local to one exported module, limiting retention and avoiding
   dependencies on encoding environments or fresh-name scopes. *)
module MakeTable (Key : Hashtbl.HashedType) = struct
  module Table = Hashtbl.Make (Key)

  let canonical table value =
    match Table.find_opt table value with
    | Some existing -> existing
    | None -> Table.add table value value; value
end

module TermTable = MakeTable (struct
  type t = T.term
  let equal = exact_equal
  let hash = Hashtbl.hash
end)

module DeclTable = MakeTable (struct
  type t = T.decl
  let equal = exact_equal
  let hash = Hashtbl.hash
end)

module EltTable = MakeTable (struct
  type t = T.decls_elt
  let equal = exact_equal
  let hash = Hashtbl.hash
end)

module SummaryTable = MakeTable (struct
  type t = P.decl_summary
  let equal = exact_equal
  let hash = Hashtbl.hash
end)

module EltSummaryTable = MakeTable (struct
  type t = P.elt_summary
  let equal = exact_equal
  let hash = Hashtbl.hash
end)

let intern_decls declarations =
  let count = max 101 (List.length declarations) in
  let terms = TermTable.Table.create (4 * count) in
  let decls = DeclTable.Table.create (2 * count) in
  let elts = EltTable.Table.create count in
  let rec term value =
    let rebuilt =
      match value with
      | T.App (op, args, range) -> T.App (op, List.map term args, range)
      | T.Quant (op, patterns, weight, sorts, body, range) ->
          T.Quant (op, List.map (List.map term) patterns, weight, sorts,
                   term body, range)
      | T.Let (values, body) -> T.Let (List.map term values, term body)
      | T.Labeled (body, label, range) -> T.Labeled (term body, label, range)
      | leaf -> leaf
    in
    TermTable.canonical terms rebuilt
  and decl value =
    let rebuilt =
      match value with
      | T.DefineFun (name, args, result, body, caption) ->
          T.DefineFun (name, args, result, term body, caption)
      | T.Assume assumption ->
          T.Assume
            { assumption with T.assumption_term = term assumption.T.assumption_term }
      | T.Module (name, declarations) -> T.Module (name, List.map decl declarations)
      | T.Eval value -> T.Eval (term value)
      | other -> other
    in
    DeclTable.canonical decls rebuilt
  in
  List.map
    (fun elt ->
      EltTable.canonical elts { elt with T.decls = List.map decl elt.T.decls })
    declarations

let intern_index index =
  let count = max 101 (List.length index) in
  let summaries = SummaryTable.Table.create (2 * count) in
  let elts = EltSummaryTable.Table.create count in
  let summary value = SummaryTable.canonical summaries value in
  List.map
    (fun elt ->
      EltSummaryTable.canonical elts
        { elt with P.elts_sums = List.map summary elt.P.elts_sums })
    index
