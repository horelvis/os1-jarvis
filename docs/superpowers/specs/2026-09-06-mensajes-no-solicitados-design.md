# When he speaks first — addressing unprompted messages, design

> **Status:** design, agreed with the user 2026-09-06. It exists because
> multi-user broke something that used to be free: when there was one
> conversation, a message JARVIS started had nowhere else to go.
>
> **The user's decision, and it is the one this design could not make
> for itself:** security alerts belong to the amo.

## The defect this starts from, and we introduced it

`JARVIS_SESSION_KEY = "agent:main:jarvis:dm:jarvis"` is written out by
hand in **two** places — `Hermes/plugins/jarvis_vision/alert.py:36` and
`Hermes/plugins/jarvis_code/voz.py:24`. That trailing `jarvis` is the
`chat_id` a turn gets when nobody said whose it was.

So after the identity work, **every unprompted message lands in a
session that belongs to nobody**: camera sightings and the code
assistant's questions arrive in the default profile rather than in the
owner's. And it lands silently, because `inject_message` returns `True`
for a session that does not exist — a trap CLAUDE.md §12 already
records (2026-08-24) and which cost this project a hunt for a log line
that cannot exist.

**A hard-coded session key was correct when there was one session.** It
is now a bug with a name.

## The spine: an unprompted message has an addressee

Everything follows from making that explicit rather than implicit.

| what he says first | who it belongs to |
|---|---|
| a camera sighting, and anything else about the house's safety | **the amo** — the user's decision |
| a reminder | whoever asked for it |
| a question from the code assistant | whoever started that task |
| a health or failure notice about himself | **the amo** |

No default of "whoever happens to be there". A message with no
addressee is a bug in whatever produced it, not something for the
delivery layer to guess — and guessing is how a private thing gets read
out to the wrong person.

## Shelf life decides queue or drop

The insight that stops this becoming a generic queue nobody needed:
**unprompted messages differ by how long they are worth saying.**

- **Perishable.** A camera sighting. This project already decided in
  August that it is retried three times and then dropped, because
  *"queueing would make him recite stale news"*. That decision stands
  and its reasoning is unchanged: somebody at the door twenty minutes
  ago is not news, it is confusion.
- **Durable.** A reminder. Marta set it for eight o'clock; her phone
  was off; at five past eight it is still worth saying. Dropping it is
  the failure, not delivering it late.

Today everything is treated as perishable because there was one
recipient who was always there. The producer declares which it is; the
delivery layer does not decide.

## Where a message comes out, and the new privacy edge

**A message is delivered on a channel that belongs to its addressee.**
A phone belongs to its person, by enrolment. The strip belongs to the
amo — until voices are told apart, which is what the first-encounter
work is for.

The consequence is worth stating on its own, because it is new and it
is easy to get wrong: **a reminder for Marta must never appear on the
strip.** The strip is in a shared room; putting her business on it is
publishing it. With one user that distinction did not exist and every
unprompted message went to the one screen. Now the screen is somebody's.

If the addressee has no reachable channel: durable waits, perishable
dies. Neither falls back to the strip.

## Interruption: he waits for a gap, briefly

An addressee mid-conversation is not interrupted. The message waits for
their turn to settle — but only for as long as it is worth: a
perishable one expires while it waits and is dropped without ever being
said. That is the same rule as above, applied to a shorter timescale,
and it means "he is busy" never becomes "you never heard about it" for
anything durable.

## What does not change

- **The anti-spam rules are untouched.** 180 s per `(camera, label)`,
  a person during quiet hours beating it, the 30 s night floor. Those
  are about the SOURCE — how often something is worth saying — and this
  design is about the DESTINATION. Conflating them would re-open a
  calibration this project measured against these very cameras.
- **He is told, never made to recite.** `inject_message` only accepts a
  *user* message, so the property is enforced by the API rather than by
  our discipline (§12, 2026-08-24). Nothing here changes that.
- **Injection stays a per-plugin permission**, default off.

## What it costs

- **Two hard-coded constants become a lookup**, and the lookup can
  fail. `inject_message` returning `True` for a missing session means
  the delivery layer must verify a session exists rather than trusting
  the return — otherwise a message for a person whose profile has not
  been created disappears exactly as quietly as today.
- **A durable message needs somewhere to live** between being produced
  and being delivered. Small, on disk, and it must survive a restart —
  a reminder that dies when the widget restarts is not durable, it is
  perishable with extra steps.
- **A new failure mode: a message addressed to somebody who no longer
  exists.** A person removed from the house, a profile deleted. It must
  be dropped with a log line, never redirected to the amo — redirecting
  is how one person's business reaches another.
- **No amo, no delivery.** Consistent with the first encounter: an
  unpaired box has no owner, so a security alert has nobody to tell and
  is dropped. Saying it to whoever is standing there would be exactly
  the accident the pairing gate exists to prevent.

## Out of scope, deliberately

- **Notifying a phone that is not open.** That is APNs, and §12
  (2026-09-01) rejected it: it takes the notification out of the house,
  which contradicts *"usando la intranet, no internet"*. A durable
  message waits until the person next opens the page.
- **Deciding who is present.** Presence is a different problem and this
  design deliberately does not need it: a message goes to its
  addressee's channel, and if nobody is listening it waits or expires.
- **Broadcast.** Nothing here says the same thing to everybody. If that
  is ever wanted — "la casa se está quemando" — it is a separate
  decision with a separate justification, not a default.
