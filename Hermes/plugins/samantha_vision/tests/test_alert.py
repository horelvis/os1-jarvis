from Hermes.plugins.samantha_vision.alert import build_prompt, deliver, make_handler
from Hermes.plugins.samantha_vision.vision import Detection


def test_the_prompt_carries_what_was_seen_and_where():
    p = build_prompt(camera="entrada", phrase="alguien")
    assert "entrada" in p
    assert "alguien" in p


def test_the_prompt_forbids_naming_the_machinery():
    p = build_prompt(camera="fuera", phrase="alguien").lower()
    # He must never say these out loud. The prompt has to say so,
    # because the model will otherwise narrate where it got the fact.
    for banned in ("cámara", "detección", "detectado", "yolo", "sensor"):
        assert banned in p, f"the prompt must forbid {banned!r} explicitly"


def test_the_prompt_asks_for_one_short_line():
    p = build_prompt(camera="fuera", phrase="alguien").lower()
    assert "una frase" in p or "una línea" in p
    assert "corta" in p


def test_the_phrase_is_inserted_verbatim():
    # describe() already produces Spanish; the prompt must not re-word it.
    p = build_prompt(camera="fuera", phrase="2 personas y un perro")
    assert "2 personas y un perro" in p


# ── the wiring: what a detection actually does ────────────────────────
#
# `deliver()` itself is a thin wrapper around the gateway and is proved
# by hand, not here. What IS worth a test is the shape of the retry —
# bounded, and dropping rather than queueing — and that the Watcher sits
# in front of the alert, since without it a camera says "alguien" every
# three seconds.


class FakeCtx:
    """A gateway that accepts, or refuses, on demand."""

    def __init__(self, accepts):
        self.accepts = list(accepts)
        self.calls = []

    def inject_message(self, content, role="user", *, session_key=None):
        self.calls.append((content, role, session_key))
        return self.accepts.pop(0) if self.accepts else False


def person(confidence=0.9):
    return Detection(label="persona", confidence=confidence, x=0.5, y=0.5)


def test_delivery_goes_to_the_strips_session_as_a_user_turn():
    ctx = FakeCtx([True])
    assert deliver(ctx, "hola", sleep=lambda _s: None) is True
    content, role, session_key = ctx.calls[0]
    assert content == "hola"
    assert role == "user"
    assert session_key == "agent:main:jarvis:dm:jarvis"


def test_a_gateway_that_is_not_ready_yet_is_retried():
    ctx = FakeCtx([False, False, True])
    slept = []
    assert deliver(ctx, "hola", sleep=slept.append) is True
    assert len(ctx.calls) == 3
    assert slept == [1.0, 3.0]


def test_a_gateway_that_never_answers_gives_up_and_drops():
    # Not a queue: a sighting with nowhere to go is lost on purpose.
    ctx = FakeCtx([])
    slept = []
    assert deliver(ctx, "hola", sleep=slept.append) is False
    assert len(ctx.calls) == 4  # one try plus the three delays, then stop
    assert slept == [1.0, 3.0, 5.0]


def test_an_injection_that_raises_does_not_reach_the_camera():
    class Exploding:
        def inject_message(self, *a, **kw):
            raise RuntimeError("gateway going down")

    assert deliver(Exploding(), "hola", sleep=lambda _s: None) is False


def test_a_detection_becomes_a_prompt_not_a_sentence():
    sent = []
    handler = make_handler(
        None, deliver_prompt=sent.append, now=lambda: 0.0, hour=lambda: 12
    )
    handler("entrada", [person()])
    assert len(sent) == 1
    assert "alguien" in sent[0]
    assert "entrada" in sent[0]
    # What is delivered is an instruction to him, never a line to read.
    assert "con tus palabras" in sent[0]


def test_the_same_thing_again_says_nothing():
    sent = []
    clock = [0.0]
    handler = make_handler(
        None, deliver_prompt=sent.append, now=lambda: clock[0], hour=lambda: 12
    )
    handler("entrada", [person()])
    clock[0] = 10.0
    handler("entrada", [person()])
    assert len(sent) == 1


