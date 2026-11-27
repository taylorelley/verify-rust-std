#!/usr/bin/env python3
"""Run concrete legal clients against a nightly with matching atomic sources."""

import argparse
import hashlib
from pathlib import Path
import subprocess
import tempfile

ATOMIC = Path("sync/atomic.rs")
INTRINSICS = Path("intrinsics/mod.rs")


def store_declaration(source):
    # Include the ordering enum and all adjacent atomic intrinsic declarations.
    start = source.index("pub enum AtomicOrdering {")
    end = source.index("pub const unsafe fn atomic_xchg", start)
    lines = source[start:end].splitlines(keepends=True)
    return "".join(line for line in lines if not line.lstrip().startswith("/// [`Ordering::"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rustc", type=Path)
    args = parser.parse_args()
    rustc = args.rustc.resolve()
    here = Path(__file__).resolve().parent
    repository = here.parents[4]
    fork = repository / "library/core/src"
    subprocess.run([rustc, "-vV"], check=True)
    sysroot = Path(subprocess.check_output([rustc, "--print", "sysroot"], text=True).strip())
    nightly = sysroot / "lib/rustlib/src/rust/library/core/src"
    atomic = (fork / ATOMIC).read_bytes()
    if atomic != (nightly / ATOMIC).read_bytes():
        raise SystemExit("The nightly sysroot and fork implement different atomic modules")
    intrinsics = store_declaration((fork / INTRINSICS).read_text())
    if intrinsics != store_declaration((nightly / INTRINSICS).read_text()):
        raise SystemExit("The nightly sysroot and fork declare different atomic load/store primitives")
    print("atomic.rs sha256:", hashlib.sha256(atomic).hexdigest(), flush=True)
    print("atomic intrinsic declarations sha256:", hashlib.sha256(intrinsics.encode()).hexdigest(), flush=True)
    with tempfile.TemporaryDirectory(prefix="challenge-7-") as directory:
        binary = Path(directory) / "bool-clients"
        subprocess.run([rustc, "--edition=2024", "--test", here / "bool-clients.rs", "-o", binary], check=True)
        subprocess.run([binary, "--test-threads=1"], check=True)


if __name__ == "__main__":
    main()
