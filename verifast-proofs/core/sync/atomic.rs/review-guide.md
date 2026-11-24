# Challenge 7 proof review

Review the pinned Rust source, the generated proof specializations and the
patched verifier together. The replay checks the Rust source and intrinsic
definitions, rebuilds the verifier from checksum-pinned archives and saves
proof logs, compiler IR, negative controls and runtime test results.

## Evidence for the required safety properties

| Challenge property | Where to start | What to check |
| --- | --- | --- |
| Part 1 constructor contracts | `verified/atomic.rs`, the `module-*` coverage logs and the `ctor-*` controls | Each contract encodes the `# Safety` section: alignment to `align_of::<AtomicX>()`, a valid location for `'a`, and only atomic access while the reference lives. |
| Part 2 helper contracts | `verified/atomic.rs`, `verify.sh` and the `library-module` log | `diff original/atomic.rs verified/atomic.rs` shows only the contracts. Each contract requires the slot permission the operation needs. |
| Optional panic contracts | `generic-helpers/coverage.json` and `generic-helpers-no-panic.rs` | The no-panic run excludes exactly the orderings that panic. |
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

## Comparison with the merged VeriFast solutions

The Challenge 5 (`LinkedList`) and Challenge 19 (`RawVec`) proofs set the
conventions this proof follows.

| | Challenges 5 and 19 | Challenge 7 |
| --- | --- | --- |
| Layout | `original/`, `verified/`, `verify.sh`, `update.sh` | The same, for the 14 constructors and the 15 helpers. The public wrappers use specialized copies with compiled MIR and LLVM comparison. |
| Link to `library/` | `refinement-checker` and `diff` | `refinement-checker`, and `diff` after the diagnostic-item attribute rewrite |
| Source changes in `verified/` | Small rewrites to place ghost commands, refinement-checked | None. Only contracts are added. |
| VeriFast flags | `-skip_specless_fns`, with `-ignore_unwind_paths` and `-allow_assume` for Challenge 5 | `-skip_specless_fns` only. Unwind paths are verified and no `assume` is used. |
| Targets | Linux x86-64 | Linux x86-64, plus AArch64 Linux for the 128-bit types, with Miri on both |
| Trusted specs | VeriFast's library specs, reviewed in verifast/verifast#863 | The same library, plus the atomic primitive contracts added by the patch |
| VeriFast version | A released version | 26.10 with a patch, until a release includes it (`verifast-upstream.md`) |

## Review status

The replay is automated and reproducible from the pinned inputs. The
committee review should focus on the trusted contracts (item 2), the frontend
patch, and the specialization comparisons for the public wrappers (item 3).
