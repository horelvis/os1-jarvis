# He stops being tied to the desk — JARVIS on the phone, design

> **Status:** design, agreed with the user 2026-09-01. Every number and
> capability below was checked on this box or against Apple's own
> documentation; where something is unverified it says so.
>
> **The user's framing, and it decides the architecture:** *"la idea es
> darle movilidad"* — and *"usando la intranet, no internet"*. The phone
> is not a second JARVIS and not a chat client. It is another pair of
> ears and another mouth for the one that already exists: same session,
> same conversation, same memory.

## What is being built

A page, served by the widget itself over HTTPS on the house's own
network, with one button. Hold it, speak, release; he answers on the
phone you spoke into. Three iPhones, nothing installed from any store.

## What is NOT possible, checked rather than assumed

Four findings shaped everything, and each closed a door somebody would
otherwise try again:

- **Home Assistant does not exist on this box.** Port 8123 closed, no
  container, and the only mention anywhere is a comment in
  `samantha-config.yaml` listing toolsets that *would* need credentials.
  CLAUDE.md §12 (2026-08-23) lists it as "the one that makes a thing in
  the living room worth having" and reads as though it were integrated;
  it never was. **This also invalidates a decision taken earlier the
  same day** in the parked "JARVIS falla en silencio" work, where the
  health alert was routed "via Home Assistant, which is already
  integrated". That has to be redone.
- **A browser will not open a microphone without a secure context.**
  `getUserMedia` works on `localhost` and on HTTPS; on
  `http://192.168.x.x` it is blocked. On iOS every browser is WebKit, so
  there is no browser to escape to. This is what forces a certificate.
- **Apple's Walkie-Talkie is watchOS**, between Apple IDs over FaceTime
  Audio, with no third-party API. The user asked about it directly.
- **iOS 16+ does have a `PushToTalk` framework** for third-party
  walkie-talkie apps, and it delivers what "always listening" wanted:
  audio from the background, even locked. It needs a native app, the
  `com.apple.developer.push-to-talk` entitlement, and — the part that
  kills it here — **APNs to wake the app**, so its headline feature
  depends on Apple's servers. That contradicts "intranet, not internet".
  The unrestricted PTT PushKit entitlement was disabled in the iOS 26
  SDK. So: the *feel* of a walkie-talkie is available in Safari today;
  the *superpower* is not, and buying it means leaving the house.

## Architecture: a peripheral, not a platform

The widget already owns the microphone, the VAD, Whisper, the echo
filter, playback and the turn machine, and already runs an asyncio loop
with `aiohttp` present. So the phone joins **that** pipeline:

```
iPhone (Safari)  ──PCM 16k──►  remote.py  ──►  dispatch(pcm)  ──►  the
   press-to-talk  ◄─PCM 24k──   (widget)        the same path        gateway
                                                the desk mic uses
```

**The gateway never learns the phone exists.** It still sees exactly one
strip, one session, one memory. Nothing in Hermes changes: no
multi-client, no second platform, and no touching `adapter.py`'s origin
check — which exists because a hostile connection does not merely
eavesdrop, it **evicts the real strip** (the one-strip swap).

Push-to-talk then removes three whole subsystems from the phone's path,
and each removal is deliberate:

- **No VAD.** The button is the utterance boundary. `vad.py` is skipped
  entirely, and with it the endpointing built the same morning — which
  is not needed when a human decides where the sentence ends.
- **No wake word.** Pressing *is* addressing him, so `wake.heard()` is
  bypassed for phone utterances.
- **No echo problem.** He answers on the phone that spoke, and only
  there; the desk stays silent for that turn. Two speakers never sound
  at once, so the cross-room feedback that made "he is in both places"
  expensive never arises. The phone's microphone is closed while he
  answers, because you are not pressing. Press while he talks and that
  is barge-in — `speaker.interrupt()` already exists.

**This narrows what the user chose, and the narrowing is the point.**
Asked where he should be, they picked "he is in both places" over "he
moves with you" — the most expensive option, knowingly. What makes it
affordable is that the two halves are separable: *listening* happens in
both places at once, and *speaking* happens in one. The desk keeps its
microphone open always; it simply does not answer a turn that came from
a phone. All the cost of "both places" lived in two speakers sounding at
once — cross-room feedback, which is this afternoon's bug multiplied —
and routing the answer removes it without taking anything the user
asked for.

## Transport

Deliberately dumb: **raw int16 PCM over the WebSocket**, no codec.

- **Up:** the page captures with Web Audio and resamples **whatever rate
  the browser hands it** — usually 48 kHz, but it is the device's choice
  and must be read from the `AudioContext` rather than assumed — down to
  the 16 kHz the pipeline speaks. Sent while held: 256 kbps, and only
  while pressed.
