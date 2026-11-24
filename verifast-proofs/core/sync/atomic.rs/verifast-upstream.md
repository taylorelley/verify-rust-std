# VeriFast changes for `core::sync::atomic`

The proofs in this directory need `verifast-26.10.patch` on top of
VeriFast 26.10 (commit `f76012fb`). The patch also applies cleanly to VeriFast
master and carries its own regression tests. This brief explains each change:
why the atomic proof needs it and why it helps VeriFast more generally. It is
written so that it can be adapted as the description of a pull request (or a
series of them) to `verifast/verifast`.

When a VeriFast release includes these changes, this directory can switch to
the repository's standard setup: set `VFVERSION` in
`verifast-proofs/setup-verifast-home`, delete `build-store-verifast.sh` and the
patch, and add `verify.sh` to `verifast-proofs/check-verifast-proofs.sh`.

## Summary

| # | Change | Kind | Unpatched 26.10 on its test |
| --- | --- | --- | --- |
| 1 | Const-generic atomic intrinsics and their contracts | Feature | `Unsupported constant value tree` |
| 2 | Sized associated-type projections | Feature | `sizedness_of_type: TODO: projection types` |
| 3 | Rustc-computed struct alignment, including generic instances | Feature | `Cannot prove alignof(...) = 2` |
| 4 | Predicate constructor arguments in assertions | Bug fix | `Type mismatch. Actual: *Wrap<V>. Expected: *T.` |
| 5 | Contracts of macro-generated functions | Bug fix (silent) | `No error found on line.`: the second expansion is never verified |
| 6 | Refinement checker: const parameters and enum constants | Feature and build fix | `Clause kind not supported` |
| 7 | Thin pointers with a generic `Sized` pointee | Feature | `atomic_xchg: expected a concrete integer or thin pointer ...` |
| 8 | `Self` in ghost code of inherent impls | Feature | `No such type parameter ...: Self` |
| 9 | Inferred type arguments in `open` and `close` of predicate constructors | Feature | `Incorrect number of type arguments` |

Each row has a test under `tests/rust`. All of them fail on unpatched 26.10 with
the error shown and pass with the patch. Together, the changes let VeriFast
verify the unmodified `core::sync::atomic` module from the current standard
library, and check it against the original with `refinement-checker`.

## 1. Const-generic atomic intrinsics

**Problem.** Since mid-2025 the standard library declares the atomic
intrinsics with the ordering as a const generic, such as
`atomic_load::<T, const ORD: AtomicOrdering, const VOLATILE: bool>`, instead of
one function per ordering (`atomic_load_acquire`). VeriFast 26.10 decodes enum
const arguments as an unsupported value tree, so any code that reaches an atomic
intrinsic, which includes all of `core::sync::atomic`, fails before proof.

**Change.**
* `specialize_atomic_access` in `vf_mir_translator.ml` decodes the
  `AtomicOrdering` argument at calls to `atomic_load`, `atomic_store`,
  `atomic_xchg`, `atomic_cxchg`, `atomic_cxchgweak`, `atomic_xadd`,
  `atomic_xsub`, `atomic_and`, `atomic_nand`, `atomic_or`, `atomic_xor`,
  `atomic_max`, `atomic_min`, `atomic_umax` and `atomic_umin`. It maps each call
  to a contract in `lib.rsspec`.
* Illegal orderings are static errors. Examples are a Release or AcqRel load,
  an Acquire or AcqRel store, and a Release or AcqRel compare-exchange failure
  ordering.
* Operands must be integers, thin raw pointers or type parameters. Literal
  `VOLATILE = true`, wide pointers, mismatched arithmetic operands and
  signedness mismatches in min and max are rejected. A generic operand or
  `VOLATILE` parameter uses the same parametric contract, which is at least as
  strong as what a volatile access requires.
* `lib.rsspec` gains contracts for these primitives, stated with the existing
  `atomic_points_to` predicate:
  * Loads accept any fraction and return a value satisfying the slot invariant.
  * Writes need permission `1` and operands that satisfy the invariant.
  * Arithmetic and bitwise operations need a slot that admits every value.
  * The byte AND, OR and XOR also accept the 0-or-1 invariant with a 0-or-1
    operand.
* The patch also adds `atomic_align_of` facts for every integer width and for
  thin pointers, and `usize::wrapping_mul`.

