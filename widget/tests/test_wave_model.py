"""The wave, as arithmetic. No GTK, no display, no Cairo.

Everything visual about the strip is verified by screenshot, but the
*behaviour* of the line — that it answers the voice, that it smooths,
that the thinking packet travels — is arithmetic and belongs here where
it can fail fast.
"""

from jarvis_widget.wave_model import WaveModel, WaveState

WIDTH = 1000.0
HEIGHT = 96.0


def _amplitude(model: WaveModel) -> float:
    centre = HEIGHT / 2
    return max(abs(y - centre) for _x, y in model.points(WIDTH, HEIGHT))


def test_points_span_the_full_width() -> None:
    model = WaveModel()
    points = model.points(WIDTH, HEIGHT)

    assert points[0][0] == 0.0
    assert points[-1][0] == WIDTH
    assert len(points) >= 2


def test_idle_is_nearly_flat() -> None:
    model = WaveModel()
    model.state = WaveState.IDLE

    for _ in range(200):
        model.advance(1 / 60)

    assert _amplitude(model) < 4.0


def test_listening_follows_the_level() -> None:
    quiet, loud = WaveModel(), WaveModel()
    for model, level in ((quiet, 0.05), (loud, 0.9)):
        model.state = WaveState.LISTENING
        for _ in range(120):
            model.set_level(level)
            model.advance(1 / 60)

    assert _amplitude(loud) > 3 * _amplitude(quiet)


def test_a_sudden_level_is_smoothed_not_snapped() -> None:
    model = WaveModel()
    model.state = WaveState.LISTENING
    model.set_level(1.0)
    model.advance(1 / 60)
    after_one_frame = _amplitude(model)

    for _ in range(120):
        model.set_level(1.0)
        model.advance(1 / 60)
    settled = _amplitude(model)

    assert after_one_frame < settled / 2


def test_the_thinking_packet_travels() -> None:
    model = WaveModel()
    model.state = WaveState.THINKING

    def peak_x() -> float:
        centre = HEIGHT / 2
        return max(model.points(WIDTH, HEIGHT), key=lambda p: abs(p[1] - centre))[0]

    model.advance(0.1)
    first = peak_x()
    model.advance(0.4)
    second = peak_x()

    assert second > first


def test_the_thinking_packet_wraps_instead_of_leaving() -> None:
    model = WaveModel()
    model.state = WaveState.THINKING

    for _ in range(600):
        model.advance(1 / 60)

    centre = HEIGHT / 2
    assert max(abs(y - centre) for _x, y in model.points(WIDTH, HEIGHT)) > 2.0


def test_speaking_ignores_a_stale_level_once_it_stops_arriving() -> None:
    model = WaveModel()
    model.state = WaveState.SPEAKING
    for _ in range(120):
        model.set_level(0.9)
        model.advance(1 / 60)
    loud = _amplitude(model)

    model.set_level(0.0)
    for _ in range(120):
        model.advance(1 / 60)

    assert _amplitude(model) < loud / 2


def test_level_is_clamped() -> None:
    model = WaveModel()
    model.state = WaveState.LISTENING
    model.set_level(50.0)
    for _ in range(120):
        model.advance(1 / 60)

    assert _amplitude(model) <= HEIGHT / 2
