#![cfg(test)]
#![cfg_attr(target_has_atomic = "128", feature(integer_atomics))]

use std::fmt::Debug;
use std::ptr::without_provenance_mut;
use std::sync::atomic::{self, AtomicPtr, Ordering};

const ORDERS: [Ordering; 5] = [
    Ordering::Relaxed,
    Ordering::Acquire,
    Ordering::Release,
    Ordering::AcqRel,
    Ordering::SeqCst,
];

#[test]
fn integer_arithmetic_wraps_and_returns_previous_value() {
    macro_rules! check_integer {
        ($atomic:ident, $ty:ty) => {{
            let cases = [<$ty>::MIN, <$ty>::MIN + 1, 1, <$ty>::MAX - 1, <$ty>::MAX];
            for order in ORDERS {
                for start in cases {
                    for delta in cases {
                        let slot = atomic::$atomic::new(start);
                        assert_eq!(slot.fetch_add(delta, order), start);
                        assert_eq!(slot.load(Ordering::Relaxed), start.wrapping_add(delta));
                        slot.store(start, Ordering::Relaxed);
                        assert_eq!(slot.fetch_sub(delta, order), start);
                        assert_eq!(slot.load(Ordering::Relaxed), start.wrapping_sub(delta));
                    }
                }
            }
        }};
    }

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

fn check_live_pointer<T: Copy + Eq + Debug>(value: T) {
    let mut live = [value; 2];
    let start = live.as_mut_ptr();
    for order in ORDERS {
        let slot = AtomicPtr::new(start);
        for delta in [0, 1, usize::MAX / 2 + 1, usize::MAX] {
            assert_eq!(slot.fetch_ptr_add(delta, order), start);
            let offset = start.wrapping_add(delta);
            assert_eq!(slot.load(Ordering::Relaxed), offset);
            assert_eq!(slot.fetch_ptr_sub(delta, order), offset);
            assert_eq!(slot.load(Ordering::Relaxed), start);

            assert_eq!(slot.fetch_byte_sub(delta, order), start);
            let offset = start.wrapping_byte_sub(delta);
            assert_eq!(slot.load(Ordering::Relaxed), offset);
            assert_eq!(slot.fetch_byte_add(delta, order), offset);
            let restored = slot.load(Ordering::Relaxed);
            assert_eq!(restored, start);
            // The restored pointer should still refer to the live allocation.
            assert_eq!(unsafe { *restored }, value);
        }

        assert_eq!(slot.fetch_ptr_add(1, order), start);
        let next = slot.load(Ordering::Relaxed);
        assert_eq!(next, start.wrapping_add(1));
        // The second element is in the same live allocation.
        assert_eq!(unsafe { *next }, value);
    }
}

#[test]
fn pointer_byte_and_element_arithmetic_wraps() {
    check_live_pointer(());
    check_live_pointer(1_u8);
    check_live_pointer(2_u16);
    check_live_pointer([3_u8; 3]);
    check_live_pointer(4_u32);

    for order in ORDERS {
        let pointer = without_provenance_mut::<u8>(usize::MAX);
        let slot = AtomicPtr::new(pointer);
        assert_eq!(slot.fetch_byte_add(1, order).addr(), usize::MAX);
        assert_eq!(slot.load(Ordering::Relaxed).addr(), 0);
        assert_eq!(slot.fetch_byte_sub(1, order).addr(), 0);
        assert_eq!(slot.load(Ordering::Relaxed).addr(), usize::MAX);
    }
}
