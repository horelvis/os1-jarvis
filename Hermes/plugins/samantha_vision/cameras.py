"""The cameras of the house, by name.

The names are interface, not configuration: they are what he says
("en la entrada") and what the user asks for. That is why a nameless
entry is dropped rather than auto-numbered — "cámara 2" is not
something anybody would say out loud.
"""

from __future__ import annotations

import os
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np
from loguru import logger


@dataclass(frozen=True)
class Camera:
    name: str
    url: str


# An RTSP URL carries the camera password, and PyAV puts the whole URL
# into the message of every failure it raises. Logging that verbatim
# writes the house's credential into the journal in plaintext, where
# `journalctl` hands it to anyone who can read the user's logs — and a
# camera that is off fails on a loop, so it lands there over and over.
# Measured 2026-08-24, the first time the plugin was pointed at the real
# cameras: `fuera unreachable — [Errno 113] No route to host:
# 'rtsp://admin:<the actual password>@192.168.100.142:554/…'`.
# The password runs to the LAST `@` of the authority, not the first, and
# it is allowed to contain one: ffmpeg splits on the last, so
# `rtsp://admin:p@ssw0rd@host/sub` is a URL an operator can plausibly
# write. A class that excluded `@` stopped at the first one and left the
# tail of the password in the journal — a partial redaction, which reads
# as a success. The username may also be empty (`rtsp://:secret@host`),
# so it is `*` and not `+`.
#
# `[^\s/]*` is what keeps the match inside ONE url: it cannot cross the
# path separator or a space, so two URLs in one message are redacted
# separately instead of being swallowed into a single match.
_CREDENTIAL = re.compile(r"(?<=://)([^/\s:@]*):[^\s/]*@")


def redact(text: str) -> str:
    """Strip the password out of any URL in `text`. Never raises.

    The user survives, because "which account cannot log in" is the
    useful half of the message and is not a secret.
    """
    return _CREDENTIAL.sub(r"\1:***@", str(text))


# The password does not live in the URL any more (Ruling 21). The URL in
# `.hermes/home/config.yaml` says `rtsp://admin:${RTSP_PASSWORD}@…` and the
# value arrives in the environment, put there by `Hermes/run-gateway.sh`
# sourcing the git-ignored `.env`.
#
# The trap, and it is the whole reason this is not one call to
# `expandvars`: an UNSET variable is left as the literal text
# `${RTSP_PASSWORD}`, which would then be used as the password and written
# into the journal by the first failure. So the names are read out of the
# RAW url and checked against the environment BEFORE expanding — checking
# afterwards would also flag a `$` that legitimately arrived inside the
# value.
#
# BRACES ONLY, and that is not a style choice. `expandvars` also expands a
# bare `$NAME`, but a password is allowed to contain a `$` and passwords
# are what this URL carries. Measured 2026-08-24, when this pattern still
# accepted the bare form: `rtsp://admin:pa$secretpart@h/sub` — a URL that
# worked, and was redacted, before Ruling 21 — was read as naming a
# variable `secretpart`, so the camera was dropped and a FRAGMENT OF THE
# PASSWORD was written into the journal by the very warning built to keep
# it out. Only `${NAME}` is treated as a placeholder now; a bare `$` is
# part of the value, and `_expand` substitutes the braced form itself
# rather than delegating to `expandvars`, which would still expand the
# bare one.
_PLACEHOLDER = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _expand(url: str) -> tuple[str | None, str | None]:
    """Substitute `${VAR}` from the environment.

    Returns `(url, None)` on success, or `(None, name)` naming the first
    variable that is not set. The URL is never returned half-expanded and
    the caller must never log it — and the name that IS logged comes from
    a braced placeholder, so it cannot be a slice of somebody's password.
    """
    missing: str | None = None

    def substitute(match: re.Match[str]) -> str:
        nonlocal missing
        name = match.group(1)
        value = os.environ.get(name)
        if value is None:
            if missing is None:
                missing = name
            return ""
        return value

    expanded = _PLACEHOLDER.sub(substitute, url)
    if missing is not None:
        return None, missing
    return expanded, None