- **Down:** CosyVoice's 24 kHz int16, unchanged. ~380 kbps while he
  answers.

Both are already the pipeline's own formats, so nothing converts at
either end, and on a local network the bitrate is noise. One iOS detail
lands in our favour: Safari requires an `AudioContext` to be created
from a user gesture, and pressing the button *is* that gesture.

## Security, and the threat model it changes

**What is behind this socket is not a chat.** It is an agent holding the
`terminal` toolset — §12 (2026-08-26) states plainly that "he can run
ANY command on this box". Until now the project's entire authentication
was *"only from this machine"*, and that stops being true the moment
anything listens on the network.

Four measures, none optional:

- **A shared secret**, generated on first run, stored 0600 under
  `~/.samantha/`, required by the WebSocket. It reaches the phone inside
  the link that gets added to the home screen.
- **The origin check is kept**, adapted to allow only the page's own
  origin. Same reasoning as `adapter.py`'s, and for the same reason:
  WebSockets are not subject to the same-origin policy.
- **Bind to the LAN interface only** (`192.168.100.58`), never
  `0.0.0.0`. This box has **twelve Docker bridges**; no container has
  any business reaching JARVIS.
- **One turn at a time.** Three phones plus the desk can press at once.
  A press during a running turn is refused and the page says so.
  Queueing spoken orders ages badly — he would answer something asked a
  minute ago.

**The cost, and it belongs in §1.1 and §2.1 because it is a change of
premise rather than a detail:** everything was on loopback, and the
assumption was "whoever has physical access to this box". It becomes
**"whoever is on the wifi"**, guests included. Nothing leaves the house,
so §1.1's letter holds; what changes is who is inside it. Rotating the
secret is regenerating the file and re-opening the link on three phones.

## The certificate, and enrolment by QR

A **local CA** generated on the box, 0600, with a leaf for **both**
`brain.local` (avahi is running, so mDNS resolves it) **and**
`192.168.100.58`, because client isolation on some networks breaks mDNS
and the IP is the fallback. Issued for ten years: touched once.

**One QR, not two**, pointing at a welcome page served over **plain
HTTP** — deliberately, because of a chicken-and-egg: HTTPS cannot be
used before the certificate it depends on is trusted. That page carries
nothing sensitive, only two buttons: install the profile, then open
JARVIS over HTTPS with the secret in the link.

**Where the QR appears**, and the two are complementary:

- **On the strip**, on request. `photo_area.py` already draws a PNG in
  the band — this is the same gesture the cameras use. It is what makes
  this a thing he does rather than an administration task: you ask him
  to come with you and he shows you how.
- **In the terminal** at startup, for when the screen is not in front of
  you.

**The QR expires.** It carries the secret, so a code left on screen or
in a log is the secret in plaintext. It lives minutes, the same trade
the band already makes with photos.

**New dependency, approved by the user:** `qrcode[png]`. Verified on
this box — writes a 501-byte PNG through `pypng` with **Pillow never
imported**. Two small pure-Python packages.

**The user installs it on ONE iPhone first** and decides from the real
friction whether to do the other two or move to a real domain with a
DNS-01 certificate, which removes the install entirely at the cost of
owning a domain.

## Testing

**Pure Python, so ordinary tests:** the secret check, the origin check,
the 48→16 kHz resampling arithmetic, the one-turn-at-a-time gate, and
that a reply returns to the endpoint that spoke and not to another.

**Not testable, and it must be said rather than faked:** that Safari on
an iPhone captures and plays. That needs a phone in a hand, exactly as
§2.3 says nothing about the strip's appearance is provable by a test.

## A rule this does not break, stated so nobody reads it wrong

§3 forbids "introducing a browser / webview of any kind". This does not
violate it. That rule governs **JARVIS's display layer on this
machine** — the strip is GTK and stays GTK. The browser here is on the
user's own iPhone, a device rather than a component. Serving a page is
not embedding an engine in him.

## Out of scope, deliberately

- **Always-listening on the phone.** It needs a native app, an Apple
  entitlement and APNs; the reasoning is above. Reopen it only if what
  is actually missed, after using this, is having him in a pocket.
- **Cameras and photos on the phone.** `JARVIS_PLATFORM` is hard-coded
  in `samantha_vision/__init__.py` precisely so an image of the inside
  of this house cannot reach any other surface (§12, 2026-08-25).
  Showing cameras on the phone means reopening that decision
  deliberately, not extending this one.
- **A second conversation.** The phone is the same session by design. A
  separate thread on the phone would be a different product.
- **Anyone but the user.** §1 says single user, always. Three iPhones
  here means three devices, not three people.
