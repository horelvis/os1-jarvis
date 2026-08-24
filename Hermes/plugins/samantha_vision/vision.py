"""What the cameras see.

Borrowed from BarnDoor (~/git/barndoor), which already had the hard
parts solved: the RTSP addresses of the house's cameras and a YOLOv9
model converted to ONNX. Nothing else of that project comes with it —
no Frigate, no MQTT, no Telegram, no second agent. Just: open a camera,
say what is in front of it.

It costs no new dependencies, which is why it fits. onnxruntime is
already here for Silero, and PyAV came in with faster-whisper, so a
camera is one import away from a widget that could already hear.

Two halves, the same split as everywhere else in this package:
`Detector` is the model and needs only a numpy array; `CameraStream`
touches the network. The detector can therefore be tested against
recorded frames with no camera in the room — which is just as well,
since the cameras are not on this machine.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# YOLOv9 as exported by BarnDoor's scripts/build-yolov9-onnx.sh:
#   IN  images  [1, 3, 320, 320] float32, RGB, NCHW, normalised to [0,1]
#   OUT output0 [1, 84, 2100]    84 = 4 box coords + 80 COCO classes
_INPUT_SIZE = 320
_COCO_PERSON = 0

DEFAULT_MODEL_PATH = Path.home() / ".samantha" / "models" / "yolov9-t-320.onnx"

# What a house cares about, out of the 80 COCO classes. Everything else
# is noise on a driveway — she does not need to announce a potted plant.
WATCHED_CLASSES = {
    0: "persona",
    1: "bicicleta",
    2: "coche",
    3: "moto",
    5: "autobús",
    7: "camión",
    15: "gato",
    16: "perro",
}

# Below this a detection is not worth speaking about. YOLOv9-t at 320 px
# is a small model on small input; it guesses, and a low bar means she
# announces shadows.
# 0.7, taken from BarnDoor's rules.py, which arrived at it against these
# same cameras. Lower and she announces shadows; this is the number a
# working system settled on rather than one I guessed.
DEFAULT_THRESHOLD = 0.7


@dataclass(frozen=True)
class Detection:
    label: str
    confidence: float
    # Centre of the box, normalised 0..1 — enough to say "a la izquierda"
    # without shipping pixel coordinates upwards.
    x: float
    y: float


class Detector:
    """YOLOv9 over onnxruntime. Frames in, things out."""

    def __init__(
        self,
        model_path: str | os.PathLike[str] | None = None,
        threshold: float = DEFAULT_THRESHOLD,
    ) -> None:
        import numpy as np
        import onnxruntime as ort

        self._np = np
        self.threshold = threshold

        path = Path(
            model_path or os.getenv("SAMANTHA_YOLO_MODEL") or DEFAULT_MODEL_PATH
        )
        if not path.is_file():
            raise FileNotFoundError(
                f"YOLO model not at {path} — copy it from BarnDoor's "
                f"frigate-config/models/, or set SAMANTHA_YOLO_MODEL"
            )
        options = ort.SessionOptions()
        options.inter_op_num_threads = 1
        options.intra_op_num_threads = 2
        self._session = ort.InferenceSession(str(path), sess_options=options)
        self._input_name = self._session.get_inputs()[0].name

    def detect(self, frame) -> list[Detection]:
        """`frame` is an HxWx3 uint8 RGB array. Returns what it recognises."""
        np = self._np
        height, width = frame.shape[:2]

        tensor = self._letterbox(frame)
        raw = self._session.run(None, {self._input_name: tensor})[0]

        # [1, 84, 2100] -> [2100, 84]: one row per candidate box.
        boxes = raw[0].T
        scores = boxes[:, 4:]
        best = scores.argmax(axis=1)
        confidence = scores[np.arange(len(scores)), best]

        keep = confidence >= self.threshold
        out: list[Detection] = []
        for index in np.flatnonzero(keep):
            class_id = int(best[index])
            if class_id not in WATCHED_CLASSES:
                continue
            cx, cy = float(boxes[index][0]), float(boxes[index][1])
            out.append(
                Detection(
                    label=WATCHED_CLASSES[class_id],
                    confidence=float(confidence[index]),
                    x=min(1.0, max(0.0, cx / _INPUT_SIZE)),
                    y=min(1.0, max(0.0, cy / _INPUT_SIZE)),
                )
            )
        del height, width
        return _deduplicate(out)

    def _letterbox(self, frame):
        """HxWx3 uint8 RGB -> [1,3,320,320] float32 in [0,1].

        Stretches rather than pads. A driveway camera is wide, so padding
        would waste a third of an already small input on grey bars, and
        YOLO copes with the distortion better than with the lost pixels.
        """
        np = self._np
        height, width = frame.shape[:2]
        ys = (np.arange(_INPUT_SIZE) * height // _INPUT_SIZE).clip(0, height - 1)
        xs = (np.arange(_INPUT_SIZE) * width // _INPUT_SIZE).clip(0, width - 1)
        resized = frame[ys][:, xs]

        tensor = resized.astype(np.float32) / 255.0
        tensor = tensor.transpose(2, 0, 1)[np.newaxis, ...]
        return np.ascontiguousarray(tensor)


def _deduplicate(detections: list[Detection]) -> list[Detection]:
    """One entry per label, keeping the most confident.

    Not real NMS. What reaches the user is a sentence — "hay alguien en
    la puerta" — and for that, three overlapping boxes of the same person
    and one box are the same fact. Keeping this dumb also keeps it out of
    the way when the answer is spoken rather than drawn.
    """
    best: dict[str, Detection] = {}
    for item in detections:
        current = best.get(item.label)
        if current is None or item.confidence > current.confidence:
            best[item.label] = item
    return sorted(best.values(), key=lambda d: -d.confidence)


def describe(detections: list[Detection]) -> str:
    """A phrase she could say. Empty when there is nothing to say."""
    if not detections:
        return ""
    people = [d for d in detections if d.label == "persona"]
    others = [d for d in detections if d.label != "persona"]

    parts: list[str] = []
    if len(people) == 1:
        parts.append("alguien")
    elif people:
        parts.append(f"{len(people)} personas")
    parts += [d.label for d in others]

    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + " y " + parts[-1]


class CameraStream:
    """One RTSP camera, read frame by frame with PyAV.

    Reads the SUB-stream by convention: BarnDoor's config points its
    detector at `*_sub` for the same reason, since 4K frames cost time to
    decode and YOLO scales them down to 320 px regardless.
    """

    def __init__(self, url: str) -> None:
        self.url = url
        self._container = None

    def open(self) -> None:
        import av

        # A camera that has gone away must not block the caller forever.
        self._container = av.open(
            self.url, options={"rtsp_transport": "tcp", "stimeout": "5000000"}
        )

    def close(self) -> None:
        if self._container is not None:
            self._container.close()
            self._container = None

    def frames(self, every: int = 10):
        """Yield HxWx3 RGB arrays, one every `every` decoded frames.

        Cameras deliver 15-30 fps and nothing in a house changes that
        fast. Sampling keeps the GPU free for Whisper and CosyVoice,
        which are on the critical path of a conversation; a camera is not.
        """
        if self._container is None:
            self.open()
        assert self._container is not None

        for index, frame in enumerate(self._container.decode(video=0)):
            if index % every:
                continue
            yield frame.to_ndarray(format="rgb24")


# ── deciding whether it is worth saying ───────────────────────────────
#
# Detecting is the easy half. The half that decides whether a device in
# a living room is bearable is knowing when to keep quiet, and BarnDoor's
# rules.py had already worked it out against these very cameras:
#
#   - the same thing, seen again within three minutes, is not news
#   - a person at night is news even when the same person at noon is not
#
# Both are borrowed outright, numbers included.
ANTI_SPAM_SECONDS = 180
QUIET_START_HOUR = 23
QUIET_END_HOUR = 7


def is_quiet_hours(hour: int) -> bool:
    """True between QUIET_START_HOUR and QUIET_END_HOUR, wrapping midnight."""
    if QUIET_START_HOUR <= QUIET_END_HOUR:
        return QUIET_START_HOUR <= hour < QUIET_END_HOUR
    return hour >= QUIET_START_HOUR or hour < QUIET_END_HOUR


class Watcher:
    """Turns a stream of detections into the rare sentence worth saying.

    Without this a camera is a machine that says "alguien" every three
    seconds for as long as somebody stands in the driveway, which is
    precisely the visible agent CLAUDE.md §1 forbids — and unbearable
    besides.
    """

    def __init__(self, anti_spam_seconds: float = ANTI_SPAM_SECONDS) -> None:
        self.anti_spam_seconds = anti_spam_seconds
        # Keyed (camera, label), not label: two cameras seeing a person
        # are two events, and collapsing them would mean somebody could
        # cross the whole property in silence after the first sighting.
        self._last_said: dict[tuple[str, str], float] = {}

    def worth_saying(
        self, detections: list[Detection], now: float, hour: int, *, camera: str
    ) -> list[Detection]:
        """Filter to what she should actually mention, and remember it."""
        out: list[Detection] = []
        for item in detections:
            key = (camera, item.label)
            previous = self._last_said.get(key)
            recent = previous is not None and (now - previous) < self.anti_spam_seconds

            # A person at night beats the anti-spam: the second time
            # somebody is in the garden at 3am is more worth saying than
            # the first, not less.
            urgent = item.label == "persona" and is_quiet_hours(hour)

            if recent and not urgent:
                continue
            self._last_said[key] = now
            out.append(item)
        return out

    def forget(self) -> None:
        """Drop the history — for tests, and for a camera coming back."""
        self._last_said.clear()
