"""AREA C2: cycle_plan pure unit tests — stack scan + mode precedence.

No Qt/DB/CDP; TableCases-style fakes only. Mirrors area doc §C2 decision
table so the extraction stays honest.
"""

from __future__ import annotations

from types import SimpleNamespace

from services.run.cycle_plan import choose_cycle_mode, inspect_stack


def _block(block_id, enabled=True, **kw):
    return SimpleNamespace(block_id=block_id, enabled=enabled, **kw)


class TestInspectStack:
    def test_empty_stack(self):
        facts = inspect_stack([])
        assert facts.stack_empty is True
        assert facts.all_disabled is False
        assert facts.scroll_block is None

    def test_all_disabled(self):
        facts = inspect_stack([_block("SCROLL_PARSE", enabled=False), _block("WAIT_PAGE", enabled=False)])
        assert facts.stack_empty is False
        assert facts.all_disabled is True
        assert facts.scroll_block is None
        assert facts.has_mem_click is False

    def test_scroll_first_enabled_wins(self):
        s1 = _block("SCROLL_PARSE", enabled=True)
        s2 = _block("SCROLL_PARSE", enabled=True)
        facts = inspect_stack([_block("WAIT_PAGE"), s1, s2])
        assert facts.scroll_block is s1

    def test_mem_click_requires_flag_and_enabled(self):
        on = _block("CLICK_USER", enabled=True, use_person_from_memory=True)
        off_flag = _block("CLICK_USER", enabled=True, use_person_from_memory=False)
        off_enabled = _block("CLICK_USER", enabled=False, use_person_from_memory=True)
        assert inspect_stack([on]).has_mem_click is True
        assert inspect_stack([off_flag]).has_mem_click is False
        assert inspect_stack([off_enabled]).has_mem_click is False
        # Missing attr defaults to False (no crash).
        assert inspect_stack([_block("CLICK_USER")]).has_mem_click is False

    def test_take_and_skip_and_user_scoped(self):
        facts = inspect_stack([
            _block("TAKE_PERSON"),
            _block("CONDITIONAL_SKIP"),
            _block("CLICK_USER"),
            _block("WAIT_PAGE"),
        ])
        assert facts.has_take is True
        assert facts.has_conditional_skip is True
        # CLICK_USER is user-scoped; WAIT_PAGE is not.
        assert "CLICK_USER" in facts.user_scoped_ids
        assert "WAIT_PAGE" not in facts.user_scoped_ids
        # Sorted tuple.
        assert tuple(sorted(facts.user_scoped_ids)) == facts.user_scoped_ids

    def test_disabled_blocks_ignored(self):
        facts = inspect_stack([
            _block("TAKE_PERSON", enabled=False),
            _block("CONDITIONAL_SKIP", enabled=False),
            _block("CLICK_USER", enabled=False),
        ])
        assert facts.has_take is False
        assert facts.has_conditional_skip is False
        assert facts.user_scoped_ids == ()
        assert facts.all_disabled is True


class TestChooseCycleMode:
    def _facts(self, **kw):
        base = dict(scroll_block=None, has_mem_click=False, has_take=False,
                    has_conditional_skip=False, user_scoped_ids=(), stack_empty=False, all_disabled=False)
        base.update(kw)
        from services.run.cycle_plan import StackFacts
        return StackFacts(**base)

    def test_stopped_first(self):
        facts = self._facts(has_mem_click=True, has_take=True, user_scoped_ids=("CLICK_USER",))
        d = choose_cycle_mode(facts, has_queue=True, take_matched=True, stopped=True)
        assert (d.mode, d.reason) == ("stopped", "stopped")

    def test_single_target_beats_everything_else(self):
        facts = self._facts(has_mem_click=True, has_take=True, user_scoped_ids=("CLICK_USER",))
        d = choose_cycle_mode(facts, has_queue=True, take_matched=False, stopped=False)
        assert (d.mode, d.reason) == ("single_target", "mem_click")

    def test_take_miss_empty(self):
        facts = self._facts(has_take=True, user_scoped_ids=())
        d = choose_cycle_mode(facts, has_queue=False, take_matched=False)
        assert (d.mode, d.reason) == ("empty", "no_take_match")

    def test_take_miss_suppressed_by_queue(self):
        facts = self._facts(has_take=True, user_scoped_ids=())
        d = choose_cycle_mode(facts, has_queue=True, take_matched=False)
        assert d.mode == "queued"

    def test_take_miss_suppressed_by_needs_user(self):
        facts = self._facts(has_take=True, user_scoped_ids=("CLICK_USER",))
        d = choose_cycle_mode(facts, has_queue=False, take_matched=False)
        assert (d.mode, d.reason) == ("empty", "empty_queue")

    def test_take_miss_suppressed_by_match(self):
        facts = self._facts(has_take=True, user_scoped_ids=())
        d = choose_cycle_mode(facts, has_queue=False, take_matched=True)
        assert (d.mode, d.reason) == ("standalone", "standalone")

    def test_queued(self):
        facts = self._facts(user_scoped_ids=("CLICK_USER",))
        d = choose_cycle_mode(facts, has_queue=True, take_matched=False)
        assert (d.mode, d.reason) == ("queued", "queue")

    def test_empty_stack(self):
        facts = self._facts(stack_empty=True)
        d = choose_cycle_mode(facts, has_queue=False, take_matched=False)
        assert (d.mode, d.reason) == ("empty_stack", "no_stack")

    def test_user_empty(self):
        facts = self._facts(user_scoped_ids=("CLICK_USER", "TYPE_MESSAGE"))
        d = choose_cycle_mode(facts, has_queue=False, take_matched=False)
        assert (d.mode, d.reason) == ("empty", "empty_queue")

    def test_standalone(self):
        facts = self._facts(user_scoped_ids=())
        d = choose_cycle_mode(facts, has_queue=False, take_matched=False)
        assert (d.mode, d.reason) == ("standalone", "standalone")

    def test_all_disabled_standalone(self):
        # All-disabled stack has no user-scoped ids and no queue → standalone
        # (preserves legacy inline-scan behaviour: needs_user empty, take
        # absent, queue empty → standalone branch).
        facts = self._facts(all_disabled=True, user_scoped_ids=())
        d = choose_cycle_mode(facts, has_queue=False, take_matched=False)
        assert (d.mode, d.reason) == ("standalone", "standalone")
