#!/usr/bin/env python3
"""Replay strong and weak compare-exchange safety proofs and check every ordering pair."""

import argparse
import hashlib
import itertools
import json
import os
from pathlib import Path
import re
import runpy
import shutil
from string import Template
import subprocess
import tempfile

FAILURE = ("Relaxed", "Acquire", "SeqCst")
PAIRS = tuple(itertools.product(("Relaxed", "Acquire", "Release", "AcqRel", "SeqCst"), repeat=2))
FLAGS = ["--edition=2024", "--crate-type=lib"]
ARM = Template("""            ($SUCCESS, $FAILURE) => {
                //@ open ${ATOMIC}_share(k, currentThread, atomic);
                //@ open_frac_borrow(k, own_atomic_contents(dst), q);
                //@ open [?f]own_atomic_contents(dst)();
                let exchanged = $CALL;
                //@ close [f]own_atomic_contents(dst)();
                //@ close_frac_borrow(f, own_atomic_contents(dst));
                exchanged
            }""")
BRIDGE = Template("""
#[allow(invalid_atomic_ordering)]
#[unsafe(no_mangle)]
pub fn $NAME(a: &$TYPE, current: $PUBLIC, new: $PUBLIC) -> ($PUBLIC, bool, u8) {
    match a.$METHOD(current, new, Ordering::$SUCCESS, Ordering::$FAILURE) {
        Ok(v) => (v, true, $TAG),
        Err(v) => (v, false, $TAG),
    }
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
    swap = runpy.run_path(str(here / "check-swap.py"))
    matrix = runpy.run_path(str(here / "check-from-ptr.py"))
    pointer = runpy.run_path(str(here / "check-ptr.py"))
    constructor = runpy.run_path(str(here / "check-bool-constructor.py"))
    replace = constructor["replace_once"]
    run = runpy.run_path(str(here / "check-bool-store.py"))["run"]
    atomic = (source / "sync/atomic.rs").read_bytes()
    if hashlib.sha256(atomic).hexdigest() != constructor["SOURCE_SHA256"]:
        raise SystemExit("Review the changed atomic source before replaying compare-exchange")
    rustc = args.rustc.resolve()
    sysroot = Path(subprocess.check_output([rustc, "--print", "sysroot"], text=True).strip())
    order_decl = runpy.run_path(str(here / "check-bool-clients.py"))["store_declaration"]
    for root in (source, sysroot / "lib/rustlib/src/rust/library/core/src"):
        intrinsic_source = (root / "intrinsics/mod.rs").read_text()
        for name, prefix in (("atomic_cxchg", ""), ("atomic_cxchgweak", "_")):
            declaration = (
                f"#[rustc_intrinsic]\n#[rustc_nounwind]\npub const unsafe fn {name}<\n"
                "    T: Copy,\n    const ORD_SUCC: AtomicOrdering,\n    const ORD_FAIL: AtomicOrdering,\n"
                f">(\n    {prefix}dst: *mut T,\n    {prefix}old: T,\n    {prefix}src: T,\n) -> (T, bool);"
            )
            if declaration not in intrinsic_source:
                raise SystemExit(f"Review the changed declaration of {name}")
        if hashlib.sha256(order_decl(intrinsic_source).encode()).hexdigest() != (
            "6bb2f571c911c962ecd2ebe85bf74df718dfab191f22a8f70ee9dad71cca0fc5"
        ):
            raise SystemExit("Review the changed AtomicOrdering ABI")

    normalized = re.sub(r"(?m)^#\[rustc_diagnostic_item = ", "#[doc = ", atomic.decode())
    header = (here / "ptr-access.rs.in").read_text().split("// METHODS\n")[0]
    slot_template = Template((here / "slot-constructor.rs.in").read_text())
    method, helper = (here / "compare-exchange.rs.in").read_text().split("// HELPER\n")
    runtime = args.verifast_bin.resolve()
    logs = args.logs.resolve()
    logs.mkdir(parents=True, exist_ok=True)
    report = logs / "coverage.json"
    report.unlink(missing_ok=True)
    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = os.pathsep.join(filter(None, (str(runtime), env.get("LD_LIBRARY_PATH"))))
    coverage = {}

    def slot(atomic_type, operand, width, size=None):
        return header + slot_template.substitute(
            POINTEE="" if size is None else f"pub struct Pointee([u8; {size}]);",
            OPERAND=operand, FIELD=operand if size is None else "*mut super::Pointee",
            ATOMIC=atomic_type, WIDTH=width,
            ALIGN_LEMMA=f"atomic_align_of_{operand}()" if size is None else "atomic_align_of_ptr::<Pointee>()",
        )

    with tempfile.TemporaryDirectory(prefix="atomic-cas-") as directory:
        work = Path(directory)
        for doc in (source / "sync").glob("atomic*.md"):
            shutil.copyfile(doc, work / doc.name)
        original = work / "lib.rs"
        original.write_text(runpy.run_path(str(here / "probe-verifast.py"))["CRATE"])
        proof = work / "cas.rs"

        def check_case(label, atomic_type, operand, public, valid, base, layout, target, llvm_type, align,
                       pointer_size=None):
            flags = [*FLAGS, "--target", target]
            variant_type = "<Pointee>" if pointer_size is not None else ""
            pointee = f"\nstruct Pointee([u8; {pointer_size}]);\n" if pointer_size is not None else ""
            case_logs = logs / label
            case_logs.mkdir(exist_ok=True)
            keys = {pair: f"sc_cas_{index}" for index, pair in enumerate(PAIRS)}

            def compile_dispatch(crate, name):
                ir = case_logs / f"{name}.ll"
                status, output = run([rustc, *flags, "--emit=llvm-ir", "-C", "opt-level=2", crate, "-o", ir],
                                     case_logs / f"{name}-rustc.log")
                if status:
                    raise SystemExit(output)
                compiled = ir.read_text()
                # LLVM may merge identical always-panicking wrappers.
                aliases = dict(re.findall(r"(?m)^@(sc_cas_\d+) = .*\balias [^\n]+, ptr @(sc_cas_\d+)$", compiled))
                compiled = re.sub(r"!noalias !\d+", "!noalias !id", compiled)
                return {
                    pair: re.sub(r"dereferenceable\(24\) @alloc_[0-9a-f]+\) #\d+", "dereferenceable(24) @location)",
                                 swap["canonical_dispatch"](compiled, aliases.get(key, key)))
                    for pair, key in keys.items()
                }

            def verify(text, name, expected, failure=False):
                proof.write_text(text)
                status, output = run(
                    [runtime / "verifast", "-verbose", "1", "-skip_specless_fns", "-rustc_args", " ".join(flags), proof],
                    case_logs / f"{name}.log", env,
                )
                if bool(status) != failure or not all(marker in output for marker in expected):
                    raise SystemExit(f"Unexpected result in {label}/{name}.log")

            def bridges(api, atomic_name):
                return "".join(BRIDGE.substitute(
                    NAME=keys[(success, failure)], TYPE=atomic_name, PUBLIC=public, METHOD=api,
                    SUCCESS=success, FAILURE=failure, TAG=i,
                ) for i, (success, failure) in enumerate(PAIRS))

            for api, intrinsic in (("compare_exchange", "atomic_cxchg"),
                                   ("compare_exchange_weak", "atomic_cxchgweak")):
                is_weak = api.endswith("_weak")

                def call(success, failure):
                    return f"intrinsics::{intrinsic}::<{operand}, {{ AO::{success} }}, {{ AO::{failure} }}>(dst, old, new)"

                branches = "\n".join(ARM.substitute(
                    SUCCESS=success, FAILURE=failure, ATOMIC=atomic_type, CALL=call(success, failure),
                ) for success, failure in PAIRS if failure in FAILURE)
                convert = " as u8" if public == "bool" else ""
                body = (f"unsafe {{ atomic_{api}(self.v.get().cast::<{operand}>(), "
                        f"current{convert}, new{convert}, success, failure) }}")
                if public == "bool":
                    body = (
                        f"let byte = {body};\n"
                        "        //@ open <std::result::Result<u8, u8>>.own(currentThread, byte);\n"
                        "        let result = match byte {\n"
                        "            Ok(observed_ok) => {\n"
                        "                let ok_bool = observed_ok != 0;\n"
                        "                //@ close bool_own(currentThread, ok_bool);\n"
                        "                Ok(ok_bool)\n"
                        "            }\n"
                        "            Err(observed_err) => {\n"
                        "                let err_bool = observed_err != 0;\n"
                        "                //@ close bool_own(currentThread, err_bool);\n"
                        "                Err(err_bool)\n"
                        "            }\n"
                        "        };\n"
                        "        //@ close <std::result::Result<bool, bool>>.own(currentThread, result);\n"
                        "        result"
                    )
                mapping = dict(METHOD=api, PUBLIC=public, ATOMIC=atomic_type, OPERAND=operand, VALID=valid,
                               BODY=body, BRANCHES=branches,
                               OWN="raw_ptr_own::<Pointee>" if pointer_size is not None else f"{operand}_own")
                signature = f"impl {atomic_type} {{\n"
                text = replace(base, signature, signature + Template(method).substitute(mapping))
                text += "\n" + Template(helper).substitute(mapping)
                original_bridge = bridges(api, atomic_type + variant_type).replace(
                    "#[unsafe(no_mangle)]",
                    '#[stable(feature = "atomic_source_proof", since = "1.0.0")]\n#[unsafe(no_mangle)]',
                )
                (work / "atomic.rs").write_text(normalized + pointee + layout.replace("$TYPE", variant_type)
                                                + original_bridge)
                expected = compile_dispatch(original, f"original-{api}")
                suffix = layout.replace("$TYPE", "") + bridges(api, atomic_type)
                proof.write_text(text + suffix)
                observed = compile_dispatch(proof, f"specialized-{api}")
                for pair in PAIRS:
                    if expected[pair] != observed[pair]:
                        raise SystemExit(f"LLVM dispatch mismatch for {label}/{api}/{pair}")
                    weak = "weak " if is_weak else ""
                    marker = rf"cmpxchg {weak}ptr %a, {llvm_type} .*? (\w+) (\w+), align {align}\b"
                    instruction = re.findall(marker, expected[pair])
                    if pair[1] in FAILURE:
                        success, failure = pair
                        orders = swap["ORDERS"]
                        if instruction != [(orders[success], orders[failure])]:
                            raise SystemExit(f"Missing or unexpected compare-exchange for {label}/{api}/{pair}")
                    elif "cmpxchg " in expected[pair] or "panic" not in expected[pair]:
                        raise SystemExit(f"Missing panic dispatch for {label}/{api}/{pair}")

                verify(text, f"proof-{api}", ("0 errors found", f"target: {target}",
                                             f"Verifying function '{atomic_type}::{api}'",
                                             f"Verifying function 'atomic_{api}'"))
                if label == "bool":
                    mutations = {
                        "success": replace(text, call("AcqRel", "Relaxed"), call("Acquire", "Relaxed")),
                        "failure": replace(text, call("AcqRel", "Acquire"), call("AcqRel", "Relaxed")),
                        "outcome": replace(text, "if ok { Ok(val) } else { Err(val) }",
                                           "if ok { Err(val) } else { Ok(val) }"),
                        "strength": replace(text, call("Relaxed", "Relaxed"),
                                            call("Relaxed", "Relaxed").replace(
                                                intrinsic, "atomic_cxchg" if is_weak else "atomic_cxchgweak")),
                    }
                    for mutation, altered in mutations.items():
                        proof.write_text(altered + suffix)
                        if compile_dispatch(proof, f"changed-{mutation}-{api}") == expected:
                            raise SystemExit(f"Source comparison accepted a changed {mutation} for {api}")
                    verify(replace(text, "new as u8", "2"), f"reject-invalid-bool-{api}",
                           ("accepts_u8(2)",), failure=True)

                if label == "u16":
                    probe = f"""
unsafe fn cxchg_fraction(dst: *mut u16, old: u16, new: u16) -> (u16, bool)
//@ req std::intrinsics::atomic_points_to(dst, 1/2, accepts_value);
//@ ens std::intrinsics::atomic_points_to(dst, 1/2, accepts_value);
//@ on_unwind_ens false;
{{
    unsafe {{ intrinsics::{intrinsic}::<u16, {{ AO::Relaxed }}, {{ AO::Relaxed }}>(dst, old, new) }}
}}
"""
                    verify(text + probe, f"reject-read-fraction-{api}",
                           ("No matching heap chunks: [_]std::intrinsics::atomic_points_to",), failure=True)
                    invalid_order = replace(text, call("Relaxed", "Relaxed"), call("Relaxed", "Release"))
                    verify(invalid_order, f"reject-intrinsic-order-{api}",
                           ("unsupported success or failure ordering",), failure=True)

            coverage[label] = {"target": target, "strengths": ["strong", "weak"],
                               "legal_pairs": 15, "panic_pairs": 10}

        bool_base = header + (here / "bool-constructor.rs").read_text()
        check_case("bool", "AtomicBool", "u8", "bool", "accepts_u8", bool_base, constructor["LAYOUT"],
                   matrix["HOST"], "i8", 1)
        integer_cases = [(f"{sig}{bits}", bits, matrix["HOST"] if bits < 128 else matrix["WIDE"])
                         for bits in matrix["WIDTHS"] for sig in "iu"]
        integer_cases += [(kind, 64, matrix["HOST"]) for kind in ("isize", "usize")]
        for operand, bits, target in integer_cases:
            atomic_type = "Atomic" + operand.title()
            width = bits // 8
            layout = Template(swap["INTEGER_LAYOUT"]).substitute(TYPE=atomic_type, WIDTH=width)
            check_case(operand, atomic_type, operand, operand, "accepts_value", slot(atomic_type, operand, width),
                       layout, target, f"i{bits}", width)
        for size in pointer["SIZES"]:
            layout = pointer["LAYOUT"].replace("$SIZE", str(size))
            check_case(f"ptr-{size}", "AtomicPtr", "*mut Pointee", "*mut Pointee", "accepts_value",
                       slot("AtomicPtr", "*mut Pointee", 8, size), layout, matrix["HOST"], "ptr", 8, size)

    report.write_text(json.dumps(coverage, indent=2) + "\n")
    print(f"Verified both strengths and checked all 25 ordering pairs per strength for {len(coverage)} cases.")


if __name__ == "__main__":
    main()
