# Challenge 7 Boolean verification

This branch starts the current-source proof of `AtomicBool::from_ptr` and ordinary
`AtomicBool::load` and `AtomicBool::store`. The runtime implementation remains the challenge fork's.

## Historical result

[The ARM64 macOS 15 replay](https://github.com/taylorelley/verify-rust-std/actions/runs/45059674164)
ran the historical scripts and pinned patched VeriFast build from
[PR #675](https://github.com/model-checking/verify-rust-std/pull/675).
The only workflow change was the runner label. The artifact digest was
`151c8817dc3561a213b4241e7ff8ff7c7214d19b4597fcf8a1a44325c2332458`.
It reports 14 constructors, including signed and unsigned 128-bit types,
15 wrappers, 14 caller harnesses, source refinement, and passing controls.
These results apply to the historical source and primitive model.

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

For the VeriFast 26.10 front-end probe, use the verifier's nightly
`nightly-2026-09-25` with `rustc-dev` and `rust-src`:

```sh
RUSTUP_TOOLCHAIN=nightly-2026-09-25 \
  python3 "$proof/probe-verifast.py" /path/to/verifast-26.10/bin /tmp/challenge-7-logs
```

On Linux x86-64, VeriFast processes the concrete-layout control and the refinement
checker passes the current module's self-comparison. Both the full current module
and the minimal associated-type example fail before proof with
`sizedness_of_type: TODO: projection types`. The compiler has accepted the source
by this stage. The identity refinement check is a tool sanity check.

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
computation. This is a targeted constructor check for Linux x86-64, pending
review of the source transfer and trusted model. The constructor part covers a writable atomic share.
The raw-byte read permission checks are described below.

## Ordinary load and store

VeriFast 26.10 fails on the enum-valued const argument in the reduced
`store-const-ordering.rs` probe. The checked patch extends the frontend at the
direct intrinsic call. It verifies the operand type is `u8`, accepts only the
three legal orderings for each operation and `VOLATILE = false`, and dispatches to the
corresponding primitive specification. The patch adds load specifications
that preserve the supplied byte permission and return a value satisfying its invariant. Those specifications consume an
atomic permission for the destination and require that the stored byte
satisfies its invariant. The compiler's atomic primitive remains trusted.

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
lifetime. The native and Miri client uses real scoped threads. Running
VeriFast 26.10 on `scope-api-probe.rs` demonstrates the gap in the formal
proof. The front end rejects calls that pass closures, and the shipped
thread specifications provide no contracts for `scope`, `spawn`, or `join`.
The proof uses the compiler's atomic operations through the intrinsic
contracts. Independent review of those contracts and the source
specialization remains open.

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

The Boolean proof review should check the lifetime-token transfers,
fractional read permissions, exact intrinsic dispatch, and the compiler
layout and code-generation assumptions. Neither the proof nor its source
comparison establishes the correctness of Rust's scoped-thread
implementation. Independent review of both specializations is pending.

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
`cargo +nightly-2026-11-19 miri test --offline` with
`MIRIFLAGS="-Zmiri-tree-borrows -Zmiri-seed=0"`.

The formal claims are limited to storage permissions and the modeled
lifetime and alignment rules. Pointer provenance and concurrent memory-model
behavior are outside these claims. The trusted alignment and intrinsic
contracts and the source comparison still require independent review.

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
emulation path. The formal contract does not describe value history, pointer
provenance or synchronization semantics. The primitive contracts and
the source comparison await independent review.

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
  cargo +nightly-2026-11-19 miri test --offline -- --ignored
```

The proof covers the native Boolean implementation and the same integer
and pointer specializations as exchange. The storage-safety contracts
permit either outcome for both strengths. The source and runtime checks
provide the evidence about strong versus weak behavior. A formal model
of synchronization and pointer provenance, and independent review of the
trusted contracts, remain open.

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

The proofs cover storage safety under trusted primitive contracts. The
exact arithmetic results and pointer provenance are checked by concrete
tests. The formal contracts and source comparison still need independent
review.

## Complete constructor replay

Install the AArch64 target libraries for both pinned Rust toolchains. The
replay runs on a Linux x86-64 host and cross-compiles the 128-bit
constructors for AArch64 Linux. The AArch64 proofs run symbolically on
the host using the AArch64 layout exported by rustc.

```sh
rustup target add --toolchain nightly-2026-09-25 aarch64-unknown-linux-gnu
rustup target add --toolchain nightly-2026-11-19 aarch64-unknown-linux-gnu
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

The review boundary includes the patched verifier's compiler-derived
alignment, the trusted intrinsic alignment premises, the lifetime and
permission contracts, and the specialization comparison. The AArch64
results are proofs of the cross-target model. Native AArch64 execution
and independent review remain open.
