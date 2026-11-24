#!/usr/bin/env python3
"""Check the scoped-thread counter abstraction against the pinned source revision."""

import argparse
import ctypes
import hashlib
import json
from pathlib import Path

SOURCE_DIGESTS = {
    "scoped.rs": "1b6a7e973c69b26c1883fde6e5665409afbd4dd38f4ca300ca0771033621e555",
    "lifecycle.rs": "a2a13015a2d0a8284f4cf2b7cd7b9fb85db4aeae0589319bbc1d8a45f843bd59",
}


class Solver:
    def __init__(self, path):
        self.z3 = ctypes.CDLL(str(path.resolve()))
        pointer, string = ctypes.c_void_p, ctypes.c_char_p
        signatures = {
            "Z3_mk_config": ([], pointer),
            "Z3_del_config": ([pointer], None),
            "Z3_mk_context": ([pointer], pointer),
            "Z3_del_context": ([pointer], None),
            "Z3_eval_smtlib2_string": ([pointer, string], string),
        }
        for name, (argument_types, result_type) in signatures.items():
            function = getattr(self.z3, name)
            function.argtypes = argument_types
            function.restype = result_type

    def check(self, query):
        config = self.z3.Z3_mk_config()
        context = self.z3.Z3_mk_context(config)
        self.z3.Z3_del_config(config)
        try:
            return self.z3.Z3_eval_smtlib2_string(context, query.encode()).decode().strip()
        finally:
            self.z3.Z3_del_context(context)


def checks(bits):
    modulus = 1 << bits
    limit = (modulus - 1) // 2
    prelude = f"""(set-logic QF_LIA)
(declare-const count Int)
(declare-const live Int)
(declare-const pending Int)
(define-fun Limit () Int {limit})
(define-fun increment () Int (mod (+ count 1) {modulus}))
(define-fun decrement () Int (mod (- count 1) {modulus}))
(assert (and (<= 0 count) (< count {modulus})
             (<= 0 live) (<= 0 pending) (= count (+ live pending))))
"""
    # Pending increments can still be in the admission or rollback path.
    # Live obligations end only when the last packet owner drops the result.
    obligations = {
        "reserve-and-count": (
            f"(< count {modulus - 1})",
            "(and (> increment 0) (= increment (+ live (+ pending 1))))",
            "unsat",
        ),
        "admission-cutoff": (
            "(<= count Limit)",
            "(and (= increment (+ count 1)) (<= increment (+ Limit 1)))",
            "unsat",
        ),
        "admit-pending": (
            "(> pending 0)", "(= count (+ (+ live 1) (- pending 1)))", "unsat",
        ),
        "rollback-rejected-reservation": (
            "(> pending 0)", "(= decrement (+ live (- pending 1)))", "unsat",
        ),
        "packet-retires-one-worker": (
            "(> live 0)", "(= decrement (+ (- live 1) pending))", "unsat",
        ),
        "last-obligation-notifies": (
            "(> count 0)", "(= (= count 1) (= decrement 0))", "unsat",
        ),
        "zero-is-quiescent": (
            "(= count 0)", "(and (= live 0) (= pending 0))", "unsat",
        ),
        "reject-lost-reservation": (
            "(= count 0)", "(= count (+ live (+ pending 1)))", "sat",
        ),
        "reject-off-by-one-notification": (
            "(> count 0)", "(= (= count 0) (= decrement 0))", "sat",
        ),
        "require-capacity-bound": (
            f"(= count {modulus - 1})", "(> increment 0)", "sat",
        ),
    }
    for name, (premise, claim, expected) in obligations.items():
        query = prelude + f"(assert {premise})\n(check-sat)\n(assert (not {claim}))\n(check-sat)\n"
        yield name, query, expected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("z3_library", type=Path)
    parser.add_argument("logs", type=Path)
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[4] / "library/std/src/thread"
    for name, expected in SOURCE_DIGESTS.items():
        if hashlib.sha256((source / name).read_bytes()).hexdigest() != expected:
            raise SystemExit(f"Review scope counter abstraction against changed {name}")
    args.logs.mkdir(parents=True, exist_ok=True)
    report = args.logs / "scope-counter.json"
    report.unlink(missing_ok=True)
    solver = Solver(args.z3_library)
    results = {}
    for bits in (32, 64):
        case_results = {}
        for name, query, expected in checks(bits):
            label = f"{bits}-{name}"
            (args.logs / f"{label}.smt2").write_text(query)
            observed = solver.check(query)
            if observed.splitlines() != ["sat", expected]:
                raise SystemExit(f"{label}: expected a feasible premise then {expected}, received {observed!r}")
            case_results[name] = {"premise": "sat", "negated_claim": expected}
        results[bits] = case_results
    report.write_text(json.dumps({"source_sha256": SOURCE_DIGESTS, "checks": results}, indent=2) + "\n")
    print("Scoped counter abstraction: 14 claims proved and six counterexample controls passed.")


if __name__ == "__main__":
    main()