**Why the atomic proof needs it.** Every atomic operation reaches one of these
intrinsics. These contracts are where the proof excludes data races, misaligned
or dangling access, and invalid values.

**General benefit.**
* Any Rust code that uses atomics on a current toolchain becomes verifiable,
  for example `Arc`, locks and lock-free structures.
* The contracts generalize the existing `atomic_store_*` specs consistently.
* Rejecting illegal orderings statically mirrors the panics in the library.

**Test.** `tests/rust/purely_unsafe/atomic_intrinsics.rs` covers concrete and
generic loads, stores and exchanges, plus a store with only a read fraction,
which must fail. `atomic_intrinsics_bad_ordering.rs` covers a Release load,
which must be rejected.

## 2. Sized associated-type projections

**Problem.** `core::sync::atomic` defines
`struct Atomic<T: AtomicPrimitive> { v: UnsafeCell<T::Storage> }`. VeriFast 26.10
stops on any struct with a projection-typed field with
`sizedness_of_type: TODO: projection types`. It also never declares the typeid
function of a projection when the trait is in the crate being verified.

**Change.**
* For each local trait without generic parameters, the exporter sends the
  associated types whose item bounds include `Sized` (`sizedAssocTypes`).
  Associated types with generics of their own are left out.
* The translator declares `Trait::Assoc_typeid` for them, as `rust_parser.ml`
  already does for `type Assoc;` in `.rsspec` traits.
* `sizedness_of_type` treats a projection as sized exactly when that typeid
  function is declared. A `?Sized` associated type is still rejected.
  `.rsspec` traits cannot declare `?Sized` associated types, and the three
  existing ones (`FnOnce::Output`, `Iterator::Item`,
  `AtomicPrimitive::AtomicInner`) are `Sized` in Rust.

**Why the atomic proof needs it.** Without it, VeriFast cannot process the
atomic module at all.

**General benefit.**
* Associated-type projections in struct fields are common: storage selected by
  a trait, `PhantomData<T::Assoc>`, and generic containers keyed by a trait's
  output type.
* The change is fail-closed: anything VeriFast cannot justify still fails as
  before.

**Test.** `tests/rust/assoc_type_projection.rs` covers implicit and explicit
`Sized` bounds. The replay in this repository also checks that a `?Sized`
projection is still rejected.

## 3. Rustc-computed struct alignment

**Problem.** VeriFast's `alignof` for structs is uninterpreted. A proof cannot
show that a `#[repr(C, align(2))]` struct, or `AtomicU16`, is 2-aligned, so it
cannot discharge the alignment premise of `close_atomic_points_to_m`. For
generic structs nothing can be known, since the alignment depends on the type
arguments: here, `Atomic<i16>` stores `Align2<i16>` through a projection.

**Change.**
* For non-generic local structs, the exporter sends rustc's ABI alignment
  (`knownAlignment`). VeriFast asserts it through a `RustcAbiAlignment` struct
  attribute.
* For generic local structs, the exporter collects each instance that occurs in
  the signature of a local function, such as `Atomic<i16>` or `Atomic<*mut T>`.
  It asks rustc for the layout in that function's typing environment and sends
  the instance with its alignment (`instanceAlignments`). VeriFast asserts
  `alignof(Atomic<i16>) == 2` for a concrete instance.
* For an instance that mentions the function's type parameters, the assertion
  is quantified over them. Rustc computed the layout without knowing those
  parameters, so the result holds for every instantiation that satisfies the
  function's bounds.
* An instance gets no fact, and therefore behaves as before, in these cases:
  rustc cannot compute its layout generically; it has lifetime or const
  arguments; its arguments mention projections; or it names types the verifier
  does not know, such as `Box<str>` or `Box<ByteStr>`. VeriFast's own `vec`
  proof covers several of these cases.

**Why the atomic proof needs it.** `from_ptr` requires `ptr` to be aligned to
`align_of::<AtomicX>()`, and the atomic permission requires
`atomic_align_of::<X>()`. Linking the two needs the alignment of each instance
of the generic `Atomic<T>`.

**General benefit.**
* The compiler's layout is the ground truth, and this replaces assumptions that
  proofs would otherwise state by hand.
* It helps any proof involving over-aligned types, SIMD-aligned buffers or
  `repr(align)` wrappers, and generic wrappers whose layout is known for the
  instances used.

