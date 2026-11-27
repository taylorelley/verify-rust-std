"""Resolve LLVM attribute group references before comparing bridge IR."""

import re


def resolve_attribute_groups(ir, fragment):
    groups = dict(re.findall(r"(?m)^attributes #(\d+) = (.+)$", ir))
    # Attribute references occur outside quoted LLVM strings and identifiers.
    return re.sub(
        r'"(?:[^"\\]|\\.)*"| #(\d+)(?=,|\s|$)',
        lambda match: " " + groups[match[1]] if match[1] else match[0],
        fragment,
    )


def function_header(ir, header, name):
    # Symbol names can differ when LLVM emits an alias for an identical bridge.
    return resolve_attribute_groups(ir, header.replace(f"@{name}(", "@bridge(", 1))
