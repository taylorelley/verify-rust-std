# Challenge 7 atomic verification

This directory verifies the safety of `core::sync::atomic` for
[Challenge 7](../../../../doc/src/challenges/0007-atomic-types.md) with
VeriFast. The proofs run on the fork's `library/core/src/sync/atomic.rs`
for Linux x86-64, and for AArch64 Linux in the 128-bit cases.

## What is proved

| Challenge 7 item | Proof step | Evidence |
| --- | --- | --- |
| Part 1: the 12 `from_ptr` constructors | `library-module`, with `constructors` as a per-type cross-check | Each constructor in the library module needs a live, initialized location with the documented alignment, `align_of::<AtomicX>()`, and lends it as an atomic slot for the reference lifetime. The location is returned when the lifetime ends. All values are symbolic. `AtomicPtr<T>` is verified once for every `T`. The 128-bit types use AArch64 Linux. |
| Part 2: the 15 unsafe helpers `atomic_store` to `atomic_umin` | `library-module` and `generic-helpers` | Each helper carries one generic contract and is verified inside the full library module. `refinement-checker` and `diff` tie the module to `library/`, as in the Challenge 5 and 19 proofs. |
| Constructor and helper coverage | `generic-helpers/coverage.json` | The replay checks that VeriFast reports each of the 14 constructors and 15 helpers as verified on the target that has it, so a skipped macro expansion fails the run. |
| Part 2 (optional): panic contracts | `generic-helpers` and the per-type wrapper proofs | Once the ordering contract excludes the invalid orderings, the helpers cannot unwind. The public wrappers unwind on invalid orderings with every resource intact. |
| Part 3: intrinsic contracts | `verifast-26.10.patch` (`bin/rust/std/lib.rsspec`) | 91 ordering variants across load, store, exchange, both compare-exchange forms, add, sub, and, nand, or, xor, max, min, umax and umin. |
| Public methods and instantiations | `bool-access`, `u16-mixed-width`, `integer-access`, `exchange`, `compare-exchange`, `arithmetic`, `bitwise`, `extrema` | Every public wrapper on `AtomicBool`, all integer widths and `AtomicPtr` at five pointee sizes, connected to the library by compiled MIR and LLVM comparison. |

The listed undefined behaviors are excluded as follows:

* **Data races.** An atomic slot permission rules out non-atomic and mixed-size
  writes to the slot. A read needs only a fraction of the permission, and a
  write needs all of it. VeriFast checks these fractions through the
  primitive contracts.
* **Dangling or misaligned access.** The slot permission can only be created
  from a live points-to resource whose address is aligned for atomic access
  at the slot type.
* **Uninitialized reads.** Creating the permission needs an initialized value.
* **Invalid values.** Each slot carries a value invariant, for example 0 or 1
  for `AtomicBool`. Stores, exchanges and compare-exchange require operands
  that satisfy it. Arithmetic and bitwise operations need an unrestricted slot,
  except for the Boolean AND, OR and XOR paths.
* **Intrinsic UB.** The frontend admits only legal orderings and supported
  operand types at intrinsic calls, so illegal orderings fail to verify.

## Trusted base

1. The intrinsic contracts and atomic permission lemmas in the VeriFast patch.
   They are the specifications of compiler primitives, so they cannot be proved
   in Rust.
2. The patched VeriFast frontend, which decodes const-generic `AtomicOrdering`
   arguments and passes rustc's alignment for structs and for the instances
   of generic structs used in function signatures, such as `Atomic<i16>`. The patch applies
   to VeriFast 26.10 and to the current master. Once a VeriFast release includes
   it, the repository's pinned release can replace it. See
   [`verifast-upstream.md`](verifast-upstream.md).
3. The per-type proofs of the public wrappers, such as `AtomicBool::store`: a
   specialized copy of each is verified, then compared with the compiled library
   code by the replay scripts. The constructors and helpers need no such
   comparison, since they are verified in the library module itself. The
   wrappers stay specialized because VeriFast cannot yet express a sharing
   predicate for the generic `Atomic<T>` (see `verifast-upstream.md`).

