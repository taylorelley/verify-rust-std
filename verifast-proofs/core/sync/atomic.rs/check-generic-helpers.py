#!/usr/bin/env python3
"""Verify the generic unsafe atomic helpers of Challenge 7 Part 2.

The helper bodies are copied verbatim from `library/core/src/sync/atomic.rs`
at replay time. Attributes are dropped, load and store are specialized to ordinary access,
and a VeriFast contract is inserted between the signature and the body. A change
to any helper body in the library is therefore verified again, rather than
compared with a hand-written copy.
"""

import argparse
import json
from pathlib import Path
import re
import subprocess

HELPERS = (
    "atomic_store", "atomic_load", "atomic_swap", "atomic_add", "atomic_sub",
    "atomic_compare_exchange", "atomic_compare_exchange_weak", "atomic_and",
    "atomic_nand", "atomic_or", "atomic_xor", "atomic_max", "atomic_min",
    "atomic_umax", "atomic_umin",
)

# The slot permission `atomic_points_to(dst, 1, valid)` grants write access to
# a live, initialized location that is aligned for atomic access at `T` and
# whose bytes are not accessed non-atomically for the duration of the call.
# `valid` is the value invariant of the slot.
WRITE = "[?f]std::intrinsics::atomic_points_to(dst, 1, ?valid)"
KEEP = "[f]std::intrinsics::atomic_points_to(dst, 1, valid)"
UNRESTRICTED = "(std::intrinsics::atomic_value_allowed)(true)"
CAS_RESULT = "(match result { Result::Ok(v) => valid(v) == true, Result::Err(v) => valid(v) == true })"
CONTRACTS = {
    # Invalid orderings panic. The unwind path returns the permission untouched.
    "atomic_store": (f"{WRITE} &*& valid(val) == true", KEEP, KEEP),
    # The generic load accepts every ordinary ordering and width.
    "atomic_load": ("[?f]std::intrinsics::atomic_points_to(dst, 1, ?valid)",
                    "[f]std::intrinsics::atomic_points_to(dst, 1, valid) &*& valid(result) == true",
                    "[f]std::intrinsics::atomic_points_to(dst, 1, valid)"),
    "atomic_swap": (f"{WRITE} &*& valid(val) == true", f"{KEEP} &*& valid(result) == true", "false"),
    "atomic_compare_exchange": (f"{WRITE} &*& valid(old) == true &*& valid(new) == true",
                                f"{KEEP} &*& {CAS_RESULT}", KEEP),
    "atomic_compare_exchange_weak": (f"{WRITE} &*& valid(old) == true &*& valid(new) == true",
                                     f"{KEEP} &*& {CAS_RESULT}", KEEP),
}
# Arithmetic and bitwise operations may produce any bit pattern of the slot
# type, so the slot must admit every value.
for name in ("atomic_add", "atomic_sub", "atomic_and", "atomic_nand", "atomic_or", "atomic_xor"):
    slot = f"std::intrinsics::atomic_points_to(dst, 1, {UNRESTRICTED})"
    CONTRACTS[name] = (f"[?f]{slot}", f"[f]{slot}", "false")
# Minimum and maximum store either the old value or `val`.
for name in ("atomic_max", "atomic_min", "atomic_umax", "atomic_umin"):
    CONTRACTS[name] = (f"{WRITE} &*& valid(val) == true", f"{KEEP} &*& valid(result) == true", "false")

# Optional Challenge 7 panic contracts: with these orderings excluded the
# helper cannot unwind, which VeriFast checks through `on_unwind_ens false`.
NO_PANIC = {
    "atomic_store": "order != Ordering::Acquire &*& order != Ordering::AcqRel",
    "atomic_load": "order != Ordering::Release &*& order != Ordering::AcqRel",
    "atomic_compare_exchange": "failure != Ordering::Release &*& failure != Ordering::AcqRel",
    "atomic_compare_exchange_weak": "failure != Ordering::Release &*& failure != Ordering::AcqRel",
}

HEADER = """#![feature(core_intrinsics)]
#![allow(internal_features)]
#![allow(dead_code)]

use std::intrinsics::{self, AtomicOrdering as AO};
use Ordering::*;

#[derive(Copy, Clone)]
#[non_exhaustive]
pub enum Ordering {
$VARIANTS
}

"""


def extract(source, name):
    """Return the signature and body of a top-level helper, without attributes."""
    match = re.search(rf"(?m)^(?:pub )?const unsafe fn {name}<.*?^}}\n", source, re.S)
    if not match:
        raise SystemExit(f"{name} is missing from the atomic module")
    text = match[0]
    split = re.search(r"\) (?:-> [^\n{]+ )?\{\n", text)
    return text[:split.end() - 2].rstrip(), text[split.end() - 2:]


