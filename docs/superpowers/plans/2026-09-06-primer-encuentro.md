# The first encounter — implementation plan (part A: the amo exists)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A box that boots with no memory waits, shows a passphrase, and pairs by voice with the person who speaks it — and from then on knows that voice when it hears it.

**Architecture:** A speaker-embedding model on the `onnxruntime` already present for Silero produces a vector per utterance; a pure module decides who that is by cosine distance against stored centroids, degrading to `casa` below a floor. A passphrase generated once per installation gates the founding act. The first encounter is the project's first conversational FLOW — ask, listen, confirm, retry — and it is written as a pure state machine so it can be tested without a microphone.

**Tech Stack:** Python 3.12, onnxruntime, numpy, pytest, ruff. One new model file. No torch, ever.

**Spec:** `docs/superpowers/specs/2026-09-06-primer-encuentro-design.md`

## Scope: part A of two

**This plan delivers one thing: the box knows whose it is.** Pairing, storing that voice, and recognising it afterwards.

**Part B — the family — is deliberately not here**: introductions ("esta es Natalia"), `"soy Natalia"` from a phone, and how he treats a voice he does not know. All of it depends on this plan AND on task 4's measurement. If two sisters of 16 and 17 do not separate, part A still works — one voice against nobody is the easy case — and part B falls back to phones, which the spec names as a supported outcome rather than a failure.

## Global Constraints

- **Spanish for anything a person reads or hears; English for code, comments and commit messages** (CLAUDE.md §2.9, §6). This plan has more user-facing Spanish than any before it: he speaks during the first encounter.
- **`ruff format` and `ruff check` must pass.** Type hints mandatory on public functions.
- **`PYTHONNOUSERSITE=1` on every invocation.** A venv with `--system-site-packages` also sees `~/.local/lib`.
- **Widget tests:** `cd widget && PYTHONNOUSERSITE=1 .venv/bin/python -m pytest -v`
- **No test touches the network, the GPU, a display or a microphone.** Anything needing those is a tool under `widget/tools/`, run by hand, whose output is written into a document.
- **No torch.** `onnxruntime` is already a dependency for Silero; the embedder rides on it. A model that requires torch is a model this plan does not use.
- **Nothing raises out of the audio thread or `_boot`.** Task 3 of the identity plan spent three fix rounds learning this: check a node's kind by `stat` before opening it, because a FIFO does not raise, it blocks, and no `except` catches a hang.
- **A failure degrades to `casa`, never to another person, and NEVER to the amo.** This is the rule the whole design rests on.

---

### Task 1: The probe — is there a model we can actually use?

**Files:**
- Create: `widget/tools/probe_locutor.py`
- Create: `docs/superpowers/specs/2026-09-06-probe-locutor.md`

**Interfaces:**
- Consumes: nothing.
- Produces: a written finding, and either a model file on disk or a plain "no".

Everything waits on this. The spec names candidates — WeSpeaker / 3D-Speaker **CAM++**, or **ECAPA-TDNN** — and marks as **unverified** that an ONNX export exists under a licence this house can use. If none does, stop and report: the amo pairing has no mechanism and the whole design needs another one.

- [ ] **Step 1: Find the candidates and their licences**

Search for ONNX exports of CAM++ and ECAPA-TDNN. For each, record: where it is published, the licence, the file size, the expected input (sample rate, mono, length) and the output dimensionality. **A licence that forbids use in a private household, or that cannot be determined, disqualifies the model** — say so rather than assuming.

- [ ] **Step 2: Write the probe**

