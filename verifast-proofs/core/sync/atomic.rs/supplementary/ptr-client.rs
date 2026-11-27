use std::mem::size_of;
use std::ptr::{null_mut, without_provenance_mut, NonNull};
use std::sync::atomic::{AtomicPtr, Ordering};

fn check_slot<T>(live: &mut T) {
    for value in [
        null_mut(),
        NonNull::<T>::dangling().as_ptr(),
        without_provenance_mut(usize::MAX),
        live as *mut T,
    ] {
        let mut slot = value;
        let ptr = &raw mut slot;
        {
            let first = unsafe { AtomicPtr::from_ptr(ptr) };
            let second = unsafe { AtomicPtr::from_ptr(ptr) };
            assert_eq!(first.as_ptr(), ptr);
            assert_eq!(second.load(Ordering::Relaxed), value);
        }
        assert_eq!(slot, value);
    }
}

#[test]
fn pointer_value_does_not_constrain_slot_conversion() {
    assert_eq!(size_of::<[u8; 3]>(), 3);
    check_slot(&mut ());
    check_slot(&mut 0_u8);
    check_slot(&mut 0_u16);
    check_slot(&mut [0_u8; 3]);
    check_slot(&mut 0_u32);
}

#[test]
fn live_pointer_survives_every_ordinary_ordering_pair() {
    let mut value = 42_u32;
    let pointer = &raw mut value;
    let slot = AtomicPtr::new(null_mut());

    for store_order in [Ordering::Relaxed, Ordering::Release, Ordering::SeqCst] {
        slot.store(pointer, store_order);
        for load_order in [Ordering::Relaxed, Ordering::Acquire, Ordering::SeqCst] {
            let loaded = slot.load(load_order);
            assert_eq!(loaded, pointer);
            // The allocation is still live and has no competing accesses.
            assert_eq!(unsafe { *loaded }, 42);
        }
    }
}
