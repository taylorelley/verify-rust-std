#!/usr/bin/env python3
"""Coverage and negative controls for the Challenge 7 module proof.

Run after verify.sh, with the patched `verifast` and `refinement-checker` on
PATH. The script checks two things:

1. Every Challenge 7 constructor and unsafe helper is reported as verified in
   the module, on both targets, including every expansion of `atomic_int!`.
2. Weakening the proof in a way that would admit undefined behavior makes
   verification (or refinement checking) fail with the expected diagnostic.
"""

from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
FLAGS = "--edition=2024 --crate-type=lib"
TARGETS = {
    "x86_64-unknown-linux-gnu": [],
    # AtomicI128 and AtomicU128 exist only on targets with 128-bit atomics.
    "aarch64-unknown-linux-gnu": ["i128", "u128"],
}
CONSTRUCTORS = ["bool", "*mut T", "i8", "u8", "i16", "u16", "i32", "u32", "i64", "u64",
                "isize", "usize"]
HELPERS = ["atomic_store", "atomic_load", "atomic_swap", "atomic_add", "atomic_sub",
           "atomic_compare_exchange", "atomic_compare_exchange_weak", "atomic_and",
           "atomic_nand", "atomic_or", "atomic_xor", "atomic_max", "atomic_min",
           "atomic_umax", "atomic_umin"]


def verifast(cwd, target="x86_64-unknown-linux-gnu"):
    return ["verifast", "-verbose", "1", "-skip_specless_fns",
            "-rustc_args", f"{FLAGS} --target {target}", "verified/lib.rs"]


def run(command, cwd):
    result = subprocess.run(command, capture_output=True, text=True, cwd=cwd)
    return result.returncode, result.stdout + result.stderr


def check_coverage():
    for target, extra in TARGETS.items():
        status, output = run(verifast(HERE, target), HERE)
        expected = [f"atomic::Atomic::<{ty}>::from_ptr" for ty in CONSTRUCTORS + extra]
        expected += [f"atomic::{name}" for name in HELPERS]
        missing = [f for f in expected if f"Verifying function '{f}'" not in output]
        if status or "0 errors found" not in output or missing:
            sys.exit(f"{target}: module proof incomplete, missing {missing}\n{output[-2000:]}")
        print(f"{target}: {len(expected)} Challenge 7 functions verified")


# (name, occurrence, old, new, command, expected diagnostic). The occurrence
# "macro" mutates the first match inside `atomic_int!`; None requires a unique match.
STORE_KEEP = "[f]std::intrinsics::atomic_points_to(dst, 1, valid)"
STORE = ("[?f]std::intrinsics::atomic_points_to(dst, 1, ?valid) &*& valid(val) == true;\n"
         f"//@ ens thread_token(currentThread) &*& {STORE_KEEP};\n"
         f"//@ on_unwind_ens thread_token(currentThread) &*& {STORE_KEEP};")
LOAD = ("//@ req thread_token(currentThread) &*& [?f]std::intrinsics::atomic_points_to(dst, 1, ?valid);\n"
        "//@ ens thread_token(currentThread) &*& [f]std::intrinsics::atomic_points_to(dst, 1, valid) &*& valid(result) == true;\n"
        "//@ on_unwind_ens thread_token(currentThread) &*& [f]std::intrinsics::atomic_points_to(dst, 1, valid);")
VERIFY = "verify"
REFINE = "refine"
CONTROLS = [
    # from_ptr without the documented alignment requirement.
    ("ctor-int-missing-alignment", "macro",
     "ptr as usize % std::mem::align_of::<Self>() == 0 &*&", "true &*&", VERIFY,
     "std::intrinsics::atomic_align_of(int8_t_typeid)) = 0"),
    # A fresh conversion of storage that is not initialized.
    ("ctor-bool-uninitialized", None,
     "if fresh { *ptr |-> ?value } else { [_]frac_borrow('a, atomic_slot(ptr as *u8, bool_byte)) };",
     "if fresh { true } else { [_]frac_borrow('a, atomic_slot(ptr as *u8, bool_byte)) };", VERIFY,
     "No matching heap chunks: points_to<bool>"),
    # Reusing a location without an existing atomic view of it.
    ("ctor-int-reuse-without-slot", "macro",
     "if fresh { *ptr |-> ?value } else { [_]frac_borrow('a, atomic_slot(ptr, (std::intrinsics::atomic_value_allowed)(true))) };",
     "if fresh { *ptr |-> ?value } else { true };", VERIFY,
     "No matching heap chunks: [_]frac_borrow"),
    # An AtomicBool slot that admits any byte would not give back a valid bool.
    ("ctor-bool-unrestricted-byte", None,
     "fix bool_byte(b: u8) -> bool { b == 0 || b == 1 }", "fix bool_byte(b: u8) -> bool { true }",
     VERIFY, "Cannot prove v1 = 0 || v1 = 1"),
    # AtomicPtr needs the alignment of the pointer-sized atomic.
    ("ctor-ptr-missing-alignment-fact", None,
     "        //@ std::intrinsics::atomic_align_of_ptr::<T>();\n", "", VERIFY,
     "std::intrinsics::atomic_align_of(pointer_typeid(T_typeid))) = 0"),
    # A store through a read-only share.
    ("helper-store-read-fraction", None, STORE,
     STORE.replace("(dst, 1, ?valid)", "(dst, ?p, ?valid)").replace("(dst, 1, valid)", "(dst, p, valid)"),
     VERIFY, "No matching heap chunks: [_]std::intrinsics::atomic_points_to<T>(dst, 1, _)"),
    # A generic load through a read-only share (a load may write, for example
    # a 128-bit load implemented with compare-exchange).
    ("helper-load-read-fraction", None, LOAD,
     LOAD.replace("(dst, 1, ?valid)", "(dst, ?p, ?valid)").replace("(dst, 1, valid)", "(dst, p, valid)"),
     VERIFY, "No matching heap chunks: [_]std::intrinsics::atomic_points_to<T>(dst, 1, _)"),
    # A helper body that differs from the library is caught by the refinement checker.
    ("refinement-changed-ordering", None,
     "Relaxed => intrinsics::atomic_xchg::<T, { AO::Relaxed }>(dst, val),",
     "Relaxed => intrinsics::atomic_xchg::<T, { AO::SeqCst }>(dst, val),", REFINE, "atomic_xchg"),
]


def check_controls():
    module = (HERE / "verified/atomic.rs").read_text()
    macro_start = module.index("macro_rules! atomic_int")
    with tempfile.TemporaryDirectory(prefix="atomic-controls-") as directory:
        work = Path(directory)
        for side in ("original", "verified"):
            shutil.copytree(HERE / side, work / side)
        target = work / "verified/atomic.rs"
        for name, where, old, new, kind, diagnostic in CONTROLS:
            if where == "macro":
                index = module.index(old, macro_start)
                mutated = module[:index] + new + module[index + len(old):]
            else:
                if module.count(old) != 1:
                    sys.exit(f"{name}: expected one occurrence of {old!r}")
                mutated = module.replace(old, new)
            target.write_text(mutated)
            command = verifast(work) if kind == VERIFY else [
                "refinement-checker", "--rustc-args", FLAGS, "original/lib.rs", "verified/lib.rs"]
            status, output = run(command, work)
            if not status or diagnostic not in output:
                sys.exit(f"{name}: expected failure with {diagnostic!r}\n{output[-2000:]}")
            print(f"{name}: rejected as expected")
        target.write_text(module)


if __name__ == "__main__":
    check_coverage()
    check_controls()
    print(f"All {len(CONTROLS)} negative controls were rejected.")
