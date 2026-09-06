# The first encounter — how JARVIS learns whose house this is, design

> **Status:** design, agreed with the user 2026-09-06. It **redefines the
> foundation** of `2026-09-05-identidad-por-persona-design.md`, which had
> identity coming from configuration; here it comes from conversation.
> That spec's tasks 8-10 survive untouched; its tasks 11-12 are replaced
> by this one.
>
> **The user's own definition, which is the whole brief:** *"Jarvis al
> iniciar por primera vez sin memoria tiene que hacer un emparejamiento
> por voz de quien es su «amo»; luego se le presentan distintos miembros
> de la familia y los va guardando por perfiles. Si accedes por el móvil
> y dices «Jarvis, soy Natalia», él ya creó ese perfil o lo asocia a uno
> existente."*

## What this revives

CLAUDE.md §10 has carried two entries since v1 that were specified and
never built: **"Onboarding / primer encuentro"** and **"Voiceprint /
huella de voz — user's voice embedding stored on first run"**. The kiosk
era took them with it, and nothing of either survives in the tree
(checked 2026-09-06: no file under `widget/` or `Hermes/plugins/`
mentions onboarding or a voiceprint). This design is those two entries,
built.

## What is being built

A box that boots with no memory does not guess who it belongs to and
does not serve anyone. It waits, and it says how to begin. Somebody
speaks a passphrase that this installation generated once and shows on
the strip; JARVIS asks for a few sentences, learns that voice, says out
loud who he now believes he is talking to, and **that person is the
amo**. Afterwards the family is introduced to him in conversation, and
he keeps each person as a profile of their own.

## The founding act, and why it is gated

**Rejected: pairing with the first voice he hears.** It reads better and
it hands the house to whoever speaks first — a guest, a child, a
television. The founding act of a trust model cannot happen by accident.

**The gate is a passphrase generated once per installation**, shown on
the strip while no amo exists and consumed the moment it works. It
proves the speaker has seen this machine's own screen; the voice that
speaks it is the voice that gets enrolled. *"Prove you are the one who
installed me, and then I will learn your voice."*

**It is a phrase, not a code, and that is not a style choice.** Whisper
transcribes language, not strings: `X7K-9QM` comes back as "equis siete
ka" or worse, and this project's own rule (CLAUDE.md §12, 2026-08-26) is
that being ignored is the one failure a spoken interface cannot afford.
So: **three or four ordinary Spanish words** drawn from a wordlist, easy
to say aloud and hard to guess. The same reasoning that made the wake
word a similarity ratio rather than a comparison applies to matching it.

**What the gate does and does not buy.** It bounds the window to
"between installation and the first pairing", and the person holding the
machine controls that window. It does **not** defend against somebody
who can read this box's disk — but such a person can already read the
roster, so no boundary is lost. Whoever says the phrase first becomes
the amo, which is the point.

**Until the amo exists, nobody has tools** — not the strip, not a phone,
not `casa`. An unpaired JARVIS talks and nothing else.

## Pairing wipes everything before it

**The user's decision, 2026-09-06: a pairing means erasing all previous
memory.** It is what lets this box change hands. A new amo does not
inherit the last one's conversations, their courses, what he learned
about them — or, and this is the part that is easy to miss, **their
enrolled phones**. A device that was trusted by the previous owner must
not still be trusted by the machine after it changes owner.

What a pairing destroys, and it must be all of it or none:

- every Hermes profile under `~/.hermes/profiles/` — memories, sessions,
  cron jobs;
- the house register and every voiceprint;
- **`~/.jarvis/personas.json`, the phone secrets** — every phone is
  de-enrolled and must be enrolled again;
- the teacher's courses and everything filed under them.

It is irreversible, so it is announced out loud before it happens and
confirmed, and the passphrase gate is what stands in front of it: this
is the second reason the founding act is gated, and the stronger one.
Pairing with whoever speaks first would not merely hand over the house —
it would erase it first.

### And therefore: re-enrolling a voice is NOT a pairing

These are two operations and confusing them would be expensive. A cold,
a new microphone, a voiceprint that has drifted — none of that is a new
owner, and none of it should cost the house its memory.

- **Pairing** is rare, deliberate and destructive: a new owner, a clean
  slate.
- **Re-enrolling a voice** adds or replaces a voiceprint for a person
  who already exists and keeps everything else. Cheap, and the ordinary
  answer to "he has stopped recognising me".

The recovery path this spec names below — regenerating the passphrase
from this box's keyboard — therefore belongs to **re-enrolment**, not to
pairing. If the only way back in were to pair again, laryngitis would
cost you every conversation you have ever had with him.

## What a person is

