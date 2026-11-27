#![feature(core_intrinsics)]
#![allow(internal_features)]

use std::intrinsics::{self, AtomicOrdering};

// Front-end reproducer. The contract is the primitive's memory obligation.
pub unsafe fn store_relaxed(dst: *mut u8, value: u8)
//@ req [?f]std::intrinsics::atomic_points_to(dst, 1, ?valid) &*& valid(value) == true;
//@ ens [f]std::intrinsics::atomic_points_to(dst, 1, valid);
//@ on_unwind_ens false;
{
    unsafe { intrinsics::atomic_store::<u8, { AtomicOrdering::Relaxed }, false>(dst, value) };
}
