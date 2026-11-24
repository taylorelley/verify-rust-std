# Supplementary notes: scoped threads

These checks are not part of the Challenge 7 claim. Challenge 7 covers the
atomic constructors, the unsafe helpers and the intrinsics, which
[`README.md`](README.md) lists. The threaded runtime clients in this directory
use `std::thread::scope` to exercise concurrent atomic and non-atomic reads.
The notes below record what VeriFast 26.10 can and cannot check about that API,
and two abstract models of its thread counter. The `scoped-thread-boundary`,
`scoped-counter` and `scoped-composition` replay steps run them.

One finding may interest the standard library maintainers independently of
Challenge 7. It is the `spawn_unchecked` overflow case described under
"Packet ownership" below.

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

## Scoped counter model and lifecycle clients

The Z3 queries in `check-scope-counter.py` use the same solver bundled
with the pinned VeriFast dependencies. They check a separate abstraction
for both 32-bit and 64-bit counters. The runner pins `scoped.rs` and
`lifecycle.rs` and records each query and result. The source correspondence
to review is:

| Pinned Rust event | Model transition |
| --- | --- |
| `increment_num_running_threads` increments before checking the old count | Reserve a pending unit. Successful admission uses the old count's `usize::MAX / 2` cutoff. |
| Admission succeeds | Transfer a pending unit to a live packet obligation without changing the count. |
| `overflow` calls the decrement routine before panicking | Remove the rejected pending reservation. |
| `Packet::drop` drops the unconsumed result before decrementing | Retire a live packet obligation. |
| The decrement returns an old count of one | Notify the waiter after the last obligation is retired. |
| `scope` observes zero with an Acquire load after the callback | The abstract model has neither a pending reservation nor a live packet obligation. |

The claims assume a supplied live or pending obligation when decrementing
and capacity for each reservation without machine-word wraparound. The
queries test the feasibility of these premises and include counterexamples for
lost reservations, incorrect notifications and increments at capacity. The
model does not prove the global capacity bound, the correspondence between
`Arc` ownership and packet retirement, the Acquire/Release edge, or Rust
callback and panic semantics.

The separate `scope-lifecycle-client.rs` uses the real standard library
methods. Native Rust and Miri check nested borrowing and joining, the
scope callback unwinding, worker panic propagation and consumption,
and waiting for a borrowed result's destructor after dropping the handle.

## Packet ownership, publication and the overflow case

The normal-path packet model in `check-scope-composition.py` checks both
drop orders and the explicit join route. It also models a failed launch
dropping both packet owners. The model assumes that `Arc` runs
`Packet::drop` exactly once when the last strong owner releases it and that
native join completes before the explicit join reads the packet. It checks
that a published result is taken or destroyed before the modeled retirement.
A mutation that retires when the parent drops its handle while the worker
still holds the packet is rejected.

The counter is modified using atomic read-modify-write operations after
initialization. For an Acquire exit load that reads the final modification,
each preceding Release decrement in the unbroken sequence synchronizes
with the load. Write-read coherence prevents that load from reading the
initial zero if a root reservation happens before it. The queries use
these memory-model rules as premises and include controls for Relaxed
loads, Relaxed decrements and an intervening non-RMW store.
[Rust atomic memory model](https://doc.rust-lang.org/std/sync/atomic/index.html#memory-model-for-atomic-accesses) · [C++ release sequences and coherence](https://eel.is/c++draft/intro.races) · [C++ atomic ordering](https://eel.is/c++draft/atomics.order)

One accounting case still needs a source proof. In `spawn_unchecked`, the
packet and both owners exist before the counter increment. If the admission
cutoff is exceeded, `overflow` compensates for the increment and panics.
With unwinding, the packet can then reach its destructor before any native
thread starts, and the destructor contains a second decrement. The Z3
control checks that this conditional sequence would leave the count one
below its starting value. The check establishes the accounting consequence
under its premise. Reachability on a supported target is open.

A sufficient capacity bound follows if every counted obligation maps to
a distinct, live, word-aligned packet allocation. The model checks that
the number of available aligned addresses is below the admission cutoff
for both word widths. The pinned `ArcInner` has two atomic counts and
`Arc::new` allocates the inner value in a box. A source proof still needs
to establish the allocation-to-obligation mapping and show it remains valid
across reservation, launch, retirement, and unwind. Track that proof
separately from the abstract arithmetic bound.

## Earlier replay

[An ARM64 macOS 15 replay](https://github.com/taylorelley/verify-rust-std/actions/runs/45059674164)
ran the scripts and patched VeriFast build from
[PR #675](https://github.com/model-checking/verify-rust-std/pull/675) against
the source of that time. The only workflow change was the runner label. The
artifact digest was
`151c8817dc3561a213b4241e7ff8ff7c7214d19b4597fcf8a1a44325c2332458`.
