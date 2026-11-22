#!/usr/bin/env python3
"""Verify ordinary Boolean atomic loads and stores and compare both executable dispatches."""

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
pub fn sc_verify_bool_store(a: &AtomicBool, value: bool, order: Ordering) -> bool {
    a.store(value, order);
    value
}

#[unsafe(no_mangle)]
pub fn sc_verify_bool_load(a: &AtomicBool, order: Ordering) -> u8 {
    a.load(order) as u8 + 2
}
"""
SCOPE_BRIDGE = """
#[unsafe(no_mangle)]
pub unsafe fn sc_verify_bool_scope(ptr: *mut bool) -> (bool, bool) {
    let reference = unsafe { AtomicBool::from_ptr(ptr) };
    let ordinary = unsafe { *reference.as_ptr().cast::<u8>() != 0 };
    (ordinary, reference.load(Ordering::Relaxed))
}
"""
SPECIALIZED_SCOPE_BRIDGE = """
#[unsafe(no_mangle)]
pub unsafe fn sc_verify_bool_scope(ptr: *mut bool) -> (bool, bool) {
    unsafe { scoped_read_permissions(ptr) }
}
"""
RUST_FLAGS = "--edition=2024 --crate-type=lib"
RELAXED = "{ AO::Relaxed }, false>(dst, val)"
RELAXED_LOAD = "{ AO::Relaxed }, false>(src)"
EXPECTED_LOADS = ("load atomic i8, ptr %a monotonic, align 1",
                  "load atomic i8, ptr %a acquire, align 1",
                  "load atomic i8, ptr %a seq_cst, align 1")
EXPECTED_STORES = ("atomic i8 %_6, ptr %a monotonic, align 1",
            "atomic i8 %_6, ptr %a release, align 1",
            "atomic i8 %_6, ptr %a seq_cst, align 1")


def normalize_dispatch(ir, operation):
    match = re.search(rf"^define [^\n]*@sc_verify_bool_{operation}\([^\n]*\{{\n.*?^\}}", ir, re.S | re.M)
    if not match:
        raise SystemExit("The compiler did not emit the inline atomic dispatch")
    # Normalize names and metadata. Retain the instruction operands, edges,
    # atomic ordering, volatility, alignment and panic message allocation.
    text = re.sub(r"(?m)\s*;[^\n]*$", "", match[0])
    text = re.sub(r"\.i(?:\.i)?(?=[:,\s])", ".i", text)
    text = re.sub(r"%(_6)\.i\b", r"%\1", text)
    text = re.sub(r"_R[A-Za-z0-9_]+\.exit\b", "dispatch.exit", text)
    text = re.sub(r" !prof !\d+", "", text)
    text = re.sub(r" #\d+(?=\s|$)", "", text)
    text = re.sub(r"dereferenceable\(24\) @alloc_[0-9a-f]+", "dereferenceable(24) @location", text)
    if operation == "load":
        text = re.sub(r"%(?:_0|value)\.sroa\.0\.0\.i\b", "%loaded", text)
        text = re.sub(r"%(?:_4\.not|_0\.i\.not)\b", "%is_zero", text)
    if operation == "scope":
        # Rename only SSA definitions and their uses in this straight-line
        # wrapper. Keep the pointer, operand graph and memory operations.
        names = re.findall(r"(?m)^  (%[\w.]+) = ", text)
        canonical = {name: f"%ssa{index}" for index, name in enumerate(names)}
        text = re.sub(r"%[\w.]+", lambda match: canonical.get(match[0], match[0]), text)
        text = re.sub(r"!noundef !\d+", "!noundef !id", text)
    return text


def run(command, log, env=None):
    result = subprocess.run(command, capture_output=True, text=True, env=env)
    output = result.stdout + result.stderr
    log.write_text(output)
    return result.returncode, output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("verifast_bin", type=Path)
    parser.add_argument("rustc", type=Path)
    parser.add_argument("logs", type=Path)
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    constructor = runpy.run_path(str(here / "check-bool-constructor.py"))
    source_root = here.parents[3] / "library/core/src"
    atomic = (source_root / "sync/atomic.rs").read_bytes()
    if hashlib.sha256(atomic).hexdigest() != constructor["SOURCE_SHA256"]:
        raise SystemExit("Atomic module changed. Review the store specialization.")
    declarations = runpy.run_path(str(here / "check-bool-clients.py"))["store_declaration"]
    expected = "6bb2f571c911c962ecd2ebe85bf74df718dfab191f22a8f70ee9dad71cca0fc5"
    runtime = args.verifast_bin.resolve()
    rustc = args.rustc.resolve()
    sysroot = Path(subprocess.check_output([rustc, "--print", "sysroot"], text=True).strip())
    for core in (source_root, sysroot / "lib/rustlib/src/rust/library/core/src"):
        excerpt = declarations((core / "intrinsics/mod.rs").read_text())
        if hashlib.sha256(excerpt.encode()).hexdigest() != expected:
            raise SystemExit("Atomic intrinsic declarations changed. Review the decoder.")
    logs = args.logs.resolve()
    logs.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = os.pathsep.join(filter(None, (
        str(runtime), env.get("LD_LIBRARY_PATH"),
    )))
    header, methods = (here / "bool-store.rs.in").read_text().split("// STORE METHOD\n")
    store, helper = methods.split("// STORE HELPER\n")
    ctor = (here / "bool-constructor.rs").read_text()
    replace = constructor["replace_once"]
    proof_text = header + replace(ctor, "impl AtomicBool {\n", "impl AtomicBool {\n" + store) + "\n" + helper
    with tempfile.TemporaryDirectory(prefix="bool-store-") as directory:
        work = Path(directory)
        for document in (source_root / "sync").glob("atomic*.md"):
            shutil.copyfile(document, work / document.name)
        normalized = re.sub(r"(?m)^#\[rustc_diagnostic_item = ", "#[doc = ", atomic.decode())
        (work / "atomic.rs").write_text(normalized + constructor["LAYOUT"] +
            (BRIDGE + SCOPE_BRIDGE).replace("#[unsafe(no_mangle)]",
                           '#[stable(feature = "atomic_source_proof", since = "1.0.0")]\n#[unsafe(no_mangle)]'))
        original = work / "lib.rs"
        original.write_text(runpy.run_path(str(here / "probe-verifast.py"))["CRATE"])
        proof = work / "proof.rs"

        def compile_dispatch(crate, label):
            ir = logs / (label + ".ll")
            status, output = run([rustc, *RUST_FLAGS.split(), "--emit=llvm-ir", "-C", "opt-level=2",
                                  crate, "-o", ir], logs / (label + "-rustc.log"))
            if status:
                raise SystemExit(output)
            return {op: normalize_dispatch(ir.read_text(), op) for op in ("load", "store", "scope")}

        original_dispatch = compile_dispatch(original, "original-store")
        proof.write_text(proof_text + constructor["LAYOUT"] + BRIDGE + SPECIALIZED_SCOPE_BRIDGE)
        specialized_dispatch = compile_dispatch(proof, "specialized-store")
        if (specialized_dispatch != original_dispatch
                or not all(op in original_dispatch["store"] for op in EXPECTED_STORES)
                or not all(op in original_dispatch["load"] for op in EXPECTED_LOADS)
                or any(original_dispatch[op].count("tail call void") != 2 for op in ("load", "store"))):
            raise SystemExit("Current and specialized Boolean dispatches do not match")
        proof.write_text(replace(proof_text, RELAXED, RELAXED.replace("Relaxed", "Release")) + BRIDGE + SPECIALIZED_SCOPE_BRIDGE)
        if compile_dispatch(proof, "wrong-order-store") == original_dispatch:
            raise SystemExit("The source comparison accepted a changed ordering")

        proof.write_text(replace(proof_text, RELAXED_LOAD, RELAXED_LOAD.replace("Relaxed", "Acquire")) + BRIDGE + SPECIALIZED_SCOPE_BRIDGE)
        if compile_dispatch(proof, "wrong-order-load")["load"] == original_dispatch["load"]:
            raise SystemExit("The source comparison accepted a changed load ordering")

        reference_load = "intrinsics::atomic_load::<u8, { AO::Relaxed }, false>(atomic.v.get().cast::<u8>())"
        wrong_reference_order = replace(proof_text, reference_load, reference_load.replace("Relaxed", "Acquire"))
        proof.write_text(wrong_reference_order + BRIDGE + SPECIALIZED_SCOPE_BRIDGE)
        if compile_dispatch(proof, "wrong-scope-order")["scope"] == original_dispatch["scope"]:
            raise SystemExit("The source comparison accepted a changed reference load ordering")

        verifier = [runtime / "verifast", "-verbose", "1", "-skip_specless_fns",
                    "-rustc_args", RUST_FLAGS]
        proof.write_text(proof_text)
        status, output = run([*verifier, proof], logs / "store-proof.log", env)
        if status or not all(marker in output for marker in (
            "0 errors found", "Verifying function 'AtomicBool::store'",
            "Verifying function 'atomic_store'", "Verifying function 'AtomicBool::load'",
            "Verifying function 'atomic_load'", "Verifying function 'mixed_reads'",
            "Verifying function 'split_and_rejoin_reads'",
            "Verifying function 'readonly_from_ptr'", "Verifying function 'read_via_ref'",
            "Verifying function 'ordinary_via_ref'", "Verifying function 'scoped_read_permissions'",
            "target: x86_64-unknown-linux-gnu",
        )):
            raise SystemExit("Boolean load/store proof or coverage failed. See store-proof.log")

        mixed_load = "intrinsics::atomic_load::<u8, { AO::Relaxed }, false>(src as *const u8)"
        for name, anchor, replacement, diagnostic in (
            ("volatile", RELAXED, RELAXED.replace("false", "true"), "only ordinary accesses"),
            ("acquire", RELAXED, RELAXED.replace("Relaxed", "Acquire"), "unsupported ordering"),
            ("invalid-byte", RELAXED, RELAXED.replace("dst, val", "dst, 2"), "Cannot prove condition"),
            ("volatile-load", RELAXED_LOAD, RELAXED_LOAD.replace("false", "true"), "only ordinary accesses"),
            ("release-load", RELAXED_LOAD, RELAXED_LOAD.replace("Relaxed", "Release"), "unsupported ordering"),
            ("ended-scope", "        let atomic = unsafe { read_via_ref",
             "        //@ end_lifetime_m(k);\n        let atomic = unsafe { read_via_ref",
             "No matching heap chunks: lifetime_token"),
            ("reference-write", reference_load,
             "({ intrinsics::atomic_store::<u8, { AO::Relaxed }, false>(atomic.v.get().cast::<u8>(), 1); 1 })",
             "No matching heap chunks: [_]std::intrinsics::atomic_points_to"),
            ("mixed-read-write", mixed_load,
             "{ intrinsics::atomic_store::<u8, { AO::Relaxed }, false>(src, ordinary); ordinary }",
             "No matching heap chunks: [_]std::intrinsics::atomic_points_to"),

        ):
            proof.write_text(replace(proof_text, anchor, replacement))
            status, output = run([*verifier, proof], logs / (name + ".log"), env)
            if not status or diagnostic not in output:
                raise SystemExit(f"Unexpected control result. See {name}.log")
    print("Verified ordinary Boolean load and store, including their unwind paths.")
    print("Current and specialized LLVM dispatches and scoped reads matched. All controls passed.")


if __name__ == "__main__":
    main()
