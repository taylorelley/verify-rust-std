# Challenge 7: atomic types and intrinsics, verified with VeriFast

This directory verifies the unmodified `library/core/src/sync/atomic.rs` against
[Challenge 7](../../../../doc/src/challenges/0007-atomic-types.md). It uses the
layout of the [LinkedList](../../../alloc/collections/linked_list.rs/) and
[RawVec](../../../alloc/raw_vec/mod.rs/) proofs:

| File | Role |
| --- | --- |
| `original/atomic.rs` | The library file. Four `#[rustc_diagnostic_item]` attributes become `#[doc]` attributes, because the proof crate cannot redefine core's diagnostic items. |
| `verified/atomic.rs` | The same file with VeriFast annotations. The only code change is `let result = ...; result` in the three `from_ptr` bodies, so that a ghost command can follow the reference creation. |
| `verify.sh` | Verifies `verified/` for Linux x86-64 and AArch64 Linux, checks with `refinement-checker` that `original/` refines `verified/`, and diffs `original/` against `library/`. |
| `check-module.py` | Checks that all 14 constructors and 15 helpers are reported verified on both targets, then checks that eight weakened proofs are rejected. |
| `verifast-26.10.patch`, `build-verifast.sh` | The VeriFast changes the proof needs, and the script that builds them on top of the 26.10 release. See [Trusted base](#trusted-base). |
| `supplementary/` | Additional evidence that is not part of the solution: per-operation proofs of the public methods, native and Miri client tests, LLVM dispatch comparisons and scoped-thread analyses. See [supplementary/README.md](supplementary/README.md). |

## Results

| Challenge 7 requirement | Where |
| --- | --- |
| Part 1: contracts for the 12 `from_ptr` methods, verified for all values of the pointee | `AtomicBool::from_ptr`, `AtomicPtr::from_ptr` and `from_ptr` in `atomic_int!`. All 10 integer expansions on x86-64 and all 12 on AArch64 are verified, including `AtomicIsize` and `AtomicUsize`. `AtomicPtr<T>` is verified for every `Sized` `T` at once, which includes the required pointee sizes. |
| Part 2: contracts for the 14 unsafe helpers | `atomic_store` to `atomic_umin`, plus `atomic_min`, at the end of `verified/atomic.rs`. The contracts are generic in `T` and verified once for all instantiations. |
| Part 2 (optional): no panics | For `atomic_store`, `atomic_load` and both compare-exchange helpers, the `on_unwind_ens` clause states exactly what an invalid ordering preserves. The other helpers have `on_unwind_ens false`. Their bodies accept every ordering. |
| Part 3: contracts for the 91 intrinsic ordering variants | `lib.rsspec` in the patch. The current library declares one const-generic intrinsic per operation, such as `atomic_load::<T, ORD, VOLATILE>`, instead of one function per ordering. The translator decodes `ORD` and dispatches each legal ordering to its contract. Illegal orderings are static errors. |

## Tour of the proof

### Atomic slots

Two definitions carry the proof:

```
pred_ctor atomic_slot<T>(p: *T, inv_: fix(T, bool))(;) = std::intrinsics::atomic_points_to(p, 1, inv_);
pred_ctor initialized<T>(p: *T)() = *p |-> ?v;
```

`atomic_points_to(p, 1, inv_)` is VeriFast's existing permission to access
location `p` atomically at type `T`, where every value stored there satisfies
`inv_`. VeriFast's `close_atomic_points_to` lemma creates it from ordinary
ownership `*p |-> v` of an initialized value, at an address aligned to
`atomic_align_of::<T>()`. `open_atomic_points_to` gives that ownership back.
The second argument is the fraction of the underlying bytes: `1` means the
atomic view owns all of them, so no non-atomic access can happen at the same
time. The outer fraction, `[f]atomic_points_to(...)`, is shared among the atomic
users.

For `AtomicBool`, the slot is the storage byte and `inv_` is `bool_byte`
(0 or 1). For the integers, `inv_` admits every value. For `AtomicPtr`, it
admits every address, and the slot grants nothing about the pointee.

### Part 1: `from_ptr`

```rust
pub const unsafe fn from_ptr<'a>(ptr: *mut bool) -> &'a AtomicBool
/*@
req atomic_mask(MaskTop) &*& [?q]lifetime_token('a) &*&
    ptr as usize % std::mem::align_of::<Self>() == 0 &*&
    exists::<bool>(?fresh) &*&
    if fresh { *ptr |-> ?value } else { [_]frac_borrow('a, atomic_slot(ptr as *u8, bool_byte)) };
@*/
/*@
ens atomic_mask(MaskTop) &*& [q]lifetime_token('a) &*&
    ref_origin(result) == ref_origin(ptr as *Self) &*&
    [_]frac_borrow('a, atomic_slot(ptr as *u8, bool_byte)) &*& [_]frac_borrow('a, ref_initialized_(result)) &*&
    if fresh { borrow_end_token('a, initialized(ptr)) } else { true };
@*/
```

The precondition encodes the `# Safety` section:

* **Alignment.** `ptr` is aligned to `align_of::<AtomicBool>()`.
* **Validity for `'a`.** A *fresh* call hands over ownership of an initialized
  value at `ptr`. The proof lends it to lifetime `'a` as an atomic slot
  (`atomic_slot_new_bool`), and the caller gets the `borrow_end_token` back. The
  caller can only recover the location by ending `'a`, after the last use of the
  reference. Any `bool` value is accepted, and the slot invariant holds because
  ownership of a `bool` implies a 0 or 1 byte.
* **The memory model.** While `'a` is alive, the location is accessible only
  through the atomic slot. The slot owns all of the bytes at a single operand
  type. Mixing conflicting atomic and non-atomic accesses, or atomic accesses of
  different sizes, therefore needs a resource that the caller no longer holds.
* A *reused* call (`fresh == false`) needs an existing atomic view of the
  location for `'a`. That is how several references to one location are created.

The integer constructors in `atomic_int!` and `AtomicPtr::from_ptr` have the
same contract, with an unrestricted invariant. A VeriFast bug that skipped the
annotations of every expansion after the first is fixed by the patch, and
`check-module.py` checks that each expansion is reported as verified.

### Part 2: the unsafe helpers

```rust
const unsafe fn atomic_store<T: Copy, const VOLATILE: bool>(dst: *mut T, val: T, order: Ordering)
//@ req thread_token(currentThread) &*& [?f]std::intrinsics::atomic_points_to(dst, 1, ?valid) &*& valid(val) == true;
//@ ens thread_token(currentThread) &*& [f]std::intrinsics::atomic_points_to(dst, 1, valid);
//@ on_unwind_ens thread_token(currentThread) &*& [f]std::intrinsics::atomic_points_to(dst, 1, valid);
```

Each helper needs a share of an atomic slot that owns all of its bytes.
Writes require the value to satisfy the slot invariant, and reads return a value
that does. Arithmetic and bitwise helpers need a slot that admits every value.
`AtomicBool` reaches `atomic_and`, `atomic_or` and `atomic_xor` with the
narrower `bool_byte` invariant. The patch has dedicated byte contracts for those
calls. Loads also need all bytes, because atomic accesses to read-only memory are
undefined behavior (module docs, "Atomic accesses to read-only memory"). The one
exception is described under Part 3.

These are the contracts that `from_ptr` makes available: opening the
`frac_borrow` from its postcondition gives `[f]atomic_points_to(ptr, 1, inv_)`.

### Part 3: the intrinsics

The intrinsics have no bodies, so their contracts are trusted. They are in
`bin/rust/std/lib.rsspec` in the patch:

* Loads need `[f]atomic_points_to(src, 1, valid)` and return a valid value.
  `atomic_load_relaxed_up_to_eight_bytes` accepts any byte fraction. The
  translator uses it only for a Relaxed load with a literal `VOLATILE = false`
  of a type of at most eight bytes on `x86_64` or `aarch64`. Those are exactly
  the loads that the module docs guarantee to work on read-only memory.
* Stores, exchanges, both compare-exchange forms, min and max need full byte
  permission and valid operands, and return a valid value.
* Add, sub, and, nand, or and xor need full byte permission to a slot that
  admits every value.

The translator decodes the `AtomicOrdering` const argument and maps each call to
its contract. It rejects these at verification time:
* Release or AcqRel loads, Acquire or AcqRel stores, and a Release or AcqRel
  compare-exchange failure ordering.
* Literal volatile accesses, which are not modeled.
* Wide pointers, arithmetic operands of different types, and min or max whose
  signedness does not match the operand.

A generic `VOLATILE` parameter, as in the helpers, gets the ordinary
contract that requires writable storage. That contract is at least as strong
as what a volatile access needs.

### How the listed undefined behaviors are excluded

* **Data races.** A non-atomic access needs `*p |-> _`, which is lent to `'a`
  for as long as an atomic reference exists. Every atomic access goes through
  one slot type and owns all of its bytes, so a mixed-size access cannot be
  formed. VeriFast checks the threads' resources separately. Shared atomic
  references cross threads through `frac_borrow` (`Sync`).
* **Dangling or misaligned accesses.** The slot is created only from a live,
  aligned location, and it lives no longer than `'a`.
* **Reading uninitialized memory.** The slot is created only from an initialized
  value.
* **Intrinsic UB.** Illegal orderings do not verify. Loads and writes on
  read-only memory need full byte permission, except as allowed by the docs.
* **Invalid values.** Every value read satisfies the slot invariant, so a byte
  read as `bool` is 0 or 1.

## Trusted base

1. **VeriFast 26.10 with `verifast-26.10.patch`.** [`upstream/`](upstream/)
   splits the patch into five pull requests for `verifast/verifast`, and
   [`verifast-upstream.md`](verifast-upstream.md) explains each change. The
   patch adds a VeriFast regression test for each change.
   VeriFast's Rust and refinement-checker test suites pass with the patch. Once a
   VeriFast release includes it, `verify.sh` can join
   `../../../check-verifast-proofs.sh` and the separate workflow can go.
2. **The intrinsic contracts** in the patched `lib.rsspec`, and VeriFast's
   existing atomic-permission lemmas, as described under Part 3.
3. **VeriFast's known limitations.** VeriFast 26.10 does not fully check
   mutable-reference and `Box` aliasing ([Rust soundness notes](https://github.com/verifast/verifast/blob/f76012fb518703b1d98e243ac4f487f16877cfcb/tests/rust/README.md)).
   The constructors create shared references from raw pointers. Their contracts
   keep the location lent for the reference lifetime.
4. **Targets.** The proof is checked for `x86_64-unknown-linux-gnu`, and for
   `aarch64-unknown-linux-gnu`, which also has the 128-bit atomics. The
   native-Boolean `AtomicBool` path is the one in scope on both targets.

The safety contracts cover ordinary (non-volatile) atomic accesses. They do not
describe value histories or synchronization, which the challenge does not ask
for.

## Running the proof

```sh
proof=verifast-proofs/core/sync/atomic.rs
rustup toolchain install nightly-2026-09-25 --profile minimal \
  --component rustc-dev,rust-src --target aarch64-unknown-linux-gnu
bash "$proof/build-verifast.sh" /tmp/verifast-c7
export PATH=/tmp/verifast-c7/verifast-26.10/bin:$PATH RUSTUP_TOOLCHAIN=nightly-2026-09-25
bash "$proof/verify.sh"
python3 "$proof/check-module.py"
```

The `VeriFast Challenge 7` workflow runs the same steps. After a toolchain
update, `update.sh` merges the library changes into `verified/atomic.rs`.

## Credits

The constructor permission proofs build on the earlier VeriFast attempt by
jellllly420 ([#675](https://github.com/model-checking/verify-rust-std/pull/675)),
and on the `atomic_store` specifications that btj added to VeriFast.
