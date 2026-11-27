#![feature(core_intrinsics)]
#![allow(internal_features)]

use std::intrinsics::{self, AtomicOrdering as AO};
use Ordering::*;

#[derive(Copy, Clone)]
#[non_exhaustive]
pub enum Ordering {
    Relaxed,
    Release,
    Acquire,
    AcqRel,
    SeqCst,
}

// Permission proof adapted from model-checking/verify-rust-std PR #675.
use std::cell::UnsafeCell;
mod private {
    #[repr(C, align(2))]
    pub struct Align2(u16);
    /*@
    pred <Align2>.own(t, v) = true;
    lem Align2_drop()
        req Align2_own(?t, ?v);
        ens true;
    {
        open Align2_own(t, v);
    }
    lem Align2_send(t1: thread_id_t)
        req Align2_own(?t, ?v);
        ens Align2_own(t1, v);
    {
        open Align2_own(t, v);
        close Align2_own(t1, v);
    }
    @*/
}
#[repr(C)]
pub struct AtomicU16 {
    v: UnsafeCell<private::Align2>,
}
unsafe impl Send for AtomicU16 {}
unsafe impl Sync for AtomicU16 {}
impl AtomicU16 {
    pub const fn load<'a>(&'a self, order: Ordering) -> u16
    //@ req thread_token(currentThread) &*& [?q]lifetime_token('a) &*& [_](<AtomicU16>.share('a, currentThread, self)) &*& <Ordering>.own(currentThread, order);
    //@ ens thread_token(currentThread) &*& [q]lifetime_token('a);
    //@ on_unwind_ens thread_token(currentThread) &*& [q]lifetime_token('a);
    {
        unsafe {
            //@ leak <Ordering>.own(_, _);
            //@ close exists::<*AtomicU16>(self);
            //@ close exists::<lifetime_t>('a);
            atomic_load(self.v.get().cast::<u16>(), order)
        }
    }

    pub const fn store<'a>(&'a self, val: u16, order: Ordering)
    //@ req thread_token(currentThread) &*& [?q]lifetime_token('a) &*& [_](<AtomicU16>.share('a, currentThread, self)) &*& <Ordering>.own(currentThread, order);
    //@ ens thread_token(currentThread) &*& [q]lifetime_token('a);
    //@ on_unwind_ens thread_token(currentThread) &*& [q]lifetime_token('a);
    {
        unsafe {
            //@ leak <Ordering>.own(_, _);
            //@ close exists::<*AtomicU16>(self);
            //@ close exists::<lifetime_t>('a);
            atomic_store(self.v.get().cast::<u16>(), val, order);
        }
    }

    pub const fn as_ptr<'a>(&'a self) -> *mut u16
    //@ req [?q]lifetime_token('a) &*& [_](<AtomicU16>.share('a, currentThread, self));
    //@ ens [q]lifetime_token('a) &*& result == ref_origin(self) as *u16;
    //@ on_unwind_ens false;
    {
        self.v.get().cast()
    }
    pub const unsafe fn from_ptr<'a>(ptr: *mut u16) -> &'a AtomicU16
    //@ req type_interp::<AtomicU16>() &*& atomic_mask(MaskTop) &*& [?q]lifetime_token('a) &*& exists::<bool>(?fresh) &*& (if fresh { *ptr |-> ?value } else { [_](<AtomicU16>.share)('a, currentThread, ptr as *AtomicU16) }) &*& ptr as usize % std::mem::align_of::<AtomicU16>() == 0;
    //@ ens type_interp::<AtomicU16>() &*& atomic_mask(MaskTop) &*& [q]lifetime_token('a) &*& [_](<AtomicU16>.share)('a, currentThread, result) &*& [_](<AtomicU16>.share)('a, currentThread, ptr as *AtomicU16) &*& [_]frac_borrow('a, ref_initialized_(result)) &*& ref_origin(result) == ref_origin(ptr as *AtomicU16) &*& (if fresh { borrow_end_token('a, (<AtomicU16>.full_borrow_content)(currentThread, ptr as *AtomicU16)) } else { true });
    //@ on_unwind_ens false;
    {
        //@ open exists::<bool>(fresh);
        /*@ if fresh {
            close_points_to(ptr as *private::Align2);
            close_points_to(ptr as *AtomicU16);
            assert *(ptr as *AtomicU16) |-> ?atomic;
            close private::Align2_own(currentThread, atomic.v);
            close <AtomicU16>.own(currentThread, atomic);
            close_full_borrow_content::<AtomicU16>(currentThread, ptr as *AtomicU16);
            borrow('a, (<AtomicU16>.full_borrow_content)(currentThread, ptr as *AtomicU16));
            share_full_borrow::<AtomicU16>('a, currentThread, ptr as *AtomicU16);
        } @*/
        //@ let p = precreate_ref(ptr as *AtomicU16);
        //@ init_ref_share::<AtomicU16>('a, currentThread, p);
        //@ open_frac_borrow('a, ref_initialized_(p), q);
        //@ open [?f]ref_initialized_::<AtomicU16>(p)();
        let result = unsafe { &*ptr.cast() };
        //@ close [f]ref_initialized_::<AtomicU16>(p)();
        //@ close_frac_borrow(f, ref_initialized_(p));
        result
    }
}
/*@
fix accepts_u16(value: u16) -> bool { true }
pred_ctor own_atomic_contents(p: *u16)(;) = std::intrinsics::atomic_points_to(p, 1, accepts_u16);
pred <AtomicU16>.own(t, value) = <private::Align2>.own(t, value.v);
lem AtomicU16_drop()
    req AtomicU16_own(?t, ?a);
    ens <private::Align2>.own(t, a.v);
{
    open AtomicU16_own(t, a);
}
lem AtomicU16_send(t1: thread_id_t)
    req AtomicU16_own(?t, ?a);
    ens AtomicU16_own(t1, a);
{
    open AtomicU16_own(t, a);
    private::Align2_send(t1);
    close AtomicU16_own(t1, a);
}
pred <AtomicU16>.share(k, t, l) = [_]frac_borrow(k, own_atomic_contents(ref_origin(l) as *u16));

lem AtomicU16_share_mono(k: lifetime_t, k1: lifetime_t, t: thread_id_t, l: *AtomicU16)
    req lifetime_inclusion(k1, k) == true &*& [_]AtomicU16_share(k, t, l);
    ens [_]AtomicU16_share(k1, t, l);
{
    open AtomicU16_share(k, t, l);
    frac_borrow_mono(k, k1, own_atomic_contents(ref_origin(l) as *u16));
    close AtomicU16_share(k1, t, l);
    leak AtomicU16_share(k1, t, l);
}

lem AtomicU16_sync(t1: thread_id_t)
    req is_Sync(typeid(AtomicU16)) == true &*& [_]AtomicU16_share(?k, ?t0, ?l);
    ens [_]AtomicU16_share(k, t1, l);
{
    open AtomicU16_share(k, t0, l);
    close AtomicU16_share(k, t1, l);
    leak AtomicU16_share(k, t1, l);
}

lem AtomicU16_share_full(k: lifetime_t, t: thread_id_t, l: *AtomicU16)
    req atomic_mask(MaskTop) &*& full_borrow(k, AtomicU16_full_borrow_content(t, l)) &*& [?q]lifetime_token(k) &*& ref_origin(l) == l;
    ens atomic_mask(MaskTop) &*& [_]AtomicU16_share(k, t, l) &*& [q]lifetime_token(k);
{
    open_full_borrow_strong_m_(k, AtomicU16_full_borrow_content(t, l));
    open AtomicU16_full_borrow_content(t, l)();
    assert AtomicU16_own(t, ?stored);
    open AtomicU16_own(t, stored);
    open private::Align2_own(t, stored.v);
    open_points_to(l as *private::Align2);
    close_points_to(l as *private::Align2);
    to_u8s_(l as *private::Align2);
    from_u8s_(l as *private::Align2);
    open_points_to(l as *private::Align2);
    std::intrinsics::atomic_align_of_u16();
    assert l as usize % std::mem::align_of::<private::Align2>() == 0;
    assert std::mem::align_of::<private::Align2>() == 2;
    std::intrinsics::close_atomic_points_to_m(l as *u16, accepts_u16);
    close own_atomic_contents(l as *u16)();
    close True();
    produce_lem_ptr_chunk restore_full_borrow_(True, own_atomic_contents(l as *u16), AtomicU16_full_borrow_content(t, l))() {
        open True();
        open own_atomic_contents(l as *u16)();
        std::intrinsics::open_atomic_points_to(l as *u16);
        close_points_to(l as *private::Align2);
        close_points_to(l);
        assert *l |-> ?value;
        close private::Align2_own(t, value.v);
        close AtomicU16_own(t, value);
        open_points_to(l);
        close AtomicU16_full_borrow_content(t, l)();
    } {
        close_full_borrow_strong_m_();
    }
    full_borrow_into_frac_m(k, own_atomic_contents(l as *u16));
    close AtomicU16_share(k, t, l);
    leak AtomicU16_share(k, t, l);
}

lem init_ref_AtomicU16(p: *AtomicU16)
    req atomic_mask(Nlft) &*& ref_init_perm(p, ?x) &*& [_]AtomicU16_share(?k, ?t, x) &*& [?q]lifetime_token(k);
    ens atomic_mask(Nlft) &*& [q]lifetime_token(k) &*& [_]AtomicU16_share(k, t, p) &*& [_]frac_borrow(k, ref_initialized_(p));
{
    open AtomicU16_share(k, t, x);
    open_ref_init_perm_AtomicU16(p);
    close_ref_initialized_AtomicU16(p, 1);
    close ref_initialized_::<AtomicU16>(p)();
    borrow_m(k, ref_initialized_(p));
    leak borrow_end_token(k, ref_initialized_(p));
    full_borrow_into_frac_m(k, ref_initialized_(p));
    close AtomicU16_share(k, t, p);
    leak AtomicU16_share(k, t, p);
}
@*/
// Included in the proof suite to check that the sharing contract is usable.
unsafe fn share_twice<'a>(ptr: *mut u16) -> (&'a AtomicU16, &'a AtomicU16)
//@ req type_interp::<AtomicU16>() &*& atomic_mask(MaskTop) &*& [?q]lifetime_token('a) &*& *ptr |-> ?value &*& ptr as usize % std::mem::align_of::<AtomicU16>() == 0;
//@ ens type_interp::<AtomicU16>() &*& atomic_mask(MaskTop) &*& [q]lifetime_token('a) &*& [_]AtomicU16_share('a, currentThread, result.0) &*& [_]AtomicU16_share('a, currentThread, result.1) &*& borrow_end_token('a, AtomicU16_full_borrow_content(currentThread, ptr as *AtomicU16));
//@ on_unwind_ens false;
{
    //@ close exists::<bool>(true);
    let first = unsafe { AtomicU16::from_ptr/*@::<'a>@*/(ptr) };
    //@ close exists::<bool>(false);
    let second = unsafe { AtomicU16::from_ptr/*@::<'a>@*/(ptr) };
    (first, second)
}
// Open the borrow only in branches that reach a non-unwinding intrinsic.
// On invalid orderings the caller's lifetime and thread tokens reach the
// panic unchanged.
const unsafe fn atomic_store(dst: *mut u16, val: u16, order: Ordering)
//@ req thread_token(currentThread) &*& exists::<*AtomicU16>(?atomic) &*& exists::<lifetime_t>(?k) &*& [?q]lifetime_token(k) &*& [_]AtomicU16_share(k, currentThread, atomic) &*& dst == ref_origin(atomic) as *u16 &*& accepts_u16(val) == true;
//@ ens thread_token(currentThread) &*& [q]lifetime_token(k);
//@ on_unwind_ens thread_token(currentThread) &*& [q]lifetime_token(k);
{
    //@ open exists::<*AtomicU16>(atomic);
    //@ open exists::<lifetime_t>(k);
    // SAFETY: the caller must uphold the safety contract for `atomic_store`.
    unsafe {
        match order {
            Relaxed => {
                //@ open AtomicU16_share(k, currentThread, atomic);
                //@ open_frac_borrow(k, own_atomic_contents(dst), q);
                //@ open [?f]own_atomic_contents(dst)();
                intrinsics::atomic_store::<u16, { AO::Relaxed }, false>(dst, val);
                //@ close [f]own_atomic_contents(dst)();
                //@ close_frac_borrow(f, own_atomic_contents(dst));
            }
            Release => {
                //@ open AtomicU16_share(k, currentThread, atomic);
                //@ open_frac_borrow(k, own_atomic_contents(dst), q);
                //@ open [?f]own_atomic_contents(dst)();
                intrinsics::atomic_store::<u16, { AO::Release }, false>(dst, val);
                //@ close [f]own_atomic_contents(dst)();
                //@ close_frac_borrow(f, own_atomic_contents(dst));
            }
            SeqCst => {
                //@ open AtomicU16_share(k, currentThread, atomic);
                //@ open_frac_borrow(k, own_atomic_contents(dst), q);
                //@ open [?f]own_atomic_contents(dst)();
                intrinsics::atomic_store::<u16, { AO::SeqCst }, false>(dst, val);
                //@ close [f]own_atomic_contents(dst)();
                //@ close_frac_borrow(f, own_atomic_contents(dst));
            }
            Acquire => panic!("there is no such thing as an acquire store"),
            AcqRel => panic!("there is no such thing as an acquire-release store"),
        }
    }
}

