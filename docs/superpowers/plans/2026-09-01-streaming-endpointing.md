# Streaming Endpointing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** JARVIS stops waiting a fixed 1.2 s of silence before answering — a second, tiny STT engine reads what you have said so far and closes the turn as soon as it reads as a finished thought, saving a measured 880 ms per turn; and the same engine makes it possible to interrupt him.

**Architecture:** `stt.py` is untouched — faster-whisper still produces every word Hermes sees, with its `initial_prompt` intact. A new `endpoint.py` adds Vosk `small-es` (39 MB, CPU, Apache 2.0) whose text never leaves the widget and is used for two decisions only: *has this person finished speaking?* and *is this sound his own echo or a person talking over him?* `vad.py` gains a short 0.35 s trigger beside its existing 1.2 s one; when the rule declines, the 1.2 s closes the turn exactly as today.

**Tech Stack:** Python 3.12, `vosk` (new dependency), the existing `onnxruntime`/`numpy`/`sounddevice` stack, pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-09-01-streaming-endpointing-design.md`

## Global Constraints

- **Language:** user-facing strings in Spanish, code/comments/docs in English (CLAUDE.md §2.9).
- **New work goes in `widget/`.** Never in `backend/` or `frontend/` (CLAUDE.md §3).
- **Run tests as:** `cd widget && PYTHONNOUSERSITE=1 ./.venv/bin/python -m pytest -v`. `PYTHONNOUSERSITE=1` is mandatory — the venv is `--system-site-packages` and also sees `~/.local/lib` without it (CLAUDE.md §2.8).
- **Lint:** `./.venv/bin/ruff check . && ./.venv/bin/ruff format --check .` before every commit.
- **`vosk` is a new Python dependency.** CLAUDE.md §8 requires confirmation for that; it was given on 2026-09-01 as part of approving the spec, which names the engine and its licence (Apache 2.0). Do not substitute a different engine — the spec measured three and rejected two.
- **The Vosk model lives at `~/.samantha/models/vosk-model-small-es-0.42/`**, beside the Silero model, and is NOT committed. 39 MB.
- **No user audio in the repository.** `os1-samantha` is public. Fixtures are transcribed text and timings only, never WAV.
- **Failure is silence, never deafness.** If Vosk cannot load, every new code path must degrade to today's behaviour. A feature that makes him faster must not be able to make him deaf (CLAUDE.md §12, 2026-08-30).

---

### Task 1: The completion rule

The pure half: text in, boolean out. No engine, no file, no audio. This is where the whole design's risk lives, so it is built first and alone.

**Files:**
- Create: `widget/samantha_widget/endpoint.py`
- Test: `widget/tests/test_endpoint.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `CompletionRule(min_words: int = 2)` with `looks_complete(partial: str) -> bool`. Task 2 calls it through a callback; Task 4 constructs it.

- [ ] **Step 1: Write the failing test**

Create `widget/tests/test_endpoint.py`:

```python
"""Whether a partial transcript reads as a finished thought.

Every case here was measured on 2026-09-01 against the user's own voice
(the spec has the traces). Vosk emits no punctuation at all, so the only
signal available is the last word — which is why the word list IS the
rule, and why it is tested this heavily.
"""

from pathlib import Path

import pytest

from samantha_widget.endpoint import CompletionRule, VoskPartials, load_partials


@pytest.fixture
def rule() -> CompletionRule:
    return CompletionRule()


@pytest.mark.parametrize(
    "partial",
    [
        # Measured: the mid-sentence pause Whisper punctuated into a
        # clean sentence and Vosk left hanging. The user was not done.
        "ahora mismo las dos camaras habra que comprobar que esten encendidas y",
        "hola ya veis que pueda se",
        "enciendeme la luz del",
        "manana tengo que",
        "ponme una alarma para las",
        "quiero que busques unas de otro",
        "es que hoy no",  # "no" ends sentences, but "hoy no" here is mid-clause
    ],
)
def test_a_thought_still_in_flight_waits(rule: CompletionRule, partial: str) -> None:
    assert rule.looks_complete(partial) is False


@pytest.mark.parametrize(
    "partial",
    [
        # Measured: the true end of the same recording.
        "de otro proveedor que no son las que habia antes",
        "hola ya veis que puedas en madrid en las ultimas veinticuatro horas",
        "enciendeme la luz del salon",
        "apaga la luz",
    ],
)
def test_a_finished_thought_closes(rule: CompletionRule, partial: str) -> None:
    assert rule.looks_complete(partial) is True


@pytest.mark.parametrize(
    "partial", ["que hora es", "no lo se", "dame mas", "creo que no"]
)
def test_words_that_can_end_a_sentence_are_not_dangling(
    rule: CompletionRule, partial: str
) -> None:
    """The regression the spec names.

    The spike's first draft put `es` in the list, so "¿qué hora es?"
    could never close early. That costs no cut — the 1.2 s fallback
    still fires — but it silently forfeits the gain on one of the
    commonest question forms. Only words that CANNOT end a sentence
    belong in the list.
    """
    assert rule.looks_complete(partial) is True


def test_too_few_words_is_never_complete(rule: CompletionRule) -> None:
    assert rule.looks_complete("hola") is False


def test_empty_is_never_complete(rule: CompletionRule) -> None:
    assert rule.looks_complete("") is False
    assert rule.looks_complete("   ") is False


def test_accents_separate_a_question_from_a_conjunction(
    rule: CompletionRule,
) -> None:
    """`que` cannot end a sentence; `qué` can. Same for como/cómo.

    Whisper writes the accent and Vosk does not, so this matters mostly
    for the tests — but folding accents away would put `qué` into the
    dangling set and lose "no sé qué".
    """
    assert rule.looks_complete("no se que") is False
    assert rule.looks_complete("no se que hacer") is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd widget && PYTHONNOUSERSITE=1 ./.venv/bin/python -m pytest tests/test_endpoint.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'samantha_widget.endpoint'`

