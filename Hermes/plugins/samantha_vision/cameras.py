"""The cameras of the house, by name.

The names are interface, not configuration: they are what he says
("en la entrada") and what the user asks for. That is why a nameless
entry is dropped rather than auto-numbered — "cámara 2" is not
something anybody would say out loud.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from loguru import logger


@dataclass(frozen=True)
class Camera:
    name: str
    url: str


def parse_cameras(cfg: dict[str, Any]) -> list[Camera]:
    """Read the `cameras` config key. Never raises.

    A broken entry must not take the working ones with it: a typo in one
    camera's config is the likeliest failure here, and losing the whole
    house to it would be absurd.
    """
    raw = cfg.get("cameras") or []
    out: list[Camera] = []
    seen: set[str] = set()
    for entry in raw:
        name = (entry or {}).get("name")
        url = (entry or {}).get("url")
        if not name or not url:
            logger.warning(
                f"samantha-vision: camera entry without name or url: {entry!r}"
            )
            continue
        if name in seen:
            logger.warning(
                f"samantha-vision: duplicate camera name {name!r}, keeping the first"
            )
            continue
        seen.add(name)
        out.append(Camera(str(name), str(url)))
    if not out:
        logger.info(
            "samantha-vision: no cameras configured (config key 'cameras' empty)"
        )
    return out


# ── the threads that watch them ───────────────────────────────────────
#
# One thread per camera, and each one owns its own failure. A camera
# that is off, unplugged or rebooting is a Tuesday: it must cost the
# journal one line, the other cameras nothing, and the gateway nothing
# at all. The gateway is the brain — if a decoder read in here took it
# down, the house would lose its voice because a driveway camera was
# rebooting.

# How long to wait before reopening a camera that failed, and the
# ceiling the backoff climbs to. Five minutes is roughly "check again
# after the reboot you are probably in the middle of".
RETRY_SECONDS = 30.0
MAX_RETRY_SECONDS = 300.0

# One frame in ten. Cameras deliver 15-30 fps and nothing in a house
# changes that fast; the GPU is wanted by Whisper and CosyVoice, which
# are on the critical path of a conversation. A camera is not.
SAMPLE_EVERY = 10

# stop() waits this long per thread and then abandons it. A thread wedged
# inside a decoder read cannot be interrupted from outside, and it is a
# daemon precisely so that it never delays shutdown (spec §3).
JOIN_TIMEOUT = 2.0


class CameraFleet:
    """The camera threads, started and stopped together.

    The two things that touch the outside world — building the detector
    (which loads an 8 MB model onto the GPU) and opening a stream (which
    talks to the network) — arrive as callables, so a test can watch the
    whole loop run without a camera or a GPU in the room.
    """

    def __init__(
        self,
        *,
        make_detector: Callable[[], Any] | None = None,
        open_stream: Callable[[str], Any] | None = None,
        retry_seconds: float = RETRY_SECONDS,
        sample_every: int = SAMPLE_EVERY,
    ) -> None:
        self._make_detector = make_detector or _default_detector
        self._open_stream = open_stream or _default_stream
        self._retry_seconds = retry_seconds
        self._sample_every = sample_every
        self._stopping = threading.Event()
        self._threads: list[threading.Thread] = []

    def start(
        self,
        cameras: list[Camera],
        on_detections: Callable[[str, list], None],
    ) -> None:
        """Start one daemon thread per camera. Never raises.

        Called from the supervisor thread, never from `register()`: the
        detector is built here, and that reads a file and claims memory.
        """
        if not cameras:
            return
        try:
            detector = self._make_detector()
        except Exception as exc:
            # Manifest failure mode #3: without the model no thread
            # starts and the plugin is inert. "He stopped noticing
            # people" has no other symptom, so it is said out loud.
            logger.error(f"samantha-vision: no detector, no cameras watched — {exc}")
            return

        for camera in cameras:
            thread = threading.Thread(
                target=self._watch,
                args=(camera, detector, on_detections),
                name=f"camera-{camera.name}",
                daemon=True,
            )
            self._threads.append(thread)
            thread.start()
        logger.info(
            f"samantha-vision: watching {len(cameras)} camera(s): "
            f"{', '.join(c.name for c in cameras)}"
        )

    def stop(self, timeout: float = JOIN_TIMEOUT) -> None:
        """Ask every thread to stop, and abandon the ones that will not.

        A thread blocked inside a decoder read does not come back until
        the read times out. Waiting for it would be the gateway waiting
        on a camera, which is the wrong way round.
        """
        self._stopping.set()
        for thread in self._threads:
            thread.join(timeout=timeout)
            if thread.is_alive():
                logger.debug(f"samantha-vision: {thread.name} still in a read, left")
        self._threads = []

    # -- one camera --------------------------------------------------------

    def _watch(self, camera: Camera, detector: Any, on_detections) -> None:
        """Open, sample, detect, report. Forever, and quietly.

        Nothing escapes this method: it is the whole of the contract with
        the gateway.
        """
        delay = self._retry_seconds
        reported = False  # this camera's failure has already been logged

        while not self._stopping.is_set():
            stream = None
            try:
                stream = self._open_stream(camera.url)
                for frame in stream.frames(self._sample_every):
                    if self._stopping.is_set():
                        break
                    if reported:
                        logger.info(f"samantha-vision: {camera.name} is back")
                    reported = False
                    delay = self._retry_seconds
                    self._report(camera, detector, frame, on_detections)
            except Exception as exc:
                # Once per camera, not once per attempt: a camera off for
                # a week would otherwise be the only thing in the journal.
                if not reported:
                    logger.warning(
                        f"samantha-vision: {camera.name} unreachable — {exc}"
                    )
                    reported = True
                else:
                    logger.debug(f"samantha-vision: {camera.name} still unreachable")
            finally:
                if stream is not None:
                    try:
                        stream.close()
                    except Exception:  # closing must never throw either
                        logger.debug(f"samantha-vision: {camera.name} would not close")

            # The stream also ends when a recording runs out, which is
            # how this path is tested; reopening it is the same loop.
            if self._stopping.wait(delay):
                return
            delay = min(delay * 2, MAX_RETRY_SECONDS)

    def _report(self, camera: Camera, detector: Any, frame, on_detections) -> None:
        """Detect on one frame and hand what it found upwards.

        The handler is somebody else's code — Task 5 hangs a gateway call
        on it — so it is not allowed to cost us the camera.
        """
        try:
            seen = detector.detect(frame)
        except Exception as exc:
            logger.debug(f"samantha-vision: {camera.name} detect failed — {exc}")
            return
        if not seen:
            return
        try:
            on_detections(camera.name, seen)
        except Exception as exc:
            logger.warning(f"samantha-vision: {camera.name} handler failed — {exc}")


def _default_detector():
    """The real YOLO session. Imported here: it loads onnxruntime."""
    from .vision import Detector

    return Detector()


def _default_stream(url: str):
    """The real camera. Imported here: it drags in PyAV, and ffmpeg with it."""
    from .vision import CameraStream

    return CameraStream(url)
