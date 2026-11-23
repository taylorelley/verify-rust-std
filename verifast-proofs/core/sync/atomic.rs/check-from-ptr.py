#!/usr/bin/env python3
"""Replay every required Challenge 7 constructor on an eligible target."""

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
import sys
import tempfile

HOST = "x86_64-unknown-linux-gnu"
WIDE = "aarch64-unknown-linux-gnu"
WIDTHS = (8, 16, 32, 64, 128)
BRIDGE = """
#[unsafe(no_mangle)]
pub unsafe fn sc_verify_integer_ctor<'a>(ptr: *mut $OPERAND) -> &'a $ATOMIC {
    unsafe { $ATOMIC::from_ptr(ptr) }
}

const _: () = {
    assert!(size_of::<$ATOMIC>() == $WIDTH);
    assert!(align_of::<$ATOMIC>() == $WIDTH);
    assert!(std::mem::offset_of!($ATOMIC, v) == 0);
};
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("verifast_bin", type=Path)
    parser.add_argument("rustc", type=Path, help="Compiler from the fork's pinned nightly")
    parser.add_argument("logs", type=Path)
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    helpers = runpy.run_path(str(here / "check-bool-constructor.py"))
    runner = runpy.run_path(str(here / "check-bool-store.py"))
    replace = helpers["replace_once"]
    source_dir = here.parents[3] / "library/core/src/sync"
    atomic = (source_dir / "atomic.rs").read_bytes()
    if hashlib.sha256(atomic).hexdigest() != helpers["SOURCE_SHA256"]:
        raise SystemExit("Atomic source changed. Review the constructor specializations.")
    rustc = args.rustc.resolve()
    runtime = args.verifast_bin.resolve()
    logs = args.logs.resolve()
    logs.mkdir(parents=True, exist_ok=True)
    report = logs / "coverage.json"
    report.unlink(missing_ok=True)
    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = os.pathsep.join(filter(None, (str(runtime), env.get("LD_LIBRARY_PATH"))))
    configs = {target: subprocess.check_output([rustc, "--target", target, "--print", "cfg"], text=True)
               for target in (HOST, WIDE)}
    template = Template((here / "slot-constructor.rs.in").read_text())
    crate = runpy.run_path(str(here / "probe-verifast.py"))["CRATE"]
    normalized = re.sub(r"(?m)^#\[rustc_diagnostic_item = ", "#[doc = ", atomic.decode())
    cases = [(f"{sign}{bits}", bits, HOST if bits < 128 else WIDE)
             for bits in WIDTHS for sign in "iu"]
    cases += [(kind, 64, HOST) for kind in ("isize", "usize")]
    coverage = {}

    with tempfile.TemporaryDirectory(prefix="integer-constructors-") as directory:
        work = Path(directory)
        for doc in source_dir.glob("atomic*.md"):
            shutil.copyfile(doc, work / doc.name)
        original = work / "lib.rs"
        original.write_text(crate)
        proof = work / "proof.rs"

        for operand, bits, target in cases:
            feature = "ptr" if operand.endswith("size") else str(bits)
            if f'target_has_atomic_load_store="{feature}"' not in configs[target].splitlines():
                raise SystemExit(f"Required {operand} constructor is unavailable on {target}")
            name = "Atomic" + operand.title()
            width = bits // 8
            case_logs = logs / operand
            case_logs.mkdir(exist_ok=True)
            source = template.substitute(POINTEE="", OPERAND=operand, FIELD=operand, ATOMIC=name,
                                         WIDTH=width, ALIGN_LEMMA=f"atomic_align_of_{operand}()")
            bridge = Template(BRIDGE).substitute(OPERAND=operand, ATOMIC=name, WIDTH=width)
            (work / "atomic.rs").write_text(normalized + bridge.replace(
                "#[unsafe(no_mangle)]",
                '#[stable(feature = "atomic_source_proof", since = "1.0.0")]\n#[unsafe(no_mangle)]',
            ))
            flags = ["--edition=2024", "--crate-type=lib", "--target", target]

            def compile_constructor(path, label):
                ir = case_logs / (label + ".ll")
                status, output = runner["run"]([rustc, *flags, "--emit=llvm-ir", "-C", "opt-level=2",
                                               path, "-o", ir], case_logs / (label + "-rustc.log"))
                if status:
                    raise SystemExit(output)
                return runner["normalize_dispatch"](ir.read_text(), "ctor", "integer")

            upstream = compile_constructor(original, "original")
            proof.write_text(source + bridge)
            if compile_constructor(proof, "specialized") != upstream:
                raise SystemExit(f"Compiled {name} constructor differs")
            proof.write_text(replace(source, "&*ptr.cast()", "&*ptr.wrapping_add(1).cast()") + bridge)
            if compile_constructor(proof, "changed-slot") == upstream:
                raise SystemExit(f"Source comparison accepted a changed {name} slot")

            verifier = [runtime / "verifast", "-verbose", "1", "-skip_specless_fns",
                        "-rustc_args", " ".join(flags)]

            def verify(label, text, expected_error=None):
                proof.write_text(text)
                status, output = runner["run"]([*verifier, proof], case_logs / (label + ".log"), env)
                if expected_error:
                    passed = status != 0 and expected_error in output
                else:
                    required = ("0 errors found", f"(target: {target} ",
                                *(f"Verifying function '{function}'" for function in (
                                    f"{name}::from_ptr", "share_twice", "recover_slot",
                                )))
                    passed = status == 0 and all(marker in output for marker in required)
                if not passed:
                    raise SystemExit(f"{name} {label} failed. See {case_logs / (label + '.log')}")

            verify("proof", source)
            verify("uninitialized", replace(source, " &*& *ptr |-> ?value &*& ptr as usize",
                                            " &*& ptr as usize"), f"No matching heap chunks: points_to<{operand}>")
            verify("live-recovery", replace(source, "    //@ end_lifetime_m(k);\n", ""),
                   "No matching heap chunks: [_]lifetime_dead_token")
            verify("wrong-alignment", replace(source, f"#[repr(C, align({width}))]",
                                              f"#[repr(C, align({2 * width}))]"),
                   f"Cannot prove alignof(private::AlignedSlot_type_info) = {width}")
            coverage[name] = {"target": target, "bytes": width, "required": not operand.endswith("size")}
            print(f"{name} passed on {target}", flush=True)

    for check, log_dir in (("check-bool-constructor.py", "bool"), ("check-ptr.py", "ptr")):
        subprocess.run([sys.executable, here / check, runtime, rustc, logs / log_dir], check=True, env=env)
    coverage["AtomicBool"] = {"target": HOST, "bytes": 1, "required": True}
    pointer = json.loads((logs / "ptr/coverage.json").read_text())
    if pointer["target"] != HOST or sorted(pointer["pointee_sizes"]) != [0, 1, 2, 3, 4]:
        raise SystemExit("Incomplete pointer constructor coverage")
    coverage["AtomicPtr"] = {"bytes": 8, "required": True, **pointer}
    challenge = here.parents[3] / "doc/src/challenges/0007-atomic-types.md"
    required = set(re.findall(r"^- `(Atomic\w+)::from_ptr`$", challenge.read_text(), re.M))
    if required != {name for name, case in coverage.items() if case["required"]}:
        raise SystemExit("Replay coverage differs from the Challenge 7 constructor list")
    report.write_text(json.dumps(coverage, indent=2) + "\n")
    print(f"All 12 required constructors passed. Two pointer-sized integer extras passed. See {report}.")


if __name__ == "__main__":
    main()
