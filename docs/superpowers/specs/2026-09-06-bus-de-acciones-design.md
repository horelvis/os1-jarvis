# The action bus — the surface stops being ten files, design

> **Status:** design, agreed with the user 2026-09-06. It takes the one
> thing `jakimli/cloe-desktop` genuinely does better than this project
> and leaves the rest of that project alone.
>
> **The user's framing, which is the brief:** *"coger lo mejor de ambos
> mundos, nuestra voz funciona genial."*

## What this is answering

The user reviewed `jakimli/cloe-desktop` — an AI desktop companion that
runs on the same Hermes gateway and the same CosyVoice as JARVIS — and
said: *"creo que su arquitectura es mejor que la nuestra."*

Partly right, and the part that is right was paid for the same day.

**Adding one state to JARVIS cost ten files.** `working`, on
2026-09-06: `wave_model.py`, `bars_model.py` (already drawn),
`protocol.py`, `adapter.py`, `jarvis/__init__.py`, `gateway.py`,
`turn.py`, `__main__.py` and two test files. In Cloe the equivalent is a
line in `plugin-rules.json`, hot-reloaded in five seconds.

**And the strip cannot be driven by anything but the gateway.** To
photograph the wave in a specific state on 2026-09-06, the only
available method was to provoke a real 49-second search turn. Three
measurements that day were invalid, and one of the three causes was
exactly this: the strip had been stopped to make room for a probe, so
there was nobody to send the frame to. Cloe's surface answers
`curl -d '{"action":"smile"}'`.

**What is NOT better about Cloe, and this decides the scope.** Its
`speak` action takes the filename of a pre-recorded MP3
(`~/.cloe/audio/`), not text — there is no endpoint that says a
sentence. It has no STT at all. Its in-process coupling of microphone
and playback does not exist because it has no microphone. JARVIS's
does, and §2.8 records what that coupling buys: interruption decided on
WORDS rather than volume, because `EchoFilter` compares the live Vosk
partial against what he is saying right now. That property does not
survive an HTTP POST.

So: the interface architecture is better; the system architecture solves
a much smaller problem. This spec takes the seam and nothing else.

## The cause, stated once

Every visual capability in this project is a bespoke frame, end to end.
`photo`, `ficha`, `console`, `asking`, `working`, `live`, `live_end`:
each has its own builder in `protocol.py`, its own entry in
`gateway.py`'s allowlist, its own dispatch branch, its own handler in
`__main__.py`, and its own push method on the adapter. Adding the next
one costs the same five edits plus tests, whatever it is.

That is the whole diagnosis. The rest of this document is what replaces
it.

## Layer 1 — one frame, one table

**The frame:**

```json
{"type": "action", "name": "working", "args": {"on": true}}
```

`name` is a short identifier; `args` is whatever that action needs.
Nothing else. An older strip that does not know an action ignores it,
the way an older strip already ignores `asking`.

**The table**, in the widget, is the only place a new action is
declared:

```python
ACCIONES: dict[str, Callable[[dict], None]] = {
    "working": lambda args: machine.working(bool(args.get("on"))),
    ...
}
```

Adding a state becomes one entry. That is the deliverable of this layer
and the measurement it will be judged on: **the next state must cost one
file, not ten.**

