// Permission proof adapted from model-checking/verify-rust-std PR #675.
use std::cell::UnsafeCell;
mod private {
    #[repr(C, align(1))]
    pub struct Align1(u8);
    /*@
    pred <Align1>.own(t, v) = true;
    lem Align1_drop()
        req Align1_own(?t, ?v);
        ens true;
    {
        open Align1_own(t, v);
    }
    lem Align1_send(t1: thread_id_t)
        req Align1_own(?t, ?v);
        ens Align1_own(t1, v);
    {
        open Align1_own(t, v);
        close Align1_own(t1, v);
    }
    @*/
}
#[repr(C)]
pub struct AtomicBool {
    v: UnsafeCell<private::Align1>,
}
unsafe impl Send for AtomicBool {}
unsafe impl Sync for AtomicBool {}
impl AtomicBool {
    pub const unsafe fn from_ptr<'a>(ptr: *mut bool) -> &'a AtomicBool
    //@ req type_interp::<AtomicBool>() &*& atomic_mask(MaskTop) &*& [?q]lifetime_token('a) &*& exists::<bool>(?fresh) &*& (if fresh { *ptr |-> ?value } else { [_](<AtomicBool>.share)('a, currentThread, ptr as *AtomicBool) }) &*& ptr as usize % std::mem::align_of::<AtomicBool>() == 0;
    //@ ens type_interp::<AtomicBool>() &*& atomic_mask(MaskTop) &*& [q]lifetime_token('a) &*& [_](<AtomicBool>.share)('a, currentThread, result) &*& [_](<AtomicBool>.share)('a, currentThread, ptr as *AtomicBool) &*& [_]frac_borrow('a, ref_initialized_(result)) &*& ref_origin(result) == ref_origin(ptr as *AtomicBool) &*& (if fresh { borrow_end_token('a, (<AtomicBool>.full_borrow_content)(currentThread, ptr as *AtomicBool)) } else { true });
    //@ on_unwind_ens false;
    {
        //@ open exists::<bool>(fresh);
        /*@ if fresh {
            points_to_bool_to_u8(ptr);
            close_points_to(ptr as *private::Align1);
            close_points_to(ptr as *AtomicBool);
            assert *(ptr as *AtomicBool) |-> ?atomic;
            close private::Align1_own(currentThread, atomic.v);
            close <AtomicBool>.own(currentThread, atomic);
            close_full_borrow_content::<AtomicBool>(currentThread, ptr as *AtomicBool);
            borrow('a, (<AtomicBool>.full_borrow_content)(currentThread, ptr as *AtomicBool));
            share_full_borrow::<AtomicBool>('a, currentThread, ptr as *AtomicBool);
        } @*/
        //@ let p = precreate_ref(ptr as *AtomicBool);
        //@ init_ref_share::<AtomicBool>('a, currentThread, p);
        //@ open_frac_borrow('a, ref_initialized_(p), q);
        //@ open [?f]ref_initialized_::<AtomicBool>(p)();
        let result = unsafe { &*ptr.cast() };
        //@ close [f]ref_initialized_::<AtomicBool>(p)();
        //@ close_frac_borrow(f, ref_initialized_(p));
        result
    }
}
/*@
fix accepts_u8(value: u8) -> bool { value == 0 || value == 1 }
pred_ctor own_atomic_contents(p: *u8)(;) = std::intrinsics::atomic_points_to(p, 1, accepts_u8);
pred <AtomicBool>.own(t, value) = <private::Align1>.own(t, value.v) &*& (value.v.0 == 0 || value.v.0 == 1);
lem AtomicBool_drop()
    req AtomicBool_own(?t, ?a);
    ens <private::Align1>.own(t, a.v);
{
    open AtomicBool_own(t, a);
}
lem AtomicBool_send(t1: thread_id_t)
    req AtomicBool_own(?t, ?a);
    ens AtomicBool_own(t1, a);
{
    open AtomicBool_own(t, a);
    private::Align1_send(t1);
    close AtomicBool_own(t1, a);
}
pred <AtomicBool>.share(k, t, l) = [_]frac_borrow(k, own_atomic_contents(ref_origin(l) as *u8));

lem AtomicBool_share_mono(k: lifetime_t, k1: lifetime_t, t: thread_id_t, l: *AtomicBool)
    req lifetime_inclusion(k1, k) == true &*& [_]AtomicBool_share(k, t, l);
    ens [_]AtomicBool_share(k1, t, l);
{
    open AtomicBool_share(k, t, l);
    frac_borrow_mono(k, k1, own_atomic_contents(ref_origin(l) as *u8));
    close AtomicBool_share(k1, t, l);
    leak AtomicBool_share(k1, t, l);
}

lem AtomicBool_sync(t1: thread_id_t)
    req is_Sync(typeid(AtomicBool)) == true &*& [_]AtomicBool_share(?k, ?t0, ?l);
    ens [_]AtomicBool_share(k, t1, l);
{
    open AtomicBool_share(k, t0, l);
    close AtomicBool_share(k, t1, l);
    leak AtomicBool_share(k, t1, l);
}

lem AtomicBool_share_full(k: lifetime_t, t: thread_id_t, l: *AtomicBool)
    req atomic_mask(MaskTop) &*& full_borrow(k, AtomicBool_full_borrow_content(t, l)) &*& [?q]lifetime_token(k) &*& ref_origin(l) == l;
    ens atomic_mask(MaskTop) &*& [_]AtomicBool_share(k, t, l) &*& [q]lifetime_token(k);
{
    open_full_borrow_strong_m_(k, AtomicBool_full_borrow_content(t, l));
    open AtomicBool_full_borrow_content(t, l)();
    assert AtomicBool_own(t, ?stored);
    open AtomicBool_own(t, stored);
    open private::Align1_own(t, stored.v);
    open_points_to(l as *private::Align1);
    div_rem(l as usize, 1);
    std::intrinsics::atomic_align_of_u8();
    std::intrinsics::close_atomic_points_to_m(l as *u8, accepts_u8);
    close own_atomic_contents(l as *u8)();
    close True();
    produce_lem_ptr_chunk restore_full_borrow_(True, own_atomic_contents(l as *u8), AtomicBool_full_borrow_content(t, l))() {
        open True();
        open own_atomic_contents(l as *u8)();
        std::intrinsics::open_atomic_points_to(l as *u8);
        close_points_to(l as *private::Align1);
        close_points_to(l);
        assert *l |-> ?value;
        close private::Align1_own(t, value.v);
        close AtomicBool_own(t, value);
        open_points_to(l);
        close AtomicBool_full_borrow_content(t, l)();
    } {
        close_full_borrow_strong_m_();
    }
    full_borrow_into_frac_m(k, own_atomic_contents(l as *u8));
    close AtomicBool_share(k, t, l);
    leak AtomicBool_share(k, t, l);
}

lem init_ref_AtomicBool(p: *AtomicBool)
    req atomic_mask(Nlft) &*& ref_init_perm(p, ?x) &*& [_]AtomicBool_share(?k, ?t, x) &*& [?q]lifetime_token(k);
    ens atomic_mask(Nlft) &*& [q]lifetime_token(k) &*& [_]AtomicBool_share(k, t, p) &*& [_]frac_borrow(k, ref_initialized_(p));
{
    open AtomicBool_share(k, t, x);
    open_ref_init_perm_AtomicBool(p);
    close_ref_initialized_AtomicBool(p, 1);
    close ref_initialized_::<AtomicBool>(p)();
    borrow_m(k, ref_initialized_(p));
    leak borrow_end_token(k, ref_initialized_(p));
    full_borrow_into_frac_m(k, ref_initialized_(p));
    close AtomicBool_share(k, t, p);
    leak AtomicBool_share(k, t, p);
}
@*/
// Included in the proof suite to check that the sharing contract is usable.
unsafe fn share_twice<'a>(ptr: *mut bool) -> (&'a AtomicBool, &'a AtomicBool)
//@ req type_interp::<AtomicBool>() &*& atomic_mask(MaskTop) &*& [?q]lifetime_token('a) &*& *ptr |-> ?value &*& ptr as usize % std::mem::align_of::<AtomicBool>() == 0;
//@ ens type_interp::<AtomicBool>() &*& atomic_mask(MaskTop) &*& [q]lifetime_token('a) &*& [_]AtomicBool_share('a, currentThread, result.0) &*& [_]AtomicBool_share('a, currentThread, result.1) &*& borrow_end_token('a, AtomicBool_full_borrow_content(currentThread, ptr as *AtomicBool));
//@ on_unwind_ens false;
{
    //@ close exists::<bool>(true);
    let first = unsafe { AtomicBool::from_ptr/*@::<'a>@*/(ptr) };
    //@ close exists::<bool>(false);
    let second = unsafe { AtomicBool::from_ptr/*@::<'a>@*/(ptr) };
    (first, second)
}
