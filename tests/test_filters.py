"""Filter engine unit tests (pure)."""
from chatflow.core.models import FilterRule, RuleType, UserRow
from chatflow.filters.engine import default_rules, evaluate, validate_rule


def row(nick, female=True, registered=False, guest=False):
    classes = {"user"}
    if female:
        classes.add("female-avatar")
    else:
        classes.add("male-avatar")
    if guest:
        classes.add("anonymous-badge")
    if registered:
        classes.add("registered-badge")
    return UserRow(nickname=nick, classes=frozenset(classes))


def test_defaults_pass_female_guest():
    rules = default_rules()
    assert evaluate(row("Lizalo4ka", female=True, guest=True), rules)[0]


def test_defaults_fail_male():
    ok, reason = evaluate(row("Dr0che", female=False, guest=True), default_rules())
    assert not ok and reason.startswith(RuleType.CLASS_INCLUDES.value)


def test_defaults_fail_registered():
    ok, reason = evaluate(row("Dr0che", female=True, registered=True), default_rules())
    assert not ok and reason.startswith(RuleType.CLASS_EXCLUDES.value)


def test_and_logic_all_must_pass():
    rules = [
        FilterRule("1", RuleType.CLASS_INCLUDES.value, "female-avatar", "", True, 0),
        FilterRule("2", RuleType.REGEX_MATCH.value, "nickname", "^L", True, 1),
    ]
    assert evaluate(row("Lizalo4ka", guest=True), rules)[0]
    ok, reason = evaluate(row("Mona", guest=True), rules)
    assert not ok and RuleType.REGEX_MATCH.value in reason


def test_regex_not_match():
    rules = [FilterRule("1", RuleType.REGEX_NOT_MATCH.value, "nickname",
                        "bot|admin", True, 0)]
    assert evaluate(row("Lizalo4ka", guest=True), rules)[0]
    assert not evaluate(row("botadmin", guest=True), rules)[0]


def test_disabled_rule_ignored():
    rules = [FilterRule("1", RuleType.CLASS_EXCLUDES.value, "female-avatar", "",
                        False, 0)]
    assert evaluate(row("Lizalo4ka", guest=True), rules)[0]


def test_invalid_regex_fails_safe_and_validates():
    rules = [FilterRule("1", RuleType.REGEX_MATCH.value, "nickname", "([", True, 0)]
    ok, _ = evaluate(row("anyone", guest=True), rules)
    assert not ok
    assert validate_rule(rules[0]) is not None
    assert validate_rule(rules[0].__class__(
        "1", RuleType.CLASS_EXCLUDES.value, "", "", True, 0))


def test_cyrillic_nickname():
    rules = [FilterRule("1", RuleType.REGEX_MATCH.value, "nickname",
                        "^[А-Яа-я_]", True, 0)]
    assert evaluate(row("МилаяКися", guest=True), rules)[0]
