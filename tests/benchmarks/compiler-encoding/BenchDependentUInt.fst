module BenchDependentUInt

module B = BenchUIntLive500

let step_state_excluded_middle
  (transition:B.transition)
  (oracle:B.oracle_t)
  (state:B.state_t)
  : Lemma (
      (B.step transition oracle state).state == state \/
      ~((B.step transition oracle state).state == state)
    ) =
  ()
