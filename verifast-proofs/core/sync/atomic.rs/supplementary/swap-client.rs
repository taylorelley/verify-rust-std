#![cfg(test)]
#![cfg_attr(target_has_atomic = "128", feature(integer_atomics))]

use std::fmt::Debug;
use std::ptr::null_mut;
use std::sync::atomic::{self, AtomicBool, AtomicPtr, Ordering};

const ORDERS: [Ordering; 5] = [
    Ordering::Relaxed,
    Ordering::Acquire,
    Ordering::Release,
    Ordering::AcqRel,
    Ordering::SeqCst,
];

#[test]
fn scalar_exchange_returns_previous_value() {
    macro_rules! check_integer {
        ($atomic:ident, $ty:ty, $order:expr) => {{
            let integer = atomic::$atomic::new(<$ty>::MIN);
            assert_eq!(integer.swap(<$ty>::MAX, $order), <$ty>::MIN);
            assert_eq!(integer.swap(1, $order), <$ty>::MAX);
            assert_eq!(integer.load(Ordering::Relaxed), 1);
        }};
    }
    for order in ORDERS {
        let boolean = AtomicBool::new(false);
        assert!(!boolean.swap(true, order));
        assert!(boolean.swap(false, order));
        assert!(!boolean.load(Ordering::Relaxed));

        check_integer!(AtomicI8, i8, order);
        check_integer!(AtomicU8, u8, order);
        check_integer!(AtomicI16, i16, order);
        check_integer!(AtomicU16, u16, order);
        check_integer!(AtomicI32, i32, order);
        check_integer!(AtomicU32, u32, order);
        check_integer!(AtomicI64, i64, order);
        check_integer!(AtomicU64, u64, order);
        check_integer!(AtomicIsize, isize, order);
        check_integer!(AtomicUsize, usize, order);
        #[cfg(target_has_atomic = "128")]
        {
            check_integer!(AtomicI128, i128, order);
            check_integer!(AtomicU128, u128, order);
        }
    }
}

fn check_pointer<T: Copy + Debug + Eq>(value: T) {
    for order in ORDERS {
        let mut live = value;
        let pointer = &raw mut live;
        let atomic = AtomicPtr::new(null_mut());

        assert!(atomic.swap(pointer, order).is_null());
        let old = atomic.swap(null_mut(), order);
        assert_eq!(old, pointer);
        // The allocation is live and has no competing accesses.
        assert_eq!(unsafe { *old }, value);
        assert!(atomic.load(Ordering::Relaxed).is_null());
    }
}

#[test]
fn pointer_exchange_returns_live_pointer() {
    check_pointer(());
    check_pointer(1_u8);
    check_pointer(2_u16);
    check_pointer([3_u8; 3]);
    check_pointer(4_u32);
}
