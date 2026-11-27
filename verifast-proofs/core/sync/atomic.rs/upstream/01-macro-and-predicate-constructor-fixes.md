# Rust: verify every macro expansion, and fix generic predicate constructor arguments

Three small fixes, each with a regression test that fails on 26.10.

## Contracts of macro-generated functions are silently dropped

All expansions of a `macro_rules!` item share the source span of the macro
body, and therefore the annotations written there. The exporter moves each
annotation to the *first* body whose span contains it. Later expansions get no
contract. Under `-skip_specless_fns` they are skipped **without any message**,
and without it they are verified against an empty contract.

A reviewer who reads an annotated macro would reasonably believe every
expansion was checked. For example, `core::sync::atomic` generates `from_ptr`
for ten integer types through `atomic_int!`, and only `AtomicI8::from_ptr` was
actually verified.

**Change.** A body whose span comes from a macro expansion gets its own copy of
the annotations in its span. The shared annotations are removed once all bodies
have been encoded. Bodies outside macro expansions keep the existing behavior.

**Test.** `tests/rust/macro_fn_specs.rs`: of two expansions, only the second
violates the shared contract. Unpatched: `No error found on line.`

## Predicate constructor arguments in assertions

`[f]holds::<Wrap<V>>(p)()` instantiates the predicate's parameter types, but
not the types of the constructor's own arguments. A generic predicate
constructor whose argument type mentions its type parameter therefore fails as
an assertion: `Type mismatch. Actual: *Wrap<V>. Expected: *T.` The same
constructor works as a `frac_borrow` argument and in `open`/`close`.

**Change.** Instantiate the argument types with the type-argument environment
before checking the arguments (`verifast1.ml`).

**Test.** `tests/rust/pred_ctor_generic_args.rs`.

## Inferred type arguments in `open` and `close`

`close C(p)()` for `pred_ctor C<T>(p: *T)()` fails with
`Incorrect number of type arguments`, although `T` follows from `p`.
Assertions already infer such arguments.

**Change.** Without explicit type arguments, `open` and `close` create inference
variables and resolve them from the arguments. A type argument that cannot be
inferred is reported as such (`verifast.ml`).

**Test.** `tests/rust/pred_ctor_infer_targs.rs`.
