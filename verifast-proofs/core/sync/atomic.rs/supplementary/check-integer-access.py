#!/usr/bin/env python3
"""Replay ordinary integer load and store proofs on Linux x86-64 and AArch64."""

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

ORDERS = {
    "load": ("Relaxed", "Acquire", "SeqCst"),
    "store": ("Relaxed", "Release", "SeqCst"),
}
BRIDGE = Template("""
#[unsafe(no_mangle)]
pub fn sc_integer_load(a: &$ATOMIC, order: Ordering) -> ($OPERAND, u8) {
    (a.load(order), 1)
}

#[unsafe(no_mangle)]
pub fn sc_integer_store(a: &$ATOMIC, value: $OPERAND, order: Ordering) -> $OPERAND {
    a.store(value, order);
    value
}
""")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("verifast_bin", type=Path)
    parser.add_argument("rustc", type=Path)
    parser.add_argument("logs", type=Path)
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    source = here.parents[4] / "library/core/src"
    constructor = runpy.run_path(str(here / "check-bool-constructor.py"))
    matrix = runpy.run_path(str(here / "check-from-ptr.py"))
    swap = runpy.run_path(str(here / "check-swap.py"))
    run = runpy.run_path(str(here / "check-bool-store.py"))["run"]
    replace = constructor["replace_once"]
    atomic = (source / "sync/atomic.rs").read_bytes()
    # The compiled comparisons below link the proof to this source.
    print("atomic.rs sha256:", hashlib.sha256(atomic).hexdigest(), flush=True)
    rustc = args.rustc.resolve()
    sysroot = Path(subprocess.check_output([rustc, "--print", "sysroot"], text=True).strip())
    declaration = runpy.run_path(str(here / "check-bool-clients.py"))["store_declaration"]
    for src in (source, sysroot / "lib/rustlib/src/rust/library/core/src"):
        declarations = declaration((src / "intrinsics/mod.rs").read_text())
        if hashlib.sha256(declarations.encode()).hexdigest() != "6bb2f571c911c962ecd2ebe85bf74df718dfab191f22a8f70ee9dad71cca0fc5":
            raise SystemExit("Atomic intrinsic declarations changed. Review integer accesses.")

    logs = args.logs.resolve()
    logs.mkdir(parents=True, exist_ok=True)
    report = logs / "coverage.json"
    report.unlink(missing_ok=True)
    runtime = args.verifast_bin.resolve()
    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = os.pathsep.join(filter(None, (str(runtime), env.get("LD_LIBRARY_PATH"))))
    normalized = re.sub(r"(?m)^#\[rustc_diagnostic_item = ", "#[doc = ", atomic.decode())
    slot_template = Template((here / "slot-constructor.rs.in").read_text())
    header, sections = (here / "ptr-access.rs.in").read_text().split("// METHODS\n")
    methods, helpers = sections.split("// HELPERS\n")
    coverage = {}

    with tempfile.TemporaryDirectory(prefix="atomic-integer-access-") as directory:
        work = Path(directory)
        for doc in (source / "sync").glob("atomic*.md"):
            shutil.copyfile(doc, work / doc.name)
        original = work / "lib.rs"
        original.write_text(runpy.run_path(str(here / "probe-verifast.py"))["CRATE"])
        proof = work / "integer.rs"

        def check_case(operand, bits, target):
            atomic_type = "Atomic" + operand.title()
            width = bits // 8
            case_logs = logs / operand
            case_logs.mkdir(exist_ok=True)
            flags = [*swap["FLAGS"], "--target", target]
            slot = slot_template.substitute(
                POINTEE="", OPERAND=operand, FIELD=operand, ATOMIC=atomic_type,
                WIDTH=width, ALIGN_LEMMA=f"atomic_align_of_{operand}()",
            )
            def specialize(fragment):
                return fragment.replace("AtomicPtr", atomic_type).replace("*mut Pointee", operand)

            signature = f"impl {atomic_type} {{\n"
            text = header + replace(slot, signature, signature + specialize(methods))
            text += "\n" + specialize(helpers).replace("read_pointer_fraction", "read_slot")
            wide = bits == 128
            if wide:
                text = text.replace("atomic_points_to(src, 1/2,", "atomic_points_to(src, 1,")
            layout = Template(swap["INTEGER_LAYOUT"]).substitute(TYPE=atomic_type, WIDTH=width)
            bridge = BRIDGE.substitute(ATOMIC=atomic_type, OPERAND=operand)
            stable_bridge = bridge.replace(
                "#[unsafe(no_mangle)]",
                '#[stable(feature = "atomic_source_proof", since = "1.0.0")]\n#[unsafe(no_mangle)]',
            )
            (work / "atomic.rs").write_text(normalized + layout + stable_bridge)

            def compile_dispatch(path, label):
                ir = case_logs / f"{label}.ll"
                status, output = run([rustc, *flags, "--emit=llvm-ir", "-C", "opt-level=2", path, "-o", ir],
                                     case_logs / f"{label}-rustc.log")
                if status:
                    raise SystemExit(output)
                return dispatches(ir.read_text())

            def dispatches(ir):
                assembled = re.sub(r"!noalias !\d+", "!noalias !id", ir)
                # Normalize the location operand and retain resolved call attributes.
                return {
                    op: re.sub(r"dereferenceable\(24\) @alloc_[0-9a-f]+\)", "dereferenceable(24) @location)",
                               swap["canonical_dispatch"](assembled, f"sc_integer_{op}"))
                    for op in ORDERS
                }

            def verify(candidate, label, expected, reject=False):
                proof.write_text(candidate)
                status, output = run(
                    [runtime / "verifast", "-verbose", "1", "-skip_specless_fns", "-rustc_args", " ".join(flags), proof],
                    case_logs / f"{label}.log", env,
                )
                if bool(status) != reject or not all(marker in output for marker in expected):
                    raise SystemExit(f"Unexpected result in {operand}/{label}.log")

            expected = compile_dispatch(original, "original")
            if operand == "u128":
                bridge_ir = (case_logs / "original.ll").read_text()
                header_change, count = re.subn(
                    r"(?m)^(define .*@sc_integer_load\([^\n]*?%_0, ptr [^\n]*?nonnull align )16(\b)",
                    r"\g<1>32\2", bridge_ir,
                )
                if count != 1 or dispatches(header_change)["load"] == expected["load"]:
                    raise SystemExit("Source comparison accepted stronger alignment on the load bridge")
                (case_logs / "changed-header-alignment.ll").write_text(header_change)
                call_change, count = re.subn(
                    r"(?m)^(attributes #\d+ = \{ noreturn) \}$",
                    r"\1 nounwind }", bridge_ir,
                )
                if count != 1 or dispatches(call_change)["load"] == expected["load"]:
                    raise SystemExit("Source comparison accepted a changed panic call unwind contract")
                (case_logs / "changed-panic-call-attributes.ll").write_text(call_change)
            proof.write_text(text + layout + bridge)
            if compile_dispatch(proof, "specialized") != expected:
                raise SystemExit(f"Compiled load or store differs for {atomic_type}")
            first_order = {"load": "Acquire", "store": "Release"}
            for op, orders in ORDERS.items():
                value = "" if op == "load" else " %value"
                observed = re.findall(
                    rf"{op} atomic i{bits}{value}, ptr %a (\w+), align {width}\b", expected[op]
                )
                if sorted(observed) != sorted(swap["ORDERS"][order] for order in orders):
                    raise SystemExit(f"Missing or incorrect atomic instructions for {atomic_type}::{op}")
                if expected[op].count("panic_fmt") != 2:
                    raise SystemExit(f"Expected two invalid-order panic branches for {atomic_type}::{op}")
                order = first_order[op]
                call = f"intrinsics::atomic_{op}::<{operand}, {{ AO::{order} }}, false>"
                proof.write_text(replace(text, call, call.replace(order, "Relaxed")) + layout + bridge)
                if compile_dispatch(proof, f"changed-order-{op}")[op] == expected[op]:
                    raise SystemExit(f"Source comparison accepted a changed ordering for {atomic_type}::{op}")

            verify(text, "proof", ("0 errors found", f"target: {target}",
                  *(f"Verifying function '{name}'" for name in (
                      f"{atomic_type}::load", f"{atomic_type}::store",
                      "atomic_load", "atomic_store", "read_slot",
                  ))))
            load = f"intrinsics::atomic_load::<{operand}, {{ AO::Relaxed }}, false>(src as *const {operand})"
            store = f"intrinsics::atomic_store::<{operand}, {{ AO::Relaxed }}, false>(src, 0); 0"
            if wide:
                fractional = text.replace("atomic_points_to(src, 1,", "atomic_points_to(src, 1/2,")
                verify(fractional, "reject-wide-fractional-load",
                       ("No matching heap chunks: [_]std::intrinsics::atomic_points_to",), reject=True)
            else:
                verify(replace(text, load, store), "reject-fractional-write",
                       ("No matching heap chunks: [_]std::intrinsics::atomic_points_to",), reject=True)
            acquire = replace(text, load, load.replace("Relaxed", "Acquire"))
            if wide:
                acquire = acquire.replace("atomic_points_to(src, 1,", "atomic_points_to(src, 1/2,")
            verify(acquire, "reject-fractional-acquire",
                   ("No matching heap chunks: [_]std::intrinsics::atomic_points_to",), reject=True)
            if operand in ("i8", "u128"):
                verify(replace(text, load, load.replace("false", "true")), "reject-volatile",
                       ("only ordinary accesses (VOLATILE=false) are modeled",), reject=True)
                verify(replace(text, load, load.replace("Relaxed", "Release")), "reject-invalid-load",
                       ("unsupported ordering for an ordinary access",), reject=True)
            coverage[operand] = {
                "target": target, "load": list(ORDERS["load"]), "store": list(ORDERS["store"]),
                "panic_branches": 4, "fractional_relaxed_read": not wide,
            }

        for bits in matrix["WIDTHS"]:
            for sign in "iu":
                target = matrix["WIDE"] if bits == 128 else matrix["HOST"]
                check_case(f"{sign}{bits}", bits, target)
        for operand in ("isize", "usize"):
            check_case(operand, 64, matrix["HOST"])

    report.write_text(json.dumps(coverage, indent=2) + "\n")
    print(f"Verified ordinary load and store for {len(coverage)} integer types, with 72 legal and 48 panic branches.")


if __name__ == "__main__":
    main()
