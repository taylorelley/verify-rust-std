#!/usr/bin/env python3
"""Replay atomic exchange safety proofs against pinned Rust source on Linux x86-64 and AArch64."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import shutil
from string import Template
import subprocess
import tempfile

from llvm_dispatch import function_header

FLAGS = ["--edition=2024", "--crate-type=lib"]
ORDERS = {
    "Relaxed": "monotonic", "Acquire": "acquire", "Release": "release",
    "AcqRel": "acq_rel", "SeqCst": "seq_cst",
}
DECLARATION = """#[rustc_intrinsic]
#[rustc_nounwind]
pub const unsafe fn atomic_xchg<T: Copy, const ORD: AtomicOrdering>(dst: *mut T, src: T) -> T;"""
INTEGER_LAYOUT = """
const _: () = {
    assert!(size_of::<$TYPE>() == $WIDTH);
    assert!(align_of::<$TYPE>() == $WIDTH);
    assert!(std::mem::offset_of!($TYPE, v) == 0);
};
"""
BRIDGE = """
#[unsafe(no_mangle)]
pub fn sc_verify_swap(a: &${TYPE}, value: $PUBLIC, order: Ordering) -> $PUBLIC {
    a.swap(value, order)
}
"""


def canonical_dispatch(ir, name="sc_verify_swap"):
    """Preserve the CFG, instruction order and operands while renaming identifiers."""
    match = re.search(rf"^define [^\n]*@{re.escape(name)}\([^\n]*\{{\n(.*?)^}}", ir, re.S | re.M)
    if not match:
        raise SystemExit("The compiler did not emit the exchange dispatch")
    body = re.sub(r"(?m)\s*;[^\n]*$", "", match[1])
    names = re.findall(r"(?m)^(?:  (%[\w.]+) = |([\w.]+):)", body)
    canonical = {ssa or "%" + block: f"%id{index}" for index, (ssa, block) in enumerate(names)}
    body = re.sub(r"%[\w.]+", lambda m: canonical.get(m[0], m[0]), body)
    body = re.sub(r"(?m)^([\w.]+):", lambda m: canonical["%" + m[1]][1:] + ":", body)
    header = function_header(ir, match[0].splitlines()[0], name)
    return header + "\n" + re.sub(r" !prof !\d+", "", body)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("verifast_bin", type=Path)
    parser.add_argument("rustc", type=Path)
    parser.add_argument("logs", type=Path)
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    source = here.parents[3] / "library/core/src"
    ctor = runpy.run_path(str(here / "check-bool-constructor.py"))
    matrix = runpy.run_path(str(here / "check-from-ptr.py"))
    pointer = runpy.run_path(str(here / "check-ptr.py"))
    run = runpy.run_path(str(here / "check-bool-store.py"))["run"]
    replace = ctor["replace_once"]
    atomic = (source / "sync/atomic.rs").read_bytes()
    # The compiled comparisons below link the proof to this source.
    print("atomic.rs sha256:", hashlib.sha256(atomic).hexdigest(), flush=True)
    rustc = args.rustc.resolve()
    if f"host: {matrix['HOST']}" not in subprocess.check_output([rustc, "-vV"], text=True):
        raise SystemExit("The exchange proof requires Linux x86-64")
    sysroot = Path(subprocess.check_output([rustc, "--print", "sysroot"], text=True).strip())
    declaration = runpy.run_path(str(here / "check-bool-clients.py"))["store_declaration"]
    for root in (source, sysroot / "lib/rustlib/src/rust/library/core/src"):
        intrinsics = (root / "intrinsics/mod.rs").read_text()
        if DECLARATION not in intrinsics or hashlib.sha256(declaration(intrinsics).encode()).hexdigest() != (
            "6bb2f571c911c962ecd2ebe85bf74df718dfab191f22a8f70ee9dad71cca0fc5"
        ):
            raise SystemExit("Review the changed atomic intrinsic ABI before replaying the proof")

    logs = args.logs.resolve()
    logs.mkdir(parents=True, exist_ok=True)
    report = logs / "coverage.json"
    report.unlink(missing_ok=True)
    coverage = {}
    runtime = args.verifast_bin.resolve()
    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = os.pathsep.join(filter(None, (str(runtime), env.get("LD_LIBRARY_PATH"))))
    target = matrix["HOST"]
    verify_command = [runtime / "verifast", "-verbose", "1", "-skip_specless_fns", "-rustc_args"]
    header = (here / "ptr-access.rs.in").read_text().split("// METHODS\n")[0]
    slot = Template((here / "slot-constructor.rs.in").read_text())
    method, helper = (here / "swap.rs.in").read_text().split("// HELPER\n")
    normalized = re.sub(r"(?m)^#\[rustc_diagnostic_item = ", "#[doc = ", atomic.decode())

    with tempfile.TemporaryDirectory(prefix="atomic-swap-") as directory:
        work = Path(directory)
        for doc in (source / "sync").glob("atomic*.md"):
            shutil.copyfile(doc, work / doc.name)
        original = work / "lib.rs"
        original.write_text(runpy.run_path(str(here / "probe-verifast.py"))["CRATE"])
        proof = work / "swap.rs"

        def compile_dispatch(crate, label):
            ir = logs / f"{label}.ll"
            status, output = run([rustc, *FLAGS, "--target", target, "--emit=llvm-ir", "-C", "opt-level=2", crate, "-o", ir],
                                 logs / f"{label}-rustc.log")
            if status:
                raise SystemExit(output)
            return canonical_dispatch(ir.read_text())

        def verify(text, label, expected):
            proof.write_text(text)
            status, output = run([*verify_command, " ".join([*FLAGS, "--target", target]), proof], logs / f"{label}.log", env)
            if bool(status) != label.startswith("reject-") or not all(x in output for x in expected):
                raise SystemExit(f"Unexpected verifier result. See {label}.log")

        def check_case(name, atomic_type, operand, public, valid, base, layout, llvm_type, align, size=None):
            pointer_arg = "<Pointee>" if size is not None else ""
            original_bridge = Template(BRIDGE).substitute(TYPE=atomic_type + pointer_arg, PUBLIC=public)
            stable_bridge = original_bridge.replace(
                "#[unsafe(no_mangle)]",
                '#[stable(feature = "atomic_source_proof", since = "1.0.0")]\n#[unsafe(no_mangle)]',
            )
            pointee = f"\nstruct Pointee([u8; {size}]);\n" if size is not None else ""
            (work / "atomic.rs").write_text(normalized + pointee + layout.replace("$TYPE", pointer_arg) + stable_bridge)
            baseline = compile_dispatch(original, f"original-{name}")
            cases = {order: f"intrinsics::atomic_xchg::<{operand}, {{ AO::{order} }}>(dst, val)" for order in ORDERS}
            branches = "\n".join(f"            {order} => {call}," for order, call in cases.items())
            mapping = dict(ATOMIC=atomic_type, OPERAND=operand, PUBLIC=public, VALID=valid,
                           VALUE="val as u8" if public == "bool" else "val",
                           RESULT=" != 0" if public == "bool" else "", BRANCHES=branches)
            signature = f"impl {atomic_type} {{\n"
            text = replace(base, signature, signature + Template(method).substitute(mapping))
            text += "\n" + Template(helper).substitute(mapping)
            bridge = Template(BRIDGE).substitute(TYPE=atomic_type, PUBLIC=public)
            suffix = layout.replace("$TYPE", "") + bridge
            proof.write_text(text + suffix)
            candidate = compile_dispatch(proof, f"specialized-{name}")
            actual_orders = re.findall(rf"atomicrmw xchg ptr %a, {llvm_type} %[\w.]+ (\w+), align {align}\b",
                                       baseline)
            if candidate != baseline or sorted(actual_orders) != sorted(ORDERS.values()):
                raise SystemExit(f"Exchange dispatch mismatch for {name}. Compare the saved LLVM files.")

            wrong = replace(text, cases["AcqRel"], cases["AcqRel"].replace("AcqRel", "Acquire"))
            proof.write_text(wrong + suffix)
            if compile_dispatch(proof, f"changed-order-{name}") == baseline:
                raise SystemExit(f"Source comparison accepted a changed exchange ordering for {name}")
            wrong_return = replace(text, "    old\n}", "    val\n}")
            proof.write_text(wrong_return + suffix)
            if compile_dispatch(proof, f"changed-return-{name}") == baseline:
                raise SystemExit(f"Source comparison accepted returning the new value for {name}")

            verify(text, f"proof-{name}", ("0 errors found", f"target: {target}",
                                          f"Verifying function '{atomic_type}::swap'",
                                          "Verifying function 'atomic_swap'"))
            coverage[name] = {"target": target, "orderings": list(ORDERS)}
            return text

        bool_base = header + (here / "bool-constructor.rs").read_text()
        bool_text = check_case("bool", "AtomicBool", "u8", "bool", "accepts_u8",
                               bool_base, ctor["LAYOUT"], "i8", 1)
        verify(replace(bool_text, "val as u8", "2"), "reject-invalid-bool", ("accepts_u8(2)",))
        integer_cases = [(f"{sign}{bits}", bits, matrix["HOST"] if bits < 128 else matrix["WIDE"])
                         for bits in matrix["WIDTHS"] for sign in "iu"]
        integer_cases += [(kind, 64, matrix["HOST"]) for kind in ("isize", "usize")]
        for operand, bits, target in integer_cases:
            atomic_type = "Atomic" + operand.title()
            width = bits // 8
            base = header + slot.substitute(POINTEE="", OPERAND=operand, FIELD=operand, ATOMIC=atomic_type,
                                            WIDTH=width, ALIGN_LEMMA=f"atomic_align_of_{operand}()")
            layout = Template(INTEGER_LAYOUT).substitute(TYPE=atomic_type, WIDTH=width)
            check_case(operand, atomic_type, operand, operand, "accepts_value", base, layout, f"i{bits}", width)

        target = matrix["HOST"]
        for size in pointer["SIZES"]:
            ptr_base = header + slot.substitute(POINTEE=f"pub struct Pointee([u8; {size}]);",
                                               OPERAND="*mut Pointee", FIELD="*mut super::Pointee",
                                               ATOMIC="AtomicPtr", WIDTH=8,
                                               ALIGN_LEMMA="atomic_align_of_ptr::<Pointee>()")
            ptr_text = check_case(f"ptr-{size}", "AtomicPtr", "*mut Pointee", "*mut Pointee", "accepts_value",
                                  ptr_base, pointer["LAYOUT"].replace("$SIZE", str(size)), "ptr", 8, size)

        fraction = """
