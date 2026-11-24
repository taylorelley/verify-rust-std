# Challenge 7 proof review

Review the pinned Rust source, the generated proof specializations and the
patched verifier together. The replay checks the Rust source and intrinsic
definitions, rebuilds the verifier from checksum-pinned archives and saves
proof logs, compiler IR, negative controls and runtime test results.

## Evidence for the required safety properties

| Challenge property | Where to start | What to check |
| --- | --- | --- |
| Live, aligned access | `constructors/coverage.json` and the constructor layout and alignment controls | The constructor obtains permission for the same slot address at the target's required alignment and retains it for the lifetime of the reference. |
| Initialized storage | Constructor `uninitialized` controls and the Boolean and pointer missing-storage controls | A fresh conversion needs a live, initialized points-to resource. A reused conversion needs an existing share. |
| Conflicting accesses | Boolean mixed-access and scoped-reference proofs, the two U16 overlap controls, and the integer fractional-write controls | A read can use fractional byte ownership. A write requires full underlying byte permission. Scope recovery requires the lifetime to end. |
| Valid values | Boolean constructor, bitwise and compare-exchange controls, plus the integer and pointer matrices | Boolean storage admits only 0 and 1. Check the XOR and swap routes in Boolean NAND. Pointer slot permission gives no permission to dereference the stored pointer. |
| Legal intrinsic calls | Compiler dispatch IR, the volatile and illegal-order controls, and the extrema signedness controls | The decoder admits the expected concrete types and orderings. The invalid public ordering paths panic while retaining the lifetime and thread tokens. |

The constructors use the x86-64 Linux target, except for the two 128-bit
integer constructors on AArch64 Linux. The signed and unsigned pointer-width
integers are extra cases. The pointer constructor and operation fixtures use
pointee byte sizes 0, 1, 2, 3 and 4. The native Boolean implementation is in
scope on these targets.

## Trusted contracts

1. **Atomic permissions.** Review the abstract `atomic_points_to` predicate,
   `close_atomic_points_to_m`, `open_atomic_points_to` and the alignment lemmas
   in the VeriFast patch. The key obligation is that an atomic permission
   accounts for the same initialized bytes as the original points-to resource.
   Check how the underlying byte fraction differs from the fraction on a
   shared atomic assertion, and how each is restored. Review the compiler
   layout check for thin pointers and the concrete alignment assumptions for
   both targets.
2. **Primitive effects.** Review the trusted contracts in the patched
   `bin/rust/std/lib.rsspec`. Loads return a value satisfying the invariant.
   Store, exchange and compare-exchange require admitted values. Arithmetic
   and general bitwise operations require unrestricted slots. AND, OR and XOR
   additionally support a Boolean byte with an admitted input. Minimum and
   maximum select from two admitted values. The compare-exchange contracts
   allow either outcome in the safety model. Source and runtime checks
   distinguish strong from weak behavior.
3. **Source comparison.** Review the compiler input and target guards, layout
   assertions, wrapper generation and normalization in each replay script.
   Constructor checks compare compiler output and layout. Operation checks
   compare optimized LLVM dispatch. Look at the retained pointer and value
   operands, orderings and panic branches. The script may remove generated
   names, metadata IDs, panic locations or follow identical LLVM aliases.
   Check that each mutation changes a field the comparison retains. The
   comparisons are specific to the pinned source, compiler and targets.
4. **Scope of the claims.** The proof establishes safety under the trusted
   contracts. Functional results, concrete pointer provenance and scoped
   thread execution have native or Miri evidence where the clients exercise
   them. The proof does not establish a general synchronization or pointer
   provenance theorem. Review the reported gaps before claiming full
   Challenge 7 coverage.

## Scoped threads

The replay records a successful proof of a simple function as a control.
Rust accepts all the scoped-thread probe programs. VeriFast reports
unsupported closure arguments at `thread::scope`, unsupported function items
as values when named callbacks are passed to `scope` and `Scope::spawn`, and
unsupported dynamic types when checking `ScopedJoinHandle::join`. The join
result carries a boxed dynamic panic payload. These probes record why the
full formal obligation remains open.

A proof against the actual scoped API needs a verifier that represents the
callback and join signatures and models the contracts for `scope`, `spawn`
and `join`. Review permission transfer into each worker and recovery after
join, including panic paths. The existing reference fixture proves the
permission protocol for its modeled scope. The threaded runtime clients
exercise the real API under native Rust and Miri.

## Review status

This guide is an author audit. Independent review of the trusted contracts
and source comparisons remains open. Keep the real scoped-thread proof
obligation open until a proof checks the actual API.