**Soundness note.** The facts come from rustc and are as trusted as the existing
size and offset facts. The quantified form is sound for the instantiations
rustc accepts. It also asserts the fact for type arguments that violate the
function's bounds, such as unsized `T`, for which no such instance exists. If
reviewers prefer, the fact could instead be assumed only inside the function
that mentions the instance.

**Test.** `tests/rust/instance_alignment.rs` covers concrete and generic
instances, and an instance that never appears in a signature, which must stay
unknown.

## 4. Predicate constructor arguments in assertions (bug fix)

**Problem.** In `check_asn`, a predicate-constructor assertion such as
`[f]holds::<Wrap<V>>(p)()` instantiates the predicate's parameter types with the
type arguments. It does not do the same for the constructor's own arguments.
Any generic predicate constructor whose argument type mentions its type
parameter therefore fails to type-check when applied as an assertion. The
message is `Type mismatch. Actual: *Wrap<V>. Expected: *T.`, and it appears both
with and without explicit type arguments. The same constructor works as a
`frac_borrow` argument or in `open` and `close` statements.

**Change.** One line: instantiate `ts0` with the type-argument environment
before checking the constructor arguments.

**Why the atomic proof needs it.** The constructor proofs wrap
`ref_initialized_::<Atomic<T>>(p)()` in small generic lemmas. That is the only
way to state them once for all atomic types inside a macro.

**General benefit.** This is a straightforward bug fix. Generic predicate
constructors such as `ref_initialized_`, `initialized` and `atomic_slot`
become usable in generic lemma contracts.

**Test.** `tests/rust/pred_ctor_generic_args.rs` covers explicit and inferred
type arguments, and an argument of the wrong type, which must still fail.

## 5. Contracts of macro-generated functions (bug fix)

**Problem.** All expansions of a `macro_rules!` item share the source span of
the macro body, so they also share the annotations written there. The exporter
moves each annotation to the first body whose span contains it. Later
expansions therefore have no contract. Under `-skip_specless_fns` they are
skipped **without any message**. Without the flag they are verified against an
empty contract.

**Change.** A body whose span comes from a macro expansion gets its own copy of
the annotations in its span. The shared annotations are removed once all bodies
have been encoded. Bodies outside macro expansions keep the existing behaviour.

**Why the atomic proof needs it.** `atomic_int!` generates `from_ptr` for ten
integer types on x86-64 and twelve on AArch64. Before the fix, only
`AtomicI8::from_ptr` was verified, and a proof run reported success.

**General benefit.**
* Much of the standard library, and of other crates, defines per-type methods
  with macros.
* The silent skip is a soundness-relevant usability problem: a reviewer reading
  the annotated macro would believe every expansion was checked.

**Test.** `tests/rust/macro_fn_specs.rs` uses two expansions, of which only the
second violates the shared contract. Unpatched, the test reports
`No error found on line.`

## 6. Refinement checker

**Problem.** The refinement checker fails on two features of current library
code:
* A const generic parameter (`const VOLATILE: bool`) produces a
  `ConstArgHasType` clause, which the exporter marks as ignored, and the checker
  then fails with `Clause kind not supported`.
* An enum-valued const argument (`{ AO::Acquire }`) is a branch value tree, which
  fails with `Branch not supported`.

The checker also no longer builds once the raw-pointer type gains its `is_thin`
field.

**Change.**
* The exporter encodes `ConstArgHasType` clauses, and the checker compares both
  the constant and its type.
* Branch value trees decode to a structural constant that is compared by value.
* The checker's synthetic raw-pointer types set `is_thin`.

**Why the atomic proof needs it.** The atomic proof follows the
`original/`-`verified/` layout of the other standard-library VeriFast proofs.
`refinement-checker` must accept the module. It must also reject a changed
ordering, and the replay checks that it does.

**General benefit.** Const generics with enum or struct arguments are
increasingly common. Refinement checking is how verified copies stay tied to the
real code.

**Test.** `tests/rust/refinement_checker/const_args_*.rs`: identical code must
pass, and a changed ordering must fail.

## 7. Thin pointers with a generic `Sized` pointee

**Problem.** The exporter decides whether a raw pointer is thin only for
concrete types. So `atomic_xchg::<*mut T, _>` in a function with `T: Sized` is
rejected, although the pointer is thin for every instantiation.

**Change.** In a function body, the exporter asks rustc for the pointer's layout
in that function's typing environment. `*mut T` with `T: Sized` is thin, and
`*mut T` with `T: ?Sized` is still rejected.

