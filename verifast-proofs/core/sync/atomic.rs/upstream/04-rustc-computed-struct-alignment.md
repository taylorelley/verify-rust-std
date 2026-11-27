# Rust: struct alignment computed by rustc

VeriFast's `alignof` for structs is uninterpreted, so a proof cannot show that a
`#[repr(C, align(2))]` struct, or `AtomicU16`, is 2-aligned. For generic structs,
the alignment depends on the type arguments.

**Change.**
* For non-generic local structs, the exporter sends rustc's ABI alignment
  (`knownAlignment`). VeriFast asserts it through a `RustcAbiAlignment` struct
  attribute.
* For generic local structs, the exporter collects each instance that occurs in
  the signature of a local function (such as `Atomic<i16>` or `Atomic<*mut T>`),
  asks rustc for the layout in that function's typing environment, and sends it
  (`instanceAlignments`). VeriFast asserts the alignment of a concrete instance,
  and a fact quantified over the function's type parameters for an instance that
  mentions them.
* No fact is produced if rustc cannot compute the layout generically, for
  lifetime or const arguments, for projections in the arguments, or for types
  VeriFast does not know. VeriFast's own `vec` proof exercises these cases and
  still verifies the same statements.

**Soundness note.** The facts are as trusted as the existing size and offset
facts. The quantified form also covers type arguments that violate the
function's bounds (for example unsized `T`), for which no such instance exists.
If preferred, the fact could be assumed only inside the function that mentions
the instance.

**Test.** `tests/rust/instance_alignment.rs`: concrete and generic instances,
and an instance that never appears in a signature, which must stay unknown.
