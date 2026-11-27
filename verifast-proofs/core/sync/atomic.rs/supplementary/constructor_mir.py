"""Compare runtime and const-evaluation MIR for the constructor itself."""

import re
import subprocess


def upstream_storage_check(source, width, operand, atomic_type):
    """Check the upstream wrapper's storage representation before specialization."""
    atomic = r'(?m)^#\[repr\(C\)\]\n#\[rustc_diagnostic_item = "Atomic"\]\n'
    atomic += r"pub struct Atomic<T: AtomicPrimitive> \{\s*v: UnsafeCell<T::Storage>,\s*\}"
    storage = rf"(?m)^    #\[repr\(C, align\({width}\)\)\]\n    pub struct Align{width}<T>\(T\);"
    if not re.search(atomic, source) or not re.search(storage, source):
        raise SystemExit(f"Review the Rust representation of {atomic_type}")
    # Type-check the actual associated storage choice inside the upstream module.
    return (
        f"\nconst _: fn(&{atomic_type}) -> &core::cell::UnsafeCell<private::Align{width}<{operand}>>"
        " = |a| &a.v;\n"
    )


def constructor_mir(path, operand, original_type, proof_type, substitutions=()):
    text = path.read_text()
    pattern = (
        r"(?m)^fn [^\n]*::from_ptr\(_1: \*mut " + re.escape(operand)
        + r"\) -> &" + re.escape(original_type) + r" \{\n(.*?)^\}"
    )
    bodies = re.findall(pattern, text, re.S)
    if len(bodies) != 2:
        raise SystemExit(f"Expected runtime and const-evaluation from_ptr MIR for {operand} in {path}")

    normalized = []
    for body in bodies:
        body = re.sub(r"(?m)^    scope \d+ \{\n        debug [^\n]+\n    \}\n", "", body)
        body = re.sub(r"(?m)^ +debug [^\n]+\n", "", body)
        normalized.append(body.replace(original_type, proof_type))
    for old, new in substitutions:
        normalized = [re.sub(rf"\b{re.escape(old)}\b", new, body) for body in normalized]
    return normalized


def emit_constructor_mir(rustc, flags, source, output):
    result = subprocess.run(
        [rustc, *flags, "--emit=mir", "-Zmir-opt-level=2", source, "-o", output],
        capture_output=True, text=True,
    )
    if result.returncode:
        raise SystemExit(result.stdout + result.stderr)


def compare_constructor_mir(rustc, flags, original, proof, logs, operand, proof_type, *, pointer=False):
    actual_mir = logs / "original-constructor.mir"
    proved_mir = logs / "specialized-constructor.mir"
    emit_constructor_mir(rustc, flags, original, actual_mir)
    emit_constructor_mir(rustc, flags, proof, proved_mir)
    upstream_operand = "*mut T" if pointer else operand
    upstream_type = f"atomic::Atomic<{upstream_operand}>"
    actual = constructor_mir(
        actual_mir, upstream_operand, upstream_type, proof_type,
        substitutions=(("T", "Pointee"),) if pointer else (),
    )
    proved = constructor_mir(proved_mir, operand, proof_type, proof_type)
    if actual != proved:
        raise SystemExit(f"Runtime or const-evaluation MIR differs for {proof_type}. See {logs}")
