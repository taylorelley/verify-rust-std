# Challenge 7 proof review

Review the pinned Rust source, the generated proof specializations and the
patched verifier together. The replay checks the Rust source and intrinsic
definitions, rebuilds the verifier from checksum-pinned archives and saves
proof logs, compiler IR, negative controls and runtime test results.

## Evidence for the required safety properties

| Challenge property | Where to start | What to check |
| --- | --- | --- |
| Generic helper contracts | `generic-helpers/coverage.json`, `generic-helpers.rs` and its controls | The 15 bodies match `atomic.rs` exactly, apart from attributes. Each contract requires the slot permission the operation needs, and the no-panic run excludes exactly the orderings that panic. |
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
   distinguish strong from weak behavior. The frontend dispatch
   (`specialize_atomic_access` in the patch) maps each intrinsic call with a
   concrete ordering to one of these contracts. For a generic operand type or
   `VOLATILE` flag, it uses the same parametric contract. Check that the
   dispatch rejects every illegal ordering.
3. **Source comparison.** The generic helpers need no comparison, since
   `check-generic-helpers.py` verifies the library text itself. Review the compiler input and target guards, layout
   assertions, wrapper generation and normalization in each replay script.
   Constructor checks compare compiler output and layout. Operation checks
   compare optimized LLVM dispatch. Look at the retained pointer and value
   operands, orderings and panic branches. The script may remove generated
   names, metadata IDs, panic locations or follow identical LLVM aliases.
   Check that each mutation changes a field the comparison retains. The
   comparisons are specific to the pinned source, compiler and targets.
4. **Scope of the claims.** The proof establishes the absence of the
   Challenge 7 undefined behaviors under the trusted contracts. Functional
   results, such as the arithmetic result or strong versus weak
   compare-exchange, have native and Miri evidence. The proof makes no claim
   about synchronization or about the pointer values stored in an `AtomicPtr`.

## Review status

The replay is automated and reproducible from the pinned inputs. The
committee review should focus on the trusted contracts (item 2), the frontend
patch, and the specialization comparisons for the public wrappers (item 3).
