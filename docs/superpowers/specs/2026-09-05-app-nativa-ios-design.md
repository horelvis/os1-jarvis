# JARVIS as a native iPhone app — design

> **Status:** design, agreed with the user 2026-09-05, written to be
> implemented by another agent. It consumes the contract in
> `2026-09-05-identidad-por-persona-design.md` (same day) and should not
> be started before that spec's probe 1 has run — see "What this
> depends on".
>
> **Why native, in the user's words:** *"vamos a movernos a una app
> nativa de iPhone; con la nueva función teacher es útil para mis
> hijas."* So the app is not a nicer button. It is the surface two
> teenagers will study on, and the reason the web page is being retired.

## What is being built

A SwiftUI app for the household's iPhones that replaces
`widget/jarvis_widget/static/movil.html` entirely. Hold to talk, he
answers on the phone that asked — the rule from 2026-09-01 is unchanged
— plus the teacher's card rendered natively, and an identity that comes
from the enrolled device rather than from a shared account.

**And he has a face here.** Decided the same day, amending the
2026-09-01 discard for this surface only (§12): the phone shows a
stylised, non-human character rather than a button or a wave. Screens:
`https://claude.ai/code/artifact/2a12d71b-15c9-4239-8bf7-ccdd462af9dc`.

The web page **stays** as the fallback for a phone with no app on it
(and for Android, if that ever matters). It is not deleted by this work.

## The constraints, and they are hard

The user has a Mac but **no paid Apple Developer account**. Everything
below follows from that and shapes the design more than any taste
question:

- **The app expires after 7 days** and must be re-signed from the Mac.
  With three or four phones in the house this is a weekly ritual, and
  the user has accepted it knowingly. Design accordingly: **nothing
  important may live only inside the app.** Enrolment, courses,
  progress and memory all live on the box; a reinstalled app must come
  back to exactly where it was, and losing the app must lose nothing.
- **No `PushToTalk` framework and no APNs.** Both need entitlements a
  free account does not get. This costs the lock-screen walkie-talkie —
  and costs nothing this project wanted, because §12 (2026-09-01)
  already rejected that path for needing Apple's servers, which
  contradicts *"usando la intranet, no internet"*.
- **Verify on the Mac before building, not after** (the implementing
  agent, not this design, must settle these): the free-provisioning
  limits on distinct App IDs and registered devices per week, and
  whether re-signing for four devices from one Apple ID is workable.

## What native actually buys — every item is a measured defect

This is the justification for the whole task, and none of it is
speculative:

1. **The audio stops arriving half-strength and full of holes.**
   Measured on a real iPhone dump on 2026-09-01: **RMS 1731 against
   3745** for the same voice into the desk microphone, and a **1,140 ms
   gap inside a single utterance**; 35% flat samples, which is genuine
   silence — buffer duplication was ruled out. With low level and a
   one-second hole, Whisper invents (*"Hola, ya, ya, ya, ya…"*). The
   page uses `createScriptProcessor`, deprecated and known to starve in
   Safari when the main thread is busy — and that same thread is also
   decoding and scheduling his reply. `AVAudioEngine` with an input tap
   runs on the audio thread. **This is the single best reason to do the
   work.**
2. **The iPhone's silent switch stops muting him.** The user heard
   nothing with everything working correctly. A web page cannot
   override the switch; `AVAudioSession` with the `.playback` category
   can and does.
3. **The certificate ritual disappears.** Today each phone installs a
   configuration profile, then separately trusts the certificate, in
   Safari only, through a settings path that moves between iOS versions
   — four separate lessons, each learned by a person losing time
   (§12, 2026-09-01). A native app pins the house CA in its own
   `URLSessionDelegate` and none of that exists any more. **Pin, do not
   disable validation**: accept exactly this CA for exactly this host.
4. **Real audio conversion.** `remote_audio.py` resamples with linear
   interpolation and says in its own docstring that a proper filter is
   where to look if transcription ever suffers. On the device,
   `AVAudioConverter` does it properly and the widget's downsample
   stops being in the path at all.