[`review-guide.md`](review-guide.md) maps each claim to its evidence and lists
the checks a reviewer should repeat.

## Full replay in CI

The `VeriFast Challenge 7` workflow builds the patched verifier and
runs the proof matrix, native clients and Miri clients. It uploads
the evidence directory on success or failure. The existing VeriFast
workflow continues to run the upstream standard library checks.

To run the same job on Linux x86-64, install the toolchains and call the
replay script with a new work directory. The source nightly is the channel
in `rust-toolchain.toml`. The verifier nightly is the one VeriFast 26.10
is built for.

```sh
proof=verifast-proofs/core/sync/atomic.rs
source_nightly=$(sed -n 's/^channel = "\(.*\)"$/\1/p' rust-toolchain.toml)
rustup toolchain install nightly-2026-09-25 --profile minimal \
  --component rustc-dev,rust-src --target aarch64-unknown-linux-gnu
rustup toolchain install "$source_nightly" --profile minimal \
  --component rust-src,miri --target aarch64-unknown-linux-gnu
bash "$proof/replay-challenge-7.sh" /tmp/challenge-7-clean-replay
```

You can pass an optional second argument with the three VeriFast
archives. The build verifies the same SHA-256 digests for local and
downloaded archives. If the source tarball endpoint is unreachable, the
build clones the 26.10 tag and checks its commit. The replay writes build
logs, verifier traces, compiled dispatch, target coverage, and native and
Miri results to `evidence/` under the work directory. A successful run
writes `evidence/result.log`. A failed step exits with its status and
leaves the logs in place.

The proofs are not tied to a hash of the atomic module. Each step either
copies the library code directly or compares compiled library code with the
verified copy. A toolchain update therefore fails only if it changes
verified behavior. Intrinsic declarations remain pinned by excerpt, so any
change to them forces a review of the trusted contracts.

The `scoped-thread-boundary`, `scoped-counter` and `scoped-composition`
steps check the threaded test clients. They are not part of the Challenge 7
claim. See [`supplementary-scoped-threads.md`](supplementary-scoped-threads.md).

## Library module proof

`original/` holds the library's `atomic.rs` and `verified/` holds the same file
with VeriFast contracts on the 14 `from_ptr` constructors and the 15 unsafe
helpers. In both copies the four
`#[rustc_diagnostic_item]` attributes become doc attributes, because the proof
crate cannot redefine core's diagnostic items. `verify.sh` follows the Challenge 5
and Challenge 19 proofs. It runs VeriFast on the whole of `verified/`, runs
`refinement-checker` to show that `original/` refines `verified/`, and diffs
`original/` against `library/` with the same attribute rewrite. After a
toolchain update, run `update.sh` to merge the library changes into
`verified/`.

```sh
PATH=/tmp/challenge-7-verifast-build/verifast-26.10/bin:$PATH \
  RUSTUP_TOOLCHAIN=nightly-2026-09-25 bash "$proof/verify.sh"
```

VeriFast runs with `-skip_specless_fns` only. It verifies unwind paths and
allows no `assume` statements. `verify.sh` checks the module for Linux x86-64 and
AArch64 Linux.

The constructor contract follows the `# Safety` section of `from_ptr`. The
caller passes `[q]lifetime_token('a)` and either ownership of an initialized,
`align_of::<AtomicX>()`-aligned location (`fresh`), or the atomic slot of an
existing view. The constructor returns a reference with the same origin and
`[_]frac_borrow('a, atomic_slot(...))`, which permits only atomic access for `'a`.
In the fresh case it also returns `borrow_end_token('a, initialized(ptr))`, so the
caller can read the location non-atomically once `'a` ends. For `AtomicBool`, the
slot is the storage byte, restricted to 0 and 1. The rustc alignment of each
atomic type reaches the proof through the patch's instance alignments.

