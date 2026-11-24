#!/usr/bin/env python3
"""Replay atomic arithmetic or bitwise safety proofs and check compiled dispatch."""

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
    parser.add_argument("--bitwise", action="store_true", help="check AND, NAND, OR and XOR")
    args = parser.parse_args()
    operations = ("and", "nand", "or", "xor") if args.bitwise else ("add", "sub")
    family = "bitwise" if args.bitwise else "arithmetic"
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
        raise SystemExit("Review the changed atomic source before replay")
    rustc = args.rustc.resolve()
    sysroot = Path(subprocess.check_output([rustc, "--print", "sysroot"], text=True).strip())
    order_decl = runpy.run_path(str(here / "check-bool-clients.py"))["store_declaration"]
    for root in (source, sysroot / "lib/rustlib/src/rust/library/core/src"):
        intrinsic_source = (root / "intrinsics/mod.rs").read_text()
        for op in operations:
            intrinsic = f"atomic_{op}" if args.bitwise else f"atomic_x{op}"
            declaration = (
                f"#[rustc_intrinsic]\n#[rustc_nounwind]\npub const unsafe fn {intrinsic}"
                "<T: Copy, U: Copy, const ORD: AtomicOrdering>(\n    dst: *mut T,\n    src: U,\n) -> T;"
            )
            if declaration not in intrinsic_source:
                raise SystemExit(f"Review the changed declaration of {intrinsic}")
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
            is_bool = label == "bool"
            public = "bool" if is_bool else delta
            returns = "bool" if is_bool else slot
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
            if is_bool:
                invariant = "std::intrinsics::atomic_bool_byte"
                base = (here / "bool-constructor.rs").read_text()
                base = replace(base, "fix accepts_u8(value: u8) -> bool { value == 0 || value == 1 }\n", "")
                base = header + base.replace("accepts_u8", invariant)
            else:
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

            checked_methods = []
            for op in operations:
                if is_pointer and op == "nand":
                    continue
                bool_nand = is_bool and op == "nand"
                scaled_pointer = is_pointer and not args.bitwise
                api = f"fetch_byte_{op}" if scaled_pointer else f"fetch_{op}"
                apis = (api, f"fetch_ptr_{op}") if scaled_pointer else (api,)
                checked_methods.extend(apis)

                def bridges(name):
                    return "".join(BRIDGE.substitute(ATOMIC=name, DELTA=public, SLOT=returns, METHOD=api_name)
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

                primitive = "xor" if bool_nand else op
                intrinsic = f"atomic_{primitive}" if args.bitwise else f"atomic_x{primitive}"
                # Preserve the order of arms from the pinned source for the IR comparison.
                arm_order = list(swap["ORDERS"])
                if primitive in ("or", "xor"):
                    arm_order[0], arm_order[-1] = arm_order[-1], arm_order[0]
                calls = {
                    order: f"intrinsics::{intrinsic}::<{slot}, {delta}, {{ AO::{order} }}>(dst, val)"
                    for order in arm_order
                }
                condition = f" &*& {invariant}(val) == true" if is_bool else ""
                mapping = dict(OP=primitive, METHOD=api, CONST="" if is_pointer else "const ", SLOT=slot,
                               DELTA=delta, ATOMIC=atomic_type, PUBLIC=public, RETURN=returns,
                               INPUT_CONDITION=condition,
                               BRANCHES="\n".join(f"            {order} => {call}," for order, call in calls.items()))
                if bool_nand:
                    mapping["ACCESS"] = (
                        "if val { atomic_xor(self.v.get().cast::<u8>(), 1, order) != 0 } "
                        "else { atomic_swap(self.v.get().cast::<u8>(), 1, order) != 0 }"
                    )
                else:
                    value = "val as u8" if is_bool else "val"
                    mapping["ACCESS"] = f"atomic_{op}(self.v.get().cast::<{slot}>(), {value}, order)"
                    if is_bool:
                        mapping["ACCESS"] += " != 0"
                methods = Template(method).substitute(mapping)
                if scaled_pointer:
                    methods += Template(element).substitute(mapping)
                signature = f"impl {atomic_type} {{\n"
                text = replace(base, signature, signature + methods) + "\n" + Template(helper).substitute(mapping)
                if bool_nand:
                    exchange = "\n".join(
                        f"            {order} => intrinsics::atomic_xchg::<u8, {{ AO::{order} }}>(dst, val),"
                        for order in swap["ORDERS"]
                    )
                    text += "\n" + Template(helper).substitute(dict(mapping, OP="swap", BRANCHES=exchange))

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
                    raise SystemExit(f"LLVM dispatch mismatch for {label}/{op}")
                for name, dispatch in expected.items():
                    zero_offset = scaled_pointer and pointer_size == 0 and name.startswith("fetch_ptr_")
                    opcodes = ("xor", "xchg") if bool_nand else (("or",) if zero_offset else (op,))
                    operand = "1" if bool_nand else ("0" if zero_offset else r"%[\w.]+")
                    for opcode in opcodes:
                        actual = re.findall(
                            rf"atomicrmw {opcode} ptr %a, i{bits} {operand} (\w+), align {bits // 8}\b",
                            dispatch,
                        )
                        if sorted(actual) != sorted(swap["ORDERS"].values()):
                            raise SystemExit(f"Missing or unexpected orderings for {label}/{name}/{opcode}")
                wrong_order = replace(text, calls["AcqRel"], calls["AcqRel"].replace("AcqRel", "Acquire"))
                proof.write_text(wrong_order + suffix)
                if compile_dispatch(proof, "changed-order") == expected:
                    raise SystemExit(f"Source comparison accepted a changed ordering for {label}/{op}")

                if label == "ptr-3" and scaled_pointer:
                    wrong_scale = replace(text, "wrapping_mul(size_of::<Pointee>())", "wrapping_mul(1)")
                    proof.write_text(wrong_scale + suffix)
                    if compile_dispatch(proof, "changed-scale") == expected:
                        raise SystemExit(f"Source comparison accepted a changed element size for {op}")
                if label == "u16":
                    other = ("atomic_or" if op == "xor" else "atomic_xor") if args.bitwise else (
                        "atomic_xsub" if op == "add" else "atomic_xadd")
                    wrong_opcode = replace(text, calls["Relaxed"], calls["Relaxed"].replace(intrinsic, other))
                    proof.write_text(wrong_opcode + suffix)
                    if compile_dispatch(proof, "changed-opcode") == expected:
                        raise SystemExit(f"Source comparison accepted a changed opcode for {op}")

                helpers = (primitive, "swap") if bool_nand else (primitive,)
                verify(text, f"proof-{op}", ("0 errors found", f"target: {target}",
                       *(f"Verifying function '{atomic_type}::{name}'" for name in apis),
                       *(f"Verifying function 'atomic_{name}'" for name in helpers)))

                if label == "u16":
                    for name, fraction, inv in (
                        ("fraction", "1/2", invariant), ("narrow-invariant", "1", "only_zero"),
                    ):
                        probe = f"""
//@ fix only_zero(value: u16) -> bool {{ value == 0 }}
unsafe fn rejected_operation(dst: *mut u16, val: u16) -> u16
//@ req std::intrinsics::atomic_points_to(dst, {fraction}, {inv});
//@ ens std::intrinsics::atomic_points_to(dst, {fraction}, {inv});
//@ on_unwind_ens false;
{{
    unsafe {{ intrinsics::{intrinsic}::<u16, u16, {{ AO::Relaxed }}>(dst, val) }}
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

                if is_bool:
                    if bool_nand:
                        invalid = replace(text, calls["Relaxed"], calls["Relaxed"].replace(intrinsic, "atomic_nand"))
                        diagnostic = "No matching heap chunks: [_]std::intrinsics::atomic_points_to"
                    else:
                        invalid = replace(text, "val as u8", "2")
                        diagnostic = "atomic_bool_byte(2)"
                    verify(invalid, f"reject-invalid-boolean-{op}", (diagnostic,), reject=True)

            coverage[label] = {"target": target, "methods": checked_methods, "orderings": list(swap["ORDERS"])}

        if args.bitwise:
            check_case("bool", "AtomicBool", "u8", "u8", constructor["LAYOUT"], matrix["HOST"], 8)
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
    print(f"Verified {family} operations and matched all five orderings for {len(coverage)} slot specializations.")


if __name__ == "__main__":
    main()
