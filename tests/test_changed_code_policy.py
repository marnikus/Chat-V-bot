"""Scoped measurements, legacy ratchets and honest exception behavior."""

import pytest

from tools.metrics.changed_code import policy, symbols


def wide(name="wide"):
    return f"def {name}(a, b, c, d, e):\n    return a\n"


def analyze(before, after):
    return policy.compare(symbols.collect(before), symbols.collect(after))


def test_legacy_metric_cannot_worsen_even_below_another_hard_cap():
    before = {"core/x.py": wide()}
    after = {"core/x.py": wide().replace("return a", "return a if b else c")}
    result = analyze(before, after)
    assert any("cc" in b and "legacy" in b for b in result["breaches"])


def test_unchanged_legacy_is_not_failed_and_new_copy_gets_no_allowance():
    before = {"core/old.py": wide()}
    assert analyze(before, before)["breaches"] == []
    copied = analyze(before, {**before, "core/copy.py": wide()})
    assert any("core/copy.py" in b for b in copied["breaches"])


def test_unique_exact_move_retains_legacy_but_ambiguous_copies_do_not():
    before = {"core/old.py": wide()}
    moved = analyze(before, {"core/new.py": wide()})
    assert moved["breaches"] == []
    assert moved["rows"][0]["status"] == "moved"
    ambiguous = analyze(before, {"core/a.py": wide(), "core/b.py": wide()})
    assert len(ambiguous["breaches"]) == 2


def test_blank_line_growth_is_not_hidden_by_ast_equality():
    before = {"core/x.py": "def f():\n    return 1\n"}
    after = {"core/x.py": "def f():\n" + "\n" * 30 + "    return 1\n"}
    assert any("loc" in b for b in analyze(before, after)["breaches"])


def test_same_named_methods_properties_and_nested_functions_have_distinct_keys():
    text = '''class A:
    @property
    def value(self):
        return 1
    @value.setter
    def value(self, new):
        self._value = new
class B:
    def value(self):
        def nested(a, b, c, d, e):
            return a
        return nested(1, 2, 3, 4, 5)
'''
    rows = symbols.collect({"core/x.py": text})
    assert len(rows) == 6
    assert len(set(rows)) == len(rows)
    result = policy.compare({}, rows)
    assert any("B.value.nested" in b and "params" in b for b in result["breaches"])


def test_class_counts_only_direct_methods_and_positional_only_params_count():
    text = "class A:\n    def f(self, a, b, c, d, e, /):\n        def child():\n            return 1\n        return child()\n"
    rows = list(symbols.collect({"core/x.py": text}).values())
    assert next(r for r in rows if r.kind == "class").metrics["methods"] == 1
    assert next(r for r in rows if r.qualname == "A.f").metrics["params"] == 5


def test_class_size_and_method_limits_apply_to_new_classes():
    methods = "\n".join(f"    def m{i}(self):\n        return {i}" for i in range(16))
    result = analyze({}, {"core/x.py": "class Large:\n" + methods + "\n"})
    assert any("methods" in b for b in result["breaches"])


def test_override_is_per_metric_and_cannot_mask_legacy_growth():
    override = "# quality-override: params=5 reason=frozen wire interface requires these arguments\n"
    assert analyze({}, {"core/x.py": override + wide()})["breaches"] == []
    result = analyze({"core/x.py": wide()}, {"core/x.py": override + wide().replace("return a", "return a if b else c")})
    assert any("legacy" in b for b in result["breaches"])


@pytest.mark.parametrize("comment", [
    "# quality-override: params=8 reason=frozen wire interface requires these arguments\n",
    "# quality-override: params=5 reason=quick fix\n",
    "# quality-override: made-up=5 reason=frozen wire interface requires these arguments\n",
    "# quality-override: params reason=frozen wire interface requires these arguments\n",
    "# quality-override params=5 reason=frozen wire interface requires these arguments\n",
    "# quality-override: params=5 reason=                         x\n",
])
def test_invalid_overrides_fail(comment):
    assert analyze({}, {"core/x.py": comment + wide()})["breaches"]