**General benefit.** Generic code over raw pointers, such as
`AtomicPtr<T>`-style containers and intrusive lists, can use the atomic
contracts without a concrete pointee.

**Test.** `swap_ptr` in `tests/rust/purely_unsafe/atomic_intrinsics.rs`, and
`atomic_intrinsics_wide_ptr.rs`, where the pointee is `?Sized` and the call
must still be rejected.

## 8. `Self` in ghost code of inherent impls

**Problem.** Ghost code in `impl Foo { ... }` cannot name `Self`, so a
specification inside a macro-generated impl cannot name the type it is about.
The Challenge 7 proof originally worked around this with a generic
`fix atomic_view<T>(p: *T) -> *Atomic<T>` whose type was inferred from an
argument.

**Change.**
* For a function in an inherent impl, the exporter sends the impl's self type
  (`isInherentImplFn`, `inherentImplSelfTy`).
* The translator declares a type alias for it, generic over the impl's
  parameters.
* The translator rewrites the identifier `Self` in that function's annotations
  to the alias. Trait methods, where `Self` is already a type parameter, are
  unchanged.
* The rewrite is textual, so an error inside an annotation that mentions `Self`
  is reported a few columns off. A parser-level alias would avoid that, if the
  maintainers prefer.

**General benefit.** Specifications can be written as in Rust, for example
`ptr as usize % align_of::<Self>() == 0`, in plain impls and in the
macro-generated impls that are common in the standard library.

**Test.** `tests/rust/self_in_ghost.rs` covers concrete, generic and
macro-generated impls, and a size claim about the wrong type, which must still
fail.

## 9. Inferred type arguments in `open` and `close`

**Problem.** `close C(p)()` for a generic predicate constructor `C<T>(p: *T)`
fails with `Incorrect number of type arguments`, even though `T` follows from
`p`. Assertions already infer such arguments.

**Change.** When no type arguments are given, `open` and `close` create
inference variables for them and resolve them from the constructor arguments.
A type argument that cannot be inferred is reported as such.

**General benefit.** Proofs no longer need explicit type arguments, which are
especially awkward inside macros.

**Test.** `tests/rust/pred_ctor_infer_targs.rs` covers an inferred round trip,
and a constructor whose type parameter does not occur in its arguments, which
must still fail.

## Not included: per-instance sharing predicates

The safe methods of `AtomicBool` and the integer atomics take `&self`, so
their semantic well-typedness needs `<Atomic<T>>.share`.

* VeriFast requires one generic definition, and a `share_full` lemma proved for
  all `T`.
* That lemma must turn plain ownership into an atomic permission at the operand
  type. That is `u8` restricted to 0 and 1 for `bool`, and `T` otherwise,
  reached through `T::Storage`.
* That cannot be expressed generically without changing how VeriFast models
  safe types.
* `AtomicPrimitive` is `impl(self)`, so its instances form a closed set.

Two designs would close the gap:
* per-instance type predicate definitions and proof obligations for structs
  generic over a sealed trait;
* or normalization of associated types through local impls, together with
  provable typeid distinctness and exhaustiveness over the sealed trait's
  impls.

A related, separate problem is that the methods take the permission out of a
shared borrow before calling a helper that may panic. The helper contracts
would therefore also need a form that takes the borrowed permission and opens
it only in branches that do not unwind.

Until the maintainers settle on a design, the public atomic methods are
checked through specialized copies and compiled-code comparison.

## Suggested pull requests

The changes are independent enough to review separately. A possible order:

1. Item 4, the predicate-constructor fix, and item 5, the macro contract fix.
   These are small bug fixes with tests. Item 9 fits with them.
2. Item 2, associated-type projections, and item 8, `Self` in ghost code.
3. Item 6, the refinement checker.
4. Item 3, compiler-exported alignment.
5. Item 1, const-generic atomic intrinsics and their contracts, with item 7. This item adds
   trusted specifications and will need the closest review.

`tests/rust/testsuite.mysh` and `tests/rust/refinement_checker/testsuite.mysh`
register the new tests. With the whole patch applied to 26.10 and the
`nightly-2026-09-25` toolchain, both suites pass on Linux x86-64 with 0 failed
processes. That includes the existing `safe_abstraction/vec` proof, which
verifies the same 2,523 statements as the release. Only the Rust suites were
run. The C and Java suites, and macOS and Windows, should go through VeriFast's
own CI.
