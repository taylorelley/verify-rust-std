# Upstreaming the VeriFast patch

The proofs need `verifast-26.10-u8-store.patch` on top of VeriFast 26.10
(commit `f76012fb`). The patch also applies cleanly to the current VeriFast
master. When a VeriFast release includes these changes, this directory can
switch to the repository's standard setup: set `VFVERSION` in
`verifast-proofs/setup-verifast-home`, then delete `build-store-verifast.sh`
and the patch.

The text below can be adapted as the description of a pull request to
`verifast/verifast`.

---

## Support for const-generic atomic intrinsics

Recent nightlies declare the atomic intrinsics with the ordering as a const
generic, as in `atomic_load::<T, ORD, VOLATILE>`, and no longer as one
function per ordering. VeriFast 26.10 stops with an unsupported-const error
on these calls. That blocks `core::sync::atomic` and every client of it.

### Frontend (`vf_mir_translator.ml`)

* `specialize_atomic_access` decodes the `AtomicOrdering` const argument
  (the exporter emits the variant index) at calls to `atomic_load`,
  `atomic_store`, `atomic_xchg`, `atomic_cxchg`, `atomic_cxchgweak`,
  `atomic_xadd`, `atomic_xsub`, `atomic_and`, `atomic_nand`, `atomic_or`,
  `atomic_xor`, `atomic_max`, `atomic_min`, `atomic_umax` and `atomic_umin`.
  It maps each call to a contract in `lib.rsspec`. Illegal orderings, such as
  a Release load, an Acquire store or a Release compare-exchange failure
  ordering, are static errors.
* The operand must be an integer, a thin raw pointer or a type parameter. A
  `VOLATILE` argument must be the concrete value `false`. Wide pointers,
  volatile accesses with a literal `true`, mismatched arithmetic operands and
  signed or unsigned mismatches in min and max are rejected.
* Generic operands use a parametric contract for legal monomorphizations.
  The helper proof specializes the load and store access flag to `false`.
* For concrete local structs, the exporter passes rustc's ABI alignment
  (`knownAlignment` in `vf_mir.capnp`). The translator records it as a
  `RustcAbiAlignment` struct attribute. A proof can then derive the alignment
  of a wrapper such as `AtomicU16` from the compiler without assuming it.

### Specifications (`bin/rust/std/lib.rsspec`)

* The patch adds `atomic_align_of` facts for every integer width and for thin
  pointers.
* It adds contracts for the atomic primitives, stated with the existing
  `atomic_points_to` predicate:
  * Loads return a value satisfying the slot invariant. On x86-64 and
    AArch64 Linux, a Relaxed load of at most eight bytes can take a read
    fraction. Other loads require full byte permission for writable storage.
  * Stores, exchanges, compare-exchanges, min and max need the write
    permission, `atomic_points_to(p, 1, inv)`, and operands that satisfy
    `inv`.
  * Arithmetic and bitwise operations need a slot that admits every value.
  * Byte AND, OR and XOR also accept the Boolean invariant with a 0 or 1
    operand.
* It adds `usize::wrapping_mul`, which `AtomicPtr::fetch_ptr_add` uses.

### Testing

The `verify-rust-std` Challenge 7 replay exercises every path. It checks the
constructors and public methods of each atomic type, the generic helpers,
and negative controls for each rejected shape and ordering. The upstream
VeriFast test suite should also run with the patch applied before it merges.
