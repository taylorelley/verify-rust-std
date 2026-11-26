# Challenge 7 proof review

Review the pinned Rust source, the generated proof specializations and the
patched verifier together. The replay checks the Rust source and intrinsic
definitions, rebuilds the verifier from checksum-pinned archives and saves
proof logs, compiler IR, negative controls and runtime test results.

## Evidence for the required safety properties

| Challenge property | Where to start | What to check |
| --- | --- | --- |
| Generic helper contracts | `generic-helpers/coverage.json`, `generic-helpers.rs` and its controls | The 15 bodies come from `atomic.rs`. The load and store proof substitutes `false` for the access flag. Each contract requires the slot permission the operation needs, and the no-panic run excludes exactly the orderings that panic. |
| Live, aligned access | `constructors/coverage.json` and the constructor layout and alignment controls | The constructor obtains permission for the same slot address at the target's required alignment and retains it for the lifetime of the reference. |
| Initialized storage | Constructor `uninitialized` controls and the Boolean and pointer missing-storage controls | A fresh conversion needs a live, initialized points-to resource. A reused conversion needs an existing share. |
| Conflicting accesses | Boolean mixed-access and scoped-reference proofs, the two U16 overlap controls, and the integer fractional-write controls | On the two checked targets a Relaxed load of at most eight bytes can use fractional byte ownership. Other loads and writes require full underlying byte permission. Scope recovery requires the lifetime to end. |
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
   `bin/rust/std/lib.rsspec`. Loads return a value satisfying the invariant. The full byte fraction denotes writable backing for loads that may fault on physically read-only storage. This interpretation covers ordinary Rust storage in the proof. The concrete control checks 128-bit Relaxed loads, and Acquire loads of every integer width.
   Store, exchange and compare-exchange require admitted values. Arithmetic
   and general bitwise operations require unrestricted slots. AND, OR and XOR
   additionally support a Boolean byte with an admitted input. Minimum and
   maximum select from two admitted values. The compare-exchange contracts
   allow either outcome in the safety model. Source and runtime checks
   distinguish strong from weak behavior. The frontend dispatch
   (`specialize_atomic_access` in the patch) maps each intrinsic call with a
   concrete ordering to one of these contracts. For generic operand types the argument applies to legal monomorphizations.
   Rustc checks the operand shape during code generation. The frontend
   rejects unresolved volatility. Check that the
   dispatch rejects every illegal ordering.
3. **Source comparison.** Review how `check-generic-helpers.py` extracts
   the helper bodies and specializes the access flag. The constructor suite
   checks the cast in the Rust source before checking layout and compiler
   output. Operation checks compare optimized LLVM dispatch, including the
   function signature, resolved attributes, pointer and value operands,
   orderings and panic branches. The 128-bit control changes the LLVM
   receiver alignment from 16 to 32 bytes. The scripts can remove generated
   names, metadata IDs and panic locations or follow LLVM aliases.
   The comparisons apply to the pinned source, compiler and targets. The
   Rust-level refinement argument still needs to account for conditions
   that optimized LLVM may erase or assume.
4. **Scope of the claims.** The verified ordinary operations exclude the
   listed undefined behaviors under the trusted contracts and source
   correspondence argument. Native and Miri tests exercise functional
   results such as arithmetic and strong versus weak compare-exchange.
   The atomic model treats stored pointer values as opaque and abstracts
   from synchronization behavior.

## Review status

The replay is automated and reproducible from the pinned inputs. The
committee review should focus on the trusted contracts (item 2), the frontend
patch, and the specialization comparisons for the public wrappers (item 3).
