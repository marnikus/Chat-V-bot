"""Scoped AST measurements; shared thresholds are applied by policy, not here."""

import ast
from collections import Counter
from dataclasses import dataclass, field
import io
import tokenize

from radon.complexity import cc_visit_ast
from cognitive_complexity.api import get_cognitive_complexity
from tools.metrics.current_audit import depth, isolated

DEFINITIONS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def measure(node, is_method=False):
    result = {"loc": node.end_lineno - node.lineno + 1}
    if isinstance(node, ast.ClassDef):
        result["methods"] = sum(isinstance(n, DEFINITIONS[:2]) for n in node.body)
        return result
    fn = isolated(node)
    args = node.args
    positional = args.posonlyargs + args.args
    static = any(isinstance(d, (ast.Name, ast.Attribute)) and
                 getattr(d, "id", getattr(d, "attr", "")) == "staticmethod"
                 for d in node.decorator_list)
    receiver = is_method and not static and positional and positional[0].arg in ("self", "cls")
    result.update(
        params=len(positional + args.kwonlyargs) + bool(args.vararg) + bool(args.kwarg)
        - bool(receiver),
        cc=cc_visit_ast(ast.Module(body=[fn], type_ignores=[]))[0].complexity,
        cognitive=get_cognitive_complexity(fn), nesting=depth(node))
    return result


@dataclass
class Symbol:
    path: str
    qualname: str
    kind: str
    node: ast.AST
    source: str
    metrics: dict
    fingerprint: str
    comments: list = field(default_factory=list)

    @property
    def key(self):
        return self.path, self.qualname, self.kind

    @property
    def label(self):
        return f"{self.path}::{self.qualname}"

    @property
    def header_end(self):
        start = self.node.lineno - 1
        snippet = "\n".join(self.source.splitlines()[start:self.node.body[0].lineno])
        brackets = 0
        for token in tokenize.generate_tokens(io.StringIO(snippet).readline):
            if token.type != tokenize.OP:
                continue
            if token.string == ":" and brackets == 0:
                return start + token.start[0]
            brackets += (token.string in "([{") - (token.string in ")]}")
        raise ValueError(f"{self.label}: cannot identify definition header")

    @property
    def body_lines(self):
        body = self.node.body
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                and isinstance(body[0].value.value, str):
            body = body[1:]
        header = self.header_end
        return {line for stmt in body for line in range(stmt.lineno, stmt.end_lineno + 1)
                if line > header}


class Inventory(ast.NodeVisitor):
    def __init__(self, path, source):
        self.path, self.source = path, source
        self.scope, self.counts, self.rows = "", Counter(), []
        self.parent_kind = "module"

    def definition(self, node):
        parent, parent_kind = self.scope, self.parent_kind
        name = ".".join(filter(None, (parent, node.name)))
        self.counts[name] += 1
        self.scope = name if self.counts[name] == 1 else f"{name}#{self.counts[name]}"
        kind = "class" if isinstance(node, ast.ClassDef) else "function"
        self.rows.append(Symbol(self.path, self.scope, kind, node, self.source,
                                measure(node, parent_kind == "class"), ast.dump(node, include_attributes=False)))
        self.parent_kind = kind
        # Definitions anywhere in the body (including if/try/match) retain scope.
        for child in node.body:
            self.visit(child)
        self.scope, self.parent_kind = parent, parent_kind

    visit_FunctionDef = definition
    visit_AsyncFunctionDef = definition
    visit_ClassDef = definition


def comments_for(source):
    return [(t.start[0], t.string) for t in tokenize.generate_tokens(io.StringIO(source).readline)
            if t.type == tokenize.COMMENT and "quality-override" in t.string]


def attach_comments(rows, source):
    lines = source.splitlines()
    remaining = comments_for(source)
    for row in rows:
        node = row.node
        start = min([node.lineno] + [d.lineno for d in node.decorator_list])
        while start > 1 and lines[start - 2].lstrip().startswith("#"):
            start -= 1
        end = row.header_end
        row.comments = [(line, text) for line, text in remaining if start <= line <= end]
        remaining = [item for item in remaining if item not in row.comments]
    return remaining


class Symbols(dict):
    """Dictionary with source-level diagnostics (e.g. orphan override comments)."""
    def __init__(self):
        super().__init__()
        self.errors = []


def collect(sources):
    result = Symbols()
    for path, source in sorted(sources.items()):
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError as exc:
            raise ValueError(f"{path}:{exc.lineno}: {exc.msg}") from exc
        inventory = Inventory(path, source)
        inventory.visit(tree)
        orphans = attach_comments(inventory.rows, source)
        result.errors.extend(f"{path}:{line}: orphan quality override" for line, _ in orphans)
        result.update((row.key, row) for row in inventory.rows)
    return result