Five controls run on the constructors: an integer constructor without the
alignment requirement, a fresh Boolean conversion without an initialized
location, reuse without an existing slot, a Boolean slot that admits any byte,
and the pointer constructor without the thin-pointer alignment fact.

## Generic unsafe helpers

`check-generic-helpers.py` checks the same contracts in a second way. It
extracts the helpers from the library at replay time, checks that
`verified/atomic.rs` states identical contracts, and runs the optional
no-panic variant and the rejection controls.

```sh
rustc_path=$(rustup which rustc)
RUSTUP_TOOLCHAIN=nightly-2026-09-25 \
  python3 "$proof/check-generic-helpers.py" \
  /tmp/challenge-7-verifast-build/verifast-26.10/bin "$rustc_path" \
  /tmp/challenge-7-generic-helpers
```

The runner copies the 15 helpers from `atomic.rs`, removes their attributes
and adds one contract to each. It type-checks the result with the source
nightly and verifies it. The contracts are generic over `T` (and `U` for the
operand of arithmetic and bitwise operations), and over `VOLATILE` for load and
store:

| Helper | Requires | Ensures |
| --- | --- | --- |
| `atomic_load` | a read fraction `[f]atomic_points_to(dst, p, valid)` | the same fraction, and `valid(result)` |
| `atomic_store` | write permission `atomic_points_to(dst, 1, valid)` and `valid(val)` | the permission |
| `atomic_swap`, `atomic_max`, `atomic_min`, `atomic_umax`, `atomic_umin` | write permission and `valid(val)` | the permission and `valid(result)` |
| `atomic_compare_exchange`, `atomic_compare_exchange_weak` | write permission, `valid(old)` and `valid(new)` | the permission and a valid value in `Ok` or `Err` |
| `atomic_add`, `atomic_sub`, `atomic_and`, `atomic_nand`, `atomic_or`, `atomic_xor` | write permission to a slot that admits every value | the permission |

On an invalid ordering, store, load and both compare-exchange helpers unwind
and return the permission. A second run adds the ordering contract for the
optional panic requirement. Store excludes `Acquire` and `AcqRel`, load
excludes `Release` and `AcqRel`, and compare-exchange excludes `Release` and
`AcqRel` as the failure ordering. With those orderings excluded, VeriFast
proves `on_unwind_ens false`.

The rejection controls cover a store with only a read fraction, a store,
exchange or maximum with an invalid value, a store with no permission,
addition on a restricted slot, the unwinding paths when the ordering contract
is missing, and a Release load or Acquire store substituted into a helper body.
Two controls run on the full module: `refinement-checker` rejects a changed
exchange ordering in `verified/`, and VeriFast rejects a store contract that
has only read access.

For `VOLATILE` the generic contract is the ordinary-access contract. It is at
least as strong as what a volatile access requires. AtomicBool's AND, OR and XOR
paths use the narrower Boolean invariant, which the generic contract does not
cover. They are verified in the `bitwise` step instead.

## Current-source replay

From the repository root with the nightly in `rust-toolchain.toml` and its
`rust-src` component installed, run:

```sh
proof=verifast-proofs/core/sync/atomic.rs
python3 "$proof/check-bool-clients.py" "$(rustup which rustc)"
```

The script compares the fork atomic module and relevant intrinsic declarations
with the compiler's source before running the client tests. The clients cover
both Boolean inputs, the valid load and store orderings, ordinary access after
join, concurrent ordinary and atomic reads, and the invalid load and store orderings.
This is concrete test evidence.

`probe-verifast.py` runs the frontend on a minimal associated-type example and on
the unannotated module:

```sh
RUSTUP_TOOLCHAIN=nightly-2026-09-25 \
  python3 "$proof/probe-verifast.py" /path/to/patched/verifast-26.10/bin /tmp/challenge-7-logs
```

