"""New-code limits, strict legacy ratchets and explicit per-symbol exceptions."""

import ast
from collections import Counter, defaultdict
import re

from tools.metrics.rule16_gate import CLASS_LIMITS, LIMITS
from tools.metrics.current_audit import isolated

FUNCTION_LIMITS = {"loc": LIMITS["func_loc"], **{k: v for k, v in LIMITS.items() if k != "func_loc"}}
OVERRIDE = re.compile(r"quality-override:\s+([a-z-]+)=(\d+)\s+reason=(.{20,})$")


def limits(symbol):
    return CLASS_LIMITS if symbol.kind == "class" else FUNCTION_LIMITS


def single_payload(symbol):
    fn = isolated(symbol.node)
    body = fn.body
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        body = body[1:]  # docstrings cannot masquerade as an embedded JS payload
    literals = []

    def visit(node):
        if isinstance(node, ast.JoinedStr) or (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            if node.end_lineno > node.lineno:
                literals.append(node.end_lineno - node.lineno + 1)
            return
        for child in ast.iter_child_nodes(node):
            visit(child)

    for stmt in body:
        visit(stmt)
    return len(literals) == 1 and literals[0] >= symbol.metrics["loc"] - LIMITS["func_loc"]


def overrides(symbol):
    allowed, errors = {}, []
    for line, comment in symbol.comments:
        text = comment[comment.index("quality-override"):].strip()
        match = OVERRIDE.fullmatch(text)
        label = f"{symbol.label}:{line}"
        if not match or text.count("quality-override") != 1 or len(match.group(3).strip()) < 20:
            errors.append(f"{label}: malformed override or reason shorter than 20 characters")
            continue
        metric, value, reason = match.groups()
        axis = "loc" if metric == "class-loc" and symbol.kind == "class" else metric
        if axis not in limits(symbol) or (symbol.kind == "class" and metric == "loc"):
            errors.append(f"{label}: unsupported override metric {metric}")
            continue
        if axis in allowed:
            errors.append(f"{label}: duplicate override for {metric}")
            continue
        allowed[axis] = int(value)
        actual = symbol.metrics[axis]
        if actual <= limits(symbol)[axis]:
            errors.append(f"{label}: stale {metric} override; symbol fits without it")
        if actual != int(value):
            errors.append(f"{label}: {metric} override declares {value}, measured {actual}")
        if axis == "loc" and symbol.kind == "function" and re.search(r"\b(js|javascript|html)\b", reason, re.I):
            if not single_payload(symbol):
                errors.append(f"{label}: JS/HTML LOC override needs one literal accounting for the excess")
    return allowed, errors


def moved_symbols(before, after):
    removed, added = defaultdict(list), defaultdict(list)
    for key in before.keys() - after.keys():
        removed[(before[key].kind, before[key].fingerprint)].append(before[key])
    for key in after.keys() - before.keys():
        added[(after[key].kind, after[key].fingerprint)].append(after[key])
    old_counts = Counter((s.kind, s.fingerprint) for s in before.values())
    new_counts = Counter((s.kind, s.fingerprint) for s in after.values())
    return {targets[0].key: removed[signature][0] for signature, targets in added.items()
            if len(targets) == len(removed[signature]) == old_counts[signature] == new_counts[signature] == 1}


def unchanged(old, new):
    return old and old.fingerprint == new.fingerprint and old.metrics == new.metrics \
        and [text for _, text in old.comments] == [text for _, text in new.comments]


def breaches_for(symbol, old, allowed):
    caps = limits(symbol)
    legacy = old is not None and any(old.metrics[k] > v for k, v in caps.items())
    errors = []
    for axis, value in symbol.metrics.items():
        if legacy:
            if value > old.metrics[axis]:
                errors.append(f"{symbol.label}: legacy {axis} worsened {old.metrics[axis]} -> {value}")
        elif value > caps[axis] and allowed.get(axis) != value:
            errors.append(f"{symbol.label}: {axis} {value} > {caps[axis]}")
    return errors


def compare(before, after):
    moves = moved_symbols(before, after)
    moved_keys = {symbol.key for symbol in moves.values()}
    deleted = sorted(before[key].label for key in before.keys() - after.keys() - moved_keys)
    result = {"rows": [], "breaches": list(getattr(after, "errors", [])),
              "new_functions": [], "deleted_symbols": deleted}
    for key, symbol in sorted(after.items()):
        old = before.get(key) or moves.get(key)
        allowed, errors = overrides(symbol)
        result["breaches"].extend(errors)
        if key in before and unchanged(old, symbol):
            continue
        status = "moved" if key in moves else "changed" if old else "new"
        breaches = breaches_for(symbol, old, allowed)
        result["breaches"].extend(breaches)
        result["rows"].append({"target": symbol.label, "kind": symbol.kind, "status": status,
                               "before": old.metrics if old else None, "after": symbol.metrics,
                               "baseline_symbol": old.label if old else None,
                               "overrides": allowed, "breaches": breaches + errors})
        if old is None and symbol.kind == "function":
            result["new_functions"].append(symbol)
    return result
