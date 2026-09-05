# The house has more than one person — identity and memory per member, design

> **Status:** design, agreed with the user 2026-09-05. Everything marked
> *measured* was read off this box today; everything marked *unverified*
> is named as a probe and must be settled before code leans on it. This
> project has twice built against a guessed Hermes API and been wrong
> (§12, 2026-08-26 and 2026-09-03), so the distinction is load-bearing.
>
> **The user's framing:** *"vamos a necesitar memoria para cada miembro
> de la familia"*, arriving with two daughters of 17 and 16 who are the
> reason — the teacher mode is what they would use.

## What this reverses, stated first

CLAUDE.md §1 says, in the list of what he is NOT: **"❌ A multi-user
system (single user, always)"**. This design deletes that line. It is
the oldest assumption in the project — older than the widget, older
than Hermes — and every surface built since rests on it: one session,
one memory, one turn in the whole house, `user_id` fixed to the string
`"primary"`.

It also softens **§1.1's privacy story in a new direction**. Nothing
starts leaving the house; but "the box belongs to the person talking to
it" (§12, 2026-08-26, the argument that bounded giving him `terminal`)
stops being true, because four people talk to it now and only one of
them owns it.

## What is being built

Four people, four memories. Each family member gets their own
conversation, their own memory of it, their own persona and their own
set of tools — and the daughters' set deliberately holds neither
`terminal` nor the house cameras. Talking from a phone identifies you
because the phone is yours. Talking in the room identifies you by your
voice. When he is not sure who is speaking, he degrades to a shared
`casa` identity rather than guessing — that rule is the spine of this
design and everything else is arranged around it.

## What was checked rather than assumed

**Hermes already does this, and we were one string literal away from
it.** Measured today, in the pinned tree:

- **Profiles are complete isolation.** `.hermes/src/hermes_cli/profiles.py`:
  each profile is a full `HERMES_HOME` under `~/.hermes/profiles/<name>/`
  with its own `config.yaml`, `.env`, `SOUL.md`, `memories/`,
  `sessions/`, `skills/`, `cron/` and `logs/`. The default profile is
  `~/.hermes` itself. So memory, persona, cron **and model** are per
  profile by construction, not by anything we write.
- **The gateway routes inbound messages to a profile.**
  `gateway/profile_routing.py` matches on `platform` + `chat_id`
  (+ `guild_id` / `thread_id`), most specific wins, and
  `GatewayRunner._profile_name_for_source` (`gateway/run.py:27920`)
  consults it from `build_source`. It is gated on
  `gateway.multiplex_profiles` and reads `gateway.profile_routes`. The
  module's docstring talks about Discord; **the matching is
  platform-generic** and `tests/gateway/test_profile_resolution.py`
  exists to pin exactly that.
- **Our adapter throws the identity away.** `Hermes/plugins/jarvis/protocol.py:62`
  validates a non-blank `user_id` on every chat frame, with a comment
  saying it flows into `build_source()` — and then
  `Hermes/plugins/jarvis/adapter.py:821` calls
  `build_source(chat_id="jarvis", …)` with the `user_id` alongside it.
  **`chat_id` is what routing keys on.** That literal is the whole
  reason the house shares one memory. The widget, for its part, sends
  `user_id="primary"` always (`widget/jarvis_widget/gateway.py:29`).
- **The teacher has no notion of a student.** `Hermes/plugins/jarvis_teacher/curso.py`
  keys courses by `curso_id` but exposes `ultimo_abierto()` — one
  global "last course opened". Two daughters studying two subjects do
  not fit in it today.
- **VRAM, live, with everything resident:** 22,883 MiB of 24,564 used —
  llama-server 16,330, CosyVoice 4,934, the widget (Whisper int8)
  1,457. **1,681 MiB free.** `llama-server` runs one slot at
  `--ctx-size 65536`.

### Unverified — probes that must run before any code leans on them

1. **Do plugins and toolsets really resolve per profile in this pinned
   Hermes?** The whole security story below depends on the daughters'
   profile not loading `terminal` or `jarvis_vision`. Plausible — each
   profile has its own `config.yaml` and plugin dir — but not measured.
   **If it turns out plugins are global to the gateway process, this
   design's tool boundary collapses and has to be redone** (most likely
   as a second gateway on another port). Probe this FIRST; it is the
   one finding that can invalidate the plan.
