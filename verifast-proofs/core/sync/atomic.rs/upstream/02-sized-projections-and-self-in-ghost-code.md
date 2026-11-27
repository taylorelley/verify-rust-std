# Rust: sized associated-type projections, and `Self` in inherent impls

Stacked on patch 01.

## Sized associated-type projections

`struct Atomic<T: AtomicPrimitive> { v: UnsafeCell<T::Storage> }` makes 26.10 stop
with `sizedness_of_type: TODO: projection types`. Typeid functions of
projections are also never declared when the trait is in the crate being
verified.

**Change.**
* The exporter sends, for each local trait without generic parameters, the
  associated types whose item bounds include `Sized` (`sizedAssocTypes`).
* The translator declares `Trait::Assoc_typeid` for them, as `rust_parser.ml`
  already does for `type Assoc;` in `.rsspec` traits.
* `sizedness_of_type` treats a projection as sized exactly when that typeid is
  declared. `?Sized` associated types are still rejected (fail-closed).
* Associated types of traits in imported `.rsspec` files, such as
  `<I as Iterator>::Item`, are also sized. A `.rsspec` trait cannot declare a
  `?Sized` associated type, so each one denotes a `Sized` type. This holds for
  the three that exist today: `FnOnce::Output`, `Iterator::Item` and
  `AtomicPrimitive::AtomicInner`. Adding a `.rsspec` trait whose Rust
  associated type is `?Sized`, such as `Deref::Target`, would need a way to say
  so first.

**Test.** `tests/rust/assoc_type_projection.rs` covers implicit and explicit
`Sized` bounds, and a projection of `Iterator::Item`.

## `Self` in ghost code of inherent impls

Ghost code in `impl Foo { ... }` cannot name `Self`, which is awkward in
macro-generated impls, where the type has no other name in the macro body.

**Change.** The exporter sends the impl's self type for functions in inherent
impls (`isInherentImplFn`, `inherentImplSelfTy`). The translator declares a
type alias for it, generic over the impl's parameters, and rewrites `Self` in
that function's annotations to the alias. Trait methods are unchanged. The
rewrite is textual, so an error inside an annotation that mentions `Self` is
reported a few columns off. A parser-level alias would avoid that if preferred.

**Test.** `tests/rust/self_in_ghost.rs`: concrete, generic and macro-generated
impls, and a wrong size claim that must still fail.
