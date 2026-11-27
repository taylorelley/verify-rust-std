#![cfg(test)]
#![cfg_attr(target_has_atomic = "128", feature(integer_atomics))]

use std::panic::catch_unwind;
use std::sync::atomic::{self, Ordering};

const LOAD: [Ordering; 3] = [Ordering::Relaxed, Ordering::Acquire, Ordering::SeqCst];
const STORE: [Ordering; 3] = [Ordering::Relaxed, Ordering::Release, Ordering::SeqCst];

#[test]
#[allow(invalid_atomic_ordering)]
fn integer_load_and_store_orderings() {
    macro_rules! check_integer {
        ($atomic:ident, $ty:ty) => {{
            let slot = atomic::$atomic::new(0);
            for store in STORE {
                for value in [<$ty>::MIN, <$ty>::MAX, !0, 1, 0] {
                    slot.store(value, store);
                    for load in LOAD {
                        assert_eq!(slot.load(load), value);
                    }
                }
            }
            slot.store(<$ty>::MAX, Ordering::Relaxed);
            for invalid in [Ordering::Acquire, Ordering::AcqRel] {
                assert!(catch_unwind(|| slot.store(0, invalid)).is_err());
                assert_eq!(slot.load(Ordering::Relaxed), <$ty>::MAX);
            }
            for invalid in [Ordering::Release, Ordering::AcqRel] {
                assert!(catch_unwind(|| slot.load(invalid)).is_err());
                assert_eq!(slot.load(Ordering::Relaxed), <$ty>::MAX);
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