def test_stale_duplicate_and_orphan_overrides_fail():
    comment = "# quality-override: params=5 reason=frozen wire interface requires these arguments\n"
    for source in (comment + "def small():\n    return 1\n", comment * 2 + wide(),
                   comment + "answer = 1\n"):
        assert analyze({}, {"core/x.py": source})["breaches"]


def test_override_text_inside_a_string_cannot_waive_anything():
    source = wide().replace("return a", 'return "quality-override: params=5 reason=frozen wire interface requires these arguments"')
    assert any("params" in b for b in analyze({}, {"core/x.py": source})["breaches"])


def test_match_nesting_and_inner_functions_are_measured_in_their_own_scope():
    text = "def outer():\n    def inner(x):\n"
    indent = "        "
    for _ in range(5):
        text += indent + "match x:\n" + indent + "    case _:\n"
        indent += "        "
    text += indent + "return x\n    return inner\n"
    rows = list(symbols.collect({"core/x.py": text}).values())
    assert rows[0].metrics["nesting"] == 0
    assert rows[1].metrics["nesting"] == 5
    assert any("nesting" in b for b in analyze({}, {"core/x.py": text})["breaches"])


def test_complexity_and_class_loc_limits_are_real():
    body = "def f(x):\n" + "".join(f"    if x == {i}:\n        x += 1\n" for i in range(12)) + "    return x\n"
    assert any("cc" in b for b in analyze({}, {"core/x.py": body})["breaches"])
    large = "class C:\n" + "".join(f"    field{i} = {i}\n" for i in range(151))
    assert any("loc" in b for b in analyze({}, {"core/x.py": large})["breaches"])


def test_only_leading_self_or_cls_is_excluded_and_kwonly_args_count():
    row = next(iter(symbols.collect({"core/x.py": "def f(a, self, *, cls=1):\n    return a\n"}).values()))
    assert row.metrics["params"] == 3
    row = next(iter(symbols.collect({"core/x.py": "async def f(self, *, a, b, c, d, e):\n    return a\n"}).values()))
    assert row.metrics["params"] == 6  # a standalone self parameter is not a receiver


def test_embedded_js_exception_is_explicit_and_does_not_waive_other_metrics():
    body = 'def build(a, b, c, d, e):\n    return """\n' + '\n'.join('    // payload' for _ in range(35)) + '\n    """\n'
    comment = f"# quality-override: loc={len(body.splitlines())} reason=single generated JS payload preserves the browser wire contract\n"
    result = analyze({}, {"backend/probe.py": comment + body})
    assert not any(": loc " in b for b in result["breaches"])
    assert any("params" in b for b in result["breaches"])
    assert analyze({}, {"backend/probe.py": body})["breaches"]
    not_payload = "def build():\n" + "".join(f"    x{i} = {i}\n" for i in range(35)) + "    return 1\n"
    bad = f"# quality-override: loc={len(not_payload.splitlines())} reason=single generated JS payload preserves the browser wire contract\n"
    assert any("one literal" in b for b in analyze({}, {"backend/probe.py": bad + not_payload})["breaches"])


def test_staticmethod_and_nested_self_parameters_are_not_receivers():
    source = "class C:\n    @staticmethod\n    def f(self, a, b, c, d):\n        def nested(self):\n            return self\n        return nested(a)\n"
    rows = list(symbols.collect({"core/x.py": source}).values())
    assert next(r for r in rows if r.qualname == "C.f").metrics["params"] == 5
    assert next(r for r in rows if r.qualname == "C.f.nested").metrics["params"] == 1


def test_renamed_or_rewritten_moves_do_not_inherit_legacy_allowance():
    original = {"core/old.py": wide()}
    for changed in (wide("renamed"), wide().replace("return a", "return b")):
        assert analyze(original, {"core/new.py": changed})["breaches"]


def test_cognitive_complexity_limit_is_enforced_independently():
    source = "def f(x):\n"
    for i in range(4):
        source += "    " * (i + 1) + "if x:\n"
    source += "                    return 1 if x else 2 if x else 3 if x else 4\n"
    metrics = next(iter(symbols.collect({"core/x.py": source}).values())).metrics
    assert metrics["cognitive"] > 15
    assert any("cognitive" in b for b in analyze({}, {"core/x.py": source})["breaches"])
