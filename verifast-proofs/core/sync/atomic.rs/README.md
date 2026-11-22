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
with the compiler's source before running two legal clients. The clients cover
both Boolean inputs, the three valid store orderings, ordinary access after
join, and concurrent ordinary and atomic reads. This is concrete test evidence.

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

The reduced `store-const-ordering.rs` probe reaches an additional VeriFast
26.10 failure. The frontend reports `Unsupported constant value tree` on the
enum-valued ordering argument to the current intrinsic. To finish the ordinary
store proof, the verifier needs a checked treatment of that argument and the
`false` volatility parameter. Verify the three legal branches and handle the
two panic branches without weakening the public specification. The
Supercritical plan tracks the remaining store proof, the complete permission
contract, and primitive boundary review.