def parse_cameras(cfg: dict[str, Any]) -> list[Camera]:
    """Read the `cameras` config key. Never raises.

    A broken entry must not take the working ones with it: a typo in one
    camera's config is the likeliest failure here, and losing the whole
    house to it would be absurd.
    """
    raw = cfg.get("cameras") or []
    if not isinstance(raw, list):
        # `cameras:` written as a name -> url mapping, or as one bare
        # string. Nothing is watched, but the journal says what was read
        # rather than showing a traceback from three frames deeper.
        logger.warning(f"samantha-vision: 'cameras' is not a list: {redact(repr(raw))}")
        raw = []
    out: list[Camera] = []
    seen: set[str] = set()
    for entry in raw:
        if not isinstance(entry, dict):
            # `- rtsp://…` instead of `- name: … / url: …`. One bad line
            # is one dropped camera, never the whole house.
            logger.warning(
                f"samantha-vision: camera entry is not a mapping: {redact(repr(entry))}"
            )
            continue
        name = entry.get("name")
        url = entry.get("url")
        if not name or not url:
            logger.warning(
                "samantha-vision: camera entry without name or url: "
                f"{redact(repr(entry))}"
            )
            continue
        if name in seen:
            logger.warning(
                f"samantha-vision: duplicate camera name {name!r}, keeping the first"
            )
            continue
        expanded, missing = _expand(str(url))
        if expanded is None:
            # Never the URL: it is half a credential either way, and the
            # unexpanded half is the name we are about to print anyway.
            logger.warning(
                f"samantha-vision: camera {str(name)!r} dropped, "
                f"${{{missing}}} is not set (see .env.example)"
            )
            continue
        seen.add(name)
        out.append(Camera(str(name), expanded))
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

        # The one detector, kept so the `mirar` tool can run it over a
        # frame it just grabbed instead of loading a SECOND ONNX session
        # for a model already resident. None until start() builds it —
        # and a fleet with no detector started no watcher thread either,
        # so it can never hand anybody a frame to run it on.
        self.detector: Any = None

        # One slot per camera, filled by the watcher thread ONLY while a
        # caller is waiting. A request arriving mid-frame therefore gets
        # the NEXT frame, never the one already analysed — "ahora" has to
        # mean now, and the watcher samples one frame in ten, so its last
        # frame can be 40 s old.
        self._pending: dict[str, np.ndarray | None] = {}
        self._wanted: dict[str, threading.Event] = {}
        self._grab_lock = threading.Lock()

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
            logger.error(
                f"samantha-vision: no detector, no cameras watched — {redact(exc)}"
            )
            return
        self.detector = detector

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
        # Snapshot: start() appends to this list, and a fleet stopped while
        # it is still starting would otherwise mutate what we iterate.
        threads, self._threads = list(self._threads), []
        for thread in threads:
            thread.join(timeout=timeout)
            if thread.is_alive():
                logger.debug(f"samantha-vision: {thread.name} still in a read, left")

    # -- handing a frame to someone asking right now ------------------------

    def _offer(self, camera: str, frame: np.ndarray) -> None:
        """Called by the watcher thread for every sampled frame.

        Costs one dict lookup when nobody is waiting, which is the normal
        case: this must not slow the detection loop down.
        """
        event = self._wanted.get(camera)
        if event is None or event.is_set():
            return
        with self._grab_lock:
            # Re-check under the lock: `_wanted` was read above WITHOUT
            # it, so the caller we found may have already timed out and
            # finished its own cleanup in the gap between that read and
            # this one. Storing anyway would pin a multi-MB frame in
            # `_pending` for nobody, forever — the next `grab()` for this
            # camera reinitialises the slot, but nothing else ever clears
            # a stray entry left behind here.
            if self._wanted.get(camera) is not event:
                return
            self._pending[camera] = frame
        event.set()

    def grab(self, camera: str, timeout: float = 2.0) -> np.ndarray | None:
        """The next frame this camera decodes, or None.

        None covers both "no such camera" and "it did not answer in time".
        A question that hangs is worse than one answered honestly, because
        he simply goes quiet (spec §4.1).
        """
        event = threading.Event()
        with self._grab_lock:
            self._wanted[camera] = event
            self._pending[camera] = None
        try:
            if not event.wait(timeout):
                return None
            with self._grab_lock:
                # Re-check identity here too: a caller can be pre-empted
                # by a later `grab()` for the same camera AFTER waking
                # (its own Event was already set) but BEFORE it reaches
                # this read. Without this check it would read whatever
                # the later caller's frame turned out to be — the same
                # ndarray object, aliased between two callers — instead
                # of the honest "you were pre-empted, and got nothing"
                # this method promises elsewhere.
                if self._wanted.get(camera) is not event:
                    return None
                return self._pending.get(camera)
        finally:
            with self._grab_lock:
                # Only remove OUR OWN registration. A second grab() for
                # the same camera, arriving while this one still waits,
                # overwrites this slot with its own Event before this one
                # is done with it — an unconditional pop here would then
                # delete THAT caller's live registration, or the frame
                # already delivered to it, out from under it. Comparing
                # identity is what tells the two apart; the camera name
                # alone cannot.
                if self._wanted.get(camera) is event:
                    self._wanted.pop(camera, None)
                    self._pending.pop(camera, None)

    # -- one camera --------------------------------------------------------

    def _watch(self, camera: Camera, detector: Any, on_detections) -> None:
        """Open, sample, detect, report. Forever, and quietly.

        Nothing escapes this method: it is the whole of the contract with
        the gateway.
        """
        delay = self._retry_seconds
        # One flag PER failure mode, not one for both. They are different
        # states and an operator reading the journal has to be able to
        # tell which one a camera is in: sharing a flag meant a camera
        # flipping between "unreachable" and "no frames" announced the
        # first one it hit and then logged nothing but DEBUG, leaving a
        # stale WARNING describing the state it was no longer in. A
        # persistent single state still costs exactly one line; entering
        # a DIFFERENT state is news and clears the other flag.
        reported_unreachable = False
        reported_empty = False

        while not self._stopping.is_set():
            stream = None
            frames_seen = 0
            try:
                stream = self._open_stream(camera.url)
                for frame in stream.frames(self._sample_every):
                    if self._stopping.is_set():
                        break
                    frames_seen += 1
                    if reported_unreachable or reported_empty:
                        logger.info(f"samantha-vision: {camera.name} is back")
                    reported_unreachable = reported_empty = False
                    delay = self._retry_seconds
                    # Before detection, deliberately: a caller waiting on
                    # grab() must not wait behind a slow detector too.
                    try:
                        self._offer(camera.name, frame)
                    except Exception as exc:
                        logger.debug(
                            f"samantha-vision: {camera.name} offer failed — "
                            f"{redact(exc)}"
                        )
                    self._report(camera, detector, frame, on_detections)
                # Manifest failure mode #4, and the one this plugin used
                # not to name. A camera that ANSWERS but yields no video —
                # wrong sub-stream path, a boot loop, a recording that has
                # already ended — raises nothing, so the `except` below
                # never runs and the backoff climbs to five minutes in
                # complete silence. From the journal it is indistinguishable
                # from a camera with nothing in front of it.
                if frames_seen == 0 and not self._stopping.is_set():
                    if not reported_empty:
                        logger.warning(
                            f"samantha-vision: {camera.name} connected but "
                            f"produced no frames"
                        )
                        reported_empty = True
                        reported_unreachable = False
                    else:
                        logger.debug(
                            f"samantha-vision: {camera.name} still producing no frames"
                        )
            except Exception as exc:
                # Once per camera, not once per attempt: a camera off for
                # a week would otherwise be the only thing in the journal.
                if not reported_unreachable:
                    logger.warning(
                        f"samantha-vision: {camera.name} unreachable — {redact(exc)}"
                    )
                    reported_unreachable = True
                    reported_empty = False
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
            logger.debug(
                f"samantha-vision: {camera.name} detect failed — {redact(exc)}"
            )
            return
        if not seen:
            return
        try:
            on_detections(camera.name, seen)
        except Exception as exc:
            logger.warning(
                f"samantha-vision: {camera.name} handler failed — {redact(exc)}"
            )


def _default_detector():
    """The real YOLO session."""
    from .vision import Detector

    return Detector()


def _default_stream(url: str):
    """The real camera."""
    from .vision import CameraStream

    return CameraStream(url)
