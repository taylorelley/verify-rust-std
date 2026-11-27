#![cfg(test)]
#![cfg_attr(target_has_atomic = "128", feature(integer_atomics))]

use std::fmt::Debug;
use std::panic::catch_unwind;
use std::ptr::null_mut;
use std::sync::atomic::{self, AtomicBool, AtomicPtr, AtomicU16, Ordering};

const SUCCESS: [Ordering; 5] = [
    Ordering::Relaxed,
    Ordering::Acquire,
    Ordering::Release,
    Ordering::AcqRel,
    Ordering::SeqCst,
];
const FAILURE: [Ordering; 3] = [Ordering::Relaxed, Ordering::Acquire, Ordering::SeqCst];

macro_rules! check_operations {
    ($slot:expr, $old:expr, $new:expr) => {{
        for success in SUCCESS {
            for failure in FAILURE {
                let slot = $slot;
                assert_eq!(slot.compare_exchange($new, $new, success, failure), Err($old));
                assert_eq!(slot.load(Ordering::Relaxed), $old);
                assert_eq!(slot.compare_exchange($old, $new, success, failure), Ok($old));
                assert_eq!(slot.load(Ordering::Relaxed), $new);

                assert_eq!(slot.compare_exchange_weak($old, $old, success, failure), Err($new));
                assert_eq!(slot.load(Ordering::Relaxed), $new);
                match slot.compare_exchange_weak($new, $old, success, failure) {
                    Ok(previous) => {
                        assert_eq!(previous, $new);
                        assert_eq!(slot.load(Ordering::Relaxed), $old);
                    }
                    Err(observed) => {
                        assert_eq!(observed, $new);
                        assert_eq!(slot.load(Ordering::Relaxed), $new);
                    }
                }
            }
        }
    }};
}

#[test]
fn scalar_success_and_failure() {
    macro_rules! check_integer {
        ($atomic:ident, $ty:ty) => {
            check_operations!(atomic::$atomic::new(<$ty>::MIN), <$ty>::MIN, <$ty>::MAX)
        };
    }
    check_operations!(AtomicBool::new(false), false, true);
    check_integer!(AtomicI8, i8);
    check_integer!(AtomicU8, u8);
    check_integer!(AtomicI16, i16);
    check_integer!(AtomicU16, u16);
    check_integer!(AtomicI32, i32);
    check_integer!(AtomicU32, u32);
    check_integer!(AtomicI64, i64);
    check_integer!(AtomicU64, u64);
    check_integer!(AtomicIsize, isize);
    check_integer!(AtomicUsize, usize);
    #[cfg(target_has_atomic = "128")]
    {
        check_integer!(AtomicI128, i128);
        check_integer!(AtomicU128, u128);
    }
}

fn check_pointer<T: Copy + Debug + Eq>(value: T) {
    let mut live = value;
    let pointer = &raw mut live;
    check_operations!(AtomicPtr::new(pointer), pointer, null_mut());
    let slot = AtomicPtr::new(pointer);
    let returned = slot.compare_exchange(pointer, null_mut(), Ordering::SeqCst, Ordering::SeqCst);
    // The allocation is still live and has no competing accesses.
    assert_eq!(unsafe { *returned.unwrap() }, value);
}

#[test]
fn pointer_success_and_failure() {
    check_pointer(());
    check_pointer(1_u8);
    check_pointer(2_u16);
    check_pointer([3_u8; 3]);
    check_pointer(4_u32);
}

#[test]
#[allow(invalid_atomic_ordering)]
fn invalid_failure_orderings_panic_without_writing() {
    let slot = AtomicU16::new(4);
    for success in SUCCESS {
        for failure in [Ordering::Release, Ordering::AcqRel] {
            assert!(catch_unwind(|| slot.compare_exchange(4, 9, success, failure)).is_err());
            assert!(catch_unwind(|| slot.compare_exchange_weak(4, 9, success, failure)).is_err());
            assert_eq!(slot.load(Ordering::Relaxed), 4);
        }
    }
}

#[test]
#[ignore = "requires Miri with an elevated weak failure rate"]
fn weak_can_fail_when_expected_value_matches() {
    let slot = AtomicU16::new(4);
    for success in SUCCESS {
        for failure in FAILURE {
            let mut observed_spurious_failure = false;
            for _ in 0..64 {
                match slot.compare_exchange_weak(4, 9, success, failure) {
                    Ok(4) => slot.store(4, Ordering::Relaxed),
                    Err(4) => {
                        assert_eq!(slot.load(Ordering::Relaxed), 4);
                        observed_spurious_failure = true;
                        break;
                    }
                    result => panic!("unexpected weak exchange result: {result:?}"),
                }
            }
            assert!(observed_spurious_failure, "{success:?}/{failure:?}");
        }
    }
    assert_eq!(slot.compare_exchange(4, 9, Ordering::SeqCst, Ordering::SeqCst), Ok(4));
}
