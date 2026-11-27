#!/usr/bin/env python3
"""Identify which features block proofs against the real scoped-thread API."""

import argparse
import json
from pathlib import Path
import subprocess

FLAGS = ("--edition=2024", "--crate-type=lib")
CLOSURE = "Function calls that pass closures are not yet supported"
FUNCTION_VALUE = "Functions as operand in rvalues are not supported yet"
PROBES = {
    "positive-control": ("pub fn control() {}\n", None),
    "scope-closure": (
        "pub fn scoped() { std::thread::scope(|_| ()); }\n", CLOSURE,
    ),
    "scope-function": (
        """
fn worker(_: &std::thread::Scope<'_, '_>) {}
pub fn scoped() { std::thread::scope(worker); }
""", FUNCTION_VALUE,
    ),
    "spawn-function": (
        """
fn worker() {}
pub fn spawn_worker<'scope, 'env>(scope: &'scope std::thread::Scope<'scope, 'env>) {
    scope.spawn(worker);
}
""", FUNCTION_VALUE,
    ),
    "join": (
        """
pub fn join_worker(handle: std::thread::ScopedJoinHandle<'_, ()>) {
    let _ = handle.join();
}
""", "Dynamic types are not yet supported",
    ),
}


def run(command, log):
    completed = subprocess.run(command, capture_output=True, text=True)
    output = completed.stdout + completed.stderr
    log.write_text(output)
    return completed.returncode, output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("verifast_bin", type=Path)
    parser.add_argument("rustc", type=Path)
    parser.add_argument("logs", type=Path)
    args = parser.parse_args()
    logs = args.logs.resolve()
    logs.mkdir(parents=True, exist_ok=True)
    report = logs / "scope-boundary.json"
    report.unlink(missing_ok=True)
    here = Path(__file__).resolve().parent
    probes = {
        **PROBES,
        "scope-and-spawn": ((here / "scope-api-probe.rs").read_text(), CLOSURE),
    }
    results = {}
    for name, (program, diagnostic) in probes.items():
        fixture = logs / f"{name}.rs"
        fixture.write_text(program)
        rc, _ = run(
            [args.rustc.resolve(), *FLAGS, "--emit=metadata", fixture, "-o", logs / f"{name}.rmeta"],
            logs / f"{name}-rustc.log",
        )
        if rc:
            raise SystemExit(f"Rust rejected {name}. See {name}-rustc.log")
        rc, output = run(
            [args.verifast_bin.resolve() / "verifast", "-verbose", "1", "-rustc_args", " ".join(FLAGS), fixture],
            logs / f"{name}-verifast.log",
        )
        if diagnostic is None:
            if rc or "0 errors found" not in output or "Verifying function 'control'" not in output:
                raise SystemExit("The positive verifier control failed.")
            results[name] = {"rustc": "accepted", "verifast": "verified"}
        else:
            if not rc or diagnostic not in output:
                raise SystemExit(f"Unexpected result for {name}. Review {name}-verifast.log")
            results[name] = {"rustc": "accepted", "verifast": "blocked", "diagnostic": diagnostic}

    report.write_text(json.dumps(results, indent=2) + "\n")
    print("Scoped-thread proof remains blocked: closure calls, function values and dynamic join payloads.")


if __name__ == "__main__":
    main()