2. **Does multiplexing work with a single custom adapter serving many
   `chat_id`s?** `base.py:3085` describes `_owner_profile` for
   "multiplexed secondary adapter" installed per credential — a
   different shape from ours, which is one socket carrying many people.
   The `build_source` → `profile_routes` path looks like the right one
   and the test above suggests it is, but confirm before building.
3. **Is a speaker-embedding model available as ONNX under a licence we
   can use?** Named candidates: WeSpeaker / 3D-Speaker `CAM++`, or
   ECAPA-TDNN. The requirement is `onnxruntime` — already a dependency
   for Silero — and **no torch**, which rules out SpeechBrain,
   Resemblyzer and pyannote as they ship.
4. **Do the two sisters separate?** See "the measurement gate" below.

## Architecture

### Identity is the `chat_id`

```
                     who is speaking?
  phone  ──► the enrolled device says so        ─┐
  room   ──► a speaker embedding decides         ─┤──►  chat_id
  unsure ──► `casa`                             ─┘        │
                                                          ▼
                    gateway.profile_routes  ──►  ~/.hermes/profiles/<person>/
                                                 memory · sessions · SOUL.md
                                                 config.yaml → model + tools
```

`adapter.py` stops hard-coding `chat_id` and passes the person through;
`user_id` keeps carrying the same value so the two never disagree. The
routing table lives in `Hermes/jarvis-config.yaml` and is applied by
`apply-config.sh` — **remembering that it deep-merges dicts and
REPLACES lists wholesale** (§12, 2026-08-24), which is exactly the
shape `profile_routes` has and exactly how a family member could be
silently un-routed on the next apply.

### Who is who, per surface

**A phone is a person** — and this needs building, which an earlier
draft of this section got wrong. **There is no per-device token today.**
`remote_auth.py` holds ONE shared secret for the whole house
(`~/.jarvis/remote.token`), every phone presents it, and the endpoint is
named after its IP address (`remote.py`: `WebEndpoint(ws,
request.remote or "phone", loop)`). So the phone side is not "add a
name to something that already identifies devices"; it is a roster of
one secret per person, a `Guard` that answers *which* person rather
than *yes*, and an enrolment act that names who it is for.

The consequence that matters for the enrolment ritual: the welcome page
hands its secret, in cleartext, to whoever asks during the window
(`enrol.py` says so itself). With one secret that was one risk; with a
roster it becomes "whoever is on the wifi during those five minutes can
take the FATHER's token, which holds `terminal`". So **the person is
chosen at the keyboard, not on the page** — see the plan's task 4.

Once built, the rest is cheap and cannot be wrong: the `Endpoint`
carries the person, `dispatch()` propagates it, and it reaches the
adapter as the `chat_id`.

**The room is a voice.** A new pure module — the embedding, the
centroids, the threshold and the decision, with no GTK and no audio
device, the shape `wave_model.py` and `bars_model.py` already have —
plus a thin runner that feeds it. It runs **after the VAD, on the same
PCM that is about to go to Whisper**, so it costs one extra pass over
audio we already have and nothing in the latency path before it.
Centroids live in `~/.jarvis/voces/<person>.npy`, written by an
enrolment mode that asks each person for a handful of sentences.

**Nobody is `casa`.** Below the confidence floor, and for any voice
never enrolled, the turn belongs to a shared profile with its own
memory, no tools, and one hard rule: **`casa` never writes into a
person's memory, and a failure NEVER degrades to another person.** A
guest lands there without anyone configuring anything.

### The measurement gate

The user's correction, and it removes the risk I had flagged: the
daughters are 17 and 16, so these are adult voices and the models are
trained for them. **What remains is sister-vs-sister**, which is the
hard case for speaker identification — same age, same sex, same house,
same accent. So before any code depends on the room knowing who is
talking: enrol both, and measure the cosine distance between their
centroids and the within-speaker spread. Ten minutes with them present.
If they do not separate, **the phones still deliver the whole feature**
and the room falls back to a single identity; that fallback is a
supported outcome of this design, not a failure of it.

The second thing to measure at the same time: a typical utterance here
is short — *"Jarvis, ¿qué hora es?"* is about 1.5 s — and speaker
identification degrades sharply below a few seconds. The threshold must
be set against real utterance lengths, not against enrolment clips.

### Turns in parallel

