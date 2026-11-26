"""Preserve a bridge's LLVM signature and resolve its attribute group."""

import re


def function_header(ir, header, name):
    # Symbol names can differ when LLVM emits an alias for an identical bridge.
    header = header.replace(f"@{name}(", "@bridge(", 1)
    groups = dict(re.findall(r"(?m)^attributes #(\d+) = (.+)$", ir))
    return re.sub(r" #(\d+)(?=\s|$)", lambda match: " " + groups[match[1]], header)
