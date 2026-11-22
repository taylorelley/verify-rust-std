# Challenge 7 Boolean verification

This branch starts the current-source proof of `AtomicBool::from_ptr` and ordinary
`AtomicBool::store`. The runtime implementation remains the challenge fork's.

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
both Boolean inputs, the three valid store orderings, ordinary access after
join, concurrent ordinary and atomic reads, and the two invalid store orderings.
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
review of the source transfer and trusted model. The documented read/read case
is still covered only by concrete testing.

## Ordinary store

VeriFast 26.10 fails on the enum-valued const argument in the reduced
`store-const-ordering.rs` probe. The checked patch extends the frontend at the
direct intrinsic call. It verifies the operand type is `u8`, accepts only the
three legal store orderings and `VOLATILE = false`, and dispatches to the
corresponding built-in store specification. Those specifications consume an
atomic permission for the destination and require that the stored byte
satisfies its invariant. The compiler's atomic primitive remains trusted.

To reproduce on Linux x86-64, use Rustup with the two nightlies above.

```sh
rustc_path=$(rustup which rustc)
bash "$proof/build-store-verifast.sh" /tmp/challenge-7-verifast-build
RUSTUP_TOOLCHAIN=nightly-2026-09-25   python3 "$proof/check-bool-store.py"   /tmp/challenge-7-verifast-build/verifast-26.10/bin "$rustc_path"   /tmp/challenge-7-store
```

The specialized helper opens its shared atomic permission only on paths that
call the non-unwinding primitive. The `Acquire` and `AcqRel` panic branches
preserve the thread and lifetime tokens. The verifier checks the public store
contract using the semantic interpretation of its safe Rust signature.

The source check pins the original atomic module and the relevant intrinsic
declarations. It checks concrete layout and compares the inlined LLVM
dispatch for this target, including the stored byte, destination, each
ordering, and panic edges. The comparison normalizes compiler-generated
names, metadata, and panic source locations. Changing the Relaxed branch to
Release must fail the comparison. The patched verifier must reject a volatile
call, an Acquire store intrinsic, and a store of byte 2 under the Boolean
invariant.

Independent review of the source specialization and primitive model remains
open. The current proof uses a writable atomic share and does not establish
the separate contract for mixed atomic and ordinary read-only access.
