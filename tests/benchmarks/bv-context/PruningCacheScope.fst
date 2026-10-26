module PruningCacheScope

irreducible
let left (i:int) : Tot (r:int{r == i}) = i

irreducible
let right (i:int) : Tot (r:int{r == i}) = i

let left_first : squash (left 3 + 4 == 7) = ()
let right_first : squash (right 5 + 6 == 11) = ()
let left_second : squash (left 7 + 8 == 15) = ()
let right_second : squash (right 9 + 10 == 19) = ()
