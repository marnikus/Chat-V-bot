"""
core/events — Event Bus (Real Path Tests)
Verifies subscribe/unsubscribe/emit/exception isolation/typed events/handlers copy.
"""
import unittest
import logging
import sys
sys.path.insert(0, "/home/user/Chat-V-bot")
from core.events import EventBus, PeopleChanged, LogMessage, GridLayoutChanged


class MockHandler:
    def __init__(self):
        self.calls = []
    def __call__(self, event):
        self.calls.append(event)


class TestEventBusPaths(unittest.TestCase):
    def setUp(self):
        self.bus = EventBus()

    # Path: subscribe -> emit -> handler gets exact instance
    def test_subscribe_emit_handler_called_with_instance(self):
        h = MockHandler()
        self.bus.subscribe(PeopleChanged, h)
        evt = PeopleChanged(reason="test", nicks=("a",))
        self.bus.emit(evt)
        self.assertEqual(len(h.calls), 1)
        self.assertIs(h.calls[0], evt)
        self.assertEqual(h.calls[0].reason, "test")

    # Path: unsubscribe removes; emit does nothing
    def test_unsubscribe_removes_handler(self):
        h = MockHandler()
        self.bus.subscribe(PeopleChanged, h)
        self.bus.unsubscribe(PeopleChanged, h)
        self.bus.emit(PeopleChanged())
        self.assertEqual(len(h.calls), 0)

    # Path: duplicate subscribe does not add twice
    def test_duplicate_subscribe_once(self):
        h = MockHandler()
        self.bus.subscribe(PeopleChanged, h)
        self.bus.subscribe(PeopleChanged, h)
        self.bus.emit(PeopleChanged())
        self.assertEqual(len(h.calls), 1)

    # Path: handler exception does not break emitter or other handlers
    def test_handler_exception_isolated(self):
        def bad_handler(evt):
            raise ValueError("bad handler")
        good = MockHandler()
        self.bus.subscribe(PeopleChanged, bad_handler)
        self.bus.subscribe(PeopleChanged, good)
        # Must not raise to emitter; good must receive event
        self.bus.emit(PeopleChanged())
        self.assertEqual(len(good.calls), 1)

    # Path: handlers_of returns copy (modifying doesn't affect internal)
    def test_handlers_of_is_copy(self):
        h = MockHandler()
        self.bus.subscribe(LogMessage, h)
        handlers = self.bus.handlers_of(LogMessage)
        handlers.pop()
        self.assertEqual(len(self.bus.handlers_of(LogMessage)), 1)

    # Path: frozen event values preserved through emit
    def test_frozen_event_immutable(self):
        evt = PeopleChanged(reason="del", nicks=("x",))
        with self.assertRaises(AttributeError):
            evt.reason = "new"
        self.bus.subscribe(PeopleChanged, MockHandler())
        self.bus.emit(evt)

    # Path: unsubscribe callable returned works
    def test_subscribe_returns_unsubscribe_callable(self):
        h = MockHandler()
        unsub = self.bus.subscribe(GridLayoutChanged, h)
        self.assertTrue(callable(unsub))
        unsub()
        self.bus.emit(GridLayoutChanged())
        self.assertEqual(len(h.calls), 0)

    # Path: emit with no subscribers does not crash
    def test_emit_no_subscribers_no_crash(self):
        self.bus.emit(LogMessage(message="hello"))

    # Path: multiple event types isolated
    def test_events_isolated_by_type(self):
        h_people = MockHandler()
        h_log = MockHandler()
        self.bus.subscribe(PeopleChanged, h_people)
        self.bus.subscribe(LogMessage, h_log)
        self.bus.emit(PeopleChanged())
        self.assertEqual(len(h_people.calls), 1)
        self.assertEqual(len(h_log.calls), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