The file imports `VoskPartials` and `load_partials`, which Task 3 adds. Until
then this import is what makes the whole file fail to collect, which is the
correct failing state for Task 1: implement `CompletionRule` AND add
placeholder-free stubs? **No** — instead, Task 1 defines `CompletionRule`
only, and Task 3 completes the module. To keep Task 1 independently green,
Task 1 writes the import line as it will finally be and Task 1's Step 3
implementation includes the two names Task 3 fills in:

```python
class VoskPartials:  # completed in Task 3
    def __init__(self, *_args, **_kwargs) -> None:
        raise FileNotFoundError("Vosk support arrives in Task 3")


def load_partials():  # completed in Task 3
    return None
```

Delete both when Task 3 replaces them.

- [ ] **Step 3: Write minimal implementation**

Create `widget/samantha_widget/endpoint.py`:

```python
"""Deciding that somebody has finished talking, from what they have said.

Two halves, deliberately separate the way `vad.py` is: `CompletionRule`
is the policy and is pure enough to test phrase by phrase, and
`VoskPartials` is the model, the only part that needs a file on disk.

Measured 2026-09-01, and it inverts the obvious answer: the BEST
transcriber is the WORST at this. At the user's mid-sentence pause
Whisper wrote «…habrá que comprobar que estén encendidas y con red.» — a
clean, punctuated, finished Spanish sentence — and closing there cut him
off mid-thought. Vosk, at the same instant, wrote «…que estén encendidas
y» and waited. Whisper COMPLETES the sentence it heard; Vosk leaves it
hanging where the speaker left it. For this one job, the engine that
cannot punctuate is the one that tells the truth.
"""

from __future__ import annotations

import re

# Spanish words that CANNOT end a sentence. The distinction is the whole
# rule and it is narrower than it looks: a word that merely *usually*
# does not end a sentence must stay out, because every entry costs the
# 880 ms saving on every sentence that legitimately ends with it.
#
# Deliberately ABSENT, each one measured or reasoned:
#   es, era, hay   — "¿qué hora es?", "no hay"
#   no, sí, ya     — "creo que no"
#   más, menos     — "dame más"
#   también, tampoco, nunca, siempre, bien, mal, aquí, allí
#   otro, otra     — "quiero otro"
#
# Accents are NOT folded away: `que` cannot end a sentence and `qué` can
# ("no sé qué"), and the same holds for como/cómo, cuando/cuándo,
# donde/dónde. Folding would put the interrogatives into this set.
_CANNOT_END = frozenset(
    # determiners and possessives
    "el la los las un una unos unas mi mis tu tus su sus nuestro nuestra "
    "nuestros nuestras vuestro vuestra este esta estos estas ese esa esos "
    "esas aquel aquella aquellos aquellas cada cierto cierta cuyo cuya "
    "cuyos cuyas"
    " "
    # prepositions, and the two contractions
    "a ante bajo con contra de desde durante en entre hacia hasta mediante "
    "para por segun sin sobre tras del al"
    " "
    # conjunctions and subordinators (unaccented forms only)
    "y e o u ni pero sino aunque porque pues que si como cuando donde "
    "mientras"
    " "
    # unstressed pronouns, which always precede their verb
    "me te se nos os le les"
    " "
    # degree adverbs that must be followed by what they modify
    "muy tan"
    .split()
)

_WORD = re.compile(r"[a-záéíóúüñ]+", re.IGNORECASE)


class CompletionRule:
    """Does this partial transcript read as a finished thought?"""

    def __init__(self, min_words: int = 2) -> None:
        self.min_words = min_words

    def looks_complete(self, partial: str) -> bool:
        words = _WORD.findall(partial.lower())
        if len(words) < self.min_words:
            return False
        return words[-1] not in _CANNOT_END
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd widget && PYTHONNOUSERSITE=1 ./.venv/bin/python -m pytest tests/test_endpoint.py -v`
Expected: PASS, all cases.

If `test_a_thought_still_in_flight_waits["es que hoy no"]` fails, that is the plan being wrong rather than the code: `no` is deliberately absent from `_CANNOT_END`. Delete that one parametrised case and note it in the commit — a partial ending in "no" genuinely is ambiguous and the fallback handles it.

- [ ] **Step 5: Lint and commit**

```bash
cd widget && ./.venv/bin/ruff check . && ./.venv/bin/ruff format --check .
git add samantha_widget/endpoint.py tests/test_endpoint.py
git commit -m "feat(stt): the rule that tells a breath from an ending"
```

---

### Task 2: The short trigger in the VAD

`UtteranceDetector` learns to ask a question at 0.35 s of silence. Default behaviour is unchanged, which is what keeps every existing VAD test meaningful.

**Files:**
- Modify: `widget/samantha_widget/vad.py`
- Test: `widget/tests/test_vad.py`

**Interfaces:**
- Consumes: `CompletionRule.looks_complete` from Task 1, indirectly — the detector takes a zero-argument callback, not the rule itself, so `vad.py` stays free of the engine.
- Produces: `UtteranceDetector(probe, *, may_close: Callable[[], bool] = lambda: False)`. Task 4 supplies the real callback.

- [ ] **Step 1: Write the failing test**

Append to `widget/tests/test_vad.py`:

