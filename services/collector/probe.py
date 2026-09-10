"""Read, classify and verify a heartbeat without owning session state."""

from .state import CollectorState


class CollectorProbe:
    @staticmethod
    async def read(collector, agent_version):
        state = await collector.parser.state()
        if int(state.get("agent") or 0) < agent_version:
            # No agent, or one that predates the pane-scoped parser: an old
            # agent cannot tell us who wrote what, so it may not be trusted.
            await collector.parser.install()
            collector._self_heals += 1
            state = await collector.parser.state()
            collector._log(
                f"Re-installed the in-page agent (v{int(state.get('agent') or 0)})",
                "info",
            )
        collector._agent = int(state.get("agent") or 0)
        collector._error = ""
        collector._last_probe = {
            "count": int(state.get("count") or 0),
            "panes": int(state.get("panes") or 0),
            "pane_source": str(state.get("pane_source") or ""),
            "participants": int(state.get("participants") or 0),
            "partner": str(state.get("partner") or ""),
            "in_authors": list(state.get("in_authors") or []),
            "out_authors": list(state.get("out_authors") or []),
            "scroll": dict(state.get("scroll") or {}),
        }

        return state

    @staticmethod
    def classify(collector, state):
        if not state.get("ok", True):
            collector._log("No chat on this page (state not ok)", "warn")
            return collector._refuse(
                CollectorState.NOT_PRIVATE, "Not in private tab now"
            )
        if state.get("tab") != "private":
            collector._log(
                f"Active tab is “{state.get('tab')}”, not private —",
                "warn",
                state.get("me") or "",
            )
            return collector._refuse(
                CollectorState.NOT_PRIVATE, "Not in private tab now"
            )
        participants = int(state.get("participants") or 0)
        # "Exactly two people" is enforced whenever the page exposes a
        # count. A private pane WITHOUT a readable counter — the partner
        # with no avatar identification (2026-09-08) — falls through to the
        # author gate below, which refuses the chat the moment any third
        # nick writes here. No gender/avatar check belongs in this path:
        # filters only govern auto-detection in the Action block.
        if (
            collector._settings["require_two_participants"]
            and participants > 0
            and participants != 2
        ):
            collector._log(
                f"Refused: {participants} participants, not a private chat",
                "warn",
                state.get("partner") or "",
            )
            return collector._refuse(
                CollectorState.GROUP_TAB,
                f"Group tab ({participants} people) — not collected",
            )

        nick = " ".join(str(state.get("partner") or "").split()).strip()
        if not nick:
            collector._log("No partner nick in the active tab", "warn")
            return collector._refuse(
                CollectorState.NOT_PRIVATE, "Not in private tab now"
            )

        return None

    @staticmethod
    def identify(collector, state):
        nick = " ".join(str(state.get("partner") or "").split()).strip()
        # My Nick is optional for the archive: in a verified two-person chat
        # the single outbound author IS me, so we adopt it for this session
        # (it is not persisted to config.json unless the user saves it).
        detected_me = " ".join(str(state.get("me") or "").split()).strip()
        outs = [str(o or "").strip() for o in (state.get("out_authors") or [])]
        if not detected_me:
            singles = [o for o in outs if o]
            if len(singles) == 1 and singles[0].lower() != nick.lower():
                detected_me = singles[0]
        if not collector.my_nick and detected_me:
            collector.configure(my_nick=detected_me)
            collector._detected_my_nick = detected_me
            collector._log(f"Detected My Nick as “{detected_me}”", "info", nick)
        elif (
            collector.my_nick
            and detected_me
            and detected_me.lower() != collector.my_nick.lower()
            and collector.my_nick.lower() not in {o.lower() for o in outs if o}
        ):
            # A saved My Nick can go stale: the user renames themselves on
            # the site, and from then on every tick would refuse the chat
            # because the pane's outbound author looks like a "stranger".
            # When the pane self-reports a DIFFERENT nick and the configured
            # one is not among the outbound authors, the pane wins for this
            # session (bug report 2026-09-08, "user now uses a diff name").
            previous = collector.my_nick
            collector.configure(my_nick=detected_me)
            collector._detected_my_nick = detected_me
            collector._log(
                f"My Nick changed from “{previous}” to "
                f"“{detected_me}” — adopted from the page",
                "info",
                nick,
            )

        my_nick = collector.my_nick or detected_me
        if my_nick and nick.lower() == my_nick.lower():
            collector._log("Partner is the same as My Nick — refusing", "warn", nick)
            return collector._refuse(
                CollectorState.NOT_PRIVATE, "Partner is ambiguous (same as My Nick)"
            )

        return None

    @staticmethod
    def verify(collector, state, nick, verify_private):
        # ── the two-step gate ─────────────────────────────────────
        check = verify_private(state, nick, collector.my_nick)
        if not check.ok:
            collector._nick = nick
            collector._log(
                f"Private-chat gate refused “{nick}” ({check.reason})", "warn", nick
            )
            return collector._refuse(*collector._gate_status(check, nick))
        collector._verified = True
        if check.me and not collector._detected_my_nick:
            collector._detected_my_nick = check.me

        collector._warning = (
            ""
            if collector.my_nick
            else "My Nick is not known yet — the archive will use "
            "the single outbound author as 'me'"
        )
        if nick != collector._nick:
            collector._nick = nick
            collector._added = 0

        return None
