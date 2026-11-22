#!/usr/bin/env python3
"""Test whether VeriFast can process the current atomic layout."""

import argparse
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

CRATE = """#![feature(core_intrinsics, staged_api, rustc_attrs, cfg_target_has_atomic,
           decl_macro, const_trait_impl, const_convert, deprecated_suggestion)]
#![feature(register_tool, impl_restriction, arbitrary_self_types_pointers)]
#![register_tool(lint)]
#![allow(internal_features)]
#![stable(feature = "atomic_source_proof", since = "1.0.0")]
use core::{cell, fmt, hint, intrinsics, mem, num, ptr};
pub mod atomic;
"""
RUST_FLAGS = "--edition=2024 --crate-type=lib"


def run(command, log):
    result = subprocess.run(command, capture_output=True, text=True)
    output = result.stdout + result.stderr
    log.write_text(output)
    diagnostic = re.search(r'Fatal error: exception Failure\("([^"]+)"\)', output)
    print(f"{log.name}: exit {result.returncode}"
          + (f", {diagnostic[1]}" if diagnostic else ""), flush=True)
    return result.returncode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("verifast_bin", type=Path)
    parser.add_argument("logs", type=Path)
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    source = here.parents[3] / "library/core/src/sync"
    runtime = args.verifast_bin.resolve()
    logs = args.logs.resolve()
    logs.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="verifast-atomic-") as directory:
        work = Path(directory)
        for path in source.glob("atomic*.md"):
            shutil.copyfile(path, work / path.name)
        atomic = (source / "atomic.rs").read_text()
        # The sysroot already defines these diagnostic items. Preserve the
        # implementation and turn the duplicate item registrations into docs.
        normalized = re.sub(r"(?m)^#\[rustc_diagnostic_item = ", "#[doc = ", atomic)
        (work / "atomic.rs").write_text(normalized)
        crate = work / "lib.rs"
        crate.write_text(CRATE)

        projection = here / "projection.rs"
        control = work / "concrete.rs"
        control.write_text(projection.read_text().replace(
            "struct Atomic<T: AtomicPrimitive>", "struct Atomic"
        ).replace("UnsafeCell<T::Storage>", "UnsafeCell<u8>"))
        verifier = [runtime / "verifast", "-skip_specless_fns", "-rustc_args", RUST_FLAGS]
        result = [
            run([*verifier, control], logs / "concrete-layout.log"),
            run([*verifier, projection], logs / "associated-layout.log"),
            run([*verifier, crate], logs / "current-source.log"),
            run([runtime / "refinement-checker", "--verbose", "0", "--rustc-args",
                 RUST_FLAGS, crate, crate], logs / "identity-refinement.log"),
        ]
    # The module check is a front-end probe. It has no safety annotations.
    return int(any(result))


if __name__ == "__main__":
    raise SystemExit(main())
