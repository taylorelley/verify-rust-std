#!/usr/bin/env python3
"""Replay the AtomicU16 specialization and its alignment and overlap controls."""

import argparse
import hashlib
import os
from pathlib import Path
import re
import runpy
import shutil
import subprocess
import tempfile

BRIDGE = """
#[unsafe(no_mangle)]
pub unsafe fn sc_verify_u16_ctor(p: *mut u16) -> *const AtomicU16 {
    (unsafe { AtomicU16::from_ptr(p) }) as *const AtomicU16
}

#[unsafe(no_mangle)]
pub fn sc_verify_u16_load(a: &AtomicU16, order: Ordering) -> u16 {
    a.load(order) ^ 1
}

#[unsafe(no_mangle)]
pub fn sc_verify_u16_store(a: &AtomicU16, value: u16, order: Ordering) -> u16 {
    a.store(value, order);
    value
}
"""
LAYOUT = """
const _: () = {
    assert!(size_of::<AtomicU16>() == 2);
    assert!(align_of::<AtomicU16>() == 2);
    assert!(std::mem::offset_of!(AtomicU16, v) == 0);
};
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("verifast_bin", type=Path)
    parser.add_argument("rustc", type=Path)
    parser.add_argument("logs", type=Path)
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    constructor = runpy.run_path(str(here / "check-bool-constructor.py"))
    boolean = runpy.run_path(str(here / "check-bool-store.py"))
    normalize = boolean["normalize_dispatch"]
    replace = constructor["replace_once"]
    src = here.parents[4] / "library/core/src"
    atomic = (src / "sync/atomic.rs").read_bytes()
    # The compiled comparisons below link the proof to this source.
    print("atomic.rs sha256:", hashlib.sha256(atomic).hexdigest(), flush=True)
    declarations = runpy.run_path(str(here / "check-bool-clients.py"))["store_declaration"]
    expected = "6bb2f571c911c962ecd2ebe85bf74df718dfab191f22a8f70ee9dad71cca0fc5"
    rustc = args.rustc.resolve()
    sysroot = Path(subprocess.check_output([rustc, "--print", "sysroot"], text=True).strip())
    for core in (src, sysroot / "lib/rustlib/src/rust/library/core/src"):
        excerpt = declarations((core / "intrinsics/mod.rs").read_text())
        if hashlib.sha256(excerpt.encode()).hexdigest() != expected:
            raise SystemExit("Atomic intrinsic declarations changed.")
    logs = args.logs.resolve()
    logs.mkdir(parents=True, exist_ok=True)
    runtime = args.verifast_bin.resolve()
    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = os.pathsep.join(filter(None, (
        str(runtime), env.get("LD_LIBRARY_PATH"),
    )))
    flags = ["--edition=2024", "--crate-type=lib"]
    verifier = [runtime / "verifast", "-verbose", "1", "-skip_specless_fns", "-rustc_args", " ".join(flags)]
    source = (here / "u16-proof.rs").read_text()

    with tempfile.TemporaryDirectory(prefix="atomic-u16-") as directory:
        work = Path(directory)
        for document in (src / "sync").glob("atomic*.md"):
            shutil.copyfile(document, work / document.name)
        normalized = re.sub(r"(?m)^#\[rustc_diagnostic_item = ", "#[doc = ", atomic.decode())
        (work / "atomic.rs").write_text(normalized + LAYOUT + BRIDGE.replace(
            "#[unsafe(no_mangle)]",
            '#[stable(feature = "atomic_source_proof", since = "1.0.0")]\n#[unsafe(no_mangle)]'))
        upstream = work / "lib.rs"
        upstream.write_text(runpy.run_path(str(here / "probe-verifast.py"))["CRATE"])
        proof = work / "u16.rs"

        def compile_dispatch(crate, label):
            ir = logs / (label + ".ll")
            status, output = boolean["run"]([rustc, *flags, "--emit=llvm-ir", "-C", "opt-level=2",
                                             crate, "-o", ir], logs / (label + "-rustc.log"))
            if status:
                raise SystemExit(output)
            text = ir.read_text()
            return {op: normalize(text, op, "u16").replace("%value.sroa.0.0.i", "%loaded")
                    for op in ("ctor", "load", "store")}

        original = compile_dispatch(upstream, "original")
        proof.write_text(source + LAYOUT + BRIDGE)
        if compile_dispatch(proof, "specialized") != original:
            raise SystemExit("Current and specialized AtomicU16 dispatches do not match")
        for op, orders in (("load", ("monotonic", "acquire", "seq_cst")),
                           ("store", ("monotonic", "release", "seq_cst"))):
            instructions = re.findall(rf"{op} atomic i16,? [^\n]* (\w+), align 2", original[op])
            if sorted(instructions) != sorted(orders) or original[op].count("tail call void") != 2:
                raise SystemExit(f"Missing AtomicU16 {op} order or panic branch")
        changed = replace(source, "{ AO::Relaxed }, false>(src)", "{ AO::Acquire }, false>(src)")
        proof.write_text(changed + LAYOUT + BRIDGE)
        if compile_dispatch(proof, "wrong-order")["load"] == original["load"]:
            raise SystemExit("Source comparison accepted a changed load ordering")

        changed_ctor = replace(source, "&*ptr.cast()", "&*ptr.wrapping_add(1).cast()")
        proof.write_text(changed_ctor + LAYOUT + BRIDGE)
        if compile_dispatch(proof, "wrong-pointer")["ctor"] == original["ctor"]:
            raise SystemExit("Source comparison accepted a changed constructor pointer")

        def verify(label, text, diagnostic=None):
            proof.write_text(text)
            status, output = boolean["run"]([*verifier, proof], logs / (label + ".log"), env)
            if diagnostic is not None:
                if status == 0 or diagnostic not in output:
                    raise SystemExit(f"Unexpected rejection control result. See {label}.log")
            elif status or not all(marker in output for marker in (
                "0 errors found", "target: x86_64-unknown-linux-gnu",
                *(f"Verifying function '{name}'" for name in (
                    "AtomicU16::from_ptr", "AtomicU16::load", "AtomicU16::store",
                    "atomic_load", "atomic_store", "share_twice", "write_disjoint_byte")),
            )):
                raise SystemExit("AtomicU16 proof or coverage failed. See proof.log")

        verify("proof", source)
        code, fixture = source.split("unsafe fn write_disjoint_byte", 1)
        for label, offset in (("overlap-first-byte", ""), ("overlap-second-byte", ".add(1)")):
            mutant = fixture.replace(", byte: *mut u8", "").replace(" &*& *byte |-> ?initial", "")
            mutant = mutant.replace(" &*& *byte |-> _", "").replace(
                "    //@ let dst = byte;",
                f"    let byte = unsafe {{ word.cast::<u8>(){offset} }};\n    //@ let dst = byte;")
            if offset:
                # Give the control an in-bounds pointer so it must fail on
                # access permissions rather than on pointer arithmetic.
                mutant = mutant.replace("accepts_u16);", "accepts_u16) &*& pointer_within_limits(word as *u8 + 1) == true;", 1)
            verify(label, code + "unsafe fn write_disjoint_byte" + mutant,
                   "No matching heap chunks: [_]points_to<u8>")
        missing_storage = replace(source, " &*& *ptr |-> ?value &*& ptr as usize",
                                  " &*& ptr as usize")
        verify("uninitialized", missing_storage, "No matching heap chunks: points_to<u16>")
        verify("wrong-align", replace(source, "#[repr(C, align(2))]", "#[repr(C, align(4))]"),
               "Cannot prove alignof(private::Align2_type_info) = 2")
    print("AtomicU16 constructor, load, store, sharing and disjoint-byte proof passed.")
    print("Rejected both overlapping byte writes, wrong alignment, uninitialized storage, a changed ordering and a changed pointer.")


if __name__ == "__main__":
    main()
