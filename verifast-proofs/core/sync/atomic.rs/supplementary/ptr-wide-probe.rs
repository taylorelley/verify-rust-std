#![feature(core_intrinsics)]
#![allow(internal_features)]
use std::intrinsics::{self, AtomicOrdering as AO};
unsafe fn load_wide(src: *const *mut [u8]) -> *mut [u8]
//@ req true;
//@ ens true;
{
    unsafe { intrinsics::atomic_load::<*mut [u8], { AO::Relaxed }, false>(src) }
}
