# refinement-checker: const generic parameters and enum-valued const arguments

The refinement checker fails on two features of current standard-library code:

* A const generic parameter (`const VOLATILE: bool`) produces a
  `ConstArgHasType` clause. The exporter marks it as ignored, and the checker
  then fails with `Clause kind not supported`.
* An enum-valued const argument (`{ AtomicOrdering::Acquire }`) is a branch
  value tree, which fails with `Branch not supported`.

**Change.**
* The exporter encodes `ConstArgHasType` clauses, and the checker compares both
  the constant and its type.
* Branch value trees decode to a structural constant compared by value.

**Test.** `tests/rust/refinement_checker/const_args_*.rs`: identical code must
refine, and a changed ordering (`Relaxed` to `SeqCst`) must not.
`const_param_type_*.rs`: two functions that differ only in the type of a const
parameter must not refine each other.
