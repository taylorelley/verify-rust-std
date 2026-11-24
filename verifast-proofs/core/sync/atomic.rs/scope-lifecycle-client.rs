#![cfg(test)]

use std::panic::{AssertUnwindSafe, catch_unwind};
use std::thread;

#[test]
fn nested_scoped_worker_returns_its_borrow_at_join() {
    let mut count = 0;
    thread::scope(|scope| {
        let borrowed = &mut count;
        scope.spawn(move || {
            scope.spawn(move || *borrowed += 1).join().unwrap();
        }).join().unwrap();
    });
    assert_eq!(count, 1);
}

#[test]
fn scope_waits_for_worker_when_scope_body_unwinds() {
    let mut count = 0;
    let outcome = catch_unwind(AssertUnwindSafe(|| {
        thread::scope(|scope| {
            scope.spawn(|| count += 1);
            panic!("scope body");
        });
    }));
    assert_eq!(outcome.unwrap_err().downcast_ref::<&str>(), Some(&"scope body"));
    assert_eq!(count, 1);
}

#[test]
fn explicit_join_consumes_worker_panic() {
    let mut count = 0;
    thread::scope(|scope| {
        let handle = scope.spawn(|| {
            count += 1;
            panic!("worker panic");
        });
        assert_eq!(handle.join().unwrap_err().downcast_ref::<&str>(), Some(&"worker panic"));
    });
    assert_eq!(count, 1);
}

#[test]
fn scope_propagates_unhandled_worker_panic_after_worker_is_done() {
    let mut count = 0;
    let outcome = catch_unwind(AssertUnwindSafe(|| {
        thread::scope(|scope| {
            scope.spawn(|| {
                count += 1;
                panic!("worker panic");
            });
        });
    }));
    assert!(outcome.is_err());
    assert_eq!(count, 1);
}

struct WriteOnDrop<'a>(&'a mut bool);

impl Drop for WriteOnDrop<'_> {
    fn drop(&mut self) {
        *self.0 = true;
    }
}

#[test]
fn implicit_join_waits_for_borrowed_result_destructor() {
    let mut dropped = false;
    thread::scope(|scope| {
        let flag = &mut dropped;
        drop(scope.spawn(move || WriteOnDrop(flag)));
    });
    assert!(dropped);
}
