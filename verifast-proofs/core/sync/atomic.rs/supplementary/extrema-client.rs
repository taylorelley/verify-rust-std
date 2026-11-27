#![cfg(test)]
#![cfg_attr(target_has_atomic = "128", feature(integer_atomics))]

use std::sync::atomic::{self, Ordering};

const ORDERS: [Ordering; 5] = [
    Ordering::Relaxed,
    Ordering::Acquire,
    Ordering::Release,
    Ordering::AcqRel,
    Ordering::SeqCst,
];

#[test]
fn min_and_max_use_the_integer_types_ordering() {
    macro_rules! check_integer {
        ($atomic:ident, $ty:ty) => {{
            let inputs: [$ty; 7] = [
                <$ty>::MIN,
                <$ty>::MIN + 1,
                0,
                1,
                !0,
                <$ty>::MAX - 1,
                <$ty>::MAX,
            ];
            for order in ORDERS {
                for old in inputs {
                    for candidate in inputs {
                        let slot = atomic::$atomic::new(old);
                        assert_eq!(slot.fetch_min(candidate, order), old);
                        assert_eq!(slot.load(Ordering::Relaxed), old.min(candidate));

                        slot.store(old, Ordering::Relaxed);
                        assert_eq!(slot.fetch_max(candidate, order), old);
                        assert_eq!(slot.load(Ordering::Relaxed), old.max(candidate));
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
