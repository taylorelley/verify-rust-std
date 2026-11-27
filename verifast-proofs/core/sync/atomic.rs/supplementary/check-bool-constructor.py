#!/usr/bin/env python3
"""Check the specialized constructor proof and the source connection."""

import argparse
import hashlib
from pathlib import Path
import re
import runpy
import shutil
import subprocess
import tempfile

from constructor_mir import constructor_mir, upstream_storage_check

LAYOUT = """
const _: () = {
    assert!(std::mem::size_of::<AtomicBool>() == 1);
    assert!(std::mem::align_of::<AtomicBool>() == 1);
    assert!(std::mem::offset_of!(AtomicBool, v) == 0);
};
"""
CONTROLS = {
    "double-fresh": (
        "close exists::<bool>(false);",
        "close exists::<bool>(true);",
        "No matching heap chunks: points_to<bool>",
    ),
    "no-share": (
        "close exists::<bool>(true);",
        "close exists::<bool>(false);",
        "No matching heap chunks: [_]AtomicBool_share",
    ),
    "uninitialized": (
        " &*& *ptr |-> ?value &*& ptr as usize",
        " &*& ptr as usize",
        "No matching heap chunks: points_to<bool>",
    ),
}


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise SystemExit(f"Expected one occurrence of {old!r}")
    return text.replace(old, new)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("verifast_bin", type=Path)
    parser.add_argument("rustc", type=Path, help="Compiler from the fork's pinned nightly")
    parser.add_argument("logs", type=Path)
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    source = here.parents[4] / "library/core/src/sync"
    atomic = (source / "atomic.rs").read_bytes()
    # The compiled comparisons below link the proof to this source.
    print("atomic.rs sha256:", hashlib.sha256(atomic).hexdigest(), flush=True)
    crate_header = runpy.run_path(str(here / "probe-verifast.py"))["CRATE"]
    logs = args.logs.resolve()
    logs.mkdir(parents=True, exist_ok=True)
    verifier = [args.verifast_bin.resolve() / "verifast", "-verbose", "1",
                "-skip_specless_fns", "-rustc_args", "--edition=2024 --crate-type=lib"]

    with tempfile.TemporaryDirectory(prefix="bool-constructor-") as directory:
        work = Path(directory)
        for document in source.glob("atomic*.md"):
            shutil.copyfile(document, work / document.name)
        normalized = re.sub(r"(?m)^#\[rustc_diagnostic_item = ", "#[doc = ", atomic.decode())
        (work / "atomic.rs").write_text(normalized + LAYOUT + upstream_storage_check(atomic.decode(), 1, "u8", "AtomicBool"))
        original = work / "lib.rs"
        original.write_text(crate_header)
        proof_text = (here / "bool-constructor.rs").read_text()
        proof = work / "bool_constructor.rs"
        proof.write_text(proof_text + LAYOUT)
        mir = []
        rustc = args.rustc.resolve()
        for crate in (original, proof):
            output = logs / (crate.stem + ".mir")
            subprocess.run([rustc, "--edition=2024", "--crate-type=lib", "--emit=mir",
                            "-Zmir-opt-level=2", crate, "-o", output], check=True,
                           capture_output=True, text=True)
            mir.append(output)
        expected = constructor_mir(mir[0], "bool", "atomic::Atomic<bool>", "AtomicBool")
        if expected != constructor_mir(mir[1], "bool", "AtomicBool", "AtomicBool"):
            raise SystemExit("Specialized from_ptr differs in runtime or const-evaluation MIR")
        # Confirm that a changed pointer computation cannot reuse the bridge.
        mutated = work / "mutated.rs"
        mutated.write_text(replace_once(proof_text, "&*ptr.cast()", "&*ptr.wrapping_add(1).cast()"))
        mutated_mir = work / "mutated.mir"
        subprocess.run([rustc, "--edition=2024", "--crate-type=lib", "--emit=mir",
                        "-Zmir-opt-level=2", mutated, "-o", mutated_mir], check=True,
                       capture_output=True, text=True)
        if expected == constructor_mir(mutated_mir, "bool", "AtomicBool", "AtomicBool"):
            raise SystemExit("Source comparison accepted a changed pointer computation")
        print("Original and specialized layouts and constructor MIR agree.")

        def verify(name, source_text):
            proof.write_text(source_text)
            result = subprocess.run([*verifier, proof], capture_output=True, text=True)
            output = result.stdout + result.stderr
            (logs / (name + ".log")).write_text(output)
            return result.returncode, output

        (logs / "verified.rs").write_text(proof_text)
        status, output = verify("constructor", proof_text)
        if status or not all(fragment in output for fragment in (
            "0 errors found", "target: x86_64-unknown-linux-gnu", "Verifying function 'AtomicBool::from_ptr'",
            "Verifying function 'share_twice'",
        )):
            raise SystemExit("Expected proof and caller coverage. See constructor.log")

        for name, (old, new, diagnostic) in CONTROLS.items():
            status, output = verify(name, replace_once(proof_text, old, new))
            if not status or f"error: {diagnostic}" not in output:
                raise SystemExit(f"Unexpected result. See {name}.log")
        print("Constructor and sharing caller verified. All rejection controls passed.")


if __name__ == "__main__":
    main()