## Architecture: still a peripheral, with the seam drawn

The app talks to the widget over the same WSS socket
`widget/jarvis_widget/remote.py` already serves, and its audio enters
the same `dispatch()` the desk microphone uses. **This deliberately
does not move to a service of its own**, and the reasoning is recorded
because it was the one structural fork of the brainstorm: the possible
future move to an AMD Ryzen AI Halo box is *future*, and it is
Ubuntu → Ubuntu, so the widget survives it. Paying today for a
migration that does not hurt is the wrong trade.

What the design does buy is the seam: **the turn and the STT sit behind
an interface** so that pulling them out of the GTK process later is a
move, not a rewrite. That is the entire concession to the future, and
it is nearly free.

```
 iPhone (SwiftUI)                     widget (one Python process)
   AVAudioEngine ──PCM 16k int16──►  remote.py ──► dispatch() ──► gateway
   AVAudioSession ◄─PCM 24k int16──   per-person turn map          │
   .playback                                                        ▼
   card view      ◄──── ficha frame ──────────────────────  jarvis_teacher
```

## Identity: the app does not get to say who it is

**The enrolled device carries the person, server-side.** The app
authenticates with its enrolment token exactly as the page does; the
widget maps token → person → `chat_id`, and from there
`gateway.profile_routes` selects the profile. The app never sends a
name, never sends a `user_id`, and cannot assert an identity it was not
enrolled with. If it could, the tool boundary in the identity spec
would be worth nothing — a daughter's phone could ask for the father's
profile, which has `terminal`.

Enrolment gains a person's name at the moment a device is enrolled,
which is a change in the widget's enrolment flow, not in the app.

## The protocol

Today, client → server: `{type:"start", rate}`, binary PCM, then
`{type:"end"}`. Server → client: `{type:"busy"}`,
`{type:"truncated"}`, and binary PCM at 24 kHz.

Additions, all server → client, all optional so an older client keeps
working — and following the precedent set when the strip's protocol
gained `photo` (§12, 2026-08-25): **an unknown frame must be dropped,
not fatal.** The page's own history has the counter-example, where an
unrecognised frame killed the turn carrying it.

- `{"type":"state", "value":"thinking"|"speaking"|"idle"}` — the
  measured 14-second wait with tools in play needs something honest to
  show. This is the frame the shelved UI task was going to need anyway.
- `{"type":"heard", "text":…}` — what Whisper understood. The third
  finding of the phone trial: today a bad transcription is invisible
  until an absurd answer arrives.
- `{"type":"ficha", …}` — the teacher's card, mirroring what the strip
  already receives, so the daughters read the lesson on the phone
  rather than on a strip in someone else's room.

## The card on the phone

The strip renders the card with WebKitGTK because there is no Markdown
widget for GTK4 (§12, 2026-09-03). **On iOS do not repeat that
reasoning**: render the Markdown natively (SwiftUI's `AttributedString`
handles CommonMark) and keep the same fence — no JavaScript, no network
loads, images only from `data:` URIs the gateway already inlines. A
phone is a screen with room on it, so the strip's paging compromise —
two fixed sizes because WebKit cannot report its height without JS —
**does not carry over**. On a phone, scroll.

## The face

**Why it is allowed here when it was refused everywhere else.** The
2026-09-01 decision dropped **any** avatar, and it stands for the strip.
Its reason was VRAM on this box — a MetaHuman measured at 3,240 MiB,
which does not fit beside the 27B. A phone renders its own face, so the
objection does not reach this surface. The other measurement from those
two days is what makes it cheap: **the face was never the expensive
part; what costs is whatever drives it.**

**What it is:** stylised 3D, deliberately not human — the user's choice
over the photoreal option. One colour, the project's own. In the
mockups the character is a pebble with two eyes and a mouth; the mockup
is SVG and proposes the FORM and the framing, not the asset.