```python
def _run_with(script: list[float], may_close) -> list[bytes]:
    detector = UtteranceDetector(ScriptedProbe(script), may_close=may_close)
    return [u for _ in script if (u := detector.push(FRAME)) is not None]


def test_the_short_trigger_closes_a_turn_early() -> None:
    """0.35 s of quiet plus a rule that says yes ends the turn.

    Measured 2026-09-01: 880 ms earlier than the 1.2 s threshold.
    """
    script = _frames((0.0, 0.5), (0.9, 2.0), (0.0, 0.5))

    utterances = _run_with(script, lambda: True)

    assert len(utterances) == 1


def test_a_rule_that_declines_leaves_todays_behaviour_exactly() -> None:
    """The 1.2 s threshold is the floor, not a thing the rule can lower.

    This is the regression that matters: if Vosk never loads, or the rule
    is always wrong, he must behave precisely as he did before.
    """
    script = _frames((0.0, 0.5), (0.9, 2.0), (0.0, 0.5))

    assert _run_with(script, lambda: False) == []

    longer = _frames((0.0, 0.5), (0.9, 2.0), (0.0, 2.0))
    assert len(_run_with(longer, lambda: False)) == 1


def test_the_rule_is_asked_once_per_pause_not_once_per_frame() -> None:
    """Otherwise a two-second pause asks it sixty times, and every one of
    those is a Vosk query and a chance to disagree with the last."""
    asked = {"n": 0}

    def may_close() -> bool:
        asked["n"] += 1
        return False

    _run_with(_frames((0.0, 0.5), (0.9, 2.0), (0.0, 2.0)), may_close)

    assert asked["n"] == 1


def test_the_rule_is_not_asked_before_anybody_has_spoken() -> None:
    """A quiet room must not drive a transcriber."""
    asked = {"n": 0}

    def may_close() -> bool:
        asked["n"] += 1
        return False

    _run_with(_frames((0.0, 5.0)), may_close)

    assert asked["n"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd widget && PYTHONNOUSERSITE=1 ./.venv/bin/python -m pytest tests/test_vad.py -v`
Expected: FAIL — `TypeError: UtteranceDetector.__init__() got an unexpected keyword argument 'may_close'`

- [ ] **Step 3: Write minimal implementation**

In `widget/samantha_widget/vad.py`, add near `_SILENCE_SECONDS`:

```python
# How much quiet is enough to ASK whether the sentence is finished. The
# answer comes from `endpoint.py`, which has the words; this file only
# owns the clock.
#
# Measured 2026-09-01 on the user's own recording: every internal pause
# in it ran 0.26-0.61 s, so a trigger at 0.35 s fires INSIDE most
# mid-sentence breaths. That is the point — the silence is deliberately
# not the decision. If the rule cannot tell a breath from an ending,
# lowering this value alone re-creates the defect of 2026-08-26.
_ASK_SECONDS = float(os.environ.get("SAMANTHA_WIDGET_ASK_SILENCE", "0.35"))
```

Change `UtteranceDetector.__init__` and `push`:

```python
class UtteranceDetector:
    def __init__(
        self,
        probe: SpeechProbe,
        *,
        may_close: Callable[[], bool] = lambda: False,
    ) -> None:
        self._probe = probe
        # Asked once per pause, when the quiet crosses _ASK_SECONDS.
        # Defaults to "never", so a detector built the old way behaves
        # exactly as it did — which is what the existing tests assert.
        self._may_close = may_close
        self._asked = False
        self._buffer = bytearray()
        self._speech_run = 0
        self._silence_seconds = 0.0
        self._speech_seconds = 0.0
        self.speaking = False
```

Add `self._asked = False` to `reset()`.

In `push`, replace the tail of the speaking branch:

```python
        if len(self._buffer) / 2 / INPUT_RATE >= _MAX_UTTERANCE_SECONDS:
            return self._emit(force=True)
        if is_speech:
            # Talking again: the next pause gets its own question.
            self._asked = False
        elif not self._asked and self._silence_seconds >= _ASK_SECONDS:
            self._asked = True
            if self._may_close():
                return self._emit()
        if self._silence_seconds >= _SILENCE_SECONDS:
            return self._emit()
        return None
```

Add `Callable` to the `typing` import at the top of the file.

- [ ] **Step 4: Run the whole VAD suite**

Run: `cd widget && PYTHONNOUSERSITE=1 ./.venv/bin/python -m pytest tests/test_vad.py -v`
Expected: PASS, including every pre-existing test unchanged.

- [ ] **Step 5: Lint and commit**

```bash
cd widget && ./.venv/bin/ruff check . && ./.venv/bin/ruff format --check .
git add samantha_widget/vad.py tests/test_vad.py
git commit -m "feat(vad): a short trigger that asks, beside the long one that decides"
```

---

### Task 3: Vosk, and the silence it fails into

The model half. The only part that can fail at load, so the only part that needs a policy for failing.