def test_nothing_worth_saying_says_nothing():
    sent = []
    handler = make_handler(
        None, deliver_prompt=sent.append, now=lambda: 0.0, hour=lambda: 12
    )
    handler("entrada", [])
    assert sent == []


def test_a_handler_that_explodes_never_reaches_the_gateway():
    def boom(_prompt):
        raise RuntimeError("no")

    handler = make_handler(None, deliver_prompt=boom, now=lambda: 0.0, hour=lambda: 12)
    handler("entrada", [person()])  # must not raise


def test_the_dropped_warning_blames_the_gateway_not_a_missing_session():
    """Corrected 2026-08-24. `inject_message` returns False only when the
    gateway is not up; a missing session row comes back True and Hermes
    logs it itself as "Plugin message injection was not routed". The line
    here used to send the reader hunting for a session that was never the
    cause."""
    from loguru import logger

    records: list = []
    sink = logger.add(lambda m: records.append(m.record), level="DEBUG")
    try:
        assert deliver(FakeCtx([]), "hola", sleep=lambda _s: None) is False
    finally:
        logger.remove(sink)

    warnings = [r["message"] for r in records if r["level"].name == "WARNING"]
    assert len(warnings) == 1, warnings
    assert "no live gateway" in warnings[0]
    assert "session" not in warnings[0].lower(), warnings[0]


# ── the picture that comes with the sighting ──────────────────────────
#
# Asked for by the user 2026-08-26: "cuando captura algún movimiento
# debe mostrar esa captura, no solo decirlo". §12's entry of 2026-08-25
# had left this deliberately undone — "the unprompted alert carries NO
# photo, anywhere… if that is ever wanted, the mechanism is already
# there" — and this is that mechanism being wired to the alert path.
#
# The frame is the one the watcher just ran YOLO over, so nothing is
# opened, decoded or grabbed for it.


def test_a_sighting_shows_the_frame_it_was_seen_in():
    sent, shown = [], []
    handler = make_handler(
        None,
        deliver_prompt=sent.append,
        show_frame=lambda frame, camera: shown.append((frame, camera)),
        now=lambda: 0.0,
        hour=lambda: 12,
    )
    handler("entrada", [person()], frame="<pixels>")

    assert shown == [("<pixels>", "entrada")]
    assert len(sent) == 1


def test_nothing_worth_saying_shows_nothing():
    sent, shown = [], []
    clock = [0.0]
    handler = make_handler(
        None,
        deliver_prompt=sent.append,
        show_frame=lambda frame, camera: shown.append(camera),
        now=lambda: clock[0],
        hour=lambda: 12,
    )
    handler("entrada", [person()], frame="<pixels>")
    clock[0] = 10.0  # inside the window: not news
    handler("entrada", [person()], frame="<pixels>")

    assert shown == ["entrada"], "the suppressed sighting must not push a photo"


def test_a_sighting_with_no_frame_still_speaks():
    # `_report` is the only caller and always has one, but a handler that
    # needed a frame would be a handler that goes silent when something
    # upstream changes.
    sent, shown = [], []
    handler = make_handler(
        None,
        deliver_prompt=sent.append,
        show_frame=lambda frame, camera: shown.append(camera),
        now=lambda: 0.0,
        hour=lambda: 12,
    )
    handler("entrada", [person()])
    assert len(sent) == 1 and shown == []


def test_a_photo_that_fails_does_not_cost_the_sentence():
    # A picture is never worth the words. Same rule `mirar` follows.
    def broken(frame, camera):
        raise RuntimeError("no disk")

    sent = []
    handler = make_handler(
        None,
        deliver_prompt=sent.append,
        show_frame=broken,
        now=lambda: 0.0,
        hour=lambda: 12,
    )
    handler("entrada", [person()], frame="<pixels>")
    assert len(sent) == 1