**What changes between states is posture, not brightness**, and this is
the part to implement faithfully because it is what makes him read as
somebody rather than as an indicator:

| state | the character |
|---|---|
| idle | breathes, blinks, invites |
| listening | leans in, eyes open, mouth parted — waiting for you to finish |
| thinking | looks up and away, mouth shut, everything slower |
| speaking | only the mouth works |

**The thinking pose is half the answer to the measured 14-second
silence.** The other half is `heard` (see the protocol): what he
understood appears BEFORE the answer does, so there is something true to
read during the wait — which also fixes the phone trial's third finding,
that a bad transcription was invisible until an absurd reply arrived.

**What this costs, and none of it exists today:**

- **A rigged model** — glTF or USDZ with ARKit blendshapes — becomes an
  asset this project has to source, license and keep. An
  image generated by a text-to-image tool is a visual reference and
  **not** an asset: without a rig it cannot move.
- **Lip-sync has to be driven on the device**, from the 24 kHz PCM the
  app already receives. Amplitude-driven jaw is the cheap floor;
  viseme-level movement is a model. Decide which before building the
  rig, because the rig has to match.
- **§1.3's aesthetic restraint now has to govern a character**, which
  is a far harder thing to hold than one line and one colour. Every
  future "can he also…" lands on this.
- **The project now has two faces** — a wave on the desktop, a
  character on the phone — and nothing forces them to agree. That is
  accepted, not overlooked: the strip is him in a room, the phone is
  him in your hand.

**Out of scope for this app, explicitly:** giving the strip a face.
That reopens the 2026-09-01 decision on the surface where it was
actually measured, and this design does not.

## Security

- **The token is the identity**, so it is also the whole authorisation
  story. Store it in the Keychain, not in `UserDefaults`.
- **Pin the house CA.** Never `NSAllowsArbitraryLoads`, never a
  delegate that accepts any certificate — that would trade a
  two-minute install ritual for trusting any network the phone joins.
- **The CA carries `nameConstraints`** since 2026-09-01, limited to
  `brain.local` and the LAN address. Note the operational trap already
  recorded: **if the box's IP changes by DHCP the phones must be
  re-enrolled**, and now that also means re-signing.
- **The threat model is whoever is on the wifi**, guests included
  (§1.1). Nothing about a native app changes that.

## Testing, and what cannot be tested

The audio conversion, the frame decoding and the reconnection logic are
ordinary units. **The three things that matter most are not testable
and must be verified by a person holding a phone**, which is exactly
what §2.3 says about anything visual and what the 2026-09-01 trial
proved by finding, in one afternoon, four iOS facts no test had:

1. that the recording actually arrives at full level with no gap — the
   measurement in "what native buys" repeated, and compared against the
   1731/3745 baseline;
2. that his voice plays with the silent switch **on**;
3. that the app trusts the box with no profile installed anywhere.

Until those three are done by hand, this feature is not finished, no
matter how green the suite is.

## What this depends on

- **Identity spec probe 1** — whether toolsets really resolve per
  profile. If they do not, the daughters' phones cannot be given a
  safe profile and the app should not ship to them.
- **Enrolment carrying a person's name** — a small widget change,
  belonging to the identity work.
- Nothing else. The transport, the certificate, the enrolment QR and
  the turn machinery all exist and were verified on a real iPhone.

## Out of scope, deliberately

- **The cameras.** `JARVIS_PLATFORM` is hard-coded in
  `jarvis_vision/__init__.py` precisely so that an image of the inside
  of this house cannot reach another surface (§12, 2026-08-25).
  Putting a camera on a phone reopens that decision; it does not extend
  this one, and it must not be done by an implementer in passing.
- **Lock-screen or background push-to-talk.** Needs entitlements and
  APNs; see the constraints.
- **Android, and the App Store.** Neither exists in this house.
- **Deleting `movil.html`.** It is the fallback.
