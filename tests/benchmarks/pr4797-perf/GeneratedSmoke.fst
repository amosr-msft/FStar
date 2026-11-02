module GeneratedSmoke

let add_one (x:int) : Tot int = x + 1

let check : squash (add_one 41 == 42) = ()