// Keep the lifetime token available on any branch that can unwind.
const unsafe fn atomic_load(src: *const u16, order: Ordering) -> u16
//@ req thread_token(currentThread) &*& exists::<*AtomicU16>(?atomic) &*& exists::<lifetime_t>(?k) &*& [?q]lifetime_token(k) &*& [_]AtomicU16_share(k, currentThread, atomic) &*& src == ref_origin(atomic) as *const u16;
//@ ens thread_token(currentThread) &*& [q]lifetime_token(k) &*& accepts_u16(result) == true;
//@ on_unwind_ens thread_token(currentThread) &*& [q]lifetime_token(k);
{
    //@ open exists::<*AtomicU16>(atomic);
    //@ open exists::<lifetime_t>(k);
    unsafe {
        match order {
            Relaxed => {
                //@ open AtomicU16_share(k, currentThread, atomic);
                //@ open_frac_borrow(k, own_atomic_contents(src as *u16), q);
                //@ open [?f]own_atomic_contents(src as *u16)();
                let value = intrinsics::atomic_load::<u16, { AO::Relaxed }, false>(src);
                //@ close [f]own_atomic_contents(src as *u16)();
                //@ close_frac_borrow(f, own_atomic_contents(src as *u16));
                value
            }
            Acquire => {
                //@ open AtomicU16_share(k, currentThread, atomic);
                //@ open_frac_borrow(k, own_atomic_contents(src as *u16), q);
                //@ open [?f]own_atomic_contents(src as *u16)();
                let value = intrinsics::atomic_load::<u16, { AO::Acquire }, false>(src);
                //@ close [f]own_atomic_contents(src as *u16)();
                //@ close_frac_borrow(f, own_atomic_contents(src as *u16));
                value
            }
            SeqCst => {
                //@ open AtomicU16_share(k, currentThread, atomic);
                //@ open_frac_borrow(k, own_atomic_contents(src as *u16), q);
                //@ open [?f]own_atomic_contents(src as *u16)();
                let value = intrinsics::atomic_load::<u16, { AO::SeqCst }, false>(src);
                //@ close [f]own_atomic_contents(src as *u16)();
                //@ close_frac_borrow(f, own_atomic_contents(src as *u16));
                value
            }
            Release => panic!("there is no such thing as a release load"),
            AcqRel => panic!("there is no such thing as an acquire-release load"),
        }
    }
}

// The full word is held as an atomic permission. An independent byte can
// still be converted to an atomic write permission.
unsafe fn write_disjoint_byte(word: *mut u16, byte: *mut u8)
//@ req atomic_mask(MaskTop) &*& std::intrinsics::atomic_points_to(word, 1, accepts_u16) &*& *byte |-> ?initial;
//@ ens atomic_mask(MaskTop) &*& std::intrinsics::atomic_points_to(word, 1, accepts_u16) &*& *byte |-> _;
//@ on_unwind_ens false;
{
    //@ let dst = byte;
    //@ std::intrinsics::atomic_align_of_u8();
    //@ div_rem(dst as usize, 1);
    //@ std::intrinsics::close_atomic_points_to_m(dst, any_byte);
    // Keep the runtime destination in sync with the permission conversion.
    unsafe { intrinsics::atomic_store::<u8, { AO::Relaxed }, false>(byte, 42) };
    //@ std::intrinsics::open_atomic_points_to(dst);
}

//@ fix any_byte(value: u8) -> bool { true }