`RemoteDesk` stops meaning "one turn in the house" and becomes a map
from person to turn. The widget holds N live turns, so `turn.py` is
instantiated per person rather than being a singleton, and the adapter's
single `_turn` slot (`adapter.py`: *"At most one open turn"*) becomes a
map keyed by `chat_id`, with the protocol frames carrying whose they
are.

**The shared engines are serialised, and that is affordable — measured.**
Two real 64K slots on `llama-server` would cost roughly another
gigabyte of KV cache against 1,681 MiB free, and a third would not fit;
they are not needed. `llama-server` queues a second request by itself
and at 47 tok/s the wait is seconds, Whisper transcribes in 67-148 ms,
and playback is genuinely simultaneous because a phone and the room are
different speakers. The one real bottleneck is **CosyVoice, which
garbles audio if clauses are synthesised concurrently** (§2.8) — so it
sits behind a global queue of one clause at a time.

**Depth is a number, not an assumption.** The user is considering an
AMD Ryzen AI Halo box (Ryzen AI Max+ 395, 128 GB unified, Linux) later.
There the KV budget stops binding and the queue can widen. So the queue
is written with its depth as a parameter, and no code is allowed to
assume serialisation as an invariant.

**The strip shows only the room's turn.** The wave is what he looks
like *here*; it is not a dashboard of the house. A daughter's turn on
her phone changes nothing on the desktop.

### What each profile may do

This is the part that matters more than the model:

| | father | daughters | `casa` |
|---|---|---|---|
| `terminal` | yes | **no** | no |
| cameras (`jarvis_vision`) | yes | **no** | no |
| teacher | yes | yes | no |
| memory of its own | yes | yes | yes, shallow |
| model | Heretic (unharnessed) | **the harnessed build** | harnessed |
| persona | JARVIS | its own `SOUL.md` | JARVIS, curt |

The harness is here because the user asked for it, and this spec
records what was measured about it on 2026-09-01 so nobody mistakes it
for a safety boundary: the harness stood in front of dark humour,
opinions of its own and staying in an unpleasant character — and in
front of **nothing** to do with medical dosing, security, law or
insulting its owner. **The boundary that actually protects anything is
the row above it: no `terminal`, no cameras.**

### Oversight

A `familia` tool, present **only in the father's profile**, read-only,
one direction. It answers "how is she getting on with fractions" from
the teacher's database and from what he has written down about them.
The user chose full visibility over the declared-surveillance variant;
that is recorded here as their decision, taken with the alternative on
the table.

This is cheap if the teacher keeps **one** database with a `alumno`
column rather than one per profile — which is also what piece 4 needs
anyway. So the teacher's store stays shared while memory stays
isolated, and that asymmetry is deliberate: a progress record is a
school report, and a conversation is not.

## Error handling

- **Identification fails, or is unsure → `casa`.** Never another
  person. This is the single rule that makes a probabilistic component
  safe to build on.
- **A route names a profile the gateway does not serve** — Hermes
  raises `ProfileRouteRejected` rather than silently using the default.
  Good; surface it, do not swallow it.
- **A person's profile is missing on disk** → `casa`, plus one log
  line. A new box that has not been provisioned must degrade, not lose
  turns.
- **Two turns for the same person** (her phone and the room) — the
  second supersedes the first, as a second `chat` frame does today.
  Parallelism is between people, not within one.

## Testing

Everything that can be pure, is: the routing table, the confidence
decision and the degradation to `casa` are functions of their inputs
and get tested with no GPU, no display and no gateway — the shape this
repo already relies on. The turn map gets the test that is impossible
today: two people mid-turn at once.

Two things cannot be tested that way and must be said out loud rather
than faked green: **speaker identification needs the real voices** (a
fixture set recorded at enrolment, and an honest confusion number), and
**profile routing needs the live gateway** — a probe, like
`tools/probe_busqueda.py`, since no test in this repo touches Hermes.

## Out of scope, deliberately

- **The native iOS app.** Its own design, this same day; it consumes
  this contract.
- **The teacher's student dimension.** Piece 4. This spec only fixes
  that the store stays single and gains a column.
- **Moving the LLM or anything else off this box.** The AMD machine is
  a possibility, not a plan; its only influence here is that the queue
  depth is a parameter.
- **Voice enrolment for guests.** They are `casa`, and that is the
  whole feature.