**The existing frames DO move, once the new path is proven** (user,
2026-09-06: *"una vez revisamos que funciona la nueva arquitectura se
migran los marcos para no dejar código basura"*). Two ways of saying the
same thing, kept side by side for ever, is how a codebase accumulates
exactly the junk this layer exists to remove. So migration is in scope —
as a LATER phase, gated on the new path working, never as a big-bang
rewrite in the same breath as introducing it.

**But not every frame is an action, and the line is not a matter of
taste.** `protocol.py` holds three families, and only one of them is
commands to a surface:

| family | frames | what they are |
|---|---|---|
| **The turn** | `token`, `done`, `error`, `silence`, `transcription` | the conversation itself, not an instruction to draw |
| **Actions** | `photo`, `ficha`, `console`, `asking`, `working` | "make the surface do this" |
| **Bytes** | `live_frame` (via `_push_bytes`), `live`, `live_end` | raw video — ~1,200 packets in two minutes |

**The five actions migrate.** They are the family this layer is about,
they are the ones a future capability would have joined, and once they
are gone `protocol.py` stops being a place new frames get added.

**The turn does not.** `token` is the hottest path in the system —
every clause of every reply — and wrapping it in an action envelope adds
indirection to it for no gain. It is also not an instruction: it is what
he said.

**The byte stream does not.** `live_frame` goes out through
`_push_bytes` because it carries a raw packet; it cannot become a JSON
action for the same reason a photograph cannot become a sentence.
`live` / `live_end` open and close that stream and belong with it.

**Migration is done frame by frame, each with its tests green before the
next**, and the old builder is deleted in the same commit that moves its
last caller. A migration that leaves the old path in "just in case" has
not migrated anything.

**Where the table lives.** In its own module (`acciones.py`), not in
`__main__.py`. `__main__.py` is already the largest file in the widget
and the wiring for every subsystem; adding a growing dispatch table to
it would recreate, in one file, the problem this layer exists to remove.
The module takes the objects it drives (the turn machine, the band) as
arguments and holds no state of its own — testable without GTK, like
`wave_model` and `photo` already are.

## Layer 2 — the strip becomes scriptable

A local way to inject an action without provoking a turn.

**Loopback only, and that is not a formality.** The strip's other socket
(`remote.py`, the phone path on `:8443`) is authenticated with a
per-person secret and an origin check because §1.1's threat model is
"whoever is on the wifi, guests included". This one binds `127.0.0.1`
and nothing else: anything that can reach it can already run code as
this user. Never `0.0.0.0` — this box has twelve Docker bridges, and
`remote.serve()`'s own comment says why.

**What it buys, concretely:** the three failed measurements of
2026-09-06, and every future screenshot of a state. `tools/` gains a
one-line way to say "show me the wave working" without a 49-second
search.

**What it is not:** a control surface for anything that matters. It
drives what is DRAWN. It does not speak, does not send a turn, does not
touch the register, does not open an enrolment window. That boundary is
part of the design, not an omission: a loopback endpoint that could
speak would be a way to put words in his mouth from any process on the
box.

## Layer 3 — Cloe as a second consumer

The same actions, additionally posted to `http://localhost:19851/action`.
Cloe draws the face; JARVIS keeps the voice.

**Why this direction and not their integration.** Cloe ships a Hermes
hook and plugin (`docs/hermes-hook/`, `docs/hermes-plugin/`) with an
installer — and that installer hardcodes `HERMES_DIR="${HOME}/.hermes"`.
This box's `HERMES_HOME` is `$REPO_ROOT/.hermes/home`, and `~/.hermes`
EXISTS with 21 entries. Their script would install into a directory that
looks alive and is not, and nothing would fire. Beyond the path, it
would mean two hook systems and two ideas of what a state means, when
this project published its own state bus on 2026-09-06.

So Cloe learns nothing about Hermes. It receives "put your working face
on" and that is all it is told.

**Its audio must be off.** Cloe plays canned MP3s with its mouth
animation. Two voices over one sentence is the failure to avoid, and
JARVIS owns the voice.

**Its assets do not require the cloud.** 24 GIFs ship in `public/gifs`,
including `working.gif`, `think.gif`, `speak.gif` and `blink.gif` —
close to a one-to-one match with the states this project already
publishes. Wan2.7 is needed only to author NEW expressions, so §1.1
holds at install time and at run time.

**Electron gets measured, not assumed.** §2.3 rejected Electron for the
strip on numbers (~389 MB resident for the whole widget against
Electron's baseline). Cloe is Electron plus an app, as a second process.
That measurement is a task of this work, and its result may end layer 3
— which costs nothing, because layers 1 and 2 stand alone.

## What this does not touch

- **Nothing in the voice path.** Not the microphone, not Silero, not
  Whisper, not Vosk's endpointing, not `EchoFilter`, not CosyVoice, not
  clause-by-clause playback, not the interruption. This is the part the
  user said works, and the part Cloe cannot do at all.
- **The wave stays.** The face, if it arrives, is additive.
- **No existing frame is migrated.**
- **The persona is untouched.**

## What is still open, and belongs to the plan rather than here

- **The state vocabulary, if Cloe arrives.** Five states are published;
  Cloe ships 24 expressions. Which map, and whether anything beyond the
  five is worth publishing, is a decision to make with a face on screen
  rather than in a document.
- **Idle behaviour.** The user chose "both, and presence can be switched
  off": the five states as the core, autonomous life as a layer with a
  switch. Nothing about that layer is designed here.
- **A minimum on-time for a state.** Measured 2026-09-06: one tool call
  lasted 10 ms, so the wave switched on and off inside a single frame.
  That flicker will be worse on a face than on a line.

## The decision this reopens, and how far

`docs/decision-log.md`, 2026-09-01 — *"He gets no face: the avatar is
dropped, all of it"* — rejected **any** avatar, on the user's own bar:
*"una cara que sólo es bonita no lo pasa"*. Layers 1 and 2 do not touch
that decision at all. Layer 3 does, and only if it ships.

What the entry decided on numbers was the expensive path: MetaHuman at
**3,240 MiB of VRAM**, which does not fit beside the 27B. That number
does not apply here — Cloe is transparent GIFs, and the entry's own
measurement of the cheap path was **~50 MiB**. The argument that has
changed is not the cost: it is that on 2026-09-06 the user asked twice
to be able to see what he is doing, which made legibility a requirement
that did not exist when the avatar was judged as decoration.

If layer 3 ships, that entry gets a successor saying exactly this. If it
does not, the entry stands whole.
