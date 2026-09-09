"""Tests for core/di.py — tiny DI container."""

import pytest
from core.di import Container


def test_register_and_resolve_singleton():
    c = Container()
    c.register("answer", lambda _: 42)
    assert c.resolve("answer") == 42
    # singleton: same object
    assert c.resolve("answer") is c.resolve("answer")


def test_transient():
    c = Container()
    c.register("obj", lambda _: object(), singleton=False)
    assert c.resolve("obj") is not c.resolve("obj")


def test_register_instance():
    c = Container()
    inst = {"x": 1}
    c.register_instance("cfg", inst)
    assert c.resolve("cfg") is inst


def test_factory_receives_container():
    c = Container()
    c.register_instance("a", 10)
    c.register("b", lambda cont: cont.resolve("a") + 5)
    assert c.resolve("b") == 15


def test_missing_key_raises():
    c = Container()
    with pytest.raises(KeyError):
        c.resolve("missing")


def test_has():
    c = Container()
    assert not c.has("x")
    c.register("x", lambda _: 1)
    assert c.has("x")
    c.register_instance("y", 2)
    assert c.has("y")


def test_clear():
    c = Container()
    c.register("x", lambda _: 1)
    c.clear()
    assert not c.has("x")
