"""The live session: one at a time, one way out, and a ceiling.

Nothing here needs a camera, a gateway or a GPU. The fleet and the three
pushes arrive as callables, the way `tool.py`'s tests already do it.

One wrinkle, and it is the point of the class under test: the tap runs
on the watcher thread and schedules onto the gateway's loop rather than
awaiting directly (`live.py`'s docstring explains why). Most of these
tests call the tap from OUTSIDE any running loop — the loop `open()`
captured has already been closed by the time `asyncio.run()` returns —
so `_schedule` finds a closed loop and returns without ever running the
push. That is fine for tests that only check the synchronous side
effects (`session.camera`, `session.expired`, `fleet.taps`). But
`test_nothing_is_sent_before_the_first_keyframe` claims to prove frames
actually arrive, so it drives the whole scenario — open, tap calls, and
the assertions — inside one `asyncio.run()`, with `asyncio.sleep(0)`
yields to let the scheduled coroutines actually run on the still-live
loop. Anything less would be asserting on a push that was never given a
chance to fire.
"""

import asyncio

from Hermes.plugins.samantha_vision.live import CEILING_SECONDS, LiveSession


class _Fleet:
    def __init__(self) -> None:
        self.taps: dict[str, object] = {}

    def set_tap(self, camera, tap):
        self.taps[camera] = tap

    def clear_tap(self, camera):
        self.taps.pop(camera, None)


class _Pushes:
    def __init__(self, ok: bool = True) -> None:
        self.ok = ok
        self.opened: list[tuple] = []
        self.frames: list[tuple] = []
        self.closed: list[tuple] = []

    async def open(self, camera, epoch, extradata, width, height):
        self.opened.append((camera, epoch, extradata, width, height))
        return self.ok

    async def frame(self, epoch, packet):
        self.frames.append((epoch, packet))
        return self.ok

    async def close(self, epoch, reason):
        self.closed.append((epoch, reason))
        return self.ok


def _session(clock=None, ok=True):
    fleet, pushes = _Fleet(), _Pushes(ok)
    now = clock or (lambda: 0.0)
    return (
        LiveSession(fleet, pushes.open, pushes.frame, pushes.close, now=now),
        fleet,
        pushes,
    )


async def _drain() -> None:
    """Let the loop actually run whatever `_schedule` just handed it.

    `run_coroutine_threadsafe` queues a callback that creates a Task,
    and the Task's first step is itself queued rather than run inline —
    two separate round trips through the ready queue. One `sleep(0)`
    only covers the first, so this yields a few times to be sure a
    push that was scheduled has actually executed by the time we look.
    """
    for _ in range(5):
        await asyncio.sleep(0)


def test_opening_installs_a_tap_and_announces_the_view():
    session, fleet, pushes = _session()

    assert asyncio.run(session.open("entrada", extradata=b"sps", size=(704, 480)))

    assert session.camera == "entrada"
    assert "entrada" in fleet.taps
    assert pushes.opened == [("entrada", 1, b"sps", 704, 480)]


def test_nothing_is_sent_before_the_first_keyframe():
    async def scenario():
        session, fleet, pushes = _session()
        await session.open("entrada", extradata=b"", size=(704, 480))

        fleet.taps["entrada"](b"delta-one", False)
        fleet.taps["entrada"](b"delta-two", False)
        await _drain()
        assert pushes.frames == []

        fleet.taps["entrada"](b"key", True)
        fleet.taps["entrada"](b"delta-three", False)
        await _drain()
        assert [packet for _epoch, packet in pushes.frames] == [
            b"key",
            b"delta-three",
        ]

    asyncio.run(scenario())


def test_closing_removes_the_tap_and_says_why():
    session, fleet, pushes = _session()
    asyncio.run(session.open("entrada", extradata=b"", size=(704, 480)))

    assert asyncio.run(session.close("asked"))

    assert fleet.taps == {}
    assert pushes.closed == [(1, "asked")]
    assert session.camera is None


def test_closing_twice_is_quiet_not_an_error():
    session, _fleet, pushes = _session()
    asyncio.run(session.open("entrada", extradata=b"", size=(704, 480)))
    asyncio.run(session.close("asked"))

    assert asyncio.run(session.close("timeout")) is False
    assert pushes.closed == [(1, "asked")]


def test_the_epoch_never_repeats():
    session, _fleet, pushes = _session()
    asyncio.run(session.open("entrada", extradata=b"", size=(704, 480)))
    asyncio.run(session.close("asked"))
    asyncio.run(session.open("entrada", extradata=b"", size=(704, 480)))

    assert [epoch for _c, epoch, *_rest in pushes.opened] == [1, 2]


def test_opening_a_second_view_closes_the_first():
    session, fleet, pushes = _session()
    asyncio.run(session.open("entrada", extradata=b"", size=(704, 480)))
    asyncio.run(session.open("fuera", extradata=b"", size=(704, 480)))

    assert pushes.closed == [(1, "asked")]
    assert list(fleet.taps) == ["fuera"]


def test_the_ceiling_closes_it():
    clock = {"t": 0.0}
    session, fleet, _pushes = _session(clock=lambda: clock["t"])
    asyncio.run(session.open("entrada", extradata=b"", size=(704, 480)))
    fleet.taps["entrada"](b"key", True)

    clock["t"] = CEILING_SECONDS + 0.1
    fleet.taps["entrada"](b"another", False)

    assert session.expired is True


def test_the_ceiling_actually_closes_the_session_on_a_live_loop():
    """The synchronous flag is only half the claim — prove the close too.

    `test_the_ceiling_closes_it` above calls the tap with no running
    loop, so `_schedule` never gets to run `close("timeout")`; it only
    proves the flag flips. Here the whole thing runs on one live loop,
    with `_drain()` giving the scheduled close a chance to execute, so
    this is the test that would fail if the ceiling stopped actually
    closing anything.
    """
    clock = {"t": 0.0}

    async def scenario():
        session, fleet, pushes = _session(clock=lambda: clock["t"])
        await session.open("entrada", extradata=b"", size=(704, 480))
        fleet.taps["entrada"](b"key", True)
        await _drain()

        clock["t"] = CEILING_SECONDS + 0.1
        fleet.taps["entrada"](b"another", False)
        await _drain()

        assert session.expired is True
        assert session.camera is None
        assert fleet.taps == {}
        assert pushes.closed == [(1, "timeout")]

    asyncio.run(scenario())


def test_a_failed_open_leaves_no_session_behind():
    session, fleet, _pushes = _session(ok=False)

    assert asyncio.run(session.open("entrada", extradata=b"", size=(704, 480))) is False
    assert session.camera is None
    assert fleet.taps == {}


def test_a_raising_open_is_swallowed_not_propagated():
    """`open()` never raises at its caller — a view is never worth a turn.

    `close()` already wraps its push in try/except (this module's own
    docstring quotes the reason); `open()`'s push is awaited directly,
    with nothing between it and whoever called `open()`. If that guard
    were ever removed, this coroutine's exception would propagate
    straight out of `session.open()` instead of coming back as `False`.
    """

    class _RaisingFleet(_Fleet):
        pass

    class _RaisingPushes(_Pushes):
        async def open(self, camera, epoch, extradata, width, height):
            raise RuntimeError("adapter socket gone")

    fleet, pushes = _RaisingFleet(), _RaisingPushes()
    session = LiveSession(fleet, pushes.open, pushes.frame, pushes.close)

    assert asyncio.run(session.open("entrada", extradata=b"", size=(704, 480))) is False
    assert session.camera is None
    assert fleet.taps == {}
