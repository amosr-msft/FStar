module FStarC.SMTEncoding.Sharing

open FStarC
open FStarC.Effect
open FStarC.SMTEncoding.Term
open FStarC.Class.Deq
open FStarC.Class.Hashable

module H = FStarC.Hash
module HT = FStarC.HashTable
module R = FStarC.Range.Ops
module U = FStarC.Util
module Real = FStarC.Real

let tag (n:int) : H.hash_code = H.of_int n
let mix (x y:H.hash_code) : H.hash_code = H.mix x y

let rec hash_list (#a:Type) (f:a -> ML H.hash_code) (xs:list a)
  : ML H.hash_code =
  match xs with
  | [] -> tag 0
  | x::xs -> mix (tag 1) (mix (f x) (hash_list f xs))

let hash_option (#a:Type) (f:a -> ML H.hash_code) (x:option a)
  : ML H.hash_code =
  match x with
  | None -> tag 0
  | Some x -> mix (tag 1) (f x)

let equal_list (#a:Type) (f:a -> a -> ML bool) (xs ys:list a)
  : ML bool =
  FStarC.List.forall2 f xs ys

let equal_option (#a:Type) (f:a -> a -> ML bool) (x y:option a)
  : ML bool =
  match x, y with
  | None, None -> true
  | Some x, Some y -> f x y
  | _ -> false

let rec hash_sort (s:sort) : ML H.hash_code =
  match s with
  | Bool_sort -> tag 0
  | Int_sort -> tag 1
  | String_sort -> tag 2
  | Term_sort -> tag 3
  | Fuel_sort -> tag 4
  | BitVec_sort n -> mix (tag 5) (H.of_int n)
  | Array (a, b) -> mix (tag 6) (mix (hash_sort a) (hash_sort b))
  | Arrow (a, b) -> mix (tag 7) (mix (hash_sort a) (hash_sort b))
  | Sort s -> mix (tag 8) (H.of_string s)

let rec equal_sort (x y:sort) : ML bool =
  match x, y with
  | Bool_sort, Bool_sort
  | Int_sort, Int_sort
  | String_sort, String_sort
  | Term_sort, Term_sort
  | Fuel_sort, Fuel_sort -> true
  | BitVec_sort x, BitVec_sort y -> x = y
  | Array (x1, x2), Array (y1, y2)
  | Arrow (x1, x2), Arrow (y1, y2) ->
      equal_sort x1 y1 && equal_sort x2 y2
  | Sort x, Sort y -> x = y
  | _ -> false

(* These discriminants are part of the hash scheme: each constructor has a
   distinct stable tag, while equality still checks every payload. *)
let op_tag (o:op) : int =
  match o with
  | TrueOp -> 0 | FalseOp -> 1 | Not -> 2
  | And -> 3 | Or -> 4 | Imp -> 5 | Iff -> 6
  | Eq -> 7 | LT -> 8 | LTE -> 9 | GT -> 10
  | GTE -> 11 | Add -> 12 | Sub -> 13 | Div -> 14
  | RealDiv -> 15 | Mul -> 16 | Minus -> 17
  | Mod -> 18 | BvAnd -> 19 | BvXor -> 20
  | BvOr -> 21 | BvAdd -> 22 | BvSub -> 23
  | BvShl -> 24 | BvShr -> 25 | BvUdiv -> 26
  | BvMod -> 27 | BvMul -> 28 | BvUlt -> 29
  | BvConcat -> 30 | BvRepeat _ -> 31
  | BvExtRol -> 32 | BvExtRor -> 33
  | BvRol _ -> 34 | BvRor _ -> 35
  | BvUext _ -> 36 | BvSext _ -> 37
  | BvExtract _ -> 38
  | BvNot -> 39 | BvNeg -> 40 | BvNand -> 41
  | BvNor -> 42 | BvXnor -> 43 | BvComp -> 44
  | BvUle -> 45 | BvUgt -> 46 | BvUge -> 47
  | BvSlt -> 48 | BvSle -> 49 | BvSgt -> 50
  | BvSge -> 51 | BvSdiv -> 52 | BvSrem -> 53
  | BvSmod -> 54 | BvAshr -> 55 | BvNego -> 56
  | BvUaddo -> 57 | BvSaddo -> 58 | BvUmulo -> 59
  | BvSmulo -> 60 | BvUsubo -> 61 | BvSsubo -> 62
  | BvSdivo -> 63 | NatToBv _ -> 64
  | BvToNat -> 65 | SBvToInt -> 66 | ITE -> 67
  | Var _ -> 68

let hash_op (o:op) : ML H.hash_code =
  match o with
  | BvRepeat n | BvRol n | BvRor n | BvUext n | BvSext n
  | NatToBv n -> mix (tag (op_tag o)) (H.of_int n)
  | BvExtract (n, m) ->
      mix (tag 38) (mix (H.of_int n) (H.of_int m))
  | Var s -> mix (tag 68) (H.of_string s)
  | _ -> tag (op_tag o)

let equal_op (x y:op) : ML bool =
  match x, y with
  | BvRepeat x, BvRepeat y | BvRol x, BvRol y
  | BvRor x, BvRor y | BvUext x, BvUext y
  | BvSext x, BvSext y | NatToBv x, NatToBv y -> x = y
  | BvExtract (x1, x2), BvExtract (y1, y2) -> x1 = y1 && x2 = y2
  | Var x, Var y -> x = y
  | _ -> op_tag x = op_tag y

let hash_qop (q:qop) : H.hash_code =
  match q with Forall -> tag 0 | Exists -> tag 1

let equal_qop (x y:qop) : bool =
  match x, y with
  | Forall, Forall | Exists, Exists -> true
  | _ -> false

let hash_pos (p:Range.pos) : H.hash_code =
  mix (H.of_int (R.line_of_pos p)) (H.of_int (R.col_of_pos p))

let equal_pos (x y:Range.pos) : ML bool = x =? y

let hash_range (r:Range.t) : H.hash_code =
  let hdef =
    mix (H.of_string (R.file_of_range r))
      (mix (hash_pos (R.start_of_range r)) (hash_pos (R.end_of_range r))) in
  let huse =
    mix (H.of_string (R.file_of_use_range r))
      (mix (hash_pos (R.start_of_use_range r))
           (hash_pos (R.end_of_use_range r))) in
  mix hdef huse

let equal_range (x y:Range.t) : ML bool =
  R.file_of_range x = R.file_of_range y &&
  equal_pos (R.start_of_range x) (R.start_of_range y) &&
  equal_pos (R.end_of_range x) (R.end_of_range y) &&
  R.file_of_use_range x = R.file_of_use_range y &&
  equal_pos (R.start_of_use_range x) (R.start_of_use_range y) &&
  equal_pos (R.end_of_use_range x) (R.end_of_use_range y)

let hash_fv (x:fv) : ML H.hash_code =
  let FV name s force = x in
  mix (H.of_string name) (mix (hash_sort s) (hash force))

let equal_fv_exact (x y:fv) : ML bool =
  let FV xn xs xf = x in
  let FV yn ys yf = y in
  xn = yn && equal_sort xs ys && xf = yf

noeq type hashed_term = {
  ht_hash:H.hash_code;
  ht_term:term
}

let term_hash (x:hashed_term) = x.ht_hash
let term_value (x:hashed_term) = x.ht_term

let physical_term (x y:term) : bool = U.physical_equality x y

let equal_term_node (x y:term) : ML bool =
  match x, y with
  | Integer x, Integer y | String x, String y -> x = y
  | Real x, Real y ->
      Real.mantissa x = Real.mantissa y &&
      Real.exponent x = Real.exponent y
  | BoundV x, BoundV y -> x = y
  | FreeV x, FreeV y -> equal_fv_exact x y
  | App xo xa xr, App yo ya yr ->
      equal_op xo yo &&
      equal_list physical_term xa ya &&
      equal_range xr yr
  | Quant xo xp xw xs xb xr, Quant yo yp yw ys yb yr ->
      equal_qop xo yo &&
      equal_list (equal_list physical_term) xp yp &&
      equal_option (fun x y -> x = y) xw yw &&
      equal_list equal_sort xs ys &&
      physical_term xb yb &&
      equal_range xr yr
  | Let xv xb, Let yv yb ->
      equal_list physical_term xv yv && physical_term xb yb
  | Labeled xb xm xr, Labeled yb ym yr ->
      physical_term xb yb &&
      U.physical_equality xm ym &&
      equal_range xr yr
  | _ -> false

noeq type term_key = {
  tk_hash:H.hash_code;
  tk_term:term
}

instance deq_term_key : deq term_key = {
  (=?) = (fun x y -> x.tk_hash =? y.tk_hash &&
                     equal_term_node x.tk_term y.tk_term);
}

instance hashable_term_key : hashable term_key = {
  hash = (fun x -> x.tk_hash);
}

noeq type term_table = {
  term_find:term_key -> ML (option term);
  term_add:term_key -> term -> ML unit
}

let canonical_term
    (table:term_table) (candidate:term) (h:H.hash_code)
  : ML hashed_term =
  let key = {
    tk_hash = h;
    tk_term = candidate
  } in
  match table.term_find key with
  | Some existing -> { ht_hash = h; ht_term = existing }
  | None ->
      table.term_add key candidate;
      { ht_hash = h; ht_term = candidate }

let rec intern_term (table:term_table) (x:term) : ML hashed_term =
  match x with
  | Integer s -> canonical_term table x (mix (tag 0) (H.of_string s))
  | String s -> canonical_term table x (mix (tag 1) (H.of_string s))
  | Real r ->
      canonical_term table x
        (mix (tag 2)
          (mix (H.of_int (Real.mantissa r)) (H.of_int (Real.exponent r))))
  | BoundV n -> canonical_term table x (mix (tag 3) (H.of_int n))
  | FreeV fv -> canonical_term table x (mix (tag 4) (hash_fv fv))
  | App op args range ->
      let args = List.map (intern_term table) args in
      let rebuilt = App op (List.map term_value args) range in
      canonical_term table rebuilt
        (mix (tag 5)
          (mix (hash_op op)
            (mix (hash_list term_hash args) (hash_range range))))
  | Quant q patterns weight sorts body range ->
      let patterns =
        List.map (fun p -> List.map (intern_term table) p) patterns in
      let body = intern_term table body in
      let rebuilt =
        Quant q
          (List.map (List.map term_value) patterns)
          weight sorts body.ht_term range in
      canonical_term table rebuilt
        (mix (tag 6)
          (mix (hash_qop q)
            (mix (hash_list (hash_list term_hash) patterns)
              (mix (hash_option H.of_int weight)
                (mix (hash_list hash_sort sorts)
                  (mix body.ht_hash (hash_range range)))))))
  | Let values body ->
      let values = List.map (intern_term table) values in
      let body = intern_term table body in
      let rebuilt = Let (List.map term_value values) body.ht_term in
      canonical_term table rebuilt
        (mix (tag 7) (mix (hash_list term_hash values) body.ht_hash))
  | Labeled body message range ->
      let body = intern_term table body in
      let rebuilt = Labeled body.ht_term message range in
      canonical_term table rebuilt
        (mix (tag 8) (mix body.ht_hash (mix (tag 0) (hash_range range))))

let rec intern_decl (terms:term_table) (x:decl) : ML decl =
  match x with
  | DefineFun name args result body caption ->
      let body = intern_term terms body in
      DefineFun name args result body.ht_term caption
  | Assume a ->
      let body = intern_term terms a.assumption_term in
      Assume { a with assumption_term = body.ht_term }
  | Module name children ->
      Module name (List.map (intern_decl terms) children)
  | Eval t ->
      let t = intern_term terms t in
      Eval t.ht_term
  | _ -> x

let intern_elt (terms:term_table) (x:decls_elt) : ML decls_elt =
  { x with decls = List.map (intern_decl terms) x.decls }

let intern_decls (declarations:decls_t) : ML decls_t =
  let count = List.length declarations in
  let size = if count = 0 then 1 else 4 * count in
  let entries = HT.create size in
  let terms = {
    term_find = (fun key -> HT.try_find entries key);
    term_add = (fun key value -> HT.add entries key value)
  } in
  List.map (intern_elt terms) declarations
