"""Tests for core/result.py — Result[T] contract."""

import pytest
from core.result import Result


def test_ok_holds_value():
    r = Result.ok(42)
    assert r.is_ok is True
    assert r.is_err is False
    assert r.value == 42
    assert r.error is None
    assert r.unwrap() == 42


def test_err_holds_message():
    r = Result.err("boom")
    assert r.is_ok is False
    assert r.is_err is True
    assert r.error == "boom"
    with pytest.raises(ValueError):
        r.unwrap()


def test_unwrap_or():
    assert Result.ok("hi").unwrap_or("default") == "hi"
    assert Result.err("e").unwrap_or("default") == "default"


def test_map_ok():
    r = Result.ok(10).map(lambda x: x * 2)
    assert r.is_ok and r.value == 20


def test_map_err_propagates():
    r = Result.err("bad").map(lambda x: x * 2)
    assert r.is_err and r.error == "bad"


def test_map_exception_becomes_err():
    r = Result.ok(5).map(lambda x: 1 / 0)
    assert r.is_err
    assert "division by zero" in r.error


def test_to_dict():
    assert Result.ok(1).to_dict() == {"ok": True, "value": 1}
    assert Result.err("x").to_dict() == {"ok": False, "error": "x"}


def test_repr():
    assert "ok" in repr(Result.ok(1)).lower()
    assert "err" in repr(Result.err("x")).lower()


def test_generic_none_value():
    r = Result.ok(None)
    assert r.is_ok and r.value is None
