#!/usr/bin/env python3
"""Replay atomic add and subtract safety proofs for integers and pointer offsets."""

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

BRIDGE = Template("""
#[unsafe(no_mangle)]
pub fn sc_verify_$METHOD(a: &$ATOMIC, value: $DELTA, order: Ordering) -> $SLOT {
    a.$METHOD(value, order)
}
""")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("verifast_bin", type=Path)
    parser.add_argument("rustc", type=Path)
    parser.add_argument("logs", type=Path)
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    source = here.parents[3] / "library/core/src"
    constructor = runpy.run_path(str(here / "check-bool-constructor.py"))
    matrix = runpy.run_path(str(here / "check-from-ptr.py"))
    pointer = runpy.run_path(str(here / "check-ptr.py"))
    swap = runpy.run_path(str(here / "check-swap.py"))
    run = runpy.run_path(str(here / "check-bool-store.py"))["run"]
    replace = constructor["replace_once"]
    atomic = (source / "sync/atomic.rs").read_bytes()
    if hashlib.sha256(atomic).hexdigest() != constructor["SOURCE_SHA256"]:
        raise SystemExit("Review the changed atomic source before replaying arithmetic")
    rustc = args.rustc.resolve()
    sysroot = Path(subprocess.check_output([rustc, "--print", "sysroot"], text=True).strip())
    order_decl = runpy.run_path(str(here / "check-bool-clients.py"))["store_declaration"]
    for root in (source, sysroot / "lib/rustlib/src/rust/library/core/src"):
        intrinsic_source = (root / "intrinsics/mod.rs").read_text()
        for op in ("add", "sub"):
            declaration = (
                f"#[rustc_intrinsic]\n#[rustc_nounwind]\npub const unsafe fn atomic_x{op}"
                "<T: Copy, U: Copy, const ORD: AtomicOrdering>(\n    dst: *mut T,\n    src: U,\n) -> T;"
            )
            if declaration not in intrinsic_source:
                raise SystemExit(f"Review the changed declaration of atomic_x{op}")
        if hashlib.sha256(order_decl(intrinsic_source).encode()).hexdigest() != (
            "6bb2f571c911c962ecd2ebe85bf74df718dfab191f22a8f70ee9dad71cca0fc5"
        ):
            raise SystemExit("Review the changed AtomicOrdering ABI")

    normalized = re.sub(r"(?m)^#\[rustc_diagnostic_item = ", "#[doc = ", atomic.decode())
    header = (here / "ptr-access.rs.in").read_text().split("// METHODS\n")[0]
    slot_template = Template((here / "slot-constructor.rs.in").read_text())
    method, rest = (here / "arithmetic.rs.in").read_text().split("// ELEMENT METHOD\n")
    element, helper = rest.split("// HELPER\n")
    runtime = args.verifast_bin.resolve()
    logs = args.logs.resolve()
    logs.mkdir(parents=True, exist_ok=True)
    report = logs / "coverage.json"
    report.unlink(missing_ok=True)
    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = os.pathsep.join(filter(None, (str(runtime), env.get("LD_LIBRARY_PATH"))))
    coverage = {}

    with tempfile.TemporaryDirectory(prefix="atomic-arithmetic-") as directory:
        work = Path(directory)
        for doc in (source / "sync").glob("atomic*.md"):
            shutil.copyfile(doc, work / doc.name)
        original = work / "lib.rs"
        original.write_text(runpy.run_path(str(here / "probe-verifast.py"))["CRATE"])
        proof = work / "arithmetic.rs"

        def check_case(label, atomic_type, slot, delta, layout, target, bits, pointer_size=None):
            is_pointer = pointer_size is not None
            flags = [*swap["FLAGS"], "--target", target]
            pointer_arg = "<Pointee>" if is_pointer else ""
            pointee = f"\nstruct Pointee([u8; {pointer_size}]);\n" if is_pointer else ""
            case_logs = logs / label
            case_logs.mkdir(exist_ok=True)
            invariant = "(std::intrinsics::atomic_value_allowed)(true)"
            base = slot_template.substitute(
                POINTEE=pointee.replace("struct", "pub struct") if is_pointer else "",
                OPERAND=slot, FIELD="*mut super::Pointee" if is_pointer else slot,
                ATOMIC=atomic_type, WIDTH=bits // 8,
                ALIGN_LEMMA="atomic_align_of_ptr::<Pointee>()" if is_pointer else f"atomic_align_of_{slot}()",
            )
            base = header + replace(base, f"fix accepts_value(value: {slot}) -> bool {{ true }}\n", "")
            base = base.replace("accepts_value", invariant)

            def verify(text, name, expected, reject=False):
                proof.write_text(text)
                status, output = run(
                    [runtime / "verifast", "-verbose", "1", "-skip_specless_fns", "-rustc_args", " ".join(flags), proof],
                    case_logs / f"{name}.log", env,
                )
                if bool(status) != reject or not all(marker in output for marker in expected):
                    raise SystemExit(f"Unexpected verifier result in {label}/{name}.log")

            for op in ("add", "sub"):
                api = f"fetch_byte_{op}" if is_pointer else f"fetch_{op}"
                apis = (api, f"fetch_ptr_{op}") if is_pointer else (api,)

                def bridges(name):
                    return "".join(BRIDGE.substitute(ATOMIC=name, DELTA=delta, SLOT=slot, METHOD=api_name)
                                   for api_name in apis)

                def compile_dispatch(crate, name):
                    ir = case_logs / f"{name}-{op}.ll"
                    status, output = run([rustc, *flags, "--emit=llvm-ir", "-C", "opt-level=2", crate, "-o", ir],
                                         case_logs / f"{name}-{op}-rustc.log")
                    if status:
                        raise SystemExit(output)
                    compiled = ir.read_text()
                    # For a one-byte pointee, element offsets and byte offsets coincide.
                    aliases = dict(re.findall(
                        r"(?m)^@(sc_verify_\w+) = .*\balias [^\n]+, ptr @(sc_verify_\w+)$", compiled
                    ))
                    return {name: swap["canonical_dispatch"](
                        compiled, aliases.get(f"sc_verify_{name}", f"sc_verify_{name}")
                    ) for name in apis}

                calls = {
                    order: f"intrinsics::atomic_x{op}::<{slot}, {delta}, {{ AO::{order} }}>(dst, val)"
                    for order in swap["ORDERS"]
                }
                mapping = dict(OP=op, METHOD=api, CONST="" if is_pointer else "const ", SLOT=slot,
                               DELTA=delta, ATOMIC=atomic_type,
                               BRANCHES="\n".join(f"            {order} => {call}," for order, call in calls.items()))
                methods = Template(method).substitute(mapping)
                if is_pointer:
                    methods += Template(element).substitute(mapping)
                signature = f"impl {atomic_type} {{\n"
                text = replace(base, signature, signature + methods) + "\n" + Template(helper).substitute(mapping)

                stable_bridge = bridges(atomic_type + pointer_arg).replace(
                    "#[unsafe(no_mangle)]",
                    '#[stable(feature = "atomic_source_proof", since = "1.0.0")]\n#[unsafe(no_mangle)]',
                )
                (work / "atomic.rs").write_text(normalized + pointee + layout.replace("$TYPE", pointer_arg)
                                                + stable_bridge)
                expected = compile_dispatch(original, "original")
                suffix = layout.replace("$TYPE", "") + bridges(atomic_type)
                proof.write_text(text + suffix)
                if compile_dispatch(proof, "specialized") != expected:
                    raise SystemExit(f"Arithmetic LLVM dispatch mismatch for {label}/{op}")
                for name, dispatch in expected.items():
                    # LLVM can express a zero-offset operation as an atomic OR with zero.
                    operation = "or" if pointer_size == 0 and name.startswith("fetch_ptr_") else op
                    operand = "0" if operation == "or" else r"%[\w.]+"
                    actual = re.findall(
                        rf"atomicrmw {operation} ptr %a, i{bits} {operand} (\w+), align {bits // 8}\b",
                        dispatch,
                    )
                    if sorted(actual) != sorted(swap["ORDERS"].values()):
                        raise SystemExit(f"Missing or unexpected orderings for {label}/{name}")
                wrong_order = replace(text, calls["AcqRel"], calls["AcqRel"].replace("AcqRel", "Acquire"))
                proof.write_text(wrong_order + suffix)
                if compile_dispatch(proof, "changed-order") == expected:
                    raise SystemExit(f"Source comparison accepted a changed arithmetic ordering for {label}/{op}")

                if label == "ptr-3":
                    wrong_scale = replace(text, "wrapping_mul(size_of::<Pointee>())", "wrapping_mul(1)")
                    proof.write_text(wrong_scale + suffix)
                    if compile_dispatch(proof, "changed-scale") == expected:
                        raise SystemExit(f"Source comparison accepted a changed element size for {op}")
                if label == "u16":
                    other = "sub" if op == "add" else "add"
                    wrong_opcode = replace(text, calls["Relaxed"], calls["Relaxed"].replace(f"x{op}", f"x{other}"))
                    proof.write_text(wrong_opcode + suffix)
                    if compile_dispatch(proof, "changed-opcode") == expected:
                        raise SystemExit(f"Source comparison accepted an opposite operation for {op}")

                verify(text, f"proof-{op}", ("0 errors found", f"target: {target}",
                       *(f"Verifying function '{atomic_type}::{name}'" for name in apis),
                       f"Verifying function 'atomic_{op}'"))

                if label == "u16":
                    for name, fraction, inv in (
                        ("fraction", "1/2", invariant), ("narrow-invariant", "1", "only_zero"),
                    ):
                        probe = f"""
//@ fix only_zero(value: u16) -> bool {{ value == 0 }}
unsafe fn bad_arithmetic(dst: *mut u16, val: u16) -> u16
//@ req std::intrinsics::atomic_points_to(dst, {fraction}, {inv});
//@ ens std::intrinsics::atomic_points_to(dst, {fraction}, {inv});
//@ on_unwind_ens false;
{{
    unsafe {{ intrinsics::atomic_x{op}::<u16, u16, {{ AO::Relaxed }}>(dst, val) }}
}}
"""
                        verify(text + probe, f"reject-{name}-{op}", (
                            "No matching heap chunks: [_]std::intrinsics::atomic_points_to",
                        ), reject=True)

                if label == "ptr-3":
                    wrong_delta = replace(text, calls["Relaxed"], calls["Relaxed"].replace(
                        ", usize,", ", u64,").replace("dst, val", "dst, val as u64"))
                    verify(wrong_delta, f"reject-pointer-delta-{op}",
                           ("expected matching integer operands or a concrete thin pointer with a usize delta",),
                           reject=True)

            coverage[label] = {"target": target, "methods": ["fetch_add", "fetch_sub"] if not is_pointer
                               else ["fetch_byte_add", "fetch_byte_sub", "fetch_ptr_add", "fetch_ptr_sub"],
                               "orderings": list(swap["ORDERS"])}

        integers = [(f"{sign}{bits}", bits, matrix["HOST"] if bits < 128 else matrix["WIDE"])
                    for bits in matrix["WIDTHS"] for sign in "iu"]
        integers += [(kind, 64, matrix["HOST"]) for kind in ("isize", "usize")]
        for operand, bits, target in integers:
            atomic_type = "Atomic" + operand.title()
            layout = Template(swap["INTEGER_LAYOUT"]).substitute(TYPE=atomic_type, WIDTH=bits // 8)
            check_case(operand, atomic_type, operand, operand, layout, target, bits)
        for size in pointer["SIZES"]:
            layout = pointer["LAYOUT"].replace("$SIZE", str(size))
            check_case(f"ptr-{size}", "AtomicPtr", "*mut Pointee", "usize", layout, matrix["HOST"], 64, size)

    report.write_text(json.dumps(coverage, indent=2) + "\n")
    print(f"Verified arithmetic and matched all five orderings for {len(coverage)} slot specializations.")


if __name__ == "__main__":
    main()
