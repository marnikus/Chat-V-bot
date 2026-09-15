"""Shared speed dials for collector/sync-driven tests (W2 of the plan in
docs/archive/2026-09-15-test-time-reduction/).

The pane fakes used by these tests (FakePage and friends) answer every
settle poll with the same deterministic state, so the production settle
window — 3 identical polls, 300 ms apart — is ~0.9 s of wall time that
proves nothing per test. These helpers patch the construction site only:
the real `SettleSpec` value object and the real settle loop still run,
just with a 15 ms window and one stable poll. Settle *behaviour* (the
tests that assert `_settled`, retries and floors) lives in the chat-sync
and scroll-parse suites, not in the collector tick families.
"""

from unittest import mock

from backend.parser_requests import SettleSpec

_PATCH_TARGET = "backend.chat_sync_session.SettleSpec"


def fast_settle():
    """A mock.patch: next SettleSpec(...) gets wait_ms=15, stable_polls=1."""
    real = SettleSpec
    return mock.patch(_PATCH_TARGET,
                      lambda **kw: real(wait_ms=15, stable_polls=1, **kw))