Unpatched VeriFast 26.10 stops on both with `sizedness_of_type: TODO: projection
types`, because `Atomic<T>` stores `T::Storage`. The patch treats a projection
as sized only when the trait declares the associated type `Sized`, explicitly or
implicitly. A `?Sized` associated type is still rejected. The patch also declares
the typeid function of such a projection, as VeriFast already does for traits in
`.rsspec` files.

## Specialized Boolean constructor

Run the constructor check with VeriFast 26.10, its September nightly, and the
fork's November nightly for compiler comparison:

```sh
rustc_path=$(rustup which rustc)
RUSTUP_TOOLCHAIN=nightly-2026-09-25   python3 "$proof/check-bool-constructor.py" /path/to/verifast-26.10/bin   "$rustc_path" /tmp/challenge-7-constructor
```

VeriFast checks the fresh conversion, reuse of an existing lifetime-bound
share, a caller that exercises both branches, and preservation of valid Boolean
bytes when the borrow is restored. It rejects claiming fresh ownership twice,
reusing a share without permission, and passing uninitialized storage.

The source comparison pins the fork atomic module and checks size, alignment,
and field offset on both Rust types. It compares compiler-generated runtime and
const-evaluation MIR, disregarding debug information and mapping the two names
of the concrete Boolean atomic type. The comparison rejects an altered pointer
computation. The constructor part covers a writable atomic share.
The raw-byte read permission checks are described below.

## Ordinary load and store

VeriFast 26.10 fails on the enum-valued const argument in the reduced
`store-const-ordering.rs` probe. The checked patch extends the frontend at the
direct intrinsic call. The Boolean replay uses `u8`. The patched verifier
also accepts the other integer widths and thin pointers. Load and store
each accept three legal orderings with `VOLATILE = false`. Loads preserve
the supplied read permission and return a value satisfying the slot
invariant. Stores require full byte permission and an input that satisfies
the invariant.

To reproduce on Linux x86-64, use Rustup with the two nightlies above.

```sh
rustc_path=$(rustup which rustc)
bash "$proof/build-store-verifast.sh" /tmp/challenge-7-verifast-build
RUSTUP_TOOLCHAIN=nightly-2026-09-25   python3 "$proof/check-bool-store.py"   /tmp/challenge-7-verifast-build/verifast-26.10/bin "$rustc_path"   /tmp/challenge-7-store
```

The specialized helpers open the shared atomic permission only on paths that
call a non-unwinding primitive. The Release and AcqRel load panics and the
Acquire and AcqRel store panics preserve the thread and lifetime tokens.
The verifier checks the public methods against their safe Rust signatures.

The source check pins the original atomic module and the relevant intrinsic
declarations. It checks concrete layout and compares the inlined LLVM
dispatch for this target, including the stored byte, destination, each
ordering, and panic edges. The comparison normalizes compiler-generated
names, metadata, and panic source locations. Changing Relaxed to Acquire for a load or Release for a store must fail the
comparison. Negative controls cover volatile calls, Release load and
Acquire store intrinsics, and storing byte 2 under the Boolean invariant.

## Mixed access permissions

The raw-byte proof splits one initialized Boolean byte into two read shares.
One reader keeps an ordinary points-to fraction while the other converts its
fraction to an atomic permission and loads through it. The proof recombines
both halves to recover the original initialized byte. Replacing the atomic
load with a store is rejected because the store requires the full underlying
byte permission. These checks run alongside the constructor and public
load/store proofs.

The reference-level fixture constructs a read-only view of the same
`&AtomicBool` layout. The atomic and ordinary reader each require half of
the scope lifetime token and retain separate byte permissions. On scope
exit, the fixture ends the lifetime and recovers the original initialized
Boolean. Controls reject an attempt to end the modeled scope before the
atomic reader runs and a store through the read-only reference.

The compiled source check compares the reference cast, `as_ptr` byte read,
and Relaxed `load` using the fork's implementations. It rejects substituting
Acquire in the reference proof. The writable-share constructor and
load/store proofs still run in the same replay.

