# VeriFast upstream series

`verifast-26.10.patch` split into five stacked pull requests for
`verifast/verifast`, in the order suggested in
[`../verifast-upstream.md`](../verifast-upstream.md). Each `NN-*.patch` applies
with `git apply` on top of VeriFast 26.10 (`f76012fb`) plus the earlier patches,
and `NN-*.md` is its pull request description. Applying all five gives exactly
`../verifast-26.10.patch`.

| # | Patch | Kind |
| --- | --- | --- |
| 01 | Macro expansions and predicate-constructor fixes | Bug fixes (one silent) |
| 02 | Sized associated-type projections, `Self` in inherent impls | Features |
| 03 | Refinement checker: const arguments | Feature |
| 04 | Struct alignment computed by rustc | Feature (trusted facts) |
| 05 | Const-generic atomic intrinsics | Feature (trusted specifications) |

Each stage builds on its own, and VeriFast's Rust test suite
(`tests/rust/testsuite.mysh`, which includes the refinement-checker suite)
passes at every stage on Linux x86-64 with `nightly-2026-09-25`.