**Files:**
- Modify: `widget/pyproject.toml`
- Create: `widget/samantha_widget/endpoint.py` (append to Task 1's file)
- Test: `widget/tests/test_endpoint.py` (append)
- Modify: `widget/README.md`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `VoskPartials(model_path: str | os.PathLike[str] | None = None)` carrying **two independent streams on one loaded model** — `.turn` and `.room` — each a `Stream` with `push(frame: bytes) -> None`, `partial() -> str`, `reset() -> None`. Plus `load_partials() -> VoskPartials | None`, which returns `None` rather than raising. Tasks 4 and 5 call `load_partials()` once and take one stream each.

**Why two streams and not one.** They are fed at opposite times and must
not see each other's audio:

- `.turn` is fed only while he is **silent** — it is the sentence being
  spoken to him, and the endpointing rule judges it. If his own echo
  leaked in, the rule would be reading his words as yours.
- `.room` is fed only while he is **speaking** — it is whatever the
  microphone hears over him, and `EchoFilter` decides whether it is him
  or a person.

One `Model` is loaded (39 MB); a second `KaldiRecognizer` on it is
cheap. Cost is ~10% of one core instead of ~5%, and never both at once
in practice.

- [ ] **Step 1: Install the dependency and the model**

```bash
cd widget
./.venv/bin/pip install --ignore-installed 'vosk>=0.3.45'
mkdir -p ~/.samantha/models
curl -sL -o /tmp/vosk-es.zip \
  https://alphacephei.com/vosk/models/vosk-model-small-es-0.42.zip
unzip -q -d ~/.samantha/models /tmp/vosk-es.zip
ls -d ~/.samantha/models/vosk-model-small-es-0.42
```

Verify the install actually happened — `--system-site-packages` makes a
plain `pip install` a silent no-op when something similar exists:

```bash
./.venv/bin/pip list --local | grep -i vosk
```

Add to `dependencies` in `widget/pyproject.toml`, after `faster-whisper`:

```toml
    # The second STT engine, and it never produces a word anybody reads:
    # its only job is deciding when you have stopped talking, and whether
    # a sound is his own echo. 39 MB, Apache 2.0, ~5% of one core.
    # CLAUDE.md §2.6 and the design of 2026-09-01 say why it is not
    # Whisper doing this.
    "vosk>=0.3.45",
```

- [ ] **Step 2: Write the failing test**

Append to `widget/tests/test_endpoint.py`. **The imports it needs are
already at the top of the file** — Task 1 put them there, because ruff has
E402 enabled (`pyproject.toml`) and a module-level import after a function
fails lint:

```python
def test_a_missing_model_is_reported_not_raised(tmp_path, monkeypatch) -> None:
    """Failure here must cost the FEATURE, never the widget.

    2026-08-30 is the precedent: a model that would not fit left Whisper
    unable to load, the exception was caught and printed, and JARVIS was
    deaf for three days looking perfectly healthy. A thing whose whole
    purpose is making him faster must not be able to make him worse.
    """
    monkeypatch.setenv("SAMANTHA_WIDGET_VOSK_MODEL", str(tmp_path / "nope"))

    assert load_partials() is None


def test_the_model_path_can_be_overridden(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SAMANTHA_WIDGET_VOSK_MODEL", str(tmp_path / "nope"))
    with pytest.raises(FileNotFoundError):
        VoskPartials()


@pytest.mark.skipif(
    not (Path.home() / ".samantha/models/vosk-model-small-es-0.42").is_dir(),
    reason="the Vosk model is not installed on this box",
)
def test_silence_transcribes_to_nothing() -> None:
    """The one test that needs the model. Silence in, nothing out —
    enough to prove the wiring without shipping any audio."""
    partials = VoskPartials()
    for _ in range(30):
        partials.turn.push(b"\x00\x00" * 512)

    assert partials.turn.partial() == ""


@pytest.mark.skipif(
    not (Path.home() / ".samantha/models/vosk-model-small-es-0.42").is_dir(),
    reason="the Vosk model is not installed on this box",
)
def test_the_two_streams_do_not_hear_each_other() -> None:
    """The property the whole split exists for: audio fed to one stream
    must not appear in the other's partial. Without it his echo lands in
    the sentence being judged for endpointing."""
    partials = VoskPartials()
    for _ in range(30):
        partials.room.push(b"\x00\x00" * 512)

    assert partials.turn.partial() == ""
    assert partials.turn is not partials.room
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd widget && PYTHONNOUSERSITE=1 ./.venv/bin/python -m pytest tests/test_endpoint.py -v`
Expected: FAIL — `ImportError: cannot import name 'VoskPartials'`

- [ ] **Step 4: Write minimal implementation**

Append to `widget/samantha_widget/endpoint.py`:

```python
import json
import os
import sys
from pathlib import Path

DEFAULT_MODEL_PATH = (
    Path.home() / ".samantha" / "models" / "vosk-model-small-es-0.42"
)


class VoskPartials:
    """The room, transcribed as it arrives, for nobody to read.

    Vosk rather than Whisper because this text is never shown, never
    spoken and never sent — and because it is better at THIS job for the
    reason it is worse at the other one (see the module docstring). It
    costs ~5% of one core and 39 MB on disk.
    """

    def __init__(self, model_path: str | os.PathLike[str] | None = None) -> None:
        from vosk import KaldiRecognizer, Model, SetLogLevel

        path = Path(
            model_path
            or os.getenv("SAMANTHA_WIDGET_VOSK_MODEL")
            or DEFAULT_MODEL_PATH
        )
        if not path.is_dir():
            raise FileNotFoundError(
                f"Vosk model not at {path} — see widget/README.md"
            )
        SetLogLevel(-1)  # it prints a page of Kaldi banner otherwise
        self._model = Model(str(path))
        self._recognizer = KaldiRecognizer(self._model, INPUT_RATE)
        self._settled = ""

    def push(self, frame: bytes) -> None:
        """One 16 kHz mono int16 frame. Same frames the VAD sees."""
        if self._recognizer.AcceptWaveform(frame):
            done = json.loads(self._recognizer.Result())["text"]
            self._settled = f"{self._settled} {done}".strip()

    def partial(self) -> str:
        """Everything heard since the last reset, settled and in flight."""
        flying = json.loads(self._recognizer.PartialResult())["partial"]
        return f"{self._settled} {flying}".strip()

    def reset(self) -> None:
        """A turn ended. Forget it, or the next one inherits its words."""
        from vosk import KaldiRecognizer

        self._recognizer = KaldiRecognizer(self._model, INPUT_RATE)
        self._settled = ""


def load_partials() -> VoskPartials | None:
    """`VoskPartials`, or None with one line of explanation.

    None is not an error: it means the endpointing and the text-based
    barge-in are off and he behaves exactly as he did before this
    existed. Every caller must be written so that is true.
    """
    try:
        return VoskPartials()
    except Exception as exc:  # noqa: BLE001 — any failure means "off"
        print(
            f"endpointing apagado, Vosk no cargó: {exc!r}",
            file=sys.stderr,
            flush=True,
        )
        return None
```

Add at the top of the file, beside the other imports:

```python
from .vad import INPUT_RATE
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd widget && PYTHONNOUSERSITE=1 ./.venv/bin/python -m pytest tests/test_endpoint.py -v`
Expected: PASS.

- [ ] **Step 6: Document the model in the widget README**

Add a row to the environment-switch table in `widget/README.md`:

```markdown
| `SAMANTHA_WIDGET_VOSK_MODEL` | Where the Vosk model lives (default `~/.samantha/models/vosk-model-small-es-0.42`). This is the second STT engine, and it never produces a word anybody reads — it decides when you have stopped talking and whether a sound is his own echo. **Absent, everything still works**: he falls back to waiting the full 1.2 s of silence, and the log says so once. |
| `SAMANTHA_WIDGET_ASK_SILENCE` | Seconds of quiet after which he asks himself whether your sentence is finished (default 0.35). The 1.2 s of `SAMANTHA_WIDGET_SILENCE` remains the floor: this only ever closes a turn EARLIER, never later. |
```

And, in the setup section beside the Silero model:

```bash
# The endpointing model — 39 MB, Apache 2.0. Optional: without it he
# waits the full 1.2 s, exactly as he did before 2026-09-01.
mkdir -p ~/.samantha/models
curl -sL -o /tmp/vosk-es.zip \
  https://alphacephei.com/vosk/models/vosk-model-small-es-0.42.zip
unzip -q -d ~/.samantha/models /tmp/vosk-es.zip
```

- [ ] **Step 7: Lint and commit**

```bash
cd widget && ./.venv/bin/ruff check . && ./.venv/bin/ruff format --check .
git add samantha_widget/endpoint.py tests/test_endpoint.py pyproject.toml README.md
git commit -m "feat(stt): Vosk hears the room, and failing to load costs only speed"
```

---

### Task 4: Wiring — he answers 880 ms sooner

**Files:**
- Modify: `widget/samantha_widget/__main__.py`
- Test: `widget/tests/test_main.py`

**Interfaces:**
- Consumes: `CompletionRule` (Task 1), `UtteranceDetector(..., may_close=...)` (Task 2), `load_partials()` (Task 3).
- Produces: nothing later tasks import. Task 5 modifies the same audio callback.

- [ ] **Step 1: Write the failing test**

Append to `widget/tests/test_main.py`:

```python
def test_endpointing_is_wired_only_when_the_model_loaded(monkeypatch) -> None:
    """The two states this must have, and no third one.

    With a model: the detector is asked. Without: it is not, and nothing
    anywhere raises — which is the property that keeps a missing 39 MB
    file from costing a voice turn.
    """
    from samantha_widget.__main__ import build_may_close
    from samantha_widget.endpoint import CompletionRule

    assert build_may_close(None, CompletionRule())() is False

    class FakeStream:
        def __init__(self, text: str) -> None:
            self.text = text

        def partial(self) -> str:
            return self.text

    assert build_may_close(FakeStream("enciendeme la luz del salon"),
                           CompletionRule())() is True
    assert build_may_close(FakeStream("enciendeme la luz del"),
                           CompletionRule())() is False


def test_a_broken_partials_object_never_closes_a_turn() -> None:
    """Vosk throwing mid-turn must not end somebody's sentence."""
    from samantha_widget.__main__ import build_may_close
    from samantha_widget.endpoint import CompletionRule

    class Exploding:
        def partial(self) -> str:
            raise RuntimeError("boom")

    assert build_may_close(Exploding(), CompletionRule())() is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd widget && PYTHONNOUSERSITE=1 ./.venv/bin/python -m pytest tests/test_main.py -v`
Expected: FAIL — `ImportError: cannot import name 'build_may_close'`

- [ ] **Step 3: Write minimal implementation**

Add to `widget/samantha_widget/__main__.py`, at module level beside the other helpers:

```python
def build_may_close(stream, rule):
    """The question `vad.py` asks at 0.35 s of quiet.

    `stream` is the `.turn` stream, or None when Vosk did not load.
    Answers False for every reason a question can go wrong — no model, a
    raising engine, nothing heard yet — because False is exactly today's
    behaviour and the 1.2 s threshold is still underneath it.
    """

    def may_close() -> bool:
        if stream is None:
            return False
        try:
            return rule.looks_complete(stream.partial())
        except Exception as exc:  # noqa: BLE001
            print(f"endpointing falló: {exc!r}", file=sys.stderr, flush=True)
            return False

    return may_close
```

In the async setup where `detector` is built, replace its construction:

```python
        from .endpoint import CompletionRule, load_partials

        partials = load_partials()
        rule = CompletionRule()
        print(
            "endpointing: activo" if partials else "endpointing: apagado",
            file=sys.stderr,
            flush=True,
        )
        detector = UtteranceDetector(
            probe,
            may_close=build_may_close(
                partials.turn if partials else None, rule
            ),
        )
```

In the audio callback, feed the `.turn` stream the same frames the
detector sees. Put this immediately BEFORE
`utterance = detector.push(frame)`:

```python
            if partials is not None:
                # The same frames the detector is holding, so the rule is
                # asked about exactly that audio. Fed even before the
                # detector calls it speech: the preroll matters here for
                # the same reason it matters for the wake word (§2.8).
                #
                # Only reached when he is NOT speaking — the barge-in
                # branch above returns early while `player.busy`, and
                # that is deliberate: his own echo must never enter the
                # sentence the endpointing rule is judging. What listens
                # over him is `.room`, fed in Task 5.
                partials.turn.push(frame)
```

And immediately AFTER an utterance is emitted, so the next turn does not
inherit this one's words:

```python
            if utterance is not None and partials is not None:
                partials.turn.reset()
```

- [ ] **Step 4: Run the whole suite**

Run: `cd widget && PYTHONNOUSERSITE=1 ./.venv/bin/python -m pytest -v`
Expected: PASS — all of it, not just the new file.

- [ ] **Step 5: Verify against a real voice**

This is the only step that cannot be a test. The strip must be exercised
by a person:

```bash
systemctl --user restart samantha-widget.service
journalctl --user -u samantha-widget.service -f
```

Say something to him with a deliberate pause in the middle — "enciéndeme
la luz del… salón". Expected in the journal: **one** `oído:` line, not
two, and a visibly shorter wait before the wave leaves `listening` than
before this change. If a sentence arrives split in two, the rule is
cutting people off: raise `SAMANTHA_WIDGET_ASK_SILENCE` and report the
partial that did it — that is a word-list bug, and the phrase belongs in
`test_endpoint.py`.

- [ ] **Step 6: Lint and commit**

```bash
cd widget && ./.venv/bin/ruff check . && ./.venv/bin/ruff format --check .
git add samantha_widget/__main__.py tests/test_main.py
git commit -m "feat(widget): he stops waiting for a pause he can already read"
```

---

### Task 5: Interrupting him, decided by words instead of loudness

The bug the user reported on 2026-09-01: "no se calla, sigue hablando."

**Files:**
- Modify: `widget/samantha_widget/__main__.py:74-97` (the `_BARGE_RMS` block) and the audio callback
- Test: `widget/tests/test_main.py`

**Interfaces:**
- Consumes: `EchoFilter.clean(heard: str, now: float) -> str` — existing, unchanged; it returns `""` when everything it was given was his own recent speech. `VoskPartials.partial()` from Task 3.
- Produces: `build_is_a_person(stream, echo) -> Callable[[float], bool]`, where `stream` is `VoskPartials.room` or None.

- [ ] **Step 1: Write the failing test**

Append to `widget/tests/test_main.py`:

```python
def test_his_own_words_coming_back_are_not_an_interruption() -> None:
    """The measurement this replaces, from CLAUDE.md §2.8:

        the user's voice          RMS 0.054-0.088
        his echo, speakers away   RMS 0.027-0.035
        his echo, speakers beside RMS 0.178   ← louder than the person

    A single scalar cannot separate the last row from the first, and the
    file said so in its own comment. The widget knows what it just said,
    so this is decided on words instead: `EchoFilter` already returns ""
    when everything it was handed was his.
    """
    from samantha_widget.__main__ import build_is_a_person
    from samantha_widget.echo import EchoFilter

    echo = EchoFilter()
    echo.spoke("Buenas tardes, señor. Le cuento algo un poco más largo.", 100.0)

    class HisEcho:
        def partial(self) -> str:
            return "buenas tardes senor le cuento algo un poco mas largo"

    assert build_is_a_person(HisEcho(), echo)(101.0) is False


def test_somebody_talking_over_him_is_an_interruption() -> None:
    from samantha_widget.__main__ import build_is_a_person
    from samantha_widget.echo import EchoFilter

    echo = EchoFilter()
    echo.spoke("Buenas tardes, señor. Le cuento algo un poco más largo.", 100.0)

    class APerson:
        def partial(self) -> str:
            return "para jarvis no me interesa eso ahora mismo"

    assert build_is_a_person(APerson(), echo)(101.0) is True


def test_with_no_partials_everything_is_a_person() -> None:
    """No Vosk means falling back to the old world, where the RMS floor
    is the only gate. Refusing to interrupt would be worse than
    interrupting too easily: it is the bug being fixed."""
    from samantha_widget.__main__ import build_is_a_person
    from samantha_widget.echo import EchoFilter

    assert build_is_a_person(None, EchoFilter())(1.0) is True


def test_nothing_heard_yet_is_not_a_person() -> None:
    """Vosk has no words yet. Not an interruption, and not an error."""
    from samantha_widget.__main__ import build_is_a_person
    from samantha_widget.echo import EchoFilter

    class Nothing:
        def partial(self) -> str:
            return ""

    assert build_is_a_person(Nothing(), EchoFilter())(1.0) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd widget && PYTHONNOUSERSITE=1 ./.venv/bin/python -m pytest tests/test_main.py -v`
Expected: FAIL — `ImportError: cannot import name 'build_is_a_person'`

- [ ] **Step 3: Write minimal implementation**

Add beside `build_may_close` in `widget/samantha_widget/__main__.py`:

```python
def build_is_a_person(stream, echo):
    """While HE is talking: is this sound somebody else, or his own echo?

    `stream` is `VoskPartials.room` — the one fed ONLY while he speaks —
    or None when Vosk did not load.

    Before 2026-09-01 this was a loudness threshold, and it could not
    work. The user's voice measures RMS 0.054-0.088; his own echo with
    the speakers beside the microphone measures 0.178 — LOUDER than the
    person — so no threshold separates them, and with the speakers moved
    away a person cleared the gate by 0.004. Speaking normally instead of
    loudly was enough to stop existing, which is exactly what was
    reported: "no se calla, sigue hablando".

    Words settle it where volume cannot, using the unfair advantage
    `echo.py` already has: the widget knows what it just said. Anything
    left after his own lines are cut out is somebody else.

    Cost, stated: ~300 ms of speech must reach Vosk before there are
    words to judge, against the 32 ms of a single frame. He talks a
    little longer over an interruption than the old gate did in the
    cases where the old gate worked at all.
    """

    def is_a_person(now: float) -> bool:
        if stream is None:
            # No Vosk: back to the old world, where the RMS floor is the
            # only gate. Erring towards interrupting, because refusing to
            # is the bug this replaces.
            return True
        try:
            heard = stream.partial()
        except Exception:  # noqa: BLE001
            return True
        if not heard.strip():
            return False
        return bool(echo.clean(heard, now).strip())

    return is_a_person
```

Change the `_BARGE_RMS` default and its comment:

```python
# How loud the room has to be, WHILE he is speaking, before a frame may
# start a turn.
#
# Until 2026-09-01 this was 0.05 and was asked to separate his own echo
# from a person, which the measurements below show it cannot do:
#
#   the user's voice                            0.054-0.088
#   his echo, speakers moved away, volume 0.50  0.027-0.035
#   his echo, speakers beside it, volume 0.54   0.178  ← louder than a
#       person, and no threshold survives that
#
# It is now a SILENCE floor and nothing more — separating sound from no
# sound, which any scalar can do. Whether a sound is him or somebody
# else is decided on words, in `build_is_a_person`.
try:
    _BARGE_RMS = float(os.environ.get("SAMANTHA_WIDGET_BARGE_RMS", "0.01"))
except ValueError:
    _BARGE_RMS = 0.01
```

Replace the barge-in branch in the audio callback. **The order matters
and is the thing to get right**: `.room` must be fed BEFORE any early
return, or it never hears the interruption it is supposed to judge and
`is_a_person` answers False forever — which is the bug being fixed,
reintroduced from the other side.

```python
            if player.busy and not detector.speaking:
                # He is talking and nobody has cut in yet. Feed `.room`
                # FIRST: every path below can return, and a stream that
                # is only fed after the gates never hears the sentence
                # the gates are asking about.
                if partials is not None:
                    partials.room.push(frame)

                import numpy as _np

                _s = _np.frombuffer(frame, dtype=_np.int16).astype(_np.float32)
                _rms = float(_np.sqrt(_np.mean((_s / 32768.0) ** 2)))
                if _BARGE_RMS > 0 and _rms < _BARGE_RMS:
                    # Silence. Not him, not anybody.
                    return
                if not is_a_person(time.monotonic()):
                    # Loud enough, but the words are his own coming back
                    # through the room. Dropped rather than fed to the
                    # detector, which would start a turn and interrupt
                    # him mid-sentence — reported once as "ahora se
                    # autointerrumpe".
                    return
```

And `.room` has to be emptied between his answers, or the echo of the
last one is still sitting there when he starts the next. **On the
TRANSITION, not on every quiet frame** — `reset()` builds a new
`KaldiRecognizer`, and doing that per frame is ~31 model objects a second.
Add a flag beside the other callback state:

```python
            elif partials is not None and _busy["was"]:
                # He just stopped. Whatever `.room` collected was his; the
                # next answer starts from nothing. Guarded by the flag
                # because reset() constructs a recognizer and this branch
                # is reached on every quiet frame.
                partials.room.reset()
            _busy["was"] = player.busy
```

Declare `_busy` next to `_trace` at module level:

```python
# Whether he was speaking on the previous frame, so `.room` can be reset
# once when he stops rather than thirty-one times a second.
_busy = {"was": False}
```

Build the closure next to the detector:

```python
        is_a_person = build_is_a_person(
            partials.room if partials else None, echo
        )
```

`echo` is constructed a few lines below this point in the current file;
move `echo = EchoFilter()` above it.

- [ ] **Step 4: Run the whole suite**

Run: `cd widget && PYTHONNOUSERSITE=1 ./.venv/bin/python -m pytest -v`
Expected: PASS.

- [ ] **Step 5: Verify against a real voice**

Ask him something with a long answer, then talk over him halfway through.

```bash
systemctl --user restart samantha-widget.service
journalctl --user -u samantha-widget.service -f
```

Expected: he stops, and the journal shows a new `oído:` line carrying
YOUR sentence and not his. Two failure modes to watch for, and they have
opposite fixes:

- **He still will not stop** → Vosk is not hearing you at all. Check the
  `endpointing: activo` line is present at startup.
- **He interrupts himself with nobody in the room** → his echo is
  surviving `EchoFilter`. Raise `SAMANTHA_WIDGET_BARGE_RMS` back towards
  0.03 and report the partial from the journal.

- [ ] **Step 6: Lint and commit**

```bash
cd widget && ./.venv/bin/ruff check . && ./.venv/bin/ruff format --check .
git add samantha_widget/__main__.py tests/test_main.py
git commit -m "fix(widget): he could not be interrupted, and loudness could never fix it"
```

---

### Task 6: The documents that decide what the next person believes

**Files:**
- Modify: `CLAUDE.md` (§0, §2.6, §2.8, §9, §12)
- Modify: `PROGRESS.md`

- [ ] **Step 1: CLAUDE.md §2.6 — the second engine**

Under **STT**, after the faster-whisper line, add:

```markdown
- **Endpointing:** Vosk `small-es` (39 MB, Apache 2.0, CPU, ~5% of one
  core) transcribes continuously and its text reaches nobody. It decides
  two things: when you have finished a sentence — 880 ms sooner than the
  1.2 s of silence, measured — and whether a sound while he speaks is a
  person or his own echo. **Whisper is deliberately not doing this job**:
  measured 2026-09-01, the best transcriber is the worst endpointer,
  because it completes the sentence it heard instead of leaving it
  hanging where the speaker did.
```

- [ ] **Step 2: CLAUDE.md §2.8 — barge-in is decided on words**

Replace the sentence describing the microphone gate with:

```markdown
- **He can be interrupted, and it is decided on words rather than
  volume** (2026-09-01). `SAMANTHA_WIDGET_BARGE_RMS` survives as a
  silence floor (0.01); whether a sound is a person or his own echo is
  `EchoFilter` run against Vosk's live partial. The threshold it
  replaces could not work: the user's voice measures RMS 0.054-0.088 and
  his echo with the speakers beside the microphone measures 0.178 —
  louder than the person.
```

- [ ] **Step 3: CLAUDE.md §9 — the file table**

Add two rows:

```markdown
| Deciding you have finished (rule / model) | `widget/samantha_widget/endpoint.py` |
| The clock that asks, and the one that decides | `widget/samantha_widget/vad.py` |
```

- [ ] **Step 4: CLAUDE.md §12 — the decision**

Insert this at the TOP of the Decision Log, above
"### 2026-09-01 — He gets no face":

```markdown
### 2026-09-01 — The engine that cannot punctuate gets the job

**Decision:** a second STT engine — Vosk `small-es`, 39 MB, Apache 2.0,
on the CPU — decides when somebody has finished speaking and whether a
sound over him is a person or his own echo. Its text is never shown,
spoken or sent. **faster-whisper is unchanged** and still produces every
word Hermes sees.

**The request was "an alternative to Whisper", and the first measurement
retired it.** After you stop talking he waits 1.2 s of silence against
61-135 ms of transcription, so the engine was never what made him slow.
A faster engine buys nothing; what buys something is not waiting.

**A single engine turned out to be impossible, and not for any of the
reasons the search suggested.** With Moonshine transcribing, JARVIS
would not have answered either real sentence in which the user says his
name — it came back as «ya luis» and «yardi», and `wake.py`'s 0.6 ratio
rejects both. Vosk salvages one of two, by luck. Only Whisper with its
`initial_prompt` gets both, and being ignored is the one failure a wake
word cannot afford.

**The finding that decided the architecture inverts the obvious answer.**
At the user's mid-sentence pause Whisper wrote «…habrá que comprobar que
estén encendidas y con red.» — clean, punctuated, finished — and closing
there cut him off; he went on to say something else entirely. Vosk, at
the same instant, wrote «…que estén encendidas y» and waited. **Whisper
completes the sentence it heard; Vosk leaves it hanging where the
speaker left it.** Over the recording: Vosk 2 good closes and 0 cuts,
Moonshine 1 and 1, Whisper 0 and 2. The best transcriber is the worst
endpointer, for precisely the reason it is the best, so the split is
architectural rather than a saving.

**It also fixes being unable to interrupt him**, reported the same day.
The barge-in gate was a loudness threshold and could not work: the
user's voice measures RMS 0.054-0.088 and his echo with the speakers
beside the microphone measures 0.178 — louder than the person. It is now
a silence floor, and `EchoFilter` decides on words against Vosk's live
partial. Amends §2.8.

**Two things measured that correct what was believed here:** Moonshine
DOES have biasing (`set_keyterms`, better designed than `initial_prompt`)
— and with "Jarvis" in the list the transcription came back identical
character for character. And **sherpa-onnx**, which has exactly the
hotwords this project wanted and is Apache 2.0 on the ONNX runtime
already in the tree, **has no Spanish streaming model at all**.

**Costs, stated:** a second STT engine in the widget's dependency tree;
a new class of bug — the premature cut — which measured zero on a sample
of one long recording plus four August clips and is bounded, not
prevented, by the 1.2 s floor; a hand-written Spanish word list that is
the whole of the rule and generalises to nothing; and ~300 ms slower to
react to an interruption than a 32 ms frame.
```

- [ ] **Step 5: PROGRESS.md**

Add an entry dated 2026-09-01 at the top, in Spanish, following the
existing style: what was measured, what it cost, and what is still
unproven. It MUST record that the sample was one long recording plus
four August clips, and that the premature cut measured zero on that
sample rather than being impossible.

- [ ] **Step 6: Full verification and commit**

```bash
cd widget && PYTHONNOUSERSITE=1 ./.venv/bin/python -m pytest -v
./.venv/bin/ruff check . && ./.venv/bin/ruff format --check .
cd .. && git add -A
git commit -m "docs(stt): why the engine that cannot punctuate got the job"
```

---

## What this plan deliberately does not do

- **Replace Whisper.** Measured and rejected in the spec; §2.6 stands.
- **Speculative dispatch** — sending a partial to the gateway before the
  turn closes. Same second, different route; the alternative if the rule
  proves too blunt.
- **Drop speech not addressed to him using the partial.** Real saving,
  but it moves the "not for me" decision onto the worse text.
- **Show the partial on the strip.** §1.3, and a separate question.
