#!/usr/bin/env python3
"""Verify AtomicPtr construction and ordinary accesses for five pointee sizes."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import shutil
import subprocess
from string import Template
import tempfile

from constructor_mir import compare_constructor_mir, upstream_storage_check

SIZES = (0, 1, 2, 3, 4)
LAYOUT = """
const _: () = {
    assert!(size_of::<Pointee>() == $SIZE);
    assert!(size_of::<*mut Pointee>() == 8);
    assert!(size_of::<AtomicPtr$TYPE>() == 8);
    assert!(align_of::<AtomicPtr$TYPE>() == 8);
    assert!(std::mem::offset_of!(AtomicPtr$TYPE, v) == 0);
};
"""
BRIDGE = """
#[unsafe(no_mangle)]
pub unsafe fn sc_verify_ptr_ctor<'a>(p: *mut *mut Pointee) -> &'a AtomicPtr$TYPE {
    unsafe { AtomicPtr::from_ptr(p) }
}

#[unsafe(no_mangle)]
pub fn sc_verify_ptr_load(a: &AtomicPtr$TYPE, order: Ordering) -> (*mut Pointee, u8) {
    (a.load(order), 1)
}

#[unsafe(no_mangle)]
pub fn sc_verify_ptr_store(a: &AtomicPtr$TYPE, value: *mut Pointee, order: Ordering) -> *mut Pointee {
    a.store(value, order);
    value
}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("verifast_bin", type=Path)
    parser.add_argument("rustc", type=Path)
    parser.add_argument("logs", type=Path)
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    constructor = runpy.run_path(str(here / "check-bool-constructor.py"))
    checks = runpy.run_path(str(here / "check-bool-store.py"))
    replace = constructor["replace_once"]
    src = here.parents[4] / "library/core/src/sync"
    atomic = (src / "atomic.rs").read_bytes()
    # The compiled comparisons below link the proof to this source.
    print("atomic.rs sha256:", hashlib.sha256(atomic).hexdigest(), flush=True)
    declaration = runpy.run_path(str(here / "check-bool-clients.py"))["store_declaration"]
    intrinsics = declaration((src.parent / "intrinsics/mod.rs").read_text())
    if hashlib.sha256(intrinsics.encode()).hexdigest() != "6bb2f571c911c962ecd2ebe85bf74df718dfab191f22a8f70ee9dad71cca0fc5":
        raise SystemExit("Atomic intrinsic declarations changed. Review pointer access.")
    template = Template((here / "slot-constructor.rs.in").read_text())

    header, sections = (here / "ptr-access.rs.in").read_text().split("// METHODS\n")
    methods, intrinsic_helpers = sections.split("// HELPERS\n")

    def render(size):
        constructor = template.substitute(POINTEE=f"pub struct Pointee([u8; {size}]);",
                                   OPERAND="*mut Pointee", FIELD="*mut super::Pointee",
                                   ATOMIC="AtomicPtr", WIDTH=8,
                                   ALIGN_LEMMA="atomic_align_of_ptr::<Pointee>()")
        combined = replace(constructor, "impl AtomicPtr {\n", "impl AtomicPtr {\n" + methods)
        return header + combined + "\n" + intrinsic_helpers

    logs = args.logs.resolve()
    logs.mkdir(parents=True, exist_ok=True)
    coverage = logs / "coverage.json"
    coverage.unlink(missing_ok=True)
    verified_sizes = []
    runtime = args.verifast_bin.resolve()
    rustc = args.rustc.resolve()
    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = os.pathsep.join(filter(None, (str(runtime), env.get("LD_LIBRARY_PATH"))))
    flags = ["--edition=2024", "--crate-type=lib"]
    if "host: x86_64-unknown-linux-gnu" not in subprocess.check_output([rustc, "-vV"], text=True):
        raise SystemExit("The compiler must target the same Linux x86-64 ABI as the proof")
    verifier = [runtime / "verifast", "-verbose", "1", "-skip_specless_fns", "-rustc_args", " ".join(flags)]
    crate = runpy.run_path(str(here / "probe-verifast.py"))["CRATE"]
    normalized = re.sub(r"(?m)^#\[rustc_diagnostic_item = ", "#[doc = ", atomic.decode())

    with tempfile.TemporaryDirectory(prefix="atomic-ptr-") as directory:
        work = Path(directory)
        for doc in src.glob("atomic*.md"):
            shutil.copyfile(doc, work / doc.name)
        upstream = work / "lib.rs"
        upstream.write_text(crate)
        proof = work / "ptr.rs"

        def compile_dispatch(source, label):
            output = logs / (label + ".ll")
            status, diagnostics = checks["run"](
                [rustc, *flags, "--emit=llvm-ir", "-C", "opt-level=2", source, "-o", output],
                logs / (label + "-rustc.log"),
            )
            if status:
                raise SystemExit(diagnostics)
            text = output.read_text()
            return {op: checks["normalize_dispatch"](text, op, "ptr")
                    for op in ("ctor", "load", "store")}

        def verify(source, label, diagnostic=None):
            proof.write_text(source)
            status, output = checks["run"]([*verifier, proof], logs / (label + ".log"), env)
            if diagnostic is not None:
                if not status or diagnostic not in output:
                    raise SystemExit(f"Unexpected control result. See {label}.log")
            elif status or not all(marker in output for marker in (
                "0 errors found", "target: x86_64-unknown-linux-gnu",
                *(f"Verifying function '{name}'" for name in (
                    "AtomicPtr::from_ptr", "share_twice", "recover_slot",
                    "AtomicPtr::as_ptr", "AtomicPtr::load", "AtomicPtr::store",
                    "atomic_load", "atomic_store", "read_pointer_fraction",
                )),
            )):
                raise SystemExit(f"Pointer proof or coverage failed. See {label}.log")

        for size in SIZES:
            generated = render(size)
            layout = LAYOUT.replace("$SIZE", str(size))
            original_bridge = BRIDGE.replace(
                "#[unsafe(no_mangle)]",
                '#[stable(feature = "atomic_source_proof", since = "1.0.0")]\n#[unsafe(no_mangle)]',
            )
            storage = upstream_storage_check(atomic.decode(), 8, "*mut Pointee", "AtomicPtr<Pointee>")
            (work / "atomic.rs").write_text(
                normalized + f"\nstruct Pointee([u8; {size}]);\n"
                + storage + (layout + original_bridge).replace("$TYPE", "<Pointee>"),
            )
            suffix = (layout + BRIDGE).replace("$TYPE", "")
            proof.write_text(generated + suffix)
            original = compile_dispatch(upstream, f"original-{size}")
            case_logs = logs / f"constructor-{size}"
            case_logs.mkdir(exist_ok=True)
            compare_constructor_mir(rustc, flags, upstream, proof, case_logs,
                                    "*mut Pointee", "AtomicPtr", pointer=True)
            if compile_dispatch(proof, f"specialized-{size}") != original:
                raise SystemExit(f"Compiled pointer operations differ at pointee size {size}")
            for op, orders in (("load", ("monotonic", "acquire", "seq_cst")),
                               ("store", ("monotonic", "release", "seq_cst"))):
                operand = "ptr," if op == "load" else "ptr %value,"
                expected_orders = sorted(orders)
                actual_orders = sorted(re.findall(
                    rf"{op} atomic {operand} ptr %a (\w+), align 8", original[op]
                ))
                if actual_orders != expected_orders or original[op].count("tail call void") != 2:
                    raise SystemExit(f"Missing pointer-typed {op} ordering or panic branch for size {size}")
            (case_logs / "verified.rs").write_text(generated)
            verify(generated, f"proof-{size}")
            verified_sizes.append(size)

        # The last case supplies the baseline for the mutation controls.
        generated = render(SIZES[-1])
        proof.write_text(replace(generated, "&*ptr.cast()", "&*ptr.wrapping_add(1).cast()") + suffix)
        if compile_dispatch(proof, "changed-slot")["ctor"] == original["ctor"]:
            raise SystemExit("Source comparison accepted a changed slot address")

        verify(replace(generated, " &*& *ptr |-> ?value &*& ptr as usize", " &*& ptr as usize"),
               "missing-slot", "No matching heap chunks: points_to")
        verify(replace(generated, "*ptr |-> ?value &*& ptr as usize % std::mem::align_of::<AtomicPtr>() == 0;",
                       "*ptr |-> ?value;"),
               "missing-alignment", "alignof(AtomicPtr_type_info)) = 0")
        verify(replace(generated, "close exists::<bool>(false);", "close exists::<bool>(true);"),
               "double-fresh", "No matching heap chunks: points_to")
        verify(replace(generated, "    //@ end_lifetime_m(k);\n", ""),
               "live-recovery", "No matching heap chunks: [_]lifetime_dead_token")
        verify(replace(generated, "#[repr(C, align(8))]", "#[repr(C, align(16))]"),
               "wrong-alignment", "Cannot prove alignof(private::AlignedSlot_type_info) = 8")

        load = "intrinsics::atomic_load::<*mut Pointee, { AO::Acquire }, false>(src)"
        wrong_order = replace(generated, load, load.replace("Acquire", "Relaxed"))
        proof.write_text(wrong_order + suffix)
        if compile_dispatch(proof, "changed-load-order")["load"] == original["load"]:
            raise SystemExit("Source comparison accepted a changed pointer load ordering")
        store = "intrinsics::atomic_store::<*mut Pointee, { AO::Release }, false>(dst, val)"
        wrong_order = replace(generated, store, store.replace("Release", "Relaxed"))
        proof.write_text(wrong_order + suffix)
        if compile_dispatch(proof, "changed-store-order")["store"] == original["store"]:
            raise SystemExit("Source comparison accepted a changed pointer store ordering")
        verify(replace(generated, load, load.replace("Acquire", "Release")),
               "illegal-load-order", "unsupported ordering for an ordinary access")
        verify(replace(generated, load, load.replace("false", "true")),
               "volatile-load", "only ordinary accesses (VOLATILE=false) are modeled")
        read = "intrinsics::atomic_load::<*mut Pointee, { AO::Relaxed }, false>(src as *const *mut Pointee)"
        write = "intrinsics::atomic_store::<*mut Pointee, { AO::Relaxed }, false>(src, std::ptr::null_mut()); std::ptr::null_mut()"
        verify(replace(generated, read, write), "store-with-read-fraction",
               "No matching heap chunks: [_]std::intrinsics::atomic_points_to")
        verify((here / "ptr-wide-probe.rs").read_text(), "wide-pointer",
               "expected a concrete integer or thin pointer")

    coverage.write_text(json.dumps({"target": "x86_64-unknown-linux-gnu", "pointee_sizes": verified_sizes}) + "\n")
    print("AtomicPtr::from_ptr verified for pointee sizes 0, 1, 2, 3, and 4.")
    print("Pointer loads and stores verified. Compiled dispatch, permissions and rejection controls passed.")


if __name__ == "__main__":
    main()
