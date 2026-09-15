"""The shared half of the two named-thing libraries.

`bot_connections` and `bot_presets` both keep a map of user-named rows in
one section of `config/presets.json`, and both must survive a missing
config (the services are constructed before a config exists in several
tests and in the standalone engine run). That read is the same read; a
second copy of it was a clone the scanner was right to flag (RULE 5).

Deliberately thin: the interesting verbs — what a row means, which ids are
legal, what "active" means — differ per section and stay in the subclass.

ideal-size: 30 lines reason=under RULE 18's 150-line floor on purpose, like
`bot_transcript`. It is the de-duplication of exactly one method; padding it
with the section-specific verbs would put connection rules in the presets'
base class, which is the coupling the split exists to avoid.
"""

from __future__ import annotations


class NamedSection:
    """Read access to one `named_*` section of the config."""

    #: subclasses set the config section they own
    SECTION = ""

    def __init__(self, config=None) -> None:
        self._config = config

    def _all(self) -> dict:
        """Every stored row, or `{}` when there is no config to read."""
        if self._config is None:
            return {}
        items = self._config.named_all(self.SECTION)
        return items if isinstance(items, dict) else {}
