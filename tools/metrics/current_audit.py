"""Reproducible Python audit; pip install radon cognitive-complexity.
Run from any directory: python tools/metrics/current_audit.py > audit.json
No application imports. LOC includes docstrings/embedded JS; SLOC is Radon's.
"""
import ast
import copy
import json
from pathlib import Path
from statistics import mean
from radon.raw import analyze
from radon.complexity import cc_visit_ast
from radon.metrics import mi_visit
from cognitive_complexity.api import get_cognitive_complexity

ROOT = Path(__file__).resolve().parents[2]
PACKAGES = ('core', 'actions', 'backend', 'bridge', 'services', 'stores', 'app')
FUNCTION = (ast.FunctionDef, ast.AsyncFunctionDef)
BLOCK = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith, ast.Try, ast.Match)


def depth(node, level=0):
    """Maximum path depth, not accumulated sibling depths; nested defs separate."""
    values = [level]
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (*FUNCTION, ast.ClassDef, ast.Lambda)):
            continue
        values.append(depth(child, level + isinstance(child, BLOCK)))
    return max(values)


def receiver(fn):
    """The first positional parameter's name — `self`, `cls`, or anything else.

    Reading only the literal name `self` (H6) made every @classmethod look
    field-free and silently shrank the cohesion denominator.
    """
    positional = fn.args.posonlyargs + fn.args.args
    return positional[0].arg if positional else None


def fields_of(fn, method_names):
    """Instance fields one method touches, excluding calls to sibling methods."""
    name = receiver(fn)
    if name is None:
        return set()
    return {n.attr for n in ast.walk(isolated(fn)) if isinstance(n, ast.Attribute)
            and isinstance(n.value, ast.Name) and n.value.id == name
            and n.attr not in method_names}


def lcom4(methods, fields, method_names):
    """Connected components over methods that share a field or call each other.

    `ubiquitous` is the H6 fix that matters most. A field EVERY method holds —
    a `self._owner` delegation handle, a `self.db` connection — links every
    method to every other and collapses the graph to one component no matter
    how unrelated the methods are. Round H hit this twice: PersonLifecycle
    reported LCOM4 = 1 and was left alone by three earlier rounds, yet
    discounting `_owner` revealed EIGHT components and a real split. So the
    components are reported BOTH ways, and a gap between them is the signal.
    """
    names = [m.name for m in methods]
    if not names:
        return 0, 0, []
    ubiquitous = {f for f in fields
                  if all(f in fields_of(m, method_names) for m in methods)}
    # NOTE: when the shared handle is the class's ONLY state, discounting it
    # leaves each method isolated and `net` simply equals the method count.
    # That is not noise to be suppressed — PersonLifecycle was exactly this
    # shape, and its split was correct — but it is only INTERESTING for a class
    # big enough that the components are separate responsibilities. Callers
    # should read `lcom4_net` together with `methods`; both numbers are always
    # reported and neither is silently adjusted.
    def components(skip):
        parent = {n: n for n in names}
        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x
        own = {m.name: fields_of(m, method_names) - skip for m in methods}
        calls = {m.name: {n.attr for n in ast.walk(isolated(m))
                          if isinstance(n, ast.Attribute) and n.attr in set(names)}
                 for m in methods}
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                if own[a] & own[b] or b in calls[a] or a in calls[b]:
                    parent[find(a)] = find(b)
        groups = {}
        for n in names:
            groups.setdefault(find(n), []).append(n)
        return groups
    raw_groups = components(set())
    net_groups = components(ubiquitous)
    return len(raw_groups), len(net_groups), sorted(ubiquitous)


class StripNested(ast.NodeTransformer):
    def visit_FunctionDef(self, node):
        return ast.copy_location(ast.Pass(), node)
    visit_AsyncFunctionDef = visit_FunctionDef
    visit_ClassDef = visit_FunctionDef


def isolated(node):
    result = copy.deepcopy(node)
    result.body = [StripNested().visit(child) for child in result.body]
    return result


def module(path):
    parts = list(path.relative_to(ROOT).with_suffix('').parts)
    if parts[-1] == '__init__':
        parts.pop()
    return '.'.join(parts)