The reference fixture checks the two worker obligations and their scope
lifetime. The native and Miri client runs the same pattern with real scoped
threads.

## First integer specialization

After building the patched verifier above, replay the integer proof:

```sh
rustc_path=$(rustup which rustc)
RUSTUP_TOOLCHAIN=nightly-2026-09-25 \
  python3 "$proof/check-u16.py" \
  /tmp/challenge-7-verifast-build/verifast-26.10/bin "$rustc_path" \
  /tmp/challenge-7-u16
```

The Linux x86-64 proof checks `AtomicU16::from_ptr` for fresh and existing
shares, and ordinary `load` and `store` for all orderings, including their
panic paths. The patch exports ABI alignment from the compiler for
concrete local structs. The proof uses that layout fact to establish
two-byte alignment for the atomic word. An alignment-four mutation fails
the expected layout assertion. The patch also accepts concrete ordinary
`u16` intrinsics and uses the existing atomic permission predicate.

The disjoint positive fixture starts with a word atomic permission and
independent byte ownership. The overlap controls instead derive the byte
pointer at each offset within the live word and fail to acquire byte
ownership. The second control supplies a pointer-bounds fact so the
failure targets permissions. These fixtures check the resource model
assuming the primitive contracts. They do not run invalid Rust code.

The source check compares the constructor and public load/store wrappers
compiled by the fork's pinned nightly. It checks size, alignment, field
offset, all emitted atomic orderings and the panic paths. It detects
mutations to the constructor pointer and a load ordering. This evidence
is specific to the pinned specialization and target.

## Pointer constructor

Use the same rebuilt verifier and pinned source compiler.

```sh
rustc_path=$(rustup which rustc)
RUSTUP_TOOLCHAIN=nightly-2026-09-25 \
  python3 "$proof/check-ptr.py" \
  /tmp/challenge-7-verifast-build/verifast-26.10/bin "$rustc_path" \
  /tmp/challenge-7-ptr
"$rustc_path" --edition=2024 --test "$proof/ptr-client.rs" -o /tmp/challenge-7-ptr-client
/tmp/challenge-7-ptr-client
```

The proof runs separately for pointee sizes 0, 1, 2, 3 and 4 bytes. Each
fresh conversion requires an initialized pointer slot, the slot's atomic
alignment and a live scope token. An existing conversion requires the
corresponding atomic share. The specification leaves the pointer value
inside the slot unrestricted. The scope fixture creates two references
and recovers ownership of the slot after ending the modeled lifetime.

The source check pins the fork's atomic module and compares the
specialized and original constructors, including their eight-byte layout
and field offset. Its mutation changes the returned slot address. Proof
controls exercise missing storage or alignment, a second fresh claim,
attempted recovery before scope end and a wrong storage layout. The
parallel runtime client suite for Booleans remains separate. The pointer
client exercises null, dangling, address-only and live pointer values
without dereferencing them.

The proof also covers ordinary pointer loads and stores on Linux x86-64
for the same five pointee sizes. The load borrows a read fraction and the
store requires full permission in the trusted primitive contracts. The patched
verifier accepts compiler-confirmed concrete thin raw pointers and rejects
wide pointers and volatile accesses.

The source comparison checks pointer-typed LLVM loads and stores, the three
legal orderings for each operation, and both invalid-order panic branches.
The controls reject changed load and store orderings, an illegal intrinsic ordering,
a volatile load, and a store attempted with only a read fraction. The pointer
client also dereferences a live pointer after all nine legal store and load
ordering pairs. To replay the client under Miri, place `ptr-client.rs` in
`src/lib.rs` in a dependency-free Cargo package with edition 2024. Run
`cargo "+$source_nightly" miri test --offline` with
`MIRIFLAGS="-Zmiri-tree-borrows -Zmiri-seed=0"`.

The proof covers storage permissions and the lifetime and alignment rules.
A slot permission gives no permission to dereference the stored pointer,
so pointer provenance does not affect the safety of the atomic operation.

## Atomic exchange

