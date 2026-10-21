module FStarC.SMTEncoding.Sharing

open FStarC.Effect
open FStarC.SMTEncoding.Term
module Pruning = FStarC.SMTEncoding.Pruning

(* Exact structural interning: list cardinality and order are preserved. *)
[@@custard_extern "FStarC_SMTEncoding_Sharing_Runtime.intern_decls"]
assume val intern_decls: decls_t -> ML decls_t

[@@custard_extern "FStarC_SMTEncoding_Sharing_Runtime.intern_index"]
assume val intern_index:
  list Pruning.elt_summary -> ML (list Pruning.elt_summary)