```python
"""Does a speaker-embedding model run on this box, on onnxruntime alone?

Run by hand:

    PYTHONNOUSERSITE=1 widget/.venv/bin/python widget/tools/probe_locutor.py <model.onnx>

Answers four questions and prints what it saw: does onnxruntime load it,
what shape does it want, what shape does it return, and how long does one
utterance take on the CPU. Nothing is written and no microphone is opened.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import onnxruntime as ort


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("uso: probe_locutor.py <model.onnx>", file=sys.stderr)
        return 2
    ruta = Path(argv[1])
    if not ruta.is_file():
        print(f"no existe: {ruta}", file=sys.stderr)
        return 2

    print(f"modelo: {ruta} ({ruta.stat().st_size / 1e6:.1f} MB)")
    sesion = ort.InferenceSession(str(ruta), providers=["CPUExecutionProvider"])

    for entrada in sesion.get_inputs():
        print(f"  entrada: {entrada.name} {entrada.shape} {entrada.type}")
    for salida in sesion.get_outputs():
        print(f"  salida:  {salida.name} {salida.shape} {salida.type}")

    # Three seconds of 16 kHz silence is enough to learn the shapes and
    # the cost. It is NOT enough to say anything about accuracy — that is
    # task 4, and it needs real voices.
    muestras = np.zeros((1, 16000 * 3), dtype=np.float32)
    nombre = sesion.get_inputs()[0].name
    empezado = time.monotonic()
    salida = sesion.run(None, {nombre: muestras})[0]
    tardado = time.monotonic() - empezado
    print(f"  embedding: {np.asarray(salida).shape} en {tardado * 1000:.0f} ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
```

- [ ] **Step 3: Run it against each candidate**

Run: `PYTHONNOUSERSITE=1 widget/.venv/bin/python widget/tools/probe_locutor.py ~/.jarvis/models/<candidate>.onnx`

Expected: shapes printed, no exception. A model that needs an input this probe cannot construct (a feature matrix rather than raw audio) is not disqualified — it means a front end is needed, and that is a cost to record.

- [ ] **Step 4: Write the finding**

`docs/superpowers/specs/2026-09-06-probe-locutor.md`: the model chosen, its licence quoted, its size, its input contract (raw audio or features — and if features, what computes them and at what cost), its output dimension, the measured CPU time for a 3-second utterance, and a plain verdict. If nothing qualifies, say so and stop.

- [ ] **Step 5: Commit**

```bash
git add widget/tools/probe_locutor.py docs/superpowers/specs/2026-09-06-probe-locutor.md
git commit -m "probe: a speaker-embedding model that runs on onnxruntime alone"
```

---

### Task 2: `voz.py` — deciding who spoke, as arithmetic

**Files:**
- Create: `widget/jarvis_widget/voz.py`
- Test: `widget/tests/test_voz.py`

**Interfaces:**
- Consumes: `personas.CASA`.
- Produces: `coseno(a, b) -> float`, `Huellas` (a mapping of person id to centroid), `Huellas.quien(vector, floor) -> str`, `PISO_POR_DEFECTO: float`.

Pure: it takes vectors, never audio, never a model, never a file. The shape `wave_model.py` and `bars_model.py` already have, and the reason this is worth insisting on — a probabilistic decision nobody can test is a probabilistic decision nobody can trust.

- [ ] **Step 1: Write the failing test**

