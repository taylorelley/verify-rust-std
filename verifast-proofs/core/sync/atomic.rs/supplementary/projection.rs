use std::cell::UnsafeCell;

pub trait AtomicPrimitive {
    type Storage: Sized;
}

#[repr(C)]
pub struct Atomic<T: AtomicPrimitive> {
    v: UnsafeCell<T::Storage>,
}

pub fn smoke()
//@ req true;
//@ ens true;
{}
