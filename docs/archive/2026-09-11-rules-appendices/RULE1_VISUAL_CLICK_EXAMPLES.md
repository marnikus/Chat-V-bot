# Appendix — RULE 1 worked examples (visual click runner)

Linked appendix of [`docs/current/AGENT_RULES.md`](../../current/AGENT_RULES.md)
RULE 1, moved out of the rules file on 2026-09-11 so the rules stay loadable in
one read (RULE 18 §18.4). The **norm** stays in the rules file; only the code
lives here.

## Correct

```python
from backend.visual_click import find_and_click

class MyBlock(BaseAction):
    async def execute(self, user_nick, cdp, engine=None):
        await self.pre_delay()
        return await find_and_click(
            cdp,
            selector=self.selector,
            label_selector=self.label_selector,
            match_text=self.match_text,
            click_selector=self.click_selector,
            highlight_enabled=self.highlight_enabled,
            confirm_pause_ms=self.confirm_pause_ms,
            label=f"my thing “{self.match_text}”",
            engine=engine,
        )
```

`actions/base.py` wraps this for the five compliant blocks (it also owns the
retry path), so a new block normally goes through `BaseAction` rather than
calling the runner directly.

## Incorrect — do not do this

```python
raw = await cdp.evaluate("document.querySelector('.x').click()")   # ✗ no logging
raw = await cdp.evaluate(build_probe(..., click=True))             # ✗ no overlays
```

Both skip the FIND/CLICK two-phase log, draw no outline, and can land the click
on a different node than the one the user saw highlighted.