Run the exchange proof with the rebuilt verifier and pinned source compiler.
Install the AArch64 target libraries for both nightlies as in the constructor replay.

```sh
rustc_path=$(rustup which rustc)
RUSTUP_TOOLCHAIN=nightly-2026-09-25 \
  python3 "$proof/check-swap.py" \
  /tmp/challenge-7-verifast-build/verifast-26.10/bin "$rustc_path" \
  /tmp/challenge-7-swap
"$rustc_path" --edition=2024 --test "$proof/swap-client.rs" -o /tmp/challenge-7-swap-client
/tmp/challenge-7-swap-client
```

The specialized wrappers cover `AtomicBool`, all signed and unsigned
integer widths in the constructor matrix, integers of pointer width,
and `AtomicPtr` at five pointee sizes. The trusted
`atomic_xchg` contracts require full byte permission to the slot and an
input satisfying its invariant. They preserve the permission and guarantee
that the returned value satisfies the same invariant. The proof restores
the lifetime token after the exchange and verifies the Boolean byte
invariant. It rejects an exchange with a read-only byte fraction, an
invalid Boolean byte or a wide pointer operand.

The source comparison checks the full LLVM dispatch for the five legal
orderings and detects changes to the ordering or return value. The native
and Miri tests check that an exchange returns the previous value and writes
the replacement. The pointer tests dereference the returned live pointer.
To run under Miri, use `swap-client.rs` as `src/lib.rs` in the pointer
client procedure above. Add `--target aarch64-unknown-linux-gnu` to run
the 128-bit cases under Miri without AArch64 hardware.

The 128-bit proofs use the AArch64 Linux target. The other proofs and
native tests use Linux x86-64. The Miri tests run on both targets.
A successful proof replay writes the per-case results to `coverage.json`.
The scope covers the native Boolean implementation and excludes the
emulation path. The contract is a safety contract. It does not
describe value history or synchronization.

## Strong and weak compare-exchange

Use the same rebuilt verifier, pinned compiler and AArch64 target libraries
as the exchange replay.

```sh
rustc_path=$(rustup which rustc)
RUSTUP_TOOLCHAIN=nightly-2026-09-25 \
  python3 "$proof/check-compare-exchange.py" \
  /tmp/challenge-7-verifast-build/verifast-26.10/bin "$rustc_path" \
  /tmp/challenge-7-compare-exchange
"$rustc_path" --edition=2024 --test "$proof/compare-exchange-client.rs" \
  -o /tmp/challenge-7-compare-exchange-client
/tmp/challenge-7-compare-exchange-client
```

The safety contracts for both compiler intrinsics require full byte
permission, valid operands and a live aligned slot. They preserve the
storage invariant and constrain the observed value on either outcome.
The wrapper proofs check that Boolean results come from a valid Boolean
byte and that invalid failure orderings unwind with the lifetime and
thread tokens intact. The verifier rejects a read-only slot permission,
an invalid Boolean replacement and a release failure ordering at an
intrinsic call.

The source check compares each of the 25 ordering pairs per method for
the 18 specializations in the exchange matrix. It checks typed
`cmpxchg` instructions with both orderings, the presence or absence of
`weak`, and panic-only paths for invalid pairs. It detects mutations to
both orderings, result variants and operation strength. The replay
writes the per-case results to `coverage.json`.

The runtime client tests success, mismatch and invalid failure ordering.
Use `compare-exchange-client.rs` as `src/lib.rs` in the Miri procedure
above. Run on both targets to exercise the 128-bit cases. To replay
spurious failure for each legal pair, run the ignored test with an
elevated Miri failure rate and a fixed seed:

```sh
MIRIFLAGS="-Zmiri-tree-borrows -Zmiri-seed=0 -Zmiri-compare-exchange-weak-failure-rate=0.9" \
  cargo "+$source_nightly" miri test --offline -- --ignored
```

