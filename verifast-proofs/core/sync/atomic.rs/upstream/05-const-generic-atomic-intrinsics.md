# Rust: const-generic atomic intrinsics

Since mid-2025, the standard library declares one intrinsic per atomic
operation with the ordering as a const generic, for example
`atomic_load::<T, const ORD: AtomicOrdering, const VOLATILE: bool>`. VeriFast
26.10 stops with `Unsupported constant value tree` at any call, so no code that
uses atomics can be verified on a current toolchain. That includes
`core::sync::atomic`, `Arc` and locks.

## Translator

`specialize_atomic_access` decodes the `AtomicOrdering` argument at calls to
`atomic_load`, `atomic_store`, `atomic_xchg`, `atomic_cxchg`, `atomic_cxchgweak`,
`atomic_xadd`, `atomic_xsub`, `atomic_and`, `atomic_nand`, `atomic_or`,
`atomic_xor`, `atomic_max`, `atomic_min`, `atomic_umax` and `atomic_umin`, and
maps each call to a contract in `lib.rsspec`. These are static errors:
* Release or AcqRel loads, Acquire or AcqRel stores, and a Release or AcqRel
  compare-exchange failure ordering. These mirror the library's panics.
* A literal `VOLATILE = true` (not modeled).
* Wide pointers, arithmetic with mismatched operand types, and min or max whose
  signedness does not match the operand.

Generic operands and a generic `VOLATILE` use the parametric contracts below.
The exporter decides pointer thinness in the function's typing environment,
so `*mut T` with `T: Sized` is accepted and `T: ?Sized` is rejected.

## Specifications (`lib.rsspec`)

The contracts use the existing `atomic_points_to` predicate and generalize the
existing `atomic_store_*` specifications:

* **Loads** return a value satisfying the slot invariant and need byte
  permission `1`. Atomic accesses to read-only memory are UB ("Atomic accesses to
  read-only memory" in the `core::sync::atomic` docs), and a load may be
  implemented with a compare-exchange. The one exception follows those docs: a
  Relaxed load of at most eight bytes on `target_arch` `x86_64` or `aarch64`, with
  a literal `VOLATILE = false`, goes to `atomic_load_relaxed_up_to_eight_bytes`,
  which accepts any fraction.
* **Stores, exchanges, both compare-exchange forms, min and max** need byte
  permission `1` and operands that satisfy the invariant, and return a value
  that satisfies it.
* **Add, sub, and, nand, or, xor** need a slot that admits every value. The byte
  AND, OR and XOR also accept the 0-or-1 invariant with a 0-or-1 operand, which
  is what `AtomicBool` needs.
* `atomic_align_of` facts for every integer width and thin pointers, and
  `usize::wrapping_mul`.

These are trusted specifications and deserve the closest review.

**Tests.** `tests/rust/purely_unsafe/atomic_intrinsics.rs` covers concrete and
generic loads, stores and exchanges. It checks that a small Relaxed load works
with a read fraction, and that these fail with one: a store, an Acquire load, a
128-bit Relaxed load, and a load whose volatility is a parameter.
`atomic_intrinsics_bad_ordering.rs` (a Release load) and
`atomic_intrinsics_wide_ptr.rs` (a `?Sized` pointee) must be rejected.