unsafe fn exchange_read_fraction(dst: *mut *mut Pointee, val: *mut Pointee) -> *mut Pointee
//@ req std::intrinsics::atomic_points_to(dst, 1/2, accepts_value);
//@ ens std::intrinsics::atomic_points_to(dst, 1/2, accepts_value);
//@ on_unwind_ens false;
{
    unsafe { intrinsics::atomic_xchg::<*mut Pointee, { AO::Relaxed }>(dst, val) }
}
"""
        verify(ptr_text + fraction, "reject-read-fraction", ("No matching heap chunks: [_]std::intrinsics::atomic_points_to",))
        wide = """
unsafe fn exchange_wide(dst: *mut *mut [u8], val: *mut [u8]) -> *mut [u8]
//@ req true;
//@ ens true;
{
    unsafe { intrinsics::atomic_xchg::<*mut [u8], { AO::Relaxed }>(dst, val) }
}
"""
        verify(header + wide, "reject-wide-ptr", ("atomic_xchg: expected a concrete integer or thin pointer",))

    report.write_text(json.dumps(coverage, indent=2) + "\n")
    print(f"All {len(coverage)} exchange cases passed the proof and matched all five orderings in the pinned Rust source.")
    print("Controls caught changed orderings and returns, an invalid Boolean byte, a read fraction and a wide pointer.")


if __name__ == "__main__":
    main()