The proof covers the native Boolean implementation and the same integer
and pointer specializations as exchange. The storage-safety contracts
permit either outcome for both strengths. The source and runtime checks
provide the evidence about strong versus weak behavior.

## Atomic addition and subtraction

Use the rebuilt verifier, pinned compiler and AArch64 target libraries
from the exchange replay.

```sh
rustc_path=$(rustup which rustc)
RUSTUP_TOOLCHAIN=nightly-2026-09-25 \
  python3 "$proof/check-arithmetic.py" \
  /tmp/challenge-7-verifast-build/verifast-26.10/bin "$rustc_path" \
  /tmp/challenge-7-arithmetic
"$rustc_path" --edition=2024 --test "$proof/arithmetic-client.rs" \
  -o /tmp/challenge-7-arithmetic-client
/tmp/challenge-7-arithmetic-client
```

The proof covers signed and unsigned integers, including pointer-width
integers, and `AtomicPtr` at pointee sizes 0, 1, 2, 3 and 4. Pointer
methods cover both byte and element offsets. For the element methods, the
specialization inlines the byte wrapper after wrapping multiplication.
The source comparison checks this inlining on every size and detects a
changed element scale. It also detects changes to arithmetic opcodes
and orderings. A successful replay writes `coverage.json`.

The primitive contracts require full byte permission and an invariant
that admits every value of the slot type. Arithmetic on a slot with a
narrower invariant, such as a byte restricted to 0 and 1, is outside that
contract. The verifier rejects narrower invariants, fractional write
permission and a non-`usize` delta for a pointer.

The native and Miri clients compare integer results against wrapping
arithmetic at the type limits. Pointer tests cover wraparound addresses
and dereference restored live pointers. Use `arithmetic-client.rs` as
`src/lib.rs` in the Miri procedure above. Run the default target and
`--target aarch64-unknown-linux-gnu` to cover the 128-bit integer cases.

The exact arithmetic results are checked by concrete tests.

## Atomic bitwise operations

Replay the bitwise cases with the arithmetic runner and the same two
pinned toolchains.

```sh
rustc_path=$(rustup which rustc)
RUSTUP_TOOLCHAIN=nightly-2026-09-25 \
  python3 "$proof/check-arithmetic.py" \
  /tmp/challenge-7-verifast-build/verifast-26.10/bin "$rustc_path" \
  /tmp/challenge-7-bitwise --bitwise
"$rustc_path" --edition=2024 --test "$proof/bitwise-client.rs" \
  -o /tmp/challenge-7-bitwise-client
/tmp/challenge-7-bitwise-client
```

The matrix covers AND, NAND, OR and XOR for the native Boolean path and
signed and unsigned integers, including pointer-width integers. It also
covers AND, OR and XOR for the five thin pointer specializations.
Pointer NAND has no public method in the pinned source. The runner
checks all five orderings against optimized LLVM output and detects
changed orderings and opcodes.

The primitive contracts preserve unrestricted integer and pointer slots.
The byte contracts for AND, OR and XOR additionally accept Boolean slots
with operands of 0 or 1. For Boolean NAND, the source and proof use XOR
with 1 or exchange with 1, depending on the input. A negative check
replaces XOR with byte NAND and confirms that the narrower Boolean
invariant prevents the call.

The native and Miri clients check the Boolean truth tables, integer
bit patterns, and pointer tagging and untagging followed by a live
dereference. To replay under Miri, use `bitwise-client.rs` as
`src/lib.rs` and run the default and `aarch64-unknown-linux-gnu`
targets as in the arithmetic replay. The 128-bit proof and Miri cases
use the AArch64 Linux target. Concrete bitwise results are exercised
by tests.

## Atomic minimum and maximum

Use the rebuilt verifier, pinned compiler and both target libraries from
the arithmetic replay.

