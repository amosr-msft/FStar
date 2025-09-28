
type 'n bv_t = | MkBV of Z.t

let z'max (n: Prims.pos) : Z.t = Z.pred (Z.shift_left Z.one (Z.to_int n))
let mkBV'mod (n: Prims.pos) (i: Z.t) : Obj.t bv_t = MkBV (Z.logand i (z'max n))

let bv_uext (n: Prims.pos) (i: Prims.pos) (a: Obj.t bv_t) : Obj.t bv_t = a

let int2bv (n: Prims.pos) (i: Z.t) : Obj.t bv_t = MkBV i
let bv2int (n: Prims.pos) (a: Obj.t bv_t) : Z.t =
  let MkBV i = a in i

let list2bv (n: Prims.pos) (l: Prims.bool Prims.list) : Obj.t bv_t =
  let rec aux acc = function
    | [] -> acc
    | b::bs -> aux (if b then Z.succ (Z.shift_left acc 1) else Z.shift_left acc 1) bs
  in MkBV (aux Z.zero l)

let bv2list (n: Prims.pos) (s: Obj.t bv_t) : Prims.bool Prims.list =
  let rec aux acc i =
    if i = 0 then acc
    else
      let bit = Z.testbit (bv2int n s) (i - 1) in
      aux (bit :: acc) (i - 1)
  in aux [] (Z.to_int n) |> List.rev

let bvand (n: Prims.pos) (a: Obj.t bv_t) (b: Obj.t bv_t) : Obj.t bv_t =
  let MkBV va = a in
  let MkBV vb = b in
  MkBV (Z.logand va vb)

let bvxor (n: Prims.pos) (a: Obj.t bv_t) (b: Obj.t bv_t) : Obj.t bv_t =
  let MkBV va = a in
  let MkBV vb = b in
  MkBV (Z.logxor va vb)

let bvor (n: Prims.pos) (a: Obj.t bv_t) (b: Obj.t bv_t) : Obj.t bv_t =
  let MkBV va = a in
  let MkBV vb = b in
  MkBV (Z.logor va vb)

let bvnot (n: Prims.pos) (a: Obj.t bv_t) : Obj.t bv_t =
  let MkBV va = a in
  MkBV (Z.lognot va)

let bvshl' (n: Prims.pos) (a: Obj.t bv_t) (s: Obj.t bv_t) : Obj.t bv_t =
  let MkBV va = a in
  let MkBV vs = s in
  MkBV (Z.shift_left va (Z.to_int vs))

let bvshl (n: Prims.pos) (a: Obj.t bv_t) (s: Prims.int) : Obj.t bv_t =
  bvshl' n a (int2bv n s)

let bvshr' (n: Prims.pos) (a: Obj.t bv_t) (s: Obj.t bv_t) : Obj.t bv_t =
  let MkBV va = a in
  let MkBV vs = s in
  MkBV (Z.shift_right va (Z.to_int vs))

let bvshr (n: Prims.pos) (a: Obj.t bv_t) (s: Prims.int) : Obj.t bv_t =
  bvshr' n a (int2bv n s)

let bv_zero (n: Prims.pos) : Obj.t bv_t = MkBV Z.zero

let bvult (n: Prims.pos) (a: Obj.t bv_t) (b: Obj.t bv_t) : Prims.bool =
  let MkBV va = a in
  let MkBV vb = b in
  Z.lt va vb

let bvadd (n: Prims.pos) (a: Obj.t bv_t) (b: Obj.t bv_t) : Obj.t bv_t =
  let MkBV va = a in
  let MkBV vb = b in
  mkBV'mod n (Z.add va vb)

let bvsub (n: Prims.pos) (a: Obj.t bv_t) (b: Obj.t bv_t) : Obj.t bv_t =
  let MkBV va = a in
  let MkBV vb = b in
  mkBV'mod n (Z.sub va vb)

let bvdiv (n: Prims.pos) (a: Obj.t bv_t) (b: Z.t) : Obj.t bv_t =
  let MkBV va = a in
  mkBV'mod n (Z.div va b)

(*
  SMT-LIB 2 specifies that division and modulo are total and deterministic for bit-vectors:
  https://github.com/SMT-LIB/SMT-LIB-2/blob/main/Theories/FixedSizeBitVectors.smt2:

   [[(bvudiv s t)]] := if bv2nat([[t]]) = 0
                       then λx:[0, m). 1
                       else nat2bv[m](bv2nat([[s]]) div bv2nat([[t]]))
*)
let bvdiv_unsafe (n: Prims.pos) (a: Obj.t bv_t) (b: Obj.t bv_t) : Obj.t bv_t =
  let MkBV vb = b in
  if Z.equal vb Z.zero then MkBV (z'max n) else bvdiv n a vb

let bvmod (n: Prims.pos) (a: Obj.t bv_t) (b: Z.t) : Obj.t bv_t =
  let MkBV va = a in
  let open Z in
  mkBV'mod n (va mod b)

(*
   [[(bvurem s t)]] := if bv2nat([[t]]) = 0
                       then [[s]]
                       else nat2bv[m](bv2nat([[s]]) rem bv2nat([[t]]))
*)
let bvmod_unsafe (n: Prims.pos) (a: Obj.t bv_t) (b: Obj.t bv_t) : Obj.t bv_t =
  let MkBV vb = b in
  if Z.equal vb Z.zero then a else bvmod n a vb

let bvmul (n: Prims.pos) (a: Obj.t bv_t) (b: Z.t) : Obj.t bv_t =
  let MkBV va = a in
  mkBV'mod n (Z.mul va b)
