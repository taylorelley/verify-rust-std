#![cfg(test)]
#![cfg_attr(target_has_atomic = "128", feature(integer_atomics))]

use std::fmt::Debug;
use std::sync::atomic::{self, AtomicBool, AtomicPtr, Ordering};

const ORDERS: [Ordering; 5] = [
    Ordering::Relaxed,
    Ordering::Acquire,
    Ordering::Release,
    Ordering::AcqRel,
    Ordering::SeqCst,
];

macro_rules! check_bitwise {
    ($slot:expr, $inputs:expr) => {{
        for order in ORDERS {
            for old in $inputs {
                for mask in $inputs {
                    let slot = $slot;
                    slot.store(old, Ordering::Relaxed);
                    assert_eq!(slot.fetch_and(mask, order), old);
                    assert_eq!(slot.load(Ordering::Relaxed), old & mask);

                    slot.store(old, Ordering::Relaxed);
                    assert_eq!(slot.fetch_nand(mask, order), old);
                    assert_eq!(slot.load(Ordering::Relaxed), !(old & mask));

                    slot.store(old, Ordering::Relaxed);
                    assert_eq!(slot.fetch_or(mask, order), old);
                    assert_eq!(slot.load(Ordering::Relaxed), old | mask);

                    slot.store(old, Ordering::Relaxed);
                    assert_eq!(slot.fetch_xor(mask, order), old);
                    assert_eq!(slot.load(Ordering::Relaxed), old ^ mask);
                }
            }
        }
    }};
}

#[test]
fn boolean_truth_tables() {
    check_bitwise!(AtomicBool::new(false), [false, true]);
}

#[test]
fn integer_bitwise_patterns() {
    macro_rules! check_integer {
        ($atomic:ident, $ty:ty) => {
            check_bitwise!(
                atomic::$atomic::new(0),
                [0, 1, 0x55, <$ty>::MIN, <$ty>::MAX, !0x55]
            )
        };
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

fn check_pointer<T: Copy + Eq + Debug>(value: T) {
    #[repr(align(8))]
    struct Aligned<T>(T);
    let mut storage = Aligned(value);
    let live = &raw mut storage.0;
    let address = live.addr();
    assert_eq!(address & 3, 0);
    for order in ORDERS {
        let slot = AtomicPtr::new(live);
        assert_eq!(slot.fetch_or(1, order), live);
        assert_eq!(slot.load(Ordering::Relaxed).addr(), address | 1);
        assert_eq!(slot.fetch_xor(3, order).addr(), address | 1);
        assert_eq!(slot.load(Ordering::Relaxed).addr(), address | 2);
        assert_eq!(slot.fetch_and(!3, order).addr(), address | 2);
        let restored = slot.load(Ordering::Relaxed);
        assert_eq!(restored, live);
        // Only the untagged pointer into the live allocation is dereferenced.
        assert_eq!(unsafe { *restored }, value);
    }
}

#[test]
fn pointer_masks_preserve_a_live_pointer_after_untagging() {
    check_pointer(());
    check_pointer(1_u8);
    check_pointer(2_u16);
    check_pointer([3_u8; 3]);
    check_pointer(4_u32);
}