def run():
    paths = sorted(p for pkg in PACKAGES for p in (ROOT / pkg).rglob('*.py')) + [ROOT / 'main.py']
    modules = {module(p) for p in paths}
    files, functions, classes, edges = [], [], [], {}
    clones = {}
    for path in paths:
        text = path.read_text(encoding='utf-8')
        tree = ast.parse(text)
        rel, mod = str(path.relative_to(ROOT)), module(path)
        raw = analyze(text)
        files.append(dict(file=rel, loc=len(text.splitlines()), sloc=raw.sloc, mi=mi_visit(text, multi=True)))
        deps = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                if isinstance(node, ast.Import):
                    targets = [a.name for a in node.names]
                else:
                    package = mod if path.stem == '__init__' else mod.rpartition('.')[0]
                    base = '.'.join(package.split('.')[:len(package.split('.'))-node.level+1]) if node.level else ''
                    base = '.'.join(x for x in (base, node.module) if x)
                    targets = [base] + [base + '.' + a.name for a in node.names]
                for target in targets:
                    while target and target not in modules:
                        target = target.rpartition('.')[0]
                    if target and target != mod:
                        deps.add(target)
            if isinstance(node, ast.stmt) and node.end_lineno - node.lineno >= 5:
                key = ast.dump(node, include_attributes=False)
                clones.setdefault(key, []).append((rel, node.lineno, node.end_lineno))
            if isinstance(node, FUNCTION):
                fn = isolated(node)
                cc = cc_visit_ast(ast.Module(body=[fn], type_ignores=[]))[0].complexity
                args = node.args
                params = len(args.posonlyargs + args.args + args.kwonlyargs) + bool(args.vararg) + bool(args.kwarg)
                positional = args.posonlyargs + args.args
                params -= bool(positional and positional[0].arg in ('self', 'cls'))
                # H6: RULE 19 §19.4's prescribed remedy for a long parameter
                # list is a PARAMETER OBJECT. The old counter could not see one:
                # a function taking a 14-field request dataclass scored 1 and
                # vanished from the report, while the same call site refactored
                # INTO that shape looked identical to a genuinely simple
                # function. `params_effective` re-expands a parameter object so
                # the remedy is visible as a remedy rather than as a disguise.
                annotations = [a.annotation for a in positional + args.kwonlyargs]
                objects = [ast.unparse(a).split('[')[0].rsplit('.', 1)[-1]
                           for a in annotations if a is not None]
                functions.append(dict(file=rel, name=node.name, line=node.lineno,
                    loc=node.end_lineno-node.lineno+1, cc=cc,
                    cognitive=get_cognitive_complexity(fn), nesting=depth(node),
                    params=params, param_objects=objects))
            if isinstance(node, ast.ClassDef):
                methods = [n for n in node.body if isinstance(n, FUNCTION)]
                method_names = {m.name for m in methods}
                fields = [fields_of(m, method_names) for m in methods]
                union = set().union(*fields) if fields else set()
                m, a = len(methods), len(union)
                lcom = (m - sum(map(len, fields))/a)/(m-1) if m > 1 and a else None
                raw_c, net_c, handles = lcom4(methods, union, method_names)
                # H6: a facade re-exports its parts' methods, so counting only
                # methods DEFINED here reports a decomposed class as tiny. The
                # reachable surface is what a caller sees.
                inherited = sorted(getattr(b, 'id', getattr(b, 'attr', '?'))
                                   for b in node.bases)
                classes.append(dict(file=rel, name=node.name, line=node.lineno,
                    loc=node.end_lineno-node.lineno+1, methods=m, lcom_star=lcom,
                    lcom4=raw_c, lcom4_net=net_c, shared_handles=handles,
                    bases=inherited, fields_declared=len([
                        n for n in node.body if isinstance(n, ast.AnnAssign)])))
        edges[mod] = deps
    # H6: a class assembled from mixins (Round H used that shape four times to
    # keep a facade's class identity while splitting its file) declares few
    # methods and looked compliant, while the surface a caller sees was
    # unchanged. Resolve local bases and report the REACHABLE method count
    # beside the declared one; RULE 18's methods-per-class budget applies to
    # the reachable number, because that is what a reader has to hold.
    declared = {}
    for cls in classes:
        declared.setdefault(cls['name'], cls)
    def reachable(name, seen):
        cls = declared.get(name)
        if cls is None or name in seen:
            return 0
        seen.add(name)
        return cls['methods'] + sum(reachable(b, seen) for b in cls['bases'])
    for cls in classes:
        cls['methods_reachable'] = reachable(cls['name'], set())

    # H6: resolve parameter objects once every class is known, then report the
    # EFFECTIVE arity — the count a caller must actually assemble.
    widths = {c['name']: c['fields_declared'] for c in classes
              if c.get('fields_declared')}
    for fn in functions:
        extra = sum(widths.get(name, 1) - 1 for name in fn.pop('param_objects', []))
        fn['params_effective'] = fn['params'] + extra
    coupling = [dict(module=m, ca=sum(m in d for d in edges.values()), ce=len(deps),
                     instability=len(deps)/(len(deps)+sum(m in d for d in edges.values()))
                     if len(deps)+sum(m in d for d in edges.values()) else None) for m,deps in edges.items()]
    duplicate_lines = {}
    groups = 0
    for hits in clones.values():
        if len({h[0] for h in hits}) < 2:
            continue
        groups += 1
        for file, lo, hi in hits:
            duplicate_lines.setdefault(file, set()).update(range(lo, hi+1))
    tests = list((ROOT/'tests').rglob('*.py'))
    return dict(files=files, functions=functions, classes=classes, coupling=coupling,
        exact_clone_groups=groups, duplicated_physical_lines=sum(map(len, duplicate_lines.values())),
        test_nonblank_noncomment=sum(sum(bool(s.strip()) and not s.lstrip().startswith('#') for s in p.read_text().splitlines()) for p in tests), test_files=len(tests),
        production_nonblank_noncomment=sum(sum(bool(s.strip()) and not s.lstrip().startswith('#') for s in p.read_text().splitlines()) for p in paths),
        mean_mi=mean(f['mi'] for f in files),
        frontend_js_files=len(list((ROOT/'ui/js').rglob('*.js'))),
        frontend_js_loc=sum(len(p.read_text().splitlines()) for p in (ROOT/'ui/js').rglob('*.js')))


if __name__ == '__main__':
    print(json.dumps(run(), indent=2))
