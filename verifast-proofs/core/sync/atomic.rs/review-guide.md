# Challenge 7 proof review

Open the **VeriFast Challenge 7** check on the submission PR and download
`challenge-7-evidence`. For an independent run, use the two toolchain installs
and the replay command in the [README](README.md#full-replay-in-ci).
The paths below are relative to the extracted artifact or the local
`evidence/` directory.

1. **Identify the run.** `toolchains-and-patch.txt` records the checkout,
   both rustc versions and the hashes of the atomic source, intrinsic declarations
   and VeriFast patch. GitHub may check out the PR's test merge commit.
   `build.log` records the verifier build. The replay writes `result.log`
   only after all proof steps, rejection controls, native clients and Miri runs pass.
2. **Part 1 — follow one constructor end to end.** In `constructors/coverage.json`,
   find `AtomicU128` on AArch64. Open `constructors/u128/verified.rs` for the
   entry contract, reference creation and storage recovery. Compare the
   `from_ptr` bodies in `original-constructor.mir` and `specialized-constructor.mir`
   in that directory. In `proof.log`, look for `Verifying function 'AtomicU128::from_ptr'`
   and `0 errors found`. In `live-recovery.log`, look for the missing
   `lifetime_dead_token`: the attempted early recovery has to fail.
   For an arbitrary stored pointer to a three-byte pointee, inspect
   `constructors/ptr/constructor-3/verified.rs` and `constructors/ptr/proof-3.log`.
3. **Parts 2 and 3 — follow one call.** In `generic-helpers/coverage.json`,
   look up `atomic_store_relaxed` under `intrinsic_lines_in_generic_helpers_rs`.
   The listed line in `generic-helpers/generic-helpers.rs` calls the modern
   const-generic intrinsic inside the extracted `atomic_store` helper. The
   positive VeriFast trace in `generic-helpers/generic-helpers.log` records
   `Verifying call` at that source span. Open `lib.rsspec` for the installed
   `atomic_store_relaxed` contract, then `generic-helpers/store-read-fraction.log`
   for the rejection when the underlying byte permission is halved. The
   replay cross-checks visited calls against every ordering variant in the
   challenge table. The 14 named helpers appear under `required_helpers`.
   The suite also verifies `atomic_min`, whose intrinsic is listed in Part 3.
4. **Inspect the data-race argument.** `u16-mixed-width/proof.log` verifies
   accesses to disjoint storage. `overlap-first-byte.log` and
   `overlap-second-byte.log` in the same directory give the expected
   permission failures for overlapping accesses. The trusted rule connecting
   these failures to Rust memory is described below. Native and Miri logs
   provide separate observations of the threaded clients.

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
   in the installed `lib.rsspec`. Some of these rules come from stock VeriFast 26.10. An atomic permission
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
3. **Source comparison.** The required Part 1 constructors are the only
   required Rust bodies proved with concrete replacements for their receiver
   types. The source check matches the exact cast expression. Rustc
   type-checks the original `UnsafeCell` field and associated storage choice
   for each instantiation and checks size, alignment and offset on both
   sides. The saved constructor MIR compares runtime and const-evaluation
   paths, including the raw-pointer-to-reference operation and unwind edges.
   For pointer constructors the check substitutes the sized `Pointee` for
   `T` and runs for each of the five required layouts. The proof uses the
   corresponding points-to predicates and preserves the allocation's
   address, provenance and borrow lifetime. The positive checks run on the
   same generated constructors whose bodies the verifier proves.

   Part 2 verifies the named unsafe helpers extracted from the actual
   `atomic.rs`. The ordinary load and store specialization substitutes
   `false` for `VOLATILE` and checks that no use of the parameter remains.
   Part 3 attaches trusted contracts to the compiler primitives these
   helpers actually call. Review the primitive specifications and frontend
   dispatch under item 2.

   The separate public-wrapper matrix checks additional integration and
   panic behavior. Optimized LLVM comparisons retain function signatures,
   resolved function and call-site attributes, pointer and value operands,
   orderings and panic branches. The AArch64 controls check both changing
   the receiver alignment and adding `nounwind` to a panic call. General
   Rust-level refinement of this additional matrix remains outside these
   comparisons.
4. **Scope of the claims.** The verified ordinary operations exclude the
   listed undefined behaviors under the trusted contracts and source
   correspondence argument. Native and Miri tests exercise functional
   results such as arithmetic and strong versus weak compare-exchange.
   The atomic model treats stored pointer values as opaque and abstracts
   from synchronization behavior.

## Decisions for the committee

The submission relies on the patched VeriFast frontend and primitive
contracts. Its load and store claims cover ordinary accesses
(`VOLATILE=false`). The constructor argument specializes the associated
storage type because the frontend cannot translate the original generic
projection. The source cast, storage type, layout and MIR checks above
are the evidence for that substitution. These are the material assumptions
to assess when deciding whether the proof satisfies the challenge.
