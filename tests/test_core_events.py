"""Tests for core/events.py — EventBus."""

from core.events import EventBus


def test_on_and_emit():
    bus = EventBus()
    received = []
    bus.on("foo", lambda p: received.append(p))
    bus.emit("foo", 123)
    assert received == [123]


def test_multiple_handlers():
    bus = EventBus()
    a, b = [], []
    bus.on("ev", lambda p: a.append(p))
    bus.on("ev", lambda p: b.append(p))
    bus.emit("ev", "x")
    assert a == ["x"] and b == ["x"]


def test_off_single():
    bus = EventBus()
    received = []

    def h(p):
        received.append(p)

    bus.on("ev", h)
    bus.off("ev", h)
    bus.emit("ev", 1)
    assert received == []


def test_off_all():
    bus = EventBus()
    bus.on("ev", lambda p: None)
    bus.on("ev", lambda p: None)
    bus.off("ev")
    assert bus.count("ev") == 0


def test_emit_unknown_is_noop():
    bus = EventBus()
    bus.emit("nothing", 1)  # should not raise


def test_handler_exception_is_isolated():
    bus = EventBus()
    ok = []

    def bad(p):
        raise RuntimeError("oops")

    bus.on("ev", bad)
    bus.on("ev", lambda p: ok.append(p))
    bus.emit("ev", "hi")
    assert ok == ["hi"]


def test_clear():
    bus = EventBus()
    bus.on("a", lambda p: None)
    bus.on("b", lambda p: None)
    bus.clear()
    assert bus.count("a") == 0
    assert bus.count("b") == 0


def test_count():
    bus = EventBus()
    assert bus.count("x") == 0
    bus.on("x", lambda p: None)
    assert bus.count("x") == 1
    bus.on("x", lambda p: None)
    assert bus.count("x") == 2


def test_no_duplicate_registration():
    bus = EventBus()

    def h(p):
        pass

    bus.on("ev", h)
    bus.on("ev", h)
    assert bus.count("ev") == 1