def ordering_variants(source):
    match = re.search(r"(?m)^pub enum Ordering \{\n(.*?)^\}", source, re.S)
    if not match:
        raise SystemExit("Ordering enum is missing from the atomic module")
    variants = re.findall(r"(?m)^    (\w+),$", match[1])
    if variants != ["Relaxed", "Release", "Acquire", "AcqRel", "SeqCst"]:
        raise SystemExit(f"Unexpected Ordering variants {variants}")
    return "\n".join(f"    {v}," for v in variants)


def proof_text(source, contracts):
    parts = [HEADER.replace("$VARIANTS", ordering_variants(source))]
    for name in HELPERS:
        signature, body = extract(source, name)
        if name in ("atomic_load", "atomic_store"):
            if signature.count(", const VOLATILE: bool") != 1 or body.count("VOLATILE>") != 3:
                raise SystemExit(f"Unexpected volatile dispatch in {name}")
            signature = signature.replace(", const VOLATILE: bool", "")
            body = body.replace("VOLATILE>", "false>")
            if "VOLATILE" in signature + body:
                raise SystemExit(f"Unresolved volatile parameter in {name}")
        req, ens, unwind = contracts[name]
        # Panic paths consume the thread token, so every helper threads it through.
        token = "thread_token(currentThread)"
        req, ens = f"{token} &*& {req}", f"{token} &*& {ens}"
        if unwind != "false":
            unwind = f"{token} &*& {unwind}"
        parts.append(f"{signature}\n//@ req {req};\n//@ ens {ens};\n//@ on_unwind_ens {unwind};\n{body}\n")
    return "".join(parts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("verifast_bin", type=Path)
    parser.add_argument("rustc", type=Path, help="Compiler from the fork's pinned nightly")
    parser.add_argument("logs", type=Path)
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    source = (here.parents[3] / "library/core/src/sync/atomic.rs").read_text()
    logs = args.logs.resolve()
    logs.mkdir(parents=True, exist_ok=True)
    flags = "--edition=2024 --crate-type=lib"
    verifier = [args.verifast_bin.resolve() / "verifast", "-verbose", "1", "-skip_specless_fns",
                "-rustc_args", flags]

    def verify(name, text, options=()):
        path = logs / f"{name}.rs"
        path.write_text(text)
        result = subprocess.run([*verifier, *options, path], capture_output=True, text=True)
        output = result.stdout + result.stderr
        (logs / f"{name}.log").write_text(output)
        return result.returncode, output

    def expect_pass(name, text, options=()):
        status, output = verify(name, text, options)
        if status or "0 errors found" not in output:
            raise SystemExit(f"Expected {name} to verify. See {name}.log")
        missing = [h for h in HELPERS if f"Verifying function '{h}'" not in output]
        if missing:
            raise SystemExit(f"{name} did not verify {missing}. See {name}.log")

    def expect_fail(name, text, diagnostic):
        status, output = verify(name, text)
        if not status or diagnostic not in output:
            raise SystemExit(f"Expected {name} to fail with {diagnostic!r}. See {name}.log")

    # The extracted bodies must still compile as Rust before VeriFast sees them.
    proof = proof_text(source, CONTRACTS)
    subprocess.run([args.rustc.resolve(), *flags.split(), "--emit=metadata",
                    "-o", logs / "generic-helpers.rmeta", "-"], input=proof, text=True, check=True)
    # Generic helper contracts depend on rustc rejecting ill-typed monomorphizations.
    # Emitting metadata alone leaves the call unchecked.
    invalid = {
        "bool-load": """pub unsafe fn probe(src: *const bool) -> bool {
            unsafe { atomic_load(src, Relaxed) }
        }""",
        "mismatched-add": """pub unsafe fn probe(dst: *mut u16, delta: u8) -> u16 {
            unsafe { atomic_add(dst, delta, Relaxed) }
        }""",
    }
    for name, caller in invalid.items():
        probe = logs / f"rustc-reject-{name}.rs"
        probe.write_text(proof + caller)
        result = subprocess.run(
            [args.rustc.resolve(), *flags.split(), "--emit=obj", "-o", probe.with_suffix(".o"), probe],
            capture_output=True, text=True,
        )
        (logs / f"rustc-reject-{name}.log").write_text(result.stdout + result.stderr)
        if result.returncode == 0 or "error[E0511]: invalid monomorphization" not in result.stderr:
            raise SystemExit(f"Rustc did not reject the expected operand shape in {probe.name}")
    expect_pass("generic-helpers", proof)
    print(f"Verified the {len(HELPERS)} generic helpers copied from the atomic module.")

    strict = dict(CONTRACTS)
    for name, condition in NO_PANIC.items():
        req, ens, _ = strict[name]
        strict[name] = (f"{req} &*& {condition}", ens, "false")
    # The excluded orderings make the panic arms unreachable, which VeriFast
    # would otherwise report as dead code.
    expect_pass("generic-helpers-no-panic", proof_text(source, strict), ["-allow_dead_code"])
    print("Verified that the helpers do not unwind once invalid orderings are excluded.")

    def mutate(name, contract=None, body=None, *, volatile=False):
        contracts = dict(CONTRACTS)
        if contract:
            contracts[name] = contract
        text = proof_text(source, contracts)
        if body:
            old, new = body
            if text.count(old) != 1:
                raise SystemExit(f"Expected one occurrence of {old!r}")
            text = text.replace(old, new)
        if volatile:
            old = "intrinsics::atomic_load::<T, { AO::Relaxed }, false>"
            if text.count(old) != 1:
                raise SystemExit(f"Expected one occurrence of {old!r}")
            text = text.replace(old, old.replace("false", "VOLATILE"))
        return text

    store_req, store_ens, store_unwind = CONTRACTS["atomic_store"]
    controls = [
        ("store-read-fraction",
         mutate("atomic_store", tuple(clause.replace("dst, 1,", "dst, 1/2,")
                                      for clause in CONTRACTS["atomic_store"])),
         "No matching heap chunks: [_]std::intrinsics::atomic_points_to<T>(dst, 1, _)"),
        ("store-invalid-value",
         mutate("atomic_store", (WRITE, store_ens, store_unwind)),
         "Cannot prove unboxed_bool(@(valid, val)) <==> true."),
        ("store-no-permission",
         mutate("atomic_store", ("true", "true", "true")),
         "No matching heap chunks: [_]std::intrinsics::atomic_points_to<T>(dst, 1, _)"),
        ("swap-invalid-value",
         mutate("atomic_swap", (WRITE, f"{KEEP} &*& valid(result) == true", "false")),
         "Cannot prove unboxed_bool(@(valid, val)) <==> true."),
        ("add-restricted-slot",
         mutate("atomic_add", (WRITE, KEEP, "false")),
         "No matching heap chunks: [_]std::intrinsics::atomic_points_to<T>(dst, 1, @(@(@std::intrinsics::atomic_value_allowed"),
        ("max-invalid-value",
         mutate("atomic_max", (WRITE, f"{KEEP} &*& valid(result) == true", "false")),
         "Cannot prove unboxed_bool(@(valid, val)) <==> true."),
        ("store-panics-without-ordering-contract",
         mutate("atomic_store", (store_req, store_ens, "false")),
         "Cannot prove condition. (Cannot prove false.)"),
        ("cas-panics-without-ordering-contract",
         mutate("atomic_compare_exchange", (CONTRACTS["atomic_compare_exchange"][0],
                                            CONTRACTS["atomic_compare_exchange"][1], "false")),
         "Cannot prove condition. (Cannot prove false.)"),
        ("generic-volatile-load",
         mutate("atomic_load", body=(
             "const unsafe fn atomic_load<T: Copy>",
             "const unsafe fn atomic_load<T: Copy, const VOLATILE: bool>"), volatile=True),
         "only ordinary accesses (VOLATILE=false) are modeled"),
        ("release-load-intrinsic",
         mutate("atomic_load", body=("Acquire => intrinsics::atomic_load::<T, { AO::Acquire }, false>(dst)",
                                     "Acquire => intrinsics::atomic_load::<T, { AO::Release }, false>(dst)")),
         "atomic_load: unsupported ordering"),
        ("acquire-store-intrinsic",
         mutate("atomic_store", body=("Release => intrinsics::atomic_store::<T, { AO::Release }, false>(dst, val)",
                                      "Release => intrinsics::atomic_store::<T, { AO::Acquire }, false>(dst, val)")),
         "atomic_store: unsupported ordering"),
    ]
    results = {}
    for name, text, diagnostic in controls:
        expect_fail(name, text, diagnostic)
        results[name] = "rejected"
    (logs / "coverage.json").write_text(json.dumps({
        "helpers": list(HELPERS), "no_panic_contracts": list(NO_PANIC), "controls": results,
    }, indent=2) + "\n")
    print(f"All {len(controls)} generic-helper rejection controls passed.")


if __name__ == "__main__":
    main()