Four things, and the separation between the third and the fourth is
load-bearing:

- **A voiceprint** — one or more embeddings, so a person can be
  recognised across a cold or a shout.
- **A name as you would say it** — with accents, capitals, whatever it
  really is. This is what he calls them out loud.
- **An id** — ASCII, `^[a-z0-9][a-z0-9_-]{0,63}$`, which is Hermes' own
  profile grammar. It is a directory name, never a display name.
- **Whether they are the amo** — a flag on an ordinary person, not a
  separate class. There is exactly one.

## How someone new enters

By being introduced. **The rule that makes it safe is one line:
creating a person requires the amo's voice.** "Esta es Natalia" said by
the amo creates her; said by anyone else it does not. Without that,
whoever walks through the house can populate it.

A new person is created **limited by construction** — no `terminal`, no
cameras — rather than created equal and stripped afterwards. Stripping
afterwards is how a permission survives: it only takes forgetting once.

## A voice he does not know

He answers, with no memory and no tools. Not silence — a JARVIS who
ignores you reads as broken, and the daughters would conclude exactly
that before anyone got round to introducing them. Not an interrogation
either; asking "who are you?" every time is a service desk, and §1 says
he is not one.

If the same unknown voice keeps coming back, he says so **once**:
*"te oigo a menudo y no sé quién eres."* Introducing yourself becomes
something that happens in a conversation rather than a form to fill in,
which is what the user asked for.

## A spoken name never promotes

`"Soy Natalia"` may create or attach a **limited** profile. `"Soy papá"`
grants nothing, said by anyone, **including papá**. The amo is paired
once, by voice, at the first encounter, and no sentence afterwards
concedes it. A claim is weaker than an enrolment, always.

## The fork with what was already built, resolved

The 2026-09-05 work made phones **enrolled per person**: the device
knows whose it is without anybody saying so. The user's example has a
phone saying "soy Natalia". Both fit, and one has to win:

**The phone stays the identity.** It is the only identity in the system
that cannot lie — it is a secret, not an assertion. On an enrolled
phone, "soy Natalia" is redundant if it is Natalia's phone and ignored
if it is not. What the sentence is *for* is **introducing somebody new
from a phone**, which is a different act.

## The measurement that is now blocking

The earlier spec deferred voice identification behind a measurement —
whether two sisters of 16 and 17 separate — because the phones
delivered the feature without it. **That deferral is dead.** The amo
pairing *is* a voice pairing, so nothing works until voices can be told
apart.

Two measurements, both cheap, both before any code leans on them:

1. **Sister against sister.** Enrol both, measure the cosine distance
   between centroids and the within-speaker spread. Same age, same sex,
   same house, same accent: this is the hard case, and it decides
   whether the family half works at all.
2. **The passphrase through the real path.** Speak it, and count how
   many attempts Whisper renders closely enough to match. The wake word
   needed five spellings of one name in a single morning; a four-word
   phrase has four chances to be mangled.

If (1) fails, the amo pairing still works (one voice against nobody is
easy) and the *family* half falls back to phones. That is a supported
outcome, not a failure.

## What this costs

- **A speaker-embedding model** in the widget — ONNX on the
  `onnxruntime` already there for Silero, no torch. Candidates:
  WeSpeaker / 3D-Speaker CAM++, or ECAPA-TDNN. **Unverified**: that an
  export exists under a usable licence.
- **A wordlist** shipped in Spanish, and a passphrase file per install.
- **A conversation with state.** The first encounter is the first thing
  in this project that is a *flow* — ask, listen, confirm, retry —
  rather than a turn. `turn.py` has no notion of one.
- **A new way to be locked out.** Lose the voiceprint, get laryngitis,
  buy a new microphone: there must be a way back in that is not "edit
  the database by hand". Regenerating the passphrase from the keyboard
  of this box is the obvious one, and it is deliberately the same
  physical-access assumption as the founding act — but it must lead to
  **re-enrolment, not to pairing**, or the way back in costs everything
  it was meant to recover (see above).
- **A destructive operation on a voice-driven surface.** Everything else
  here is reversible; this is not. It needs a confirmation that cannot
  be given by accident, and "yes" said to a machine that mis-heard the
  question is exactly how it would be.

## Out of scope, deliberately

- **Identifying a speaker in a recorded conversation.** He identifies
  who is talking to him, not who was in the room.
- **More than one amo.** One house, one owner; a second would need a
  model for what happens when they disagree.
- **Voice as a password.** The voiceprint says *who*, the passphrase and
  the phone secrets say *whether*. A recording of the amo must not be
  able to open anything, which is why nothing here grants a tool on the
  strength of a voice alone.
