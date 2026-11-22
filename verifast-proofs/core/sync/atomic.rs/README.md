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

## Proof obligations

The proposed Boolean argument uses a lifetime-bound share over the byte range,
an initialized value in `{0, 1}`, and the permission required to write through the
three ordinary store intrinsics. It must establish permission recovery and
compatibility with documented read/read sharing. The proof must reject conflicting
ordinary access, invalid Boolean bytes, and outliving the backing allocation.
The solver must exercise those controls and identify why each is rejected.

The missing verifier feature is associated-type projection in struct fields.
A workable alternative could specialize the proof input to `Atomic<bool>`.
This requires a separately checked connection for concrete layout, field and
pointer projections, lifetimes, and ordinary intrinsic calls at the selected
target. The historical source hash and the current identity refinement check
provide no such connection. The Supercritical plan keeps the Boolean permission
proof and primitive boundary review open.
