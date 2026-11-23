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

The proof covers the constructor on Linux x86-64. Its atomic alignment
premise for thin pointers and source comparison still require independent
review. Ordinary pointer loads and stores have no formal proof here.
