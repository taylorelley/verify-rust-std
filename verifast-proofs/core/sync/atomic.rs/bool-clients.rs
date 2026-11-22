use std::sync::atomic::{AtomicBool, Ordering};
use std::thread;

const _: () = {
    assert!(size_of::<AtomicBool>() == size_of::<bool>());
    assert!(align_of::<AtomicBool>() == align_of::<bool>());
};

#[test]
fn sharing_allows_atomic_stores_and_recovers_ordinary_access_after_join() {
    for initial in [false, true] {
        let mut backing = initial;
        thread::scope(|scope| {
            let first = unsafe { AtomicBool::from_ptr(&raw mut backing) };
            assert_eq!(first.load(Ordering::Relaxed), initial);
            for order in [Ordering::Relaxed, Ordering::Release, Ordering::SeqCst] {
                scope.spawn(move || first.store(!initial, order));
                scope.spawn(move || first.store(!initial, order));
            }
        });
        assert_eq!(backing, !initial);
        backing = initial;
        assert_eq!(backing, initial);
    }
}

#[test]
fn initialized_storage_allows_concurrent_atomic_and_ordinary_reads() {
    for initial in [false, true] {
        let mut backing = initial;
        thread::scope(|scope| {
            let atomic = unsafe { AtomicBool::from_ptr(&raw mut backing) };
            scope.spawn(move || assert_eq!(atomic.load(Ordering::Relaxed), initial));
            scope.spawn(move || {
                let ordinary = atomic.as_ptr();
                assert_eq!(unsafe { ordinary.read() }, initial);
            });
        });
    }
}