```python
import numpy as np

from jarvis_widget.personas import CASA
from jarvis_widget.voz import PISO_POR_DEFECTO, Huellas, coseno


def _v(*xs: float) -> np.ndarray:
    return np.array(xs, dtype=np.float32)


def test_cosine_is_one_for_the_same_direction_and_zero_for_a_right_angle():
    assert coseno(_v(1, 0), _v(2, 0)) == 1.0
    assert coseno(_v(1, 0), _v(0, 1)) == 0.0


def test_a_zero_vector_is_similar_to_nothing_and_does_not_divide_by_zero():
    assert coseno(_v(0, 0), _v(1, 0)) == 0.0


def test_the_nearest_person_wins_when_it_clears_the_floor():
    huellas = Huellas({"papa": _v(1, 0), "marta": _v(0, 1)})
    assert huellas.quien(_v(0.9, 0.1), piso=0.5) == "papa"
    assert huellas.quien(_v(0.1, 0.9), piso=0.5) == "marta"


def test_below_the_floor_nobody_is_recognised():
    huellas = Huellas({"papa": _v(1, 0)})
    assert huellas.quien(_v(0, 1), piso=0.5) == CASA


def test_an_empty_store_recognises_nobody_rather_than_crashing():
    assert Huellas({}).quien(_v(1, 0), piso=0.5) == CASA


def test_two_people_too_close_together_is_reported_rather_than_guessed():
    # Sisters. If the best and the second-best are within `margen`, he
    # does not know which, and saying `casa` is the honest answer.
    huellas = Huellas({"marta": _v(1, 0.02), "lucia": _v(1, 0.0)})
    assert huellas.quien(_v(1, 0.01), piso=0.5, margen=0.05) == CASA


def test_the_default_floor_is_a_number_somebody_chose():
    assert 0.0 < PISO_POR_DEFECTO < 1.0
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `cd widget && PYTHONNOUSERSITE=1 .venv/bin/python -m pytest tests/test_voz.py -v`
Expected: FAIL, `ModuleNotFoundError`.

- [ ] **Step 3: Write the module**

```python
"""Who spoke, decided as arithmetic on vectors.

Pure: this module never sees audio, never loads a model and never opens
a file. It is handed embeddings and it answers with a person id, so the
one probabilistic decision in the system is the one thing here that can
be tested exhaustively without a microphone in the room.

Two floors, not one, and the second is the interesting one. `piso` is
how sure he must be at all; `margen` is how much clearer the best
answer must be than the second. Two sisters of the same age in the same
house are the case this project actually has, and for them the failure
is not "nobody is close" but "two people are equally close" — which the
first floor cannot see. Below either, the answer is `CASA`.

**A failure degrades to `CASA` and never to another person**, which is
what makes it safe to build the rest on.
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np

from .personas import CASA

# Where "sure enough" sits. Calibrated against real voices in task 4;
# until then it is a placeholder that fails safe by being high.
PISO_POR_DEFECTO = 0.6

# How much clearer the winner must be than the runner-up.
MARGEN_POR_DEFECTO = 0.05


def coseno(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity, and 0.0 rather than a division by zero.

    A silent or clipped utterance can produce a zero vector, and this is
    called from the audio path where an exception has nowhere to go.
    """
    na = float(np.linalg.norm(a))
    nb = float(np.linalg.norm(b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


class Huellas:
    """The stored centroids, and the question asked of them."""

    def __init__(self, centroides: Mapping[str, np.ndarray]) -> None:
        self._centroides = dict(centroides)

    def __len__(self) -> int:
        return len(self._centroides)

    def quien(
        self,
        vector: np.ndarray,
        *,
        piso: float = PISO_POR_DEFECTO,
        margen: float = MARGEN_POR_DEFECTO,
    ) -> str:
        """The person this voice belongs to, or `CASA`.

        `CASA` means "not attributable", which covers three different
        situations deliberately collapsed into one: nobody is enrolled,
        nobody is close enough, and two people are equally close. The
        caller must not be able to tell them apart, because acting
        differently on them is how a guess becomes an identity.
        """
        if not self._centroides:
            return CASA
        puntuados = sorted(
            ((coseno(vector, c), quien) for quien, c in self._centroides.items()),
            reverse=True,
        )
        mejor, quien = puntuados[0]
        if mejor < piso:
            return CASA
        if len(puntuados) > 1 and mejor - puntuados[1][0] < margen:
            return CASA
        return quien
```

- [ ] **Step 4: Run the tests**

Run: `cd widget && PYTHONNOUSERSITE=1 .venv/bin/python -m pytest tests/test_voz.py -v`
Expected: PASS, 7 tests.

- [ ] **Step 5: Format, lint and commit**

```bash
cd widget && .venv/bin/ruff format jarvis_widget/voz.py tests/test_voz.py && .venv/bin/ruff check .
cd .. && git add widget/jarvis_widget/voz.py widget/tests/test_voz.py
git commit -m "feat(widget): who spoke, as arithmetic on vectors"
```

---

### Task 3: The embedder — PCM in, a vector out

**Files:**
- Create: `widget/jarvis_widget/locutor.py`
- Test: `widget/tests/test_locutor.py`
- Modify: `widget/README.md`

**Interfaces:**
- Consumes: task 1's model and its input contract.
- Produces: `Locutor(model_path)` with `.listo -> bool` and `.vector(pcm: bytes) -> np.ndarray | None`; `ENV_MODELO = "JARVIS_WIDGET_LOCUTOR_MODEL"`.

The impure half, kept as thin as it can be so that everything worth testing lives in task 2.

- [ ] **Step 1: Write the failing test**

```python
import numpy as np

from jarvis_widget.locutor import Locutor


class FakeSesion:
    """Stands in for onnxruntime. The point of this test is the wrapper's
    behaviour around the model, not the model."""

    def __init__(self, salida=None, revienta=False):
        self._salida = salida if salida is not None else np.ones((1, 192), np.float32)
        self._revienta = revienta

    def get_inputs(self):
        class E:
            name = "feats"

        return [E()]

    def run(self, _outputs, _feed):
        if self._revienta:
            raise RuntimeError("el modelo ha explotado")
        return [self._salida]


def test_a_missing_model_is_not_ready_and_does_not_raise(tmp_path):
    locutor = Locutor(tmp_path / "no-existe.onnx")
    assert not locutor.listo
    assert locutor.vector(b"\x00\x00" * 16000) is None


def test_a_vector_comes_back_flat_and_float32():
    locutor = Locutor.para_pruebas(FakeSesion())
    v = locutor.vector(b"\x00\x00" * 16000)
    assert v is not None and v.ndim == 1 and v.dtype == np.float32


def test_a_model_that_raises_costs_the_utterance_and_nothing_else():
    # The audio thread calls this. An exception here would make him deaf
    # while looking perfectly healthy — the failure CLAUDE.md §2.8
    # records costing three days in August.
    locutor = Locutor.para_pruebas(FakeSesion(revienta=True))
    assert locutor.vector(b"\x00\x00" * 16000) is None
    assert locutor.vector(b"\x00\x00" * 16000) is None


def test_an_utterance_too_short_to_mean_anything_is_refused():
    locutor = Locutor.para_pruebas(FakeSesion())
    assert locutor.vector(b"\x00\x00" * 800) is None
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `cd widget && PYTHONNOUSERSITE=1 .venv/bin/python -m pytest tests/test_locutor.py -v`
Expected: FAIL, `ModuleNotFoundError`.

- [ ] **Step 3: Write the module**

Load the session lazily and never at import; refuse an utterance shorter than `_MINIMO_SEGUNDOS = 1.0`, because speaker identification below a second is guesswork and this project's typical utterance is short; convert `bytes` of int16 to the float32 the model wants; catch every exception from `run`, log **once** and return `None` thereafter for that utterance. Follow `vad.SileroDetector` for how a model is loaded and held in this codebase, and `stt.py` for how a failure is reported without killing the thread.

`para_pruebas(sesion)` is a classmethod that builds a `Locutor` around an already-made session, so the tests need no model file.

- [ ] **Step 4: Run the tests, and document the switch**

Run: `cd widget && PYTHONNOUSERSITE=1 .venv/bin/python -m pytest tests/test_locutor.py -v`
Expected: PASS.

Add `JARVIS_WIDGET_LOCUTOR_MODEL` to `widget/README.md` in the same style as its neighbours — CLAUDE.md §5 claims the README documents every switch, and an undocumented one makes that claim false.

- [ ] **Step 5: Commit**

```bash
cd widget && .venv/bin/ruff format . && .venv/bin/ruff check .
cd .. && git add widget/jarvis_widget/locutor.py widget/tests/test_locutor.py widget/README.md
git commit -m "feat(widget): an utterance becomes a vector, or nothing at all"
```

---

### Task 4: The measurements — is it him, and are they two?

**Files:**
- Create: `widget/tools/medir_voces.py`
- Create: `docs/superpowers/specs/2026-09-06-medicion-voces.md`

**Interfaces:**
- Consumes: tasks 2 and 3.
- Produces: a number, and a decision about part B.

**This is TWO measurements with two different requirements, and separating them is what lets part A finish without waiting for anybody** (the user's own observation, 2026-09-06):

- **4a — the amo, and it needs only him.** Does his voice get recognised as his, reliably, across a day: different distances, a cold, the television on, a shout, a whisper? One voice against nobody is the easy case, and this is the half that gates the founding act. **It can be done today, by one person, without arranging anything.**
- **4b — sister against sister, and it needs both of them present.** Same age, same sex, same house, same accent: the hard case. It gates part B and nothing else.

Do 4a first and do not let 4b hold part A up. If 4b eventually fails, part A still works and the family half falls back to phones — which the spec names a supported outcome rather than a failure.

- [ ] **Step 1: Write the tool**

It records N utterances per person (prompting in Spanish, one person at a time), embeds each with `Locutor`, and prints: the centroid-to-centroid cosine between every pair of people, the within-person spread, and — the number that matters — **how many utterances would be attributed to the wrong person** at a range of floors. It writes the raw vectors to `~/.jarvis/medicion/` so the calculation can be redone without gathering everyone again.

- [ ] **Step 2a: Run it with the amo alone — this is the one that unblocks part A**

Ten short utterances of the length he will actually hear — *"Jarvis, ¿qué hora es?"*, not a paragraph. **Measure what the system will meet, not what flatters it.** Then ten more under the conditions it will actually meet: from across the room, with the television on, tired, and one whispered. What matters here is not telling him from somebody else — there is nobody else yet — but that the same person clears the floor consistently. A floor he fails in his own living room is a floor that will refuse him at the founding act.

- [ ] **Step 2b: Run it with both sisters, when both are available**

Ten each, same conditions. This gates part B only. If it cannot be scheduled, record that and move on — part A does not wait for it.

- [ ] **Step 3: Write the finding**

`docs/superpowers/specs/2026-09-06-medicion-voces.md`: the pairwise distances, the confusion count at each floor, the floor chosen and why, and a verdict on part B. Update `voz.PISO_POR_DEFECTO` and `MARGEN_POR_DEFECTO` to the measured values in the same commit — the placeholders exist to be replaced.

- [ ] **Step 4: Commit**

```bash
git add widget/tools/medir_voces.py docs/superpowers/specs/2026-09-06-medicion-voces.md widget/jarvis_widget/voz.py
git commit -m "measure: whether two sisters separate, and where the floor goes"
```

---

### Task 5: The house register — people on disk

**Files:**
- Create: `widget/jarvis_widget/casa.py`
- Test: `widget/tests/test_casa.py`

**Interfaces:**
- Consumes: `personas.normalizar`, `voz.Huellas`.
- Produces: `Registro(path)` with `.amo -> str | None`, `.personas() -> list[Persona]`, `.huellas() -> Huellas`, `.emparejar(nombre, vectores) -> Persona`, `.recordar(persona_id, vector)`; `Persona` as a frozen dataclass of `id`, `nombre`, `amo`.

**Three files, three sensitivities, and they stay apart.** `~/.jarvis/personas.json` holds phone SECRETS (built in the identity plan). This one is `~/.jarvis/casa.json` — who exists, what they are called, who is the amo — and the voiceprints are `.npy` files under `~/.jarvis/voces/`. Vectors are not secrets and names are not credentials; putting them in one file would mean one leak spills all three.

- [ ] **Step 1: Write the failing tests**

Cover: a missing register has no amo and no people; pairing writes an amo and it survives a reload; **a second `emparejar` when an amo already exists raises rather than replacing one** (the founding act happens once); the register file is 0600; a corrupt, binary, directory-at-the-path or dangling-symlink register yields an empty register and never raises or hangs (the whole of task 3 of the identity plan is the argument for this test); `recordar` adds a vector to a person and the centroid moves; a person id that does not survive `normalizar` is refused.

- [ ] **Step 2: Run them, watch them fail, then implement**

Follow `remote_auth.py` exactly for the file handling — it is the module that already paid for these lessons: check the node's kind by `stat` before opening, catch `(OSError, UnicodeDecodeError, json.JSONDecodeError)` together, log once naming the path and never the contents, leave an unreadable file alone, and `os.open` with mode `0o600` before writing anything.

- [ ] **Step 3: Run the tests and commit**

```bash
cd widget && .venv/bin/ruff format . && .venv/bin/ruff check .
cd .. && git add widget/jarvis_widget/casa.py widget/tests/test_casa.py
git commit -m "feat(widget): who lives here, on disk, and only once"
```

---

### Task 6: The passphrase

**Files:**
- Create: `widget/jarvis_widget/frase.py`
- Create: `widget/jarvis_widget/palabras.py`
- Test: `widget/tests/test_frase.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `generar(n=4) -> str`, `parecida(dicho: str, frase: str) -> bool`, `cargar_o_crear(path) -> str`, `consumir(path)`.

- [ ] **Step 1: Write the failing tests**

```python
from jarvis_widget.frase import consumir, cargar_o_crear, generar, parecida


def test_a_phrase_is_ordinary_words_a_person_can_say():
    frase = generar(4)
    palabras = frase.split()
    assert len(palabras) == 4
    # Words, not a code: Whisper transcribes language, and "X7K-9QM"
    # comes back as "equis siete ka". Being unheard is the one failure
    # a spoken interface cannot afford (CLAUDE.md §12, 2026-08-26).
    assert all(p.isalpha() and p.islower() for p in palabras)


def test_two_phrases_are_not_the_same():
    assert generar() != generar()


def test_it_is_matched_the_way_the_wake_word_is_matched():
    # Whisper produced five spellings of one name in a single morning,
    # so this is a similarity, not a comparison.
    assert parecida("gato ventana lento roble", "gato ventana lento roble")
    assert parecida("Gato, ventana, lento, roble.", "gato ventana lento roble")
    assert parecida("gato bentana lento roble", "gato ventana lento roble")
    assert not parecida("hola qué tal", "gato ventana lento roble")


def test_it_is_made_once_and_reused_until_consumed(tmp_path):
    ruta = tmp_path / "frase.txt"
    primera = cargar_o_crear(ruta)
    assert cargar_o_crear(ruta) == primera
    consumir(ruta)
    assert cargar_o_crear(ruta) != primera


def test_the_file_is_not_world_readable(tmp_path):
    ruta = tmp_path / "frase.txt"
    cargar_o_crear(ruta)
    assert oct(ruta.stat().st_mode)[-3:] == "600"
```

- [ ] **Step 2: Implement**

`palabras.py` ships a list of ordinary Spanish nouns and adjectives — **at least 512**, so four words give ≥36 bits — chosen to be unambiguous when spoken: no near-homophones, no words Whisper is known to mangle, nothing with an accent that changes the word. Use `secrets.choice`, not `random`.

`parecida` normalises both sides (strip punctuation, fold case and accents, collapse whitespace) and compares with `difflib.SequenceMatcher` at the same 0.6 ratio `wake.py` uses, **plus** a rule the wake word does not need: at least three of the four words must match individually, so a long unrelated sentence cannot pass on overall similarity alone.

- [ ] **Step 3: Run, format, commit**

```bash
cd widget && .venv/bin/ruff format . && .venv/bin/ruff check .
cd .. && git add widget/jarvis_widget/frase.py widget/jarvis_widget/palabras.py widget/tests/test_frase.py
git commit -m "feat(widget): a passphrase you can say out loud"
```

---

### Task 7: The first encounter, as a state machine

**Files:**
- Create: `widget/jarvis_widget/encuentro.py`
- Test: `widget/tests/test_encuentro.py`

**Interfaces:**
- Consumes: `frase.parecida`, `voz`, `casa.Registro`.
- Produces: `Encuentro(registro, frase)` with `.estado`, `.oye(texto, vector) -> Respuesta | None`, and `Respuesta` carrying what he should say and whether he is finished.

**This is the project's first FLOW rather than a turn**, and it is written pure so it can be driven entirely from tests: no audio, no GTK, no clock but the one you pass in. `turn.py` has no notion of a multi-step conversation and is not touched.

The states: `ESPERANDO` (no amo; only the passphrase advances it) → `PIDIENDO` (asking for sentences; counts them) → `CONFIRMANDO` (says the name back and waits for a yes) → `HECHO`. A wrong answer at any point returns to the previous state with something to say, never to a dead end.

- [ ] **Step 1: Write the failing tests**

Cover: nothing but the passphrase leaves `ESPERANDO`, and a stranger talking is answered without advancing; the passphrase advances it once and **not twice**; it collects N utterances and only counts ones with a usable vector; it asks for a name and refuses one that does not survive `normalizar`, saying so in Spanish; confirmation requires an affirmative and a "no" sends it back to asking; when it finishes, the register has an amo; and — the security test — **the passphrase does nothing at all once an amo exists.**

- [ ] **Step 2: Implement, run, commit**

Every string he says is Spanish and belongs to his character: courteous, precise, dry, no exclamation marks, never servile. Read `Hermes/jarvis-soul.md` before writing them.

```bash
cd widget && .venv/bin/ruff format . && .venv/bin/ruff check .
cd .. && git add widget/jarvis_widget/encuentro.py widget/tests/test_encuentro.py
git commit -m "feat(widget): the first encounter, as a state machine"
```

---

### Task 8: Showing the passphrase on the strip

**Files:**
- Modify: `widget/jarvis_widget/window.py`, `widget/jarvis_widget/theme.py`
- Test: `widget/tests/test_encuentro.py` (the pure half only)

**Interfaces:**
- Consumes: task 7's state.
- Produces: the strip shows the passphrase while, and only while, no amo exists.

Reuse what exists rather than inventing: the band above the wave already grows for a photo and a card (`photo_area.py`, `ficha_area.py`). The passphrase is text, in the one colour, in the strip's own typography.

**Nothing here is provable by a test** (CLAUDE.md §2.3). Verify with `ffmpeg -f x11grab` and confirm with `xwininfo -name "JARVIS"` that you photographed the strip and not a lock screen. Attach the screenshot path to the report.

- [ ] **Step 1: Add the text to the band**

The band already knows how to grow for a photo and a card. Give it a
third thing to hold: two lines, centred, in `theme.TERRACOTTA`, in the
strip's own typography — the phrase itself larger than the sentence
above it. The sentence is Spanish and is the only instruction anybody
gets, so it has to be complete on its own: *"Dígame esta frase para que
sepa quién es usted."* Nothing else on screen; there is no second step
to explain because there is no second step.

- [ ] **Step 2: Show it only while there is no amo**

The window asks `registro.amo is None` when it decides. It is not a
setting and there is no way to turn it on afterwards: once an amo
exists, the passphrase is consumed and the band has nothing to show.

- [ ] **Step 3: Photograph it, because nothing here is provable by a test**

```bash
ffmpeg -y -f x11grab -video_size 1920x1080 -i :0 -frames:v 1 /tmp/frase.png
xwininfo -name "JARVIS"
```

The second command is not optional: a screenshot of a locked session is
a convincing picture of the wrong thing, and this project has taken one
before (CLAUDE.md §5).

- [ ] **Step 4: Commit, naming the screenshot in the message**

```bash
cd widget && .venv/bin/ruff format . && .venv/bin/ruff check .
cd .. && git add widget/jarvis_widget/window.py widget/jarvis_widget/theme.py
git commit -m "feat(widget): the strip says how to begin, until somebody does"
```

---

### Task 9: Wiring it into the running widget

**Files:**
- Modify: `widget/jarvis_widget/__main__.py`
- Test: `widget/tests/test_main.py`

**Interfaces:**
- Consumes: everything above.
- Produces: a running JARVIS that pairs on first boot and knows the amo's voice afterwards.

Two seams, and both belong where `dispatch()` already decides things:

1. **Unpaired**, every utterance goes to `Encuentro` instead of the gateway. He is not deaf — he answers — but nothing reaches Hermes and no tool exists.
2. **Paired**, each desk utterance is embedded and identified, and the person becomes the turn's `chat_id` exactly as a phone's does. `casa` when unsure.

**The identification must not sit in front of the answer.** Embed on the same PCM already going to Whisper, in the same thread that already calls it, and if it is slow or fails, the turn proceeds as `casa` rather than waiting. Measure the added latency and put the number in the report; §1.4 says latency beats correctness and this is exactly that trade.

- [ ] **Step 1: Write the failing tests**

```python
def test_an_unpaired_box_answers_but_never_reaches_the_gateway(monkeypatch):
    # He is not deaf while unpaired — he answers — but nothing said to
    # him becomes a turn, so no tool exists and no memory is written.
    enviados = []

    class FakeClient:
        async def send_chat(self, text, *, wake=False, chat_id=None):
            enviados.append((text, chat_id))

    # ... drive dispatch with no amo in the register ...
    assert enviados == []


def test_a_paired_box_sends_the_recognised_person_as_the_chat_id():
    # ... amo "papa" enrolled, an utterance whose vector matches ...
    assert enviados == [("¿qué hora es?", "papa")]


def test_an_unrecognised_voice_is_casa_and_still_gets_a_turn():
    # `casa` is a person with no tools, not a refusal: he answers.
    assert enviados == [("hola", "casa")]


def test_a_broken_embedder_costs_identity_and_not_the_turn():
    # The whole point. A model that fails must not make him deaf — the
    # failure CLAUDE.md §2.8 records costing three days in August.
    assert enviados == [("hola", "casa")]
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `cd widget && PYTHONNOUSERSITE=1 .venv/bin/python -m pytest tests/test_main.py -v`
Expected: FAIL — `dispatch` knows nothing about a register.

- [ ] **Step 3: Implement the two seams**

In `dispatch()`, after the transcription and the echo filter, before the wake word:

```python
                # Unpaired: nothing reaches Hermes. He talks, and that
                # is all he does — no session, no memory, no tools.
                if registro.amo is None:
                    respuesta = encuentro.oye(text, locutor.vector(pcm))
                    if respuesta is not None:
                        say(respuesta.dice)
                    origin.settle()
                    return
```

and, for a desk turn that is somebody's:

```python
                # Who this was. `casa` when unsure, and unsure covers
                # nobody enrolled, nobody close enough, and two people
                # equally close — deliberately indistinguishable to the
                # caller (see `voz.Huellas.quien`).
                if phone is not None:
                    persona = phone.persona
                else:
                    vector = locutor.vector(pcm)
                    persona = CASA if vector is None else huellas.quien(vector)
```

`huellas` is re-read from the register when it changes, not on every utterance.

- [ ] **Step 4: Run the whole suite**

Run: `cd widget && PYTHONNOUSERSITE=1 .venv/bin/python -m pytest -v`
Expected: PASS, and the count grows by the four tests above.

- [ ] **Step 5: Measure what identification costs a turn**

With `JARVIS_WIDGET_DUMP` set, speak (or use `JARVIS_WIDGET_FAKE_MIC`) and record the milliseconds between the end of the utterance and `send_chat`, with the embedder on and off. Put both numbers in the report. If the difference is more than ~150 ms, say so plainly rather than shipping it quietly — §1.4 is explicit that latency wins, and this is the trade it was written for.

- [ ] **Step 6: Commit**

```bash
cd widget && .venv/bin/ruff format . && .venv/bin/ruff check .
cd .. && git add widget/jarvis_widget/__main__.py widget/tests/test_main.py
git commit -m "feat(widget): he pairs on first boot, and knows the voice after"
```

---

## What part A does not do

Named here so nobody has to guess where the edges are:

- **It does not introduce anybody.** Only the amo exists. Part B.
- **It does not act on an unknown voice** beyond `casa`'s ordinary limits.
- **It does not identify a speaker on a phone** — a phone is already an identity that cannot lie, and voice adds nothing there.
- **It does not create Hermes profiles.** That was tasks 11-12 of the identity plan and it is rewritten by part B.
- **It has no recovery flow yet.** Losing the voiceprint means regenerating the passphrase by hand from this box's keyboard. Part B, or its own small piece.