```sh
rustc_path=$(rustup which rustc)
RUSTUP_TOOLCHAIN=nightly-2026-09-25 \
  python3 "$proof/check-arithmetic.py" \
  /tmp/challenge-7-verifast-build/verifast-26.10/bin "$rustc_path" \
  /tmp/challenge-7-extrema --extrema
"$rustc_path" --edition=2024 --test "$proof/extrema-client.rs" \
  -o /tmp/challenge-7-extrema-client
/tmp/challenge-7-extrema-client
```

The verifier checks all five orderings for `fetch_min` and `fetch_max`
on signed and unsigned integer atomics. The compiler uses `min` and
`max` for signed comparisons and `umin` and `umax` for unsigned
comparisons. The replay compares compiled dispatch, including signedness
and alignment, and detects changes to signedness or memory ordering.

The trusted contracts require full byte permission and an input that
satisfies the slot invariant. Since the operation selects either the
resident value or the supplied value, the contracts preserve the slot
invariant and guarantee it for the returned value. A proof client
exercises a slot restricted to zero. The controls reject a candidate
outside that invariant, a read-only byte fraction, and a mismatch
between the operand type and the intrinsic's comparison signedness.

The runtime client checks the previous and stored values across each
type's limits. Use `extrema-client.rs` as `src/lib.rs` in the Miri
procedure above and run both target variants. The 128-bit cases are
verified for the AArch64 Linux target and exercised there under Miri.
The concrete comparison results are tested on the source nightly.

## Complete integer load and store replay

Use the rebuilt verifier, pinned compiler and both target libraries.

```sh
rustc_path=$(rustup which rustc)
RUSTUP_TOOLCHAIN=nightly-2026-09-25 \
  python3 "$proof/check-integer-access.py" \
  /tmp/challenge-7-verifast-build/verifast-26.10/bin "$rustc_path" \
  /tmp/challenge-7-integer-access
"$rustc_path" --edition=2024 --test "$proof/integer-access-client.rs" \
  -o /tmp/challenge-7-integer-access-client
/tmp/challenge-7-integer-access-client
```

The matrix covers the ten fixed-width and two pointer-width integer
types. The 128-bit cases use the AArch64 Linux target. The specialized
programs verify all 72 legal load and store branches and 48 invalid
ordering panic branches. Unwinding preserves the thread and lifetime
tokens. Each case proves a fractional read and rejects a store with
that same fractional permission. The verifier continues to reject
volatile access and illegal intrinsic orderings.

The replay checks the slot layout and compares optimized LLVM dispatch
with the pinned source for each type and target. It detects changes to
both load and store orderings and writes `coverage.json` on success.

For Miri, use `integer-access-client.rs` as `src/lib.rs` and run both
the default and `aarch64-unknown-linux-gnu` targets. The client checks
integer limits and confirms that invalid orderings panic without writing
to the slot.

## Complete constructor replay

Install the AArch64 target libraries for both pinned Rust toolchains. The
replay runs on a Linux x86-64 host and cross-compiles the 128-bit
constructors for AArch64 Linux. The AArch64 proofs run symbolically on
the host using the AArch64 layout exported by rustc.

```sh
rustup target add --toolchain nightly-2026-09-25 aarch64-unknown-linux-gnu
rustup target add --toolchain "$source_nightly" aarch64-unknown-linux-gnu
rustc_path=$(rustup which rustc)
RUSTUP_TOOLCHAIN=nightly-2026-09-25 \
  python3 "$proof/check-from-ptr.py" \
  /tmp/challenge-7-verifast-build/verifast-26.10/bin "$rustc_path" \
  /tmp/challenge-7-constructors
```

The runner verifies every integer constructor with a fresh share and with
an existing share. It checks slot ownership recovery after the modeled
lifetime and rejects uninitialized storage, early recovery, incorrect
layout, and a changed slot address. It reruns the Boolean and pointer
proofs and checks the results against the constructor list in Challenge 7.
A successful run writes `coverage.json` with the proof target for each
type. The signed and unsigned pointer-sized integers are tracked as extras.

The AArch64 proofs use the alignment that rustc exports for that target.
Miri runs the AArch64 clients. The replay does not run on native AArch64
hardware.
