module PruningEmptyPattern

assume val f : int -> int
assume val g : int -> int
assume val p : int -> prop
assume val q : int -> prop

assume val empty_alternative :
  x:int -> Lemma (p x)
  [SMTPatOr [[]; [SMTPat (f x); SMTPat (g x)]]]

[@@expect_failure]
let use_both : squash (q (g 0) ==> p (f 0)) = ()
