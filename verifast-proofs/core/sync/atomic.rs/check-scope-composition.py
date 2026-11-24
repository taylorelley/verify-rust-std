#!/usr/bin/env python3
"""Check packet retirement and the conditions for scope-exit synchronization."""

import argparse
from collections import deque
from dataclasses import dataclass, replace
import hashlib
import json
from pathlib import Path
import runpy

ARC_DIGEST = "3b88d14a0a0ac58249371d0191200f7bdbdf0c3397476ca543b1244c12a754ca"


@dataclass(frozen=True)
class Packet:
    parent: bool = True
    worker: bool = True
    launched: bool = False
    result: str = "empty"
    retirements: int = 0


def transitions(state, early_retirement=False):
    if state.parent and state.worker and not state.launched:
        yield "launch", replace(state, launched=True)
        yield "launch fails and drops both owners", replace(
            state, parent=False, worker=False, retirements=1)
        return
    if state.worker and state.result == "empty":
        yield "worker publishes a result", replace(state, result="published")
    if state.worker and state.result == "published":
        if state.parent:
            yield "worker drops its owner", replace(state, worker=False)
        else:
            yield "worker drops last owner and settles result", replace(
                state, worker=False, result="settled", retirements=state.retirements + 1)
    if state.parent:
        if state.worker:
            yield "parent drops its owner without joining", replace(
                state, parent=False, retirements=int(early_retirement))
        else:
            yield "parent drops last owner and settles result", replace(
                state, parent=False, result="settled", retirements=state.retirements + 1)
            if state.result == "published":
                yield "parent joins, takes result, and drops last owner", replace(
                    state, parent=False, result="taken", retirements=state.retirements + 1)


def explore_packets(early_retirement=False):
    start = Packet()
    pending = deque([(start, ())])
    visited = {start}
    while pending:
        state, trace = pending.popleft()
        retired = not state.parent and not state.worker
        if state.retirements != int(retired) or (retired and state.result == "published"):
            return len(visited), list(trace)
        for event, next_state in transitions(state, early_retirement):
            if next_state not in visited:
                visited.add(next_state)
                pending.append((next_state, (*trace, event)))
    return len(visited), None


def memory_queries():
    # The separator is the latest non-RMW modification before the observed
    # write, or the initialization at position zero. C++20 [intro.races]
    # and [atomics.order] give the relation in release_sequence below.
    prelude = """(set-logic QF_LIA)
(declare-const head Int)
(declare-const observed Int)
(declare-const separator Int)
(declare-const acquire Bool)
(declare-const releasing Bool)
(assert (and (> head 0) (>= observed head) (<= 0 separator observed)))
(define-fun release_sequence () Bool (and releasing (< separator head)))
(define-fun synchronizes () Bool (and acquire release_sequence))
"""
    cases = {
        "acquire-reads-unbroken-release-sequence": ("(and acquire releasing (= separator 0))", "synchronizes", "unsat"),
        "relaxed-exit-loses-synchronization": ("(and (not acquire) releasing (= separator 0))", "synchronizes", "sat"),
        "relaxed-retirement-loses-synchronization": ("(and acquire (not releasing) (= separator 0))", "synchronizes", "sat"),
        "intervening-store-breaks-release-sequence": ("(and acquire releasing (< head separator observed))", "synchronizes", "sat"),
    }
    for name, (premise, claim, result) in cases.items():
        yield name, prelude + f"(assert {premise})\n(check-sat)\n(assert (not {claim}))\n(check-sat)\n", result

    # A root reservation happens before the scope's exit load. Write-read
    # coherence rules out taking the load's value from the earlier init.
    yield "root-reservation-excludes-initial-zero", """(set-logic QF_LIA)
(declare-const reserved Int)
(declare-const observed Int)
(assert (> reserved 0))
(assert (>= observed reserved))
(check-sat)
(assert (= observed 0))
(check-sat)
""", "unsat"

    # If every counted obligation injects into a live packet allocation,
    # a word-aligned base address gives a sufficient capacity bound.
    for bits in (32, 64):
        slots = (1 << bits) // (bits // 8)
        limit = ((1 << bits) - 1) // 2
        yield f"{bits}-aligned-packet-capacity", f"""(set-logic QF_LIA)
(declare-const count Int)
(assert (and (<= 0 count) (<= count {slots})))
(check-sat)
(assert (> count {limit}))
(check-sat)
""", "unsat"

    # Conditional source path: reserve, rollback, then unwind and drop the
    # packet. Check conservation without any machine-word wraparound.
    yield "overflow-unwind-extra-retirement", """(set-logic QF_LIA)
(declare-const initial Int)
(declare-const limit Int)
(assert (and (> limit 1) (> initial limit) (<= initial (* 2 limit))))
(define-fun after_reservation () Int (+ initial 1))
(define-fun after_rollback () Int (- after_reservation 1))
(define-fun after_packet_drop () Int (- after_rollback 1))
(check-sat)
(assert (not (= after_packet_drop initial)))
(check-sat)
""", "sat"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("z3_library", type=Path)
    parser.add_argument("logs", type=Path)
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    counter = runpy.run_path(str(here / "check-scope-counter.py"))
    rust_library = here.parents[3] / "library"
    digests = {f"std/src/thread/{name}": digest for name, digest in counter["SOURCE_DIGESTS"].items()}
    digests["alloc/src/rcs/arc.rs"] = ARC_DIGEST
    for name, expected in digests.items():
        if hashlib.sha256((rust_library / name).read_bytes()).hexdigest() != expected:
            raise SystemExit(f"Review scoped ownership and ordering against changed {name}")

    args.logs.mkdir(parents=True, exist_ok=True)
    report = args.logs / "scope-composition.json"
    report.unlink(missing_ok=True)
    count, failure = explore_packets()
    _, mutation = explore_packets(early_retirement=True)
    if failure is not None or mutation is None:
        raise SystemExit("Packet model or early-retirement control failed")
    results = {
        "source_sha256": digests,
        "packet": {"reachable_states": count, "early_retirement_counterexample": mutation},
        "smt": {},
        "open": ["overflow-unwind-accounting", "actual Arc and thread backend refinement"],
    }
    solver = counter["Solver"](args.z3_library)
    for name, query, expected in memory_queries():
        (args.logs / f"{name}.smt2").write_text(query)
        observed = solver.check(query).splitlines()
        if observed != ["sat", expected]:
            raise SystemExit(f"{name}: expected a feasible premise then {expected}, received {observed}")
        results["smt"][name] = {"premise": "sat", "negated_claim": expected}
    report.write_text(json.dumps(results, indent=2) + "\n")
    print(f"Checked {count} packet states and {len(results['smt'])} ordering or accounting queries.")
    print("Overflow unwind remains an open accounting obligation.")


if __name__ == "__main__":
    main()
