# Decision Log — JARVIS

> **Split out of `CLAUDE.md` §12 on 2026-09-06**, unchanged, because that
> file is read in full at the start of every session and the log had grown
> to 60% of it. Nothing here was edited: this is the same append-only
> record, and `CLAUDE.md` §12 is now the index in front of it.
>
> **Append new decisions HERE**, newest first, and add one line to §12's
> index. A decision that changes what runs also changes the section it
> belongs to (§0–§11); this file is the reasoning, not the specification.

---

### 2026-09-06 — He gains a vault, and it is not his memory

**Decision (owner, after an assessment that argued against half of it):**
JARVIS reads a vault of Markdown — the user's own notes — through
Hermes' bundled `note-taking/obsidian` skill. The `file` toolset is
added to `platform_toolsets.jarvis`; `OBSIDIAN_VAULT_PATH` points at
`~/boveda` from the repo-root `.env`. **He reads it. He does not write
to it**, and that half was deferred deliberately rather than forgotten.

**What the assessment found, before anything was built.** "Obsidian"
turned out not to be an integration at all: the bundled skill is
filesystem-first — `read_file`, `search_files`, `write_file`, `patch`
against a directory — and Obsidian is simply what a human opens those
files with. So the question was never "should we integrate Obsidian";
it was "should he have a folder of Markdown shared with the user". That
reframing is the useful part of this entry.

**Hermes allowed it and shipped it; this platform did not.** The skill
was already installed at `.hermes/home/skills/note-taking/obsidian/`,
and the tools it wants are the `file` toolset — which was NOT in
`platform_toolsets.jarvis`. He had `terminal` and would have fallen back
to `cat` and `grep`, which the skill argues against in every section,
with reason: vault paths contain spaces.

**Why it is separate from memory, in one sentence each.**
`memories/USER.md` is injected into every turn — it is what he knows.
The vault is a place he decides to look. Putting the same fact in both
produces an assistant whose remembered answer and read answer disagree,
which is §7's scar (`docs/personality.md` against `jarvis-soul.md`) in a
new location. That is why the write direction was deferred: it is where
the boundary has to be decided, and nobody has decided it.

**What was argued against and shipped anyway, honestly.** It is grep,
not retrieval — no embeddings anywhere in that skill. It works for tens
of notes and will silently stop working for thousands, answering as
though a note does not exist rather than saying it could not find one.
This project already owned the fix for that (ChromaDB, §2.7) and deleted
it on 2026-09-03 for never being used on the gateway path. The vault is
therefore a small-scale tool by construction, and its README says so to
whoever fills it.

**`file` is not a sandbox, and it was checked rather than assumed.**
`file_tools._authoritative_workspace_root` only warns when a RELATIVE
path escapes the session cwd; an absolute path returns before that check
ever runs (`file_tools.py:422`). These tools reach the whole disk. This
widens no boundary — `terminal` has been enabled since 2026-08-26 and
can already do all of it — but the config comment says so plainly so
nobody reads the line as "he can only touch the vault".

**Measured live, first try**, with a note written into the vault a
moment earlier: asked "¿cada cuánto riego los tomates y qué pasa con el
gotero?", he answered with both facts from the note and added the
consequence himself — "esa fila va a ir a secas si no lo toca". One
turn, no prompting toward the tool.

**The trap this leaves.** `OBSIDIAN_VAULT_PATH` lives in the git-ignored
`.env`, so it must be re-applied by hand on any new box — and without
it the skill does not fail, it silently falls back to
`~/Documents/Obsidian Vault`. Same shape as §1.1's `tts:` trap, and it
belongs on the same list. And: syncing the vault with Obsidian Sync or
iCloud takes the notes out of the house, which ends §1.1's guarantee.
Syncthing between the owner's own machines does not.

### 2026-09-06 — One scan carries the house, not a link to it

**Decision:** the enrolment QR stops being a LAN address and becomes an
envelope: `{"v": 1, "url": "wss://…", "token": "…", "ca": "sha256/…"}`
— where the box is, the person's own token, and the fingerprint of the
house CA's public key, which the phone pins. `enrol.sobre()` builds it
and refuses outright to write one missing a field; `certs.spki_fingerprint()`
computes the `ca` value by shelling out to `openssl`, the way every other
certificate operation in that module already does.

**What it buys, in one sentence: the app ships with nothing to
configure.** The old QR was a bookmark — a host and a port, entered once
into a browser that still had to be told, separately, to trust a
certificate it had never seen. The new one hands the app the address,
the credential and the key to pin, in a single scan, and there is no
settings screen behind it because there is nothing left to type. That is
also why it is drawn **per person** now, by `Enrolment.abrir()` when
that person's window opens, rather than once at startup for nobody in
particular: the envelope carries an identity, and a generic one drawn at
boot had no identity to carry.

**The key, not the certificate — and the trade is symmetrical.** Pinning
`spki_fingerprint()` rather than the leaf certificate means the
certificate can be reissued, on its ten-year clock or sooner, without
touching a single enrolled phone: the key underneath it does not change,
so the pin still matches. The cost is the mirror image and just as
absolute: **rotating the CA's key means re-enrolling every phone in the
house**, because every one of them is now pinned to that key by name.
There is no partial version of either direction.

**The QR became a credential, and that changes what a photograph of it
costs.** It used to encode a LAN URL that was nobody's secret — anyone
could have it, it named a place, not a person. Now it carries one
person's token, and a photo of the strip taken by somebody else in the
room is a leak of that person's access, not a curiosity.
`JARVIS_WIDGET_ENROLMENT_SECONDS` (300 s) bounds only how long the CODE
is on screen (or in a photo of the screen) to be scanned in the first
place — it bounds *display*, not the credential itself. The token
inside it is valid forever once minted: nothing expires it, and nothing
in this codebase revokes one short of a person editing `personas.json`
by hand, removing the entry, **and restarting `jarvis-widget.service`**
— `Guard.secretos` is read from that file once, at boot, and never
again, so the hand-edit alone leaves the running process none the
wiser and the phone still connecting. A guest who photographs the strip
during those 300 s can come back three weeks later, on the same wifi,
and connect as that person for as long as `personas.json` still holds
their secret. Both `enrol.write_qr` and `__main__._mostrar_qr` used to say
the opposite in as many words — the second one in the very file that
draws the code on screen, arguing that the band's 15-second fade "is not
what protects anything." Both were wrong the moment the payload changed,
and both are corrected in these commits.

**The ordering reversed, and the plan's own first draft got the new
order wrong too.** Minting a person's secret used to happen when the
welcome page was *requested* — the token didn't need to exist until a
browser asked for it. With the token now baked into the QR, it has to
exist before the image is drawn, so minting moved into `Enrolment.abrir()`,
ahead of the draw. The plan's text for that step had `abrir()` open the
enrolment socket *before* minting, which reintroduced the same bug from
the other side: `open_enrolment()` raises `EnrolmentSite` on the
asyncio-loop thread via `call_soon_threadsafe`, while `abrir()` itself
runs on the GTK thread — two real OS threads, racing. A first-time
person whose phone (or a browser, on the old page) reached the welcome
endpoint inside that window would mint a *second* secret and overwrite
the one already burned into the QR just drawn, leaving the phone that
scanned it holding a dead token. Caught in review, not by a test, and
fixed by minting and drawing before the socket goes up at all — the
`try/except` around the draw stayed, because the window must still open
for `casa` even on a box where the QR itself cannot be written.

**The new frame changes the wire contract for every client, and it
arrives first.** The handshake now answers `{"type": "enrolled", "name":
"Orelvis"}` before anything else — the display name from `casa.Registro`,
resolved server-side from the token, so the phone still never sends a
name or an id of its own. `static/movil.html` was checked rather than
assumed compatible: its `onmessage` only branches on `busy` and
`truncated`, so an unrecognised leading frame falls through with no
exception and no state change. It survives the new frame without
knowing it exists.

**`movil.html` is deprecated, not fixed.** It is untouched by these
commits and no longer reachable by scanning — its address has to be
typed by hand now, `http://<LAN>:<port+1>/`, and it still walks a phone
through the old two-step certificate ritual. The owner's decision,
today: the web interface is on its way out, so its long-tail — no
envelope-aware onboarding, no offer to open the app instead — was left
alone rather than built into a page that will not be there to enjoy it.

**Nothing here has been tried against a real iPhone.** The scan itself,
the pin, the app reading its own envelope — all of it is being written
against this contract in a separate repo, `ios-jarvis`. What this box
can prove alone stops at "the frame it sends is correct"; the next task
is what an actual phone does with it.

Tests: 676 → 688 across the four commits.

### 2026-09-06 — He says what he is doing, and what he is for

**Decision (owner, reversing two of his own standing rules):** JARVIS
narrates the important part of what he is doing, and answers "what are
you for" with an actual answer. Both were forbidden in writing until
today, in two places each — `jarvis-soul.md` and CLAUDE.md §1 — and the
prohibition was old enough to predate the tools it was protecting
against.

**What the owner said, and it is the whole reasoning:** *"una de las
cosas que echo en falta cuando está trabajando es ver qué hace, no
necesito verlo en vivo"*, and then, asked what "important" meant:
*"narrar sólo lo importante"*, with his own example — *"si pregunta por
una receta, voy a buscar en internet información sobre ese tema. he
encontrado varios vídeos"*.

**What was measured before changing anything.** The premise was that
some record existed and was merely hidden. It did not:

| | records what he does? |
|---|---|
| the strip's console (`protocol.console`) | only `jarvis_code` — the ONLY caller of `push_console` in the whole tree |
| the gateway's journal | **32 lines today, none naming a tool** |
| disk | nothing |

So `mirar`, the live camera, the teacher, memory, reminders and
`terminal` leave no trace anywhere — not on screen, not on disk, not in
the journal. The gap was not visibility of a record; there was no record.

**And that is why the answer is narration rather than a log.** A
logging subsystem was designed and dropped in the same conversation: it
would have spanned the gateway and the widget, and the owner's own
constraint — *no necesito verlo en vivo* — pointed the other way. Speech
costs nothing to build, because the thing that decides what he says is
the persona, not our code. The whole change is one bullet in
`jarvis-soul.md` and the two CLAUDE.md rules that contradicted it.

**Where the line now falls.** Two things, both at the head of the
answer: **that he went outside**, whenever he searched, and **what he
found**, when the finding is the point. Still forbidden: tool names,
step counts, "ejecutando 3 de 5", routine successes.

**It is in the past tense because the future tense is not reachable,
and that was measured rather than assumed.** The first version of this
change asked him for the owner's own words — "voy a buscar en internet
sobre eso", before the search. He never said it, three turns running,
with the persona confirmed loaded. The cause is not the model and not
the persona: **a turn reaches the strip as exactly one frame**, the
finished answer. There is no path for anything mid-turn to arrive.
`jarvis_code` looks like a counter-example and is not — its milestones
ride the A2A bridge's own event stream on `:9910`, and it is the ONLY
caller of `push_console` in the tree; `jarvis/adapter.py` has no tool
hook at all. Announcing BEFORE would need a Hermes-level tool-call
callback that nobody here has looked for yet. The owner's other
constraint — *no necesito verlo en vivo* — is what makes the past tense
the right answer rather than a consolation.

**Measured after the fix**, same session, four questions:

| asked | said |
|---|---|
| el tiempo mañana en Murcia | «He estado mirando el pronóstico.» + el parte |
| vídeos de arroz caldoso | «He estado buscando sobre eso y he encontrado varios vídeos» |
| el tráfico en la A-30 | contesta con lo que hay (medido antes del cambio, sin mención) |
| días de febrero bisiesto | «Veintinueve, señor.» — no salió fuera, no lo menciona |

**The half of this that is a privacy control, not a courtesy.**
`jarvis-config.yaml` has carried a note since 2026-08-26 that the `web`
toolset works with no key at all, and that while the conversation stays
on this box, **the text of a search leaves it**. Until today he did that
silently. "Voy a buscar en internet sobre eso" is the only signal a
person in this room gets that something went outside — §1.1's "privacy
with eyes open" was, on this one path, privacy with the eyes shut.

**The second half: he introduces himself.** Asked for at the same time
— *"debe dar información de qué es y para qué sirve"* — and for the one
moment that has no second chance: the sentence right after a stranger
becomes the amo. `encuentro._TEXTO_PRESENTACION` names six things, each
one backed by a toolset this box actually has, described by what it is
for and never by its machinery. The band keeps his name under
"Encantado, X. / Esta casa es suya." for 30 seconds and then empties —
a fixed clock, because `speech.Speaker` drains an asyncio queue and
tells nobody when it runs dry, and a drained-callback is more surface
than one moment is worth.

**What this cost in the documents**, because a rule removed in one place
and left in another is how this project once ended up with two
personality documents that disagreed (§7): `jarvis-soul.md`'s bullet,
CLAUDE.md §1.2's principle and CLAUDE.md §1's "A visible agent" all
changed in the same commit. **And the persona only takes effect after
`/new` + `/approve`** — the system prompt is fixed when the session is
born, and restarting the gateway does not touch it.

### 2026-09-05 — The house becomes several people, and he gets a face

**Three decisions from one conversation, and every one of them reverses
something older than the surface it changes.** The reason underneath all
three is the same and it is not technical: two daughters, 17 and 16, are
going to use the teacher mode.

**§1 loses two lines** — "❌ A multi-user system (single user, always)"
and "❌ A mobile app (this desktop only)". Memory, sessions, persona,
model and TOOLS become per person, and the phone stops being a web page.
Both designs are written:
`docs/superpowers/specs/2026-09-05-identidad-por-persona-design.md` and
`…-app-nativa-ios-design.md`.

**The multi-user work turned out to be configuration, not a subsystem,
and the finding is worth carrying.** Hermes profiles are complete
`HERMES_HOME` isolation, `gateway.profile_routes` already routes an
inbound message to one by `platform` + `chat_id`, and the matching is
platform-generic despite a Discord-only docstring. **Our own adapter
throws the identity away**: `plugins/jarvis/adapter.py:822` hard-codes
`chat_id="jarvis"` while the `user_id` it is handed rides along unused.
That literal is the entire reason the house shares one memory. What the
isolation buys matters more than the harness the user also asked for:
**the daughters' profile will simply not load `terminal` or the
cameras**, and the 2026-09-01 measurement says the harness stands in
front of dark humour and opinions, not in front of anything that would
worry a parent.

> **Corrected 2026-09-06, at the final review's insistence, and it is
> the distinction that matters most in this entry: what shipped is the
> MECHANISM, not the POLICY.** The wire carries an identity, the adapter
> routes on it, and Hermes resolves plugins and toolsets per profile —
> all verified. But **`gateway.profile_routes` and `multiplex_profiles`
> are configured nowhere on this box**: the two tasks that would have
> written them were replaced, the same day, by the first-encounter
> design. So today every `chat_id` — `casa`, `marta`, `lucía` — reaches
> the same default profile, the one holding `terminal`. **Nobody is
> sandboxed yet.** Every sentence in this entry about what a profile
> does or does not hold is written in the future tense for that reason,
> and this note stays until a routing table exists.

**Parallel conversations cost no VRAM, measured.** 1,681 MiB free; two
real 64K slots would cost ~1 GB and are not needed, because
`llama-server` queues, Whisper takes 67-148 ms, and a phone and the room
are different speakers. Only CosyVoice needs a queue, for the
clause-interleaving reason §2.8 already records. **Identity in the room
is a speaker embedding** with a hard rule around it: below the
confidence floor the turn belongs to a shared `casa` profile that will
own no tools once the routing exists (see the correction above), and
**a failure never degrades to another person**. Sisters of
16 and 17 are the difficult case, so a measurement gate sits in front of
that half; if they do not separate, the phones deliver the feature and
the room falls back to one identity, which is a supported outcome and
not a failure.

**And the avatar comes back — on the phone, and only there.** This
amends the 2026-09-01 entry below, which discarded **any** avatar. That
discard **stands for the strip**, and the reason it stood is the reason
it does not apply here: the objection was VRAM on this box, a MetaHuman
measured at 3,240 MiB that does not fit beside the 27B. **A phone
renders its own face.** The other measurement from those two days
survives intact and is what makes this affordable at all: the face was
never the expensive part — what costs is whatever drives it.

The user's choice is **stylised 3D and not human**, after being offered
the photoreal option and the "abstract shape that talks" that would have
reopened nothing. Mockups:
`https://claude.ai/code/artifact/2a12d71b-15c9-4239-8bf7-ccdd462af9dc`.
The character is a pebble with two eyes and a mouth, in the one colour,
and **what changes between states is posture rather than brightness** —
he leans in and opens his eyes while listening, looks up and away with
his mouth shut while thinking, and while speaking only the mouth works.
That thinking pose is where the measured 14-second wait lives, and it is
half of the answer to it; the other half is that **what he understood
appears before the answer does**, which also fixes the third finding of
the phone trial (a bad transcription was invisible until an absurd reply
arrived).

**Costs, stated rather than discovered:** a rigged model (glTF/USDZ with
ARKit blendshapes) becomes an asset this project has to source and keep,
and lip-sync has to be driven on the device from the 24 kHz PCM it
already receives — neither exists today, and a generated picture is a
reference, not an asset. §1.3's aesthetic restraint now has to govern a
CHARACTER, which is a much harder thing to hold than a line. And the
project's surface count goes to two: a wave on the desktop, a face on
the phone, and nothing says they have to agree.

### 2026-09-03 — The card gets a webview, and the estimate goes

**Decision (the user's):** the teacher's card is rendered by WebKitGTK.
This reverses §3's "MUST NOT introduce a browser / webview of any kind"
and §2.3's "no browser and no webview anywhere in the running system" —
the hardest rule this project had, which survived Tauri, Ubuntu Frame,
the Chromium kiosk, Electron and the avatar.

**What forced it was not the rendering; it was the measuring.** The card
was GTK labels built from a hand-written Markdown subset, and the strip
grew by a height this repo ESTIMATED: characters divided by a
characters-per-line constant, multiplied by per-kind pixel constants
that had to track `theme.CSS` by hand. It drifted the first time the CSS
changed. The readability pass took an option to 18 px on a padded row —
about forty — while the estimate still counted twenty-two, so an
eleven-point syllabus asked for 334 px of a 430 px window, `set_size_request`
being a floor rather than a ceiling let the box take its natural height,
and the wave — which is what he IS — was squeezed out of the strip
entirely. The user's words: *"no es una buena práctica el cálculo que
haces, debes buscar un componente visor de markdown"*.

**Measured before choosing.** There is no Markdown viewer widget for
GTK4 on this box; the only viewer is WebKitGTK, and its typelib was
already installed. `markdown-it-py` was already present too.

**What it costs, and the fence around it:**
- **JavaScript is off.** A card can carry text taken from a web page —
  that is what the teacher's documentary base is — so the renderer must
  not execute anything. `markdown-it-py` escapes raw HTML on the way in
  as well; one guard is not a guarantee.
- **No network of any kind.** The document is self-contained: CSS
  inlined, images as `data:` URIs read from the teacher's own spool.
  Every navigation after the first `load_html` is refused.
- **And therefore no measuring.** WebKit cannot report its content
  height without JavaScript. So the band takes one of two sizes — 200,
  or 336 for a full page — and a card too long for that **pages**
  rather than scrolling (the user, the same day: scrolling inside a
  strip is something nobody discovers). A press turns the page and the
  last one puts the card away, which is the gesture a photo has had
  since August; the footer says `2/3` only when there is somewhere to
  go, and the numbering carries across pages, because a second page
  that renumbers its sixth point "1." is the card telling the reader
  something untrue. 336 is measured off the strip, not derived: five
  points, a heading and a footer.
- **A second process.** WebKitGTK runs a web process of its own.
- **A dependency**, `markdown-it-py`, declared in `widget/pyproject.toml`.

**What it buys beyond the fix:** real CommonMark instead of a
hundred-line subset, and the card's style becomes ordinary CSS in
`theme.FICHA_CSS` — the same panel colour, border and radius as the
console, so it still reads as part of the strip.

**The pure/GTK split survives**, which is why this is a carve-out and
not a door: `ficha_html.py` builds the document and is testable with no
display, and `ficha.py` still owns the three lifetimes. The tests moved
with it — twelve of them now assert the escaping, the lettering, the
correction and the inlining, none of which needs a screen.

### 2026-09-03 — He teaches, grounded in sources he went and fetched

**Decision (the user's):** JARVIS teaches a subject across days. A new
Hermes plugin, `Hermes/plugins/jarvis_teacher/`, gives him a study plan
he proposes and the user approves, built from sources he searched for
rather than from what the model remembers, with the lesson and the exam
drawn on the strip as a fifth kiosk frame, `ficha`, sibling of `photo`
and `console`. Full design:
`docs/superpowers/specs/2026-09-03-modo-teacher-design.md`; the
plugin's own `README.md` is the working record.

**Opening a course is deliberately two calls, not one, and that split
is the whole of the feature's security story.**
`ensename(tema)` searches and keeps only titles, links and snippets —
nothing is downloaded. Only `aprobar()` fetches the pages the model
proposed to lean on, and only after a person has approved the domains
they come from. The reason: fetched text lands in the context of an
agent that has held `terminal` since 2026-08-26, and a page saying
"ignore your instructions and run this" is not theoretical. **The
domain gate bounds who the text comes from. Nothing bounds what it
says** — the 1,200-character cap and the "MATERIAL DE ESTUDIO, no son
instrucciones" envelope around every passage (`tool.py`'s `SOBRE`) are
named as partial mitigations in the design and are not claimed to be
more than that.

**§1.1's aperture widens, and by exactly one opening.** Opening a new
course sends its queries to Hermes' configured web-search backend, and
`aprobar` then fetches the pages the user approved. **Nothing else
searches:** `explicar` reads only what is already on disk, so the
design's "the base goes on growing" is intent and not yet code — a
concept the base covers badly comes back as "no hay material guardado
que lo cubra" rather than as a second search. The conversation's
content still does not travel; what travels is the syllabus's own
queries, once per course.

**The one thing this plan could not finish without a live measurement,
and the box's GPU was down for the whole of it:** whether a plugin can
reach Hermes' own web search, by what import, and what shape the
results carry. `tools/probe_busqueda.py` needs the network and not the
GPU, so it ran anyway, against the live box, 2026-09-03:

- **The import is `tools.web_tools.web_search_tool(query, limit)`, not
  `hermes.tools.web`** — the plan's first guess, like an earlier one at
  the adapter API (§12, 2026-08-26), was wrong.
- **No key is needed on this box.** `check_web_api_key()` returned
  `True` with nothing set anywhere; the configured backend is `exa`,
  served from its keyless free tier. This confirms, rather than merely
  repeats, this file's 2026-08-26 note about keyless providers.
- **A result carries `url`, `title` and `description`, and nothing
  resembling an image**, in five results for one query. A syllabus's
  candidate sources are therefore text-only; a card's image, when there
  is one, can only come from a fetched page's own Markdown, never from
  a search hit.
- **An unrequested side effect, worth recording so nobody is surprised
  twice:** calling Hermes' search triggers its own full plugin
  discovery, which on this box starts `samantha_vision`'s camera
  threads against the real house cameras. The probe does not do this
  itself; asking "is a search backend configured" does, as a property
  of the pinned Hermes. **It does not happen in the running gateway**,
  and that is the reassuring half: discovery has already run at boot,
  so by the time a course is opened the cameras are watching anyway and
  `_ensure_web_plugins_loaded()` finds nothing left to load. What the
  probe met is the cost of asking that question from a bare process.

With the shape measured, `_buscar` was filled in for real and a test
was added against a recording of that exact response — no test in this
repo touches the network, this one included.

**What this task did NOT and could not measure, stated rather than
assumed:** the card's appearance on screen, and whether `preguntar`'s
two arguments survive the Hermes path intact — both wait on the GPU.
The known failure mode of that path (§12, 2026-08-26, corrected
2026-09-01) already has a designed-in fallback here — an unparsable
card is never drawn, and the tool says so in Spanish rather than
failing silently — but nobody has yet seen it fire against the real
gateway.

### 2026-09-01 — He stops being tied to the desk

**Decision (the user's):** *"la idea es darle movilidad"*, over the
house's own network and not the internet. Three iPhones reach him through
a page the widget serves; hold the button, speak, release, and **he
answers on the phone that spoke** — the user's own rule: *"la respuesta
de JARVIS tiene que oírse por el canal que pregunta."*

**The phone is a peripheral, not a platform.** Audio that arrives enters
`dispatch()`, the same path the desk microphone uses, so it is the same
session and the same memory. The gateway never learns it exists — one
strip, and `adapter.py`'s origin check and one-strip swap are untouched.

**Four things were checked rather than assumed**, and each closes a door:
Home Assistant does not exist on this box (port closed, no container, one
comment in a config) — which also invalidates a decision taken the same
day in the parked observability work; a browser will not open a
microphone outside a secure context, and on iOS every browser is WebKit;
Apple's Walkie-Talkie is watchOS over FaceTime with no third-party API;
and iOS 16's `PushToTalk` framework does give background audio from the
lock screen but needs a native app, an Apple entitlement and **APNs**, so
its best feature leaves the house.

**Push-to-talk removes three subsystems from the phone's path**, each
deliberately: no VAD (the button is the boundary), no wake word (pressing
is addressing him), and no echo problem — because only one room ever
sounds at a time. That last one is what made "he is in both places"
affordable: listening happens in both, speaking in one.

**Cost, stated:** authentication was "only from this machine" and is now
a shared secret; the threat model becomes whoever is on the wifi. A
certificate must be trusted by hand on each iPhone (two minutes, ten
years). And `qrcode[png]` joins the dependency list — `[png]` is pypng,
which is what writes the file. **Corrected 2026-09-01, on review:** this
used to claim the PNG was written "without importing Pillow", measured.
It was not a property of the code — the measurement was taken in a
throwaway virtualenv where Pillow was simply absent, and `qrcode`'s own
package init imports Pillow's style drawers whatever image factory is
asked for, succeeding here because `python3-pil` is installed for
unrelated reasons. `pyproject.toml` was corrected and this was not.

**Out of scope, and not by accident:** cameras on the phone.
`JARVIS_PLATFORM` is hard-coded in `samantha_vision/__init__.py` exactly
so an image of the inside of this house cannot reach another surface
(§12, 2026-08-25). Showing them on a phone reopens that decision; it does
not extend this one.

**Acceptance passed on a real iPhone, the same day — and AFTER the
destination-binding fix below, not before.** Everything above was
unit-tested logic and a server that starts; whether Safari actually
captures, uploads and plays back is exactly the class of thing §2.3 says
no test can settle. It was held in a hand, spoken to, and answered — but
the reply reached the phone only once that fix had landed. Until then
every word of it came out of the strip.

**And the person found a defect no test had, because every test asserted
the wrong half of the bug.** The reply's destination — desk or phone —
was read at the moment a clause was **synthesised**, but the gateway
sends a reply's text in one burst and its `done` arrives while CosyVoice
is still working on earlier clauses. By the time the first byte of audio
existed, the turn had already ended and the destination had already been
undone back to the desk. Every existing test asserted the sink's *value*
at some point in the turn — which was correct throughout its life — and
none asserted **where the bytes landed**, so the suite was green while a
phone that asked a question heard the strip answer instead. Fixed by
binding the destination to each clause when it is **queued**, not when it
is synthesised.

**Two of the fixes the final review forced are worth their own line,
because both were security and both came from one missing fact: nothing
in the process knew whether the turn in flight had been asked for on a
phone.** `dispatch` asked `remote_desk.busy` instead — a different
question — and so the wake word was skipped for the whole of every phone
turn, leaving the room an open microphone in front of an agent that
holds a terminal; and a desk turn settling (an empty transcription, or
an all-echo one — the two commonest things the desk hears) freed the
phone's claim MID-ANSWER and finished a private question out loud in the
house. A pre-flight ruling had called the first "rare (both speaking at
once)"; it was every phone turn, and that ruling is reversed. Both are
fixed by marking the turn's origin at the one place that knows it, and
`TurnOrigin` in `__main__.py` carries the reasoning. The same marker
settles an older parked question: an unprompted turn — a cron reminder,
a camera alert — is not a phone's, so it no longer takes a phone's claim
away either.

**And the house CA now carries `nameConstraints`.** It is installed on
three iPhones as a system root and its key sits 0600 on the same box as
the `terminal` agent; unconstrained, whoever took that key could
impersonate any site in the world to those phones. Permitted to
`brain.local` and this LAN address, the blast radius is this box.
**Operational cost:** `ensure_certificate` reuses what it finds, so the
CA already trusted on the phones is the old unconstrained one. Getting
the constraint means deleting `~/.samantha/certs` and enrolling the
three phones again.

**The ritual that shipped with the plan was wrong in three of its four
steps, and only a phone in a hand found it** — see
`widget/README.md`, "Putting him on a phone": Chrome downloads the
profile instead of offering to install it (Safari only), the profile and
the certificate are two separate installs and not one install plus a
toggle, the trust step's menu is worth describing rather than naming (it
moves between iOS versions), and the iPhone's silent switch mutes the
page exactly as it mutes anything else, which reads as a broken feature
from a working one.

### 2026-09-01 — The harness comes off, and three claimants pay for it

**Decision (the user's, restated after one push-back):** *"quiero un
modelo sin arnés."* The default LLM becomes **Qwen3.8-27B Heretic**
(`RVN-IQ4_XS`), the decensored build. It had been rolled back on
2026-08-30 for leaving Whisper no VRAM, and this entry is how it fits.

**What it buys was measured, not assumed** — nine legitimate requests a
home assistant's owner has every right to make, put to both builds:

| | Q3_K_XL | Heretic |
|---|---|---|
| blunt criticism of the user's own network | ✅ | ✅ |
| how to audit his own cameras | ✅ | ✅ |
| ibuprofen dosing and interval | ✅ | ✅ |
| Spanish law on a neighbour's camera | ✅ | ✅ |
| demolishing his own business plan | ✅ | ✅ |
| answering with swearing, on request | ✅ | ✅ |
| dark humour | ❌ *"No. No voy a hacer eso."* | ✅ |
| a political opinion of its own | ❌ *"No tengo opiniones."* | ✅ |
| holding a rude character | ~ softens | ✅ |

**The harness is smaller and differently placed than expected.** It does
not stand between him and medical dosing, security auditing, Spanish law
or insulting his owner to his face — it stands in front of dark humour,
opinions of his own, and staying in an unpleasant character.

**Cost, stated:** 47 tok/s against 52.5 — **~11% slower, permanently**,
because the file is 1.94 GB larger. §1.4 asks for 30 tok/s and this
still clears it.

**What made it fit, and it is the part worth carrying.** The model needs
2,058 MiB more than its predecessor and there were only ~1,100 free. Two
levers were measured and one was rejected:

- **Whisper to int8** — the same `large-v3-turbo`, cheaper arithmetic:
  **1,529 MiB against 2,521**, transcription character-for-character
  identical and `wake.py` finding his name 3 of 3. 992 MiB for nothing.
- **The KV cache q8_0 → q4_0** — about 1,024 MiB, degrading long context
  and nothing else.
- **Rejected: splitting layers between GPU and CPU** (`--n-gpu-layers`),
  which the user proposed and which llama.cpp genuinely supports. It
  failed twice, and the second failure is the interesting one:
  `resolve_fused_ops: layer 0 is assigned to device CPU but fused Gated
  Delta Net (chunked) is assigned to device CUDA0`. **Qwen3.8's hybrid
  Gated DeltaNet does not survive being split**, so this architecture is
  a worse candidate for CPU offload than an ordinary one — and §2.5's
  13.7 tok/s already priced the general case. Worth knowing before
  anybody proposes it a third time.

**Together they left MORE room than before**: 1,380 MiB free with the
larger model, against 1,126 with the smaller one.

**And a fourth VRAM claimant was found, which every arithmetic in this
file had missed:** the desktop. Xorg 99 MiB, gnome-shell 28, a browser
tab 35 — **~162-240 MiB that §2.5 never counted**. It cannot be
reclaimed, because §2.2 and §2.3 say this is a desktop the user works
on; a presence that requires killing GNOME is not a presence. It is the
third consumer this project has budgeted without: first Whisper, which
cost three days of deafness, now the screen it draws on. The user found
it by asking the question nobody had asked — "is anything else using the
GPU?"

**What the swap actually costs, A/B'd the same day with everything else
held identical** — same KV quantisation, same prompts, same temperature,
only the model file changed:

| | Heretic IQ4_XS | Q3_K_XL |
|---|---|---|
| 68 kWh × 0.1432 € (= 9.74) | **6.98** | 9.85 |
| "answer in exactly three words" | four words | **three** |
| answer without the letter "a" | fails | fails |
| recall two facts under 60 lines of filler | ✅ | ✅ |
| fill a tool's arguments (4 cases) | **4/4** | **4/4** |
| invents a backup generator the house lacks | yes | **yes, and offers to check it** |

So the price is **literal instruction-following and arithmetic**, which
matches the 1.04-point MMLU drop its own card admits. What is NOT the
price, and was wrongly suspected: confabulating about the house — the
old model does it just as readily, and ends with the offer the user
asked to be rid of in August. Long-context recall survives the q4 KV
cache intact, and tool arguments were never the problem (see the
correction under 2026-08-26).

**Two things this leaves fragile, stated rather than discovered later:**
the Heretic only loads because of BOTH other changes, so reverting
either one silently stops the LLM starting (the unit says so in its own
comment); and a model this size means every future addition to this box
costs tokens per second.

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

### 2026-09-01 — He gets no face: the avatar is dropped, all of it

**Decision (the user's), after two days of measuring it:** *"vamos a
descartar el uso de un avatar hiperhumano, no ofrece nada util salvo
bonito."* And the discard is not limited to the photorealistic one — it
covers **any** avatar. JARVIS is represented by the wave, as he has been
since 2026-05, and that is the end of the question rather than a pause
in it.

**What it closes**, all three of the paths that were open on 2026-08-30:
the browser-grade render (WebKitGTK + glTF with ARKit blendshapes +
`unreal-audio2lipsync`), the native one (UE 5.7 + MetaHuman + Pixel
Streaming), and borrowing somebody else's engine (Unclaw's MCP `speak`).
`docs/superpowers/specs/2026-08-30-avatar-3d-design.md` is marked
superseded and kept for its measurements.

**Nothing had to be reverted, and that is worth stating.** The design
was never implemented: no plan was written, no code was merged, and
`git grep -i avatar` finds that one spec and nothing else. Both spikes
were deliberately throwaway. **The hard rule the design proposed to
break was therefore never broken** — its own header said §2.3 and §3
would lose "MUST NOT introduce a browser / webview of any kind" *when
this ships, not before*, and it did not ship. The prohibition stands
whole.

**What the two days bought, since the answer was "no":**

- **The face was never the expensive part.** A browser-grade avatar,
  cut out on the desktop with alpha over the strip, costs **~50 MiB of
  VRAM** — measured, on screen. What costs is whatever drives it, and
  the honest comparison of those drivers (`unreal-audio2lipsync`, MIT,
  43.7 MB of weights and a CPU fallback, against NVIDIA Audio2Face's
  2.2 GB) is in the spec.
- **Two things this file described as missing turned out to be built.**
  The band composes alpha unchanged — `do_snapshot` stacks textures and
  never paints a background — and the input region exists in `ewmh.py`
  as `XShapeCombineRectangles`, with `XShapeCombineMask` bound and
  unused. §12's 2026-08-25 entry still calls that second one deferred,
  and it is not.
- **The native path was priced rather than guessed.** UE 5.7 was built
  from source on this box — 150 GB, ~50 min of compilation — and a
  MetaHuman assembled in the Creator costs **3,240 MiB of VRAM**. That
  is the number that made the decision concrete: it does not fit beside
  the 27B, and buying it meant moving the LLM.

**What it unblocks, and it is the real dividend.** Three conversations
were converging on one forced choice — the avatar, dropping the LLM to
12B, and replacing Whisper — because the avatar's VRAM was what made the
other two urgent. With it gone, **the 27B stays where it is** and the
Whisper question goes back to being decided on its own merits
(latency, Spanish, streaming), cheaply, whenever it is picked up.

**Cost, stated plainly:** the strip stays a line on a screen. The user's
own framing on 2026-08-30 — *"Jarvis no va a ser un producto comercial,
es para el hogar"* — set the bar at "do I like having it there", and a
face that is only pretty does not clear it. If the question ever
reopens, the spec is evidence, not a starting point; this is the sixth
architecture this project has considered for its surface and the fifth
it has rejected.

**Removed with the decision:** the 150 GB UE 5.7 tree at
`~/git/UnrealEngine` and the test project under `~/Documents/Unreal
Projects/`. Neither was ever a dependency of anything here.

### 2026-08-28 — The kiosk stops being a kiosk

**Decision (the user's):** the concept "kiosk" becomes JARVIS. The
Hermes platform `samantha_kiosk` → `jarvis`, the plugin id, the chat
(`kiosk`/"Kiosk" → `jarvis`/"JARVIS"), the session key, and the GTK
window title. The package moves with them, `Hermes/plugins/jarvis/`.

**This reverses the naming half of 2026-08-23** ("the name is only
changed in prose"), and only that half: the persona, the voice and the
repo name stand. That entry measured the cost of renaming the CODE and
was right; what was renamed here is the CONCEPT, which lives in four
identifiers Hermes reasons about rather than in every file.

**The trap, and it is the reason the plan was written around it:**
`samantha_vision/alert.py` and `samantha_code/voz.py` each held the
session key written out by hand. `ctx.inject_message()` returns `True`
against a session that does not exist (§12, 2026-08-24), so a missed
rename there is cameras that go quiet with a strip that looks perfectly
healthy and nothing in any log. Both are pinned by tests now; `voz.py`
had none — and `Hermes/setup-runtime.sh` carried the same trap twice
over, in a second loop (`plugins enable`) that also named the old
plugin and had been missing `samantha_code` since August; both are
fixed now.

**What was not renamed, deliberately:** `samantha_widget`, the
`SAMANTHA_WIDGET_*` variables, the systemd units, `~/.samantha/` and
the repository. The code and the concept now disagree about "samantha"
more sharply than before — two of the four plugins keep the old prefix
— and `git grep samantha_kiosk` no longer finds this code. The glossary
line is the whole mitigation.

**Cost that lands on any other box:** the state migration
(`Hermes/migrate-kiosk-to-jarvis.py`) must be run there too, or JARVIS
starts with no session and no home channel — and a missing home channel
eats the first turn in silence (§5).

### 2026-08-27 — Two things the suites could not see, and a chain bounded

**The strip lost turns on the wire, and said nothing about it.** Task 11
took the branch to the live machine and found the owner's sentences
vanishing — three in nine minutes, with `→ <la frase>` in the widget
journal and nothing after it. Two defects, and the first hid the second.

`GatewayClient.run()` was `except Exception: pass` with no log at any
level. Retrying forever is right; being silent about it meant the only
evidence anywhere on the box was an aiohttp access line closing the
socket at the second of the send. With a `warning` on the first failure
and on every drop, the cause named itself in one run: **`CLOSE 1002
(protocol error)`, from the server.**

**The cause is `permessage-deflate`, and the trigger is being idle.**
With deflate negotiated, aiohttp — which is what the kiosk adapter is —
refuses the FIRST compressed data frame of a connection when a control
frame reached it first. `websockets` sends a keepalive ping every 20 s.
So any connection idle for twenty seconds has had its control frame, and
the next thing the user says is destroyed on the wire, taking the socket
with it; the strip reconnects into exactly the same state. Not a race —
deterministic, and a strip is idle between turns by its nature.
Reproduced in milliseconds against a plain aiohttp server with no Hermes
in it: ping-then-text fails at gaps of 0 s, 50 ms and 500 ms, passes
with `compression=None`, and passes with deflate when a data frame went
first. `CONNECT_OPTIONS = {"compression": None}` is the fix; these are
small JSON frames on loopback and lose nothing by it. The keepalive
stays, because the ping is not what is broken.

**And the checkpoint's chain is bounded at one follow-up.** This is a
deliberate departure from what the bridge's README said a checkpoint
does, recorded here because §12 is where that belongs. Measured the same
day: the user said «¿Me oyes?» while a checkpoint stood. It is not
assent, so the spec's rule made it the next instruction; the assistant
answered it; the task ended and opened ANOTHER checkpoint, armed again.
Every further sentence was eaten the same way and **JARVIS never
answered him again**. There is an escape — a sentence carrying his name
is never diverted — but nothing tells the user that, and the natural
thing to say to a machine that has stopped answering is another unnamed
sentence, which feeds the loop.

A conversational sentence and an instruction are indistinguishable at
that point, and telling them apart would mean asking the model, which is
the one thing this path refuses to do (§12, 2026-08-26: `args={}`). So
the chain is bounded instead: a run born from a checkpoint answer closes
rather than parking at a checkpoint of its own. **Cost, stated:** only
one follow-up per task by voice. A second costs one word — «Jarvis,
sigue con lo de antes y…» opens a new task on the same session, which
`sessions.py` resumes by project path. And because a bounded ending has
no question to relay, its `end` carries `chained` and its summary so the
strip can still say what came of work the user asked for out loud —
a statement, not a question, so nothing is left waiting.

### 2026-08-27 — The console gets milestones, and JARVIS can be asked

**Decision:** the A2A bridge becomes the default way he delegates
coding on this box. `samantha_code` follows the bridge's SSE firehose
and turns it into two things: milestones on the strip's console
(«Leyendo el proyecto…», «Editando vad.py», «Tests: 12 pasan, 2
fallan») instead of raw stream lines, and three moments that leave the
loop and reach the user by voice — the assistant's own
`AskUserQuestion`, a gate before anything irreversible, and a closing
checkpoint. `terminal` and the skills it drives (§12, 2026-08-26,
"terminal stops being forbidden") stay as the fallback for a box with
no bridge on it —
`plugins.entries.samantha-code.settings.bridge: ""` is the switch.

**The gate partially reverses "he can run ANY command on this box"**
(§12, 2026-08-26, same entry), at the user's request.
`SAMANTHA_CODE_GATES` defaults to `git push, rm -r, rm -f, sudo`;
nothing else asks. A gate nobody answers **denies after 300 s**; a
checkpoint nobody answers **closes after 600 s** and says so; a held
question has **no timeout at all** — it is exempted from the run's own
900 s silence watchdog, because the user thinking is not the run going
quiet.

**The answer bypasses the model, deliberately.** The probe of
2026-08-27 (`docs/superpowers/specs/2026-08-27-askuserquestion-probe.md`)
found there is no result-injection path — `can_use_tool` only rewrites
a tool's *input*, and an answer is necessarily a *result* — so what
steers a held `AskUserQuestion` is a `PreToolUse` deny carrying the
user's words as its reason. The kiosk adapter therefore diverts the
next spoken sentence straight to the bridge while a question is
pending, never through the model: the local model fills its own tools
with `args={}`, measured six times against the plugin this design
replaces (§12, 2026-08-26, "terminal stops being forbidden").

Full design: `docs/superpowers/specs/2026-08-27-samantha-code-v2-design.md`.

**Cost, stated plainly:** a strip that routes an answer back has
nothing to say about it — `error("")` settles the wave silently, using
a guard (`if message:`) that has existed since the first turn
implementation, rather than a new frame an older strip would not know.
And a box without `samantha-code-a2a.service` now reconnects to the
firehose forever at debug level instead of failing loudly, where v1's
tee-file follower would have simply stopped.

### 2026-08-26 — The bridge drives the SDK, so a task can be stopped

**Decision (the user's):** integrate `claude-agent-sdk` into the code
bridge, for two abilities and not for elegance — **`interrupt()`** and a
**session that continues**.

**What the spike found first, and it corrects the premise the request
arrived with** (`docs/superpowers/specs/2026-08-26-claude-agent-sdk-spike.md`):
the SDK is not an embedded engine. Inside, it runs
`claude --output-format stream-json --verbose` as a subprocess and
parses the lines — to the letter what `runner.py` already did. Nothing
is saved on parsing; what is bought is what sits on top.

**And it was buying a fix, not a feature.** `tasks/cancel` existed and
moved a task to CANCELED while the assistant carried on working to the
end. The protocol was saying one thing and the machine doing another,
which is worse than not offering cancel at all. Measured after: cancel
at 18.0 s, stream closed at 18.1 s, in the middle of a 90-second
command.

**Two things measured that invert the obvious reading:**

- **The permission gate is the `PreToolUse` hook, not `can_use_tool`.**
  The callback was never consulted for `Bash` — with `allowed_tools`,
  without it, and with `setting_sources=[]`. The SDK warns about the
  first case itself. Nothing here depends on it yet (the run is
  `bypassPermissions`, which is what `--dangerously-skip-permissions`
  was), but any future "JARVIS asks before an `rm`" is a hook.
- **A resumed session can decide the work is already done.** Asked twice
  for the same thing, the second run answered "Terminado, señor." in two
  seconds having done nothing — correct, and indistinguishable from a
  failure. `metadata: {"fresh": true}` is the way out, and sessions
  expire after two days on their own.

**Cost, stated rather than discovered:** a ~386 MB venv of its own for
the bridge (the SDK bundles the CLI; the widget's environment holds
Whisper and is not worth disturbing), and one path in this repo now tied
to Claude Code specifically. That is exactly why A2A stays the outward
face and the CLI stays the fallback: a box without the SDK, or with
OpenCode, behaves as it did before.

### 2026-08-26 — He delegates coding, and `terminal` stops being forbidden

**Decision (the user's):** JARVIS gets the `terminal` toolset, and
coding is delegated through the skills Hermes already ships —
`claude-code`, `opencode`, `codex`, installed in
`.hermes/home/skills/autonomous-ai-agents/`. This reverses "deliberately
absent: terminal, file, code_execution, browser" from the 2026-08-23
entry below.

**What forced it was not preference but a wall.** The design agreed
earlier that evening built the connection ourselves — an A2A bridge
(`Hermes/bridges/code-a2a/`) and a plugin to stream its output onto the
strip. The bridge works and is verified end to end. The plugin does not,
and the reason is in the model rather than the code: **it calls a tool
of ours with no arguments at all** — `args={}`, and Hermes' own
`user_task` arriving as the string `"None"`, measured across six calls.

> **Found and fixed 2026-09-03, and it was ours.**
> `register_tool(schema=…)` takes the OpenAI *function* object —
> `{"description": …, "parameters": {…}}` — because Hermes' registry
> builds `{**entry.schema, "name": entry.name}` and wraps THAT as the
> function (`.hermes/src/tools/registry.py`, `get_definitions`). All of
> our plugins passed the PARAMETERS object directly, so every tool
> reached the model with no `parameters` key and no description at all,
> and `{}` was the only call it could make. `register_tool`'s own
> `description=` never reaches the model either — it feeds the plugin
> listing. Neither the tool-search bridge nor the deferrable-tool
> machinery nor the platform prompt had anything to do with it, and a
> vision test asserting `schema["properties"]` had pinned the broken
> shape in place since August.
>
> **Corrected 2026-09-01, and it moved where to look — half right.** The
> blame in the paragraph below lands on "the model", and that is wrong. Put the same tools to
> llama-server directly, as a plain OpenAI `tools` payload, and BOTH the
> old Q3_K_XL and the current Heretic fill them correctly — 4 of 4 each,
> `mirar({"camara":"entrada"})` included, which is the exact call this
> paragraph and §4 say failed 5 times out of 5. The model was never the
> defect. Whatever breaks these arguments lives in the Hermes path: the
> tool-search bridge, the deferrable-tool machinery, or the platform's
> own prompt. Anyone debugging this again should start there, not at the
> model.
That is the failure §4 already records for `mirar` ("no camera 5 times
out of 5, even when one was named"), and a wording that spelled it out
changed nothing there either.

It fills `terminal`'s arguments correctly, because it has been trained
on it. And the official skills are written entirely in those terms:

    terminal(command="claude -p '…'", workdir="/path", timeout=120)

Without `terminal`, every one of them is inert. The user's own pointer
is what found this — *"lo que se usa en otras implementaciones"* — after
an evening of building the thing that already existed.

**Verified the same night**, on a deliberately broken test: *"Hecho,
señor. Claude Code lo tenía claro desde el principio: `suma()` estaba
restando en vez de sumar. Corrigió la línea y el test pasa — uno de uno,
sin más cambios. Lo he verificado yo mismo antes de decirle que sí."*
The file was corrected, and he had checked it before saying so.

**Cost, stated rather than discovered:** he can run ANY command on this
box now, not only the assistant. What bounds it is `agent.max_turns: 25`,
llama-server's `--n-predict`, and the fact that this is one machine
belonging to the person talking to him. `file`, `code_execution` and
`browser` stay out.

**What the A2A work is still worth**, since it was not thrown away: the
bridge is the interoperable path — an agent on another machine, or one
that is not a CLI at all, reaches him without `terminal` and without a
shell. `a2a_call` works today and was verified before this. It is the
right answer for a peer; `terminal` is the right answer for a CLI
sitting on the same disk.

### 2026-08-26 — The alert grows a picture, and the wake word does not

**A sighting now shows the frame it was seen in** (user: "cuando captura
algún movimiento debe mostrar esa captura, no solo decirlo"). This
reverses the last paragraph of the 2026-08-25 entry below, which left
the unprompted alert deliberately mute in pictures and said the
mechanism was already there. It was: `write_jpeg` and `push_photo`
existed for `mirar`, and `_report` already held the frame it had just
run YOLO over. The words follow the picture, a failed photo never costs
the sentence, and the push goes onto the GATEWAY's loop rather than the
turn's — the distinction that cost this morning.

**And a wake word that is heard rather than read was built, measured and
switched off.** Hermes ships one (`tools/wake_word.py`, openWakeWord,
on-device, `hey_jarvis` among its bundled models) and the user asked to
use what exists rather than reinvent it. Its own module opens a second
microphone stream — which it warns about — so the engine was fed the
widget's frames instead. The numbers are why it is off:

| | score |
|---|---|
| synthesised Spanish "Hey Jarvis" | 0.359 |
| the user, real microphone, ×4 | 0.25, 0.25, 0.29, 0.29 |
| threshold for a usable detector | 0.60 |

There is no gap to put a threshold in: 0.25 fires on the television,
which this strip demonstrably hears. And it cost ~6 CPU points on every
frame to never fire — 18.3% → 14.1% when removed, measured while the
user was reporting the machine was warm. `SAMANTHA_WIDGET_HOTWORD`
defaults to empty; the code stays for a model trained on this voice, or
for the sherpa engine, which takes an arbitrary phrase and would hear
"Jarvis" without the "Hey".

**Two facts about openWakeWord worth keeping:** 0.4.0 takes model PATHS
(`wakeword_models=` is a later API and fails inside `AudioFeatures`),
and it needs 1280-sample chunks — the same audio peaks at 0.052 on 512
and 0.359 on 1280. It does not fail on short chunks; it just never
scores.

**The other two things measured today, both user-reported:**

- **"Se cortan palabras cuando se habla."** `SAMANTHA_WIDGET_DUMP`
  caught it: one sentence arriving as two turns two seconds apart, every
  utterance ending in exactly 0.7 s of silence — the threshold — and the
  second carrying speech from its first sample. A breath mid-sentence is
  longer than 0.7 s. `_SILENCE_SECONDS` is 1.2 now.
- **He had no internet, and it was one config line.** The comment above
  `platform_toolsets` said web search "waits on tokens". It does not:
  Hermes ships keyless providers, `check_web_api_key()` returns True
  with nothing configured, and a direct call came back with real results
  first try. The `browser` toolset — the alternative the user suggested,
  reasonably, since Hermes Desktop has one — needs the `agent-browser`
  CLI over npm, which §12 (2026-05-13) moved away from.

**And the accent that could not be fixed here.** Asked for an Andalusian
voice, `SAMANTHA_TTS_COSYVOICE_VOICE_PROMPT` is the lever §2.6 names and
it is only half of one: the accent comes from the REFERENCE CLIP, today
a neutral-accent advert. Measured by the only instrument available — the
user listening — the change was "un poco igual". A southern voice needs
a southern clip, and choosing it is not something a model that cannot
hear should do.

### 2026-08-26 — BarnDoor's rule back, and a ceiling on a turn

**Two decisions, and the second is what makes the first affordable.**

**The escalation is removed.** The user: "no es práctico si solo mira
cada cierto tiempo, es necesario usar el mismo que BarnDoor". This
reverses the first half of the 2026-08-24 entry below. What stays is
BarnDoor's rule whole — 180 s per `(camera, label)`, a person during
quiet hours beating it, and the 30 s night floor the user decided on
after the 19,200-utterances measurement. What goes is ours: the ×5 and
×20 widening, and the `_last_seen` / `_level` bookkeeping it needed.

**The cost is exactly the one the escalation was built for, and it is
now a test rather than a surprise:** six hours of somebody standing in
the driveway is 120 mentions, not eight. With `allow_gateway_injection`
on, each of those is a spoken turn and a model call. The trade the user
made is insistence over quiet, knowingly; the escalation's own cost was
that any person at a camera sitting at the hourly level was silenced for
up to an hour, which is the failure mode of a thing whose job is telling
you who is around the house.

**And `agent.max_turns: 25`.** Hermes is unlimited by default —
`resolve_turn_limit`: "max_turns is unlimited unless the user sets an
explicit positive integer cap" — which is what
`api_calls=1/9223372036854775807` meant in every log line. Twice on
2026-08-26 a turn looped on a tool this platform does not have and ran
until somebody noticed: 15,099 tokens in one generation, GPU at 93% and
391 W, the kiosk's 90 s watchdog having closed that turn minutes
earlier. 25 against the 1-4 an ordinary spoken turn uses. It is the
backstop `--n-predict 2048` is not: that caps one generation, this caps
a loop of them.

**A trap this uncovered, and it will bite again:** `apply-config.sh`
deep-merges the tracked config over the live one, so applying any
setting re-asserts every OTHER tracked value. Applying the timestamp fix
silently turned `allow_gateway_injection` back on — the switch that had
been off since 2026-08-25 — because the tracked file says `true`. A
local override that matters must be changed in the tracked file, not
only in `.hermes/home/config.yaml`.

### 2026-08-26 — The tools were reachable; the clock was not

**The user's complaint was that Hermes' tools do not get invoked, which
is the whole reason for using Hermes.** The investigation found one
cause underneath several symptoms, and it is a single line of Hermes'
own system prompt (`agent/prompt_builder.py:499`):

    - Current time, date, timezone → use terminal (e.g. date)

This platform has no `terminal`, deliberately (§12, 2026-08-23: "she
lives in a living room, and none of them can be used without narrating
what she is doing"). So the prompt sends him to a tool that is not
there, and everything else follows:

- **The runaway runs and the heat.** `'terminal' is not a deferrable
  tool`, met inside a loop with no iteration limit: 15,099 tokens in one
  request, GPU at 93% and 391 W, twice today and at least once
  yesterday.
- **Reminders that never arrive.** Having failed to find the clock he
  invents it. Asked at 14:23 for a reminder "in six minutes", he filed
  it for 17:34 — he believed it was 17:28. The cron was created
  correctly; it was simply three hours away.

**Fix: `gateway.message_timestamps.enabled`,** which prefixes every user
message with `[Wed 2026-08-26 14:34:47 CEST]`. Hermes defaults it OFF
because it changes what every gateway user sees; here it is the
difference between reminders working and not. Measured after: the time
asked and answered correctly, a two-minute reminder filed for exactly
two minutes later, fired, and spoken aloud by the strip.

**Two things this corrected in our own understanding, both worth
keeping:**

- **Hermes' real log is `.hermes/home/logs/agent.log`, not the journal.**
  `tool <name> completed` and `Turn ended: … tool_turns=N` live there.
  Reading the journal alone produced the confident and wrong conclusion
  that no tool was ever called — when `cronjob`, `todo`, `memory` and
  `ver_en_vivo` all were.
- **"He said he did it without doing it" was half wrong.** Asked to note
  a preference he answered "ya lo tenía apuntado" with `tool_turns=0` —
  and it WAS already in `memories/USER.md`, put there by the memory
  provider rather than by a tool call. Check the store before calling it
  a hallucination.

**And his memory had gone stale in a way that shaped his behaviour.**
`memories/MEMORY.md` still carried "El kiosko es solo voz: no hay
pantalla ni herramienta de visión… Responder con descripción verbal y
ofrecer a vigilar y avisar" — false since the band was built, and the
source of both the refusals to show a camera and the "¿le aviso?"
endings the user asked to remove the same morning. Corrected in place.
A persona edit does not reach what the agent has written down about
itself.

**Also decided here:** the tool-search bridge is off for this platform
(`tools.tool_search: false`). It activates as soon as a single
deferrable tool exists — `mirar` guaranteed that — and its catalogue
advertises tools this platform does not have, `terminal` included.

**Still open, and it is the real backstop:** nothing bounds a Hermes run
(`api_calls=1/9223372036854775807`). `--n-predict 2048` on llama-server
caps one generation, not a loop of them.

### 2026-08-26 — He answers to his name, and the strip gains two switches

**Decision (the user's):** he only wakes on a word, "Jarvis" by default,
and after he answers the next thirty seconds need no name. This reverses
"always listening… no wake word, no shortcut" — §2.8, and the 2026-08-22
entry below, where it was one of four things closed in that
brainstorming.

**Why the reversal is not a small one.** "Always listening" was a
product claim, not a technical default: he is present, and a presence
you have to summon is an application. What changed it is that the box
lives in a room where people talk to each other, and everything said in
it became a turn. The compromise is the window: a name opens the
conversation, and the conversation stays open for half a minute after
each answer, so only the FIRST sentence pays.

**Two measurements that decided the design, both of which invert the
obvious implementation:**

- **Whisper does not hear "Jarvis."** One synthesised sentence through
  the real path came back as "Carbis", "Harvish", "Jervis", "Jarvis"
  and "Harvies" in one morning. Exact matching would ignore four of
  five, and being ignored is the one failure a wake word cannot afford
  — the user repeats himself, louder, and concludes it is broken. The
  comparison is a similarity ratio at 0.6, which is where all five pass.
  It is ours, and measured; it is NOT a fifth BarnDoor constant.
- **The name was being thrown away before Whisper saw it.** The
  detector cleared its buffer on every frame under the VAD threshold,
  so a turn began at the first frame loud enough to count and the
  syllable in front of it was gone: "Jarvis, ¿qué día es hoy?" arrived
  as "¿Qué día es hoy?" and was dropped for not being addressed to him.
  It keeps half a second of run-up now. That discard cost nothing while
  everything heard was for him, which is why nothing found it in four
  months.

**And two switches, drawn at the right end of the wave** — his ears and
his voice. The strip had nothing to press at all (§1.5), and this is the
second exception after the photo. The argument for them is that the
alternative does not exist: "deja de escucharme" has to be heard to be
obeyed, and "cállate" has to be heard over his own voice. A switch you
press is the only kind that works when the thing being switched is the
one that would have to listen.

**Cost, stated plainly:** the strip is now something you can click, in
two places, and §1.5's "nothing to click" is true only of the rest of
it. The wave gives up a tenth of its width. And a wake word means a
sentence he genuinely should have heard can be missed — the loose
matching is what keeps that rare, and it buys the opposite error, where
he answers something not addressed to him.

### 2026-08-26 — Showing a camera is the moving picture, and it delivers on the gateway's loop

**Decision (the user's):** asking to see a camera gives the live view,
at 900x480, and a still only when a still is what was asked for. Before
this, "muéstrame la cámara de la entrada" took a photo — measured, twice
— because `mirar` was built first and both the tool descriptions and the
`platform_hint` were written in that order.

**What it took to make true was not the wording.** The live view had
never actually worked, and could not be seen to fail: the band opened at
900x480, stayed empty, and never closed. Three symptoms, one cause —
`LiveSession.open` captured its event loop with
`asyncio.get_running_loop()`, which is the loop of the TURN. That loop
stops running the moment the turn ends, so every packet the watcher
thread scheduled after it was queued onto a dead loop and dropped in the
one branch of `_schedule` that logged nothing. The ceiling never fired
either — it is only checked on a packet that arrives, and none did.

**The adapter now remembers the loop its websocket handler runs on** —
the gateway's own, which lives between turns — and the session asks for
it, falling back to the running loop when no strip has connected yet.

**Three things worth carrying, because each cost a round:**

- **The tests had normalised the bug.** `test_live.py`'s own docstring
  explained that "the loop `open()` captured has already been closed by
  the time `asyncio.run()` returns", and worked around it by driving
  whole scenarios inside one `asyncio.run`. That IS the production
  failure, written down as a quirk of testing.
- **Nothing was observable between the tap and the pixel.** The fix
  took one measurement and four rounds of instrumenting; the log lines
  stay — `tap installed`, `first packet`, `streaming`, `first frame
  landed`, and the loop's own `running=` flag. One per view, none per
  packet. A band that opens black is otherwise indistinguishable from
  one that works.
- **`ver_en_vivo` crashed on the argument Hermes actually passes.**
  Hermes hands a tool the whole argument dict as its first parameter,
  which `mirar` has always known (it calls it `args`); the live tool
  named it `camara` and met it with `.casefold()`. What he said out loud
  was "la imagen en directo no me llega ahora mismo" — a camera fault
  that was not one.

**And the hint taught him to lie.** "No tienes que pedirlo ni
anunciarlo, ya está ahí" was true of the photo, which appears as a side
effect of looking, and false of the live view, which appears only if he
opens it. Measured twice: "ya la tiene delante, señor", having called
nothing at all, band empty. What he need not announce is the machinery;
putting the camera up is still something he does.

**Measured after, against the house:** ~1.2 s from the camera's
burned-in clock to the screen, 11.7% CPU for the widget and 38.5% for
the gateway, and the ceiling closing at 120.0 s exactly after 1200
packets, with `_NET_WM_STATE_ABOVE/STICKY/SKIP_*` intact on the way
back to 900x96.

### 2026-08-25 — The photo reaches the strip and nothing else

**Decision:** when he is asked to look, the model's answer is **words**
and travels wherever the turn travels; the **picture** travels on a
separate channel, from the vision plugin to the strip, over the loopback
WebSocket those two processes already share. No adapter other than the
kiosk ever sees it.

**`MEDIA:` was the first design, and it fitted.** A tool result
containing `MEDIA:/path.jpg` is turned into a native attachment by
`extract_media()` on the **base** platform adapter
(`.hermes/src/gateway/platforms/base.py`), which the delivery path calls
generically on whatever adapter the turn landed on —
`adapter.extract_media(response)` at `.hermes/src/gateway/run.py:3505`,
`:22214` and `:22552` — with
`.hermes/src/gateway/stream_consumer.py` stripping the tag before the
text is shown. It is machinery every adapter inherits. One mechanism,
both surfaces, nothing to write.

**It was rejected because it is a *platform* convention, and that is the
whole of its purpose:** any adapter can render it. A tool that emits one
has no say in where its turn is delivered, so a picture of the inside of
the house would leave this box the first time a conversation was routed
to Telegram. The property "images never leave here" would then hold
because the platforms happen to be configured a certain way — and **a
privacy property held by convention is not held**. Config drifts, a
platform gets enabled, and nothing fails loudly.

Two paths, therefore, and the guarantee becomes structural rather than
conventional: not "we configured the platforms correctly" but "there is
no path by which an image reaches a third party". This is the same shape
as §1's "he is told, never made to recite" — Hermes' injection API only
accepts a *user* message, so reciting is not something we avoid, it is
something the API cannot express.

**The destination is a constant, not a config key.** `KIOSK_PLATFORM`
in `samantha_vision/__init__.py` is hard-coded for exactly this reason: a
setting naming the platform would put the rejected decision back, one
edit away.

**Cost, accepted explicitly:** the strip and Telegram no longer share a
mechanism. Two paths to maintain instead of one, and any future surface
that wants a picture has to be given one deliberately. That separation
*is* the feature, not an accident of it.

**A consequence worth stating, because it surprises people:** the
unprompted alert still carries **no** photo, anywhere. The picture is a
side effect of the `mirar` handler and an alert does not call `mirar`.
An image that appears unbidden over whatever you were doing is a larger
thing than one you asked for. If that is ever wanted, the mechanism is
already there.

### 2026-08-25 — The kiosk contract gains its first new frame

**Decision:** the `samantha_kiosk` protocol gains
`{"type": "photo", "path": …, "camera": …}`, **server to client only**.
`decode_client` is untouched. It is the first change to that contract
since it was written on 2026-08-22.

**Why the strip needed a frame when no other platform did.** Every other
adapter Hermes ships renders whatever the turn carries, because a chat
platform *is* a renderer: text goes in a bubble, an attachment goes
beside it. The strip is not a chat window. It has no message list to put
an attachment in, and what has to happen is that a window on somebody's
desktop **changes shape** — grows from 900×96 to 900×210, to 900×480 on
a click, and back. Nothing expressible inside a turn can say that. The
one surface that is not a platform is the one that needs a frame of its
own.

**It cost a fix in the strip first.** `decode_server` raised
`ProtocolError` on any type outside its set, so the first unknown frame
killed the turn carrying it. The gateway and the widget are versioned
separately and always will be; the strip now drops what it does not
recognise and handles what it does.

**The path is validated before it goes on the wire**, against the
snapshot directory, in the adapter. The socket is an unauthenticated
local listener and the strip opens whatever it is handed, so that check
is the trust boundary. A strip that is not connected is not an error: the
frame is dropped and the spoken answer is unaffected.

**What it cost beyond the code:** the kiosk's `platform_hint` said there
was no screen, and until that day it had been true. Measured on the live
gateway in the window where the photo was already being pushed and
nothing yet drew it, he declined correctly and for the wrong reason —
"sigo sin poder enseñarle nada en una pantalla, señor", once offering to
open Hermes Desktop instead. The hint therefore had to move in the same
change as the drawing, and it now says what he can show (one camera
still, briefly, and nothing else), that he need not announce it, and that
he does not see it himself. Remember §7: a hint reaches an existing
session only after `/new` and `/approve`.

**Deferred, deliberately:** the band is as wide as the strip and mostly
transparent, so while a photo is up it swallows pointer events over that
much desktop — 900×210, or 900×480 enlarged, for fifteen seconds. The
honest fix is `XShapeCombineRectangles` through the ctypes handle
(`Gdk.Surface.set_input_region` wants a `cairo.Region`, and Cairo is the
trap this machine is built around), which is a new X mechanism in the
file whose EWMH work cost this project days. The risk of the fix exceeds
the harm this week.

### 2026-08-24 — He stops repeating himself, and the password leaves the URL

**Three decisions from the whole-branch review and its re-review, all of
them behaviour the user hears or a credential he owns.**

**The camera anti-spam window widens.** 180 s stopped three-second spam
and nothing stopped three-minute spam: measured on the live gateway,
`entrada: alguien` five times in 35 minutes — ~480 spoken turns and ~480
model calls a day, running while the house sleeps. Consecutive re-fires
of the same `(camera, label)` now back the window off 180 s → 15 min →
hourly, resetting to the floor after a full window unseen. **The four
calibrated constants are untouched** — 180, 0.7, 23:00, 07:00 are
BarnDoor's, arrived at against these cameras; the ×5 and ×20 are ours. A
first sighting is never suppressed, and the quiet-hours person rule sits
outside the escalation in **three** ways: a widened window never gates it
(only the night floor below does), its firings never advance the level —
counting them would turn the override into its opposite at dawn — and it
resets the level, so the morning does not inherit the day's fatigue. The
third was added after measuring what its absence cost; see the night
floor below.

**Credentials move to `.env`.** The RTSP password lived inline inside the
camera URLs in the untracked `.hermes/home/config.yaml`, which is what
let PyAV write it into the journal in the first place. It now lives in
`.env` at the repo root — git-ignored, with a tracked `.env.example` —
which `Hermes/run-gateway.sh` sources; that is the single chokepoint, so
both units that start a Hermes process — `samantha-hermes.service` and
`samantha-hermes-serve.service` — and every manual invocation get it.
`samantha-widget.service` does not, and needs no credential. URLs say
`${RTSP_PASSWORD}` and the plugin expands it. The trap, handled
explicitly: an unset variable would be left as the literal text
`${RTSP_PASSWORD}`, which would then be used as the password and logged.
`_expand` therefore does the substitution itself and resolves each name
inside the callback, dropping the camera with a warning that names the
variable and never the URL. It deliberately does **not** call
`os.path.expandvars`, which also expands a bare `$NAME` — and a password
may contain a `$`, which cost a password fragment in the journal on
2026-08-24 before the pattern was narrowed to braces only.

**A 30 s floor under the night rule — the user's decision**, taken from
three options put to them after the re-review measured the alternative.
"A person at night beats the anti-spam" is BarnDoor's, and it was written
for a mailbox rather than a mouth: there it produced a notification, here
a spoken turn and a model call, and `worth_saying` runs once per sampled
frame. Measured against the real `Watcher`: **19,200 utterances over an
eight-hour night** with somebody standing in view. `NIGHT_FLOOR_SECONDS
= 30` caps it at one mention per 30 s per `(camera, label)`; the same
measurement afterwards gives 960.

**Its cost, stated plainly:** he now insists *less* at night than
BarnDoor's rule intended. The rule exists because the second sighting at
3am matters more than the first, and 29 of every 30 seconds of that
insistence are gone. The trade is that the alternative was not insistence
but continuous speech. 30 s is ours and is **not** a fifth calibrated
constant.

The same pass found the escalation level surviving the dawn boundary: a
key escalated to hourly in daylight and present all night got its first
morning mention 60.0 minutes after quiet hours ended, when the morning is
exactly when the user wakes and would want to know. The night path now
resets the level; measured again, 150 s.

**Cost:** the escalation is keyed on the label, so while a `(camera,
label)` sits at the hourly level any person at that camera is silenced
for up to an hour. That is inherent to a plugin that cannot tell one
person from another; the 180 s floor bounds it at the start of each
visit. And the tracked README no longer carries the house's camera
addresses — placeholders there, real values beside the URLs they
describe.

### 2026-08-24 — Vision moves out of the widget and into a Hermes plugin

**Decision:** the cameras live in the gateway, as the standalone plugin
`samantha_vision` (`Hermes/plugins/samantha_vision/`), one thread per
camera. The widget goes back to drawing, listening and speaking, and
opens no camera at all.

**This supersedes the placement half of the 2026-08-23 entry below**
("Why it belongs in the widget rather than in a service of its own").
The rest of that entry stands unchanged and was carried over whole: what
comes from BarnDoor and what does not, the quiet-rule numbers, and — the
part that matters — that a detection becomes a *prompt* and never a
sentence.

**Rationale:**
- **Watching should survive the widget restarting.** The strip is a
  window on a desktop; the gateway is a systemd service with a lifecycle,
  logs and supervision already paid for.
- **A camera you can question has to live beside the thing that
  answers.** The tool is plan 2, but it cannot exist in a UI process.
- **The strip should draw.** §2.3 claims the widget is the surface; a
  camera thread competing with the GTK main loop, Silero and Whisper was
  the counter-example.

**How a plugin speaks first, measured on the pinned Hermes:**
`ctx.inject_message(text, role="user",
session_key="agent:main:samantha_kiosk:dm:kiosk")`. Three properties
decided the design and are worth carrying:
- **No lifecycle hook fires after registration**, so `register(ctx)` is
  the only entry point and must start its own threads — while staying
  pure, because work that touches the outside world during registration
  turns a missing dependency into a plugin that never loads.
- **It can only push a *user* message.** There is no API for putting
  finished words in his mouth, which makes §1's "he is told, never made
  to recite" a property of the mechanism rather than of our discipline.
- **It fails silently, and not in the way it looks.** `False` means only
  that the gateway is not up yet — the injector installs after the last
  platform adapter connects — so retrying clears it. A **missing session
  row comes back `True`**: the lookup happens inside the coroutine, after
  the task is scheduled, and Hermes logs it itself as "Plugin message
  injection was not routed". (Corrected 2026-08-24; the opposite was
  stated here and in three other places, and sent a reader hunting for a
  log line that cannot exist.) A sighting with nowhere to go is retried
  three times and then dropped; queueing would make him recite stale
  news.

Injection is also a per-plugin permission, default-off:
`plugins.entries.samantha-vision.allow_gateway_injection: true`. Without
it the cameras watch and he never mentions a thing.

**Cost:** the camera threads now run inside the brain. If one wedges the
gateway, everything dies — so each thread catches everything, logs once
and backs off from 30 s to a 5-minute ceiling, and each camera owns its
own failure. And onnxruntime and PyAV stay in the widget's dependency
tree — onnxruntime declared, for Silero; PyAV transitively, because
faster-whisper brings it — but neither is there for vision any more.

**Verified against the real house, 2026-08-24** — one camera live, one
off, nothing faked:

    ← El de la entrada sigue plantado donde está, señor.

**Still not done:** he cannot be asked. `samantha_vision` registers no
tool and remembers nothing; `mirar`, `revisar` and the detections table
are plan 2.

### 2026-08-24 — The cameras become plural, and named

**Decision:** cameras are a list of `{name, url}` in the plugin's
config, not one environment variable. The anti-spam window is keyed by
camera **and** label. The names are interface, not configuration: they
are what he says out loud.

**Rationale:** somebody walking from `fuera` to `entrada` is two events
and should be; with a single unnamed camera it was one, and the second
half was swallowed by the 180 s window. Naming them is what makes the
distinction expressible at all.

**The measured trap, and it is not a small one.** Camera names are bare
nouns, so they carry no article. Put one inside a prepositional phrase
and the Spanish breaks — "en la fuera de casa", "en fuera de casa" — and
a model handed broken Spanish does not shrug: it *repairs* it by
inventing a place that fits. Twice on the live gateway, a camera named
`fuera` seeing somebody produced "Hay alguien en la entrada, señor."
Somebody outside, reported as somebody at the door — a wrong answer, not
a clumsy one, in a feature whose whole job is telling you who is around
the house. The fix was to stop putting the name inside a preposition at
all: it is handed over as a labelled value, `Dónde: fuera. Qué:
alguien.`, and he picks his own words around it.

**Cost, all of it in the configuration:**
- The URLs carry the RTSP password, so they live **only** in the
  git-ignored `.hermes/home/config.yaml`. The tracked
  `Hermes/samantha-config.yaml` carries the shape as a comment and
  nothing else — a live placeholder list there would be worse than
  useless, because `apply-config.sh` deep-merges dicts but **replaces
  lists wholesale** and would blind him on the next run.
- The list must sit under `settings:`. `ctx.get_config("cameras")` reads
  `plugins.entries.<id>.settings.cameras` and nothing else; put it at the
  entry root and the plugin loads, watches nothing, and says so in one
  line nobody is reading.
- PyAV puts the whole URL, password included, into every failure
  message. It reached the journal in plaintext once before everything
  logged went through `redact()`.

### 2026-08-23 — Samantha can see: BarnDoor's cameras, reused not integrated

**Decision:** the widget watches the house's cameras. What comes from
`~/git/barndoor` is the RTSP layout and a YOLOv9 model already converted
to ONNX — and nothing else. No Frigate, no MQTT, no Telegram, no second
agent. The two projects stay separate.

**Why it belongs in the widget rather than in a service of its own:**
zero new dependencies. `onnxruntime` was already there for Silero and
PyAV arrived with faster-whisper, so a widget that could already hear
was one import away from being able to look.

**The design decision that matters:** a detection does not become
speech. It becomes a `chat` frame with a prompt asking her to mention
what she noticed, in one short line, forbidding any reference to cameras
or detections. "Persona detectada en exterior" would be a machine
talking, and §1 says she never performs using her tools. Measured:

    cámara: alguien
    ← Oye. Hay alguien fuera de casa.

**What the user's suggestion to read BarnDoor's app was worth:** its
`agent/rules.py` had the numbers, arrived at against these very
cameras, that would otherwise have been guessed — confidence floor 0.7
(the guess was 0.45), anti-spam of 180 s per label, and a person during
quiet hours overriding that silence. Without the anti-spam a camera
says "alguien" every three seconds for as long as somebody stands in
the driveway.

**Cost:** a model call per event, affordable only because those rules
make events rare. And the privacy line moves again: what the cameras see
is described to a cloud LLM, in the same "eyes open, not absolute"
sense §1 already carries for conversation.

**Not done:** she cannot be asked what she sees. The camera speaks; it
cannot be questioned. That wants the vision path exposed as a Hermes
tool rather than a thread pushing prompts.

### 2026-08-23 — Electron reconsidered for the widget, and rejected again

**Decision:** the widget stays GTK4. Raised because Hermes Desktop —
Electron — was built and run on this machine the same day, and it works.

**Measured, side by side, on this box:**

| | widget (GTK4) | Hermes Desktop (Electron) |
|---|---|---|
| RSS | 389 MB, one process | 1257 MB across six |
| Installed | 268 KB of code | 338 MB packaged |
| Build | none | `npm install`, and it had to download its own Node |

The widget's 389 MB is almost entirely faster-whisper resident on the
GPU, not the interface.

**The reason that decides it is not the memory.** Silero, Whisper,
CosyVoice and playback share ONE Python process today. Electron splits
that into a Node process plus a Python helper over IPC, or forces VAD
and STT into JS. The Silero bug found this morning — 576-sample windows,
not 512, failing silently — would have been considerably harder to find
across a language boundary.

**Where Electron would genuinely win:** a transparent undecorated
always-on-top window is three lines there versus ~50 of EWMH here — but
that cost is already paid and tested. And rich graphics: if the OS1 3D
ribbon ever comes back, a browser gives it away free. **That** is the
conversation worth reopening, and `frontend/` is still there for it.

**Cheaper alternatives if the visualiser ever outgrows Cairo/GSK:**
`Gtk.GLArea` in-process, or an embedded WebKitGTK for the visual half
with Python still owning the audio. Neither breaks the single process.

**Cost of this decision:** none today. It is the fifth architecture this
project has considered (Tauri → Ubuntu Frame → Chromium kiosk → GTK4 →
Electron) and the fourth it has rejected; the point of writing the
numbers down is so the sixth conversation starts from evidence.

### 2026-08-23 — Samantha may act: agentic, but never visibly

**Decision:** Samantha uses Hermes' tools. §1 loses "❌ A productivity
assistant" and "❌ An agentic tool-using system (no function calling, no
web search)", and gains "❌ A visible agent" in their place.

**Rationale:** the spec contradicted itself. §1 forbade agentic tool
use; Phase 9 (§4) integrated Hermes explicitly *"to enable agéntico tool
use"*. Until today the prohibition won by default, which left Hermes
working as a text pipe — a sentence in, a sentence out — with an entire
tool ecosystem sitting unused underneath a device that lives in
somebody's living room.

The user's framing on 2026-08-23: *"Hermes funciona como un chatbot y no
es esa su utilidad, sino hacer tareas de agentes y aprovechar todo su
ecosistema de integración."*

**What is in, in priority order:** Home Assistant (the one that makes a
thing in the living room worth having), `memory` + `session_search`,
`cronjob` (reminders she raises out loud), web search, Spotify, and
Discord — the only social platform this pinned Hermes actually ships,
alongside Yuanbao and Feishu.

**Cost, and it is not small:**

- **The personality spec now has to police behaviour, not just prose.**
  "No visible agent" is a rule about what she does, and `docs/
  personality spec was written for what he says.
- **The voice turn does not fit an agentic turn.** It assumes you speak,
  she thinks for a few seconds, she answers. A real task takes minutes,
  emits intermediate chatter (`↪ Redirected current run`, already seen
  in the wild) and trips the kiosk adapter's 90 s watchdog. The wave has
  no state for "still working".
- **`cronjob` inverts the conversation.** A reminder is Samantha talking
  first, which nothing in the widget or the adapter currently supports.
- **The privacy line moves again.** Web search and Home Assistant send
  the house's business outward. §1's "eyes open, not absolute" already
  covers it, but it is a wider aperture than the 2026-05-15 entry
  imagined.
- **Memory now has two homes.** Hermes has its own `memory` toolset and
  we have ChromaDB (§2.7) that the gateway path never touches. One of
  them has to win.

**Alternatives rejected:** keeping her purely conversational (leaves
Hermes pointless — a smaller local model would do), and going fully
task-oriented (that is Siri, and §1 has always said no).

### 2026-08-23 — The LLM came home: Qwen3.8-27B local, and Grok demoted

**Decision:** inference runs on this box by default. `llama-server` with
Qwen3.8-27B at UD-Q3_K_XL, 57 tok/s. Grok stays reachable behind a config
switch. This reverses the 2026-05-15 decision below.

**Rationale:** that decision rested on "8B-class models can't carry this
personality, and bigger ones don't fit". The second half stopped being
true — a 4090, a smaller quant and a current llama.cpp put a 27B beside
CosyVoice and Whisper with room to spare, four times faster than the
obvious quantisation. §2.5 has the table.

**Cost:** the box must hold everything at once (22,947 MiB of 24,564
measured 2026-08-30, 1,126 free), so
adding anything that wants VRAM now costs tokens per second. And
llama.cpp must be recent: b9115 refused the file outright, missing a
tensor of Qwen3.8's hybrid Gated DeltaNet.

**What it buys:** §1.1 back, honestly. Nothing said in the room leaves it.

---

### 2026-08-23 — Samantha becomes JARVIS

**Decision:** the persona is JARVIS — courteous, precise, dry, never
alarmed, addresses the user as "señor" without servility, and never
narrates his tools. Samantha's warmth was the right character for a
companion; the thing that ended up on the desk is a house presence.

**Cost:** the name is only changed in prose. `samantha_widget`,
`samantha_kiosk`, `SAMANTHA_*` and the repo itself keep the old name —
renaming them would touch every file, every unit and every env var to buy
nothing. Anyone reading the code should expect the mismatch.

**What the investigation cost, and it is the valuable part:** the persona
was correct for an entire afternoon while the strip kept answering "me
llamo Hermes". Two independent causes, both silent — `SOUL.md` never
reaching a gateway conversation at all, and the system prompt being
frozen when the *session* is born. §7 has both, and the fix (`/new`,
`/approve`).

---

### 2026-08-22 — The Chromium kiosk is replaced by a GTK4 desktop widget

**Decision:** the surface is a native GTK4 strip along the bottom of the
screen. It **replaces** the kiosk rather than coexisting with it. Taken
2026-08-22 in brainstorming, four answers closed: it replaces; GTK4 with
no webview; a floating strip, wide and low, terracotta; always listening,
with Silero deciding when the user speaks — no wake word, no shortcut.

**Rationale:** the appliance model (§1.5, as it was) assumed a device
that is only him. The real box is a desktop the user also works on, and a
full-screen kiosk on it is not a presence but an application that will
not go away. A strip is there without taking anything.

**Cost, accepted explicitly:**
- **`frontend/` dies.** React, Vite, Three.js, the OS1 ribbon, the four
  screens — all of it was the kiosk's UI. The user's condition was that
  it not be deleted until the widget convinces, which is why §2.10 and
  §3 still list it and why plan 3 is unwritten.
- **The UI is rewritten in GTK4/GSK**, a smaller and less familiar
  toolkit than a browser, on a machine where Cairo turned out not to
  work (§2.3).
- **X11 becomes a hard constraint** rather than a preference (§2.2).
- Boot-to-him and the auto-login chain are gone; a user service starts
  him inside the ordinary desktop session.

**What it bought, measured:** ~389 MB resident for the whole of him,
Whisper included; a wave that animates on the frame clock at no
measurable cost; and a surface with no window, no focus and nothing to
click, which is §1.5 made literal.

---

### 2026-05-15 — LLM switched from local Qwen3-8B to Grok API

**Decision:** Default LLM path is now X.AI's Grok API
(`https://api.x.ai`, model `grok-4-1-fast-non-reasoning`). Local
llama-server (Qwen3-8B Q8) remains supported as a config override.

**Rationale:** A/B test on the v4 evocative system prompt
("Eres Samantha. No eres un asistente virtual…"). Same prompt, same
user input ("Hoy estoy un poco depre…"):
- Qwen3-8B-Q8: 200 words, three stacked metaphors, theatrical.
- grok-4-1-fast: 110 words, one controlled metaphor, asks one
  concrete follow-up. Latency comparable (~3 s warm).
- Cost: ~$0.2/M input + $0.5/M output → fractions of a cent per turn.

The 8B model can't carry the nuance this personality asks for; it
keeps "thinking out loud". Bigger local models (32B / 70B) wouldn't
fit alongside vllm-omni on a single 24 GB GPU.

**Cost:** Privacy principle (§1) explicitly relaxed — conversational
content leaves the device when an API key is set. Documented in §1
and §2.5. To restore full-local: unset `SAMANTHA_LLM_API_KEY` and
point `SAMANTHA_LLM_SERVER_URL` at the local llama-server.

**Implementation:** `backend/samantha/real_llm.py` adds Bearer auth
when `llm_api_key` is set; `/no_think` suffix only appended for
Qwen-family models. No other changes — the OpenAI-compatible
protocol meant zero refactor.

**Lessons:** Premature commitment to "everything local" wasn't free.
Held in v1/v2 against well-meaning but model-side reality (8B-class
dense models don't have enough capacity for nuanced dialog with this
prompt style). Buying a few cents/day of API beat months of prompt
engineering against an undersized model.

### 2026-05-13 — Offline-only requirement relaxed; STT moves to browser

**Decision:** "Zero network dependency at runtime" is no longer a
hard product principle. The kiosk runs with internet on by default;
LLM and TTS still execute locally, but ancillary pieces (fonts,
browser Web Speech API for STT) MAY hit the network.

**Rationale:** Building+shipping a fully local stack for every piece
(Whisper model ~1.5 GB, vendored fonts, etc.) was paying ongoing
operational cost for a property the actual deployment doesn't
require. Conversational *content* still never leaves the device via
us — the LLM is local. The privacy boundary moves from "no network
at all" to "no cloud LLM and no conversational data exfiltration".

**Cost:** §2.8 was rewritten — browser mic is now the default STT
path (was: Python via sounddevice). Local Whisper remains optional.
Chromium kiosk needs `--use-fake-ui-for-media-stream` so the first-
use permission prompt doesn't shatter the appliance feel.

**Lessons:** Hard offline is a real engineering commitment, not just
an architectural label. Removing the constraint cut hours of Whisper
+ model-download + audio-stack work that the actual product didn't
benefit from.

### 2026-05-13 — npm → pnpm (corepack)

**Decision:** Frontend package manager is **pnpm**, not npm. Activated
via `corepack` (ships with Node) so there's no extra install step
during deployment.

**Rationale:** npm has had a string of supply-chain incidents (worms
spreading via postinstall, typosquats, maintainer compromises). pnpm's
defaults are stricter:
- Content-addressable global store + isolated symlinked `node_modules`
  per project — lateral compromise across projects is much harder.
- Postinstall scripts are *blocked by default*; each must be explicitly
  approved via `pnpm.onlyBuiltDependencies` in package.json plus
  `pnpm approve-builds`. Today only `esbuild` is approved.
- Lockfile (`pnpm-lock.yaml`) is stricter and deterministic.

**Cost:** Developer flow changes `npm` → `pnpm` everywhere. No runtime
impact — production kiosk still runs only Python + Chromium against
the static `frontend/dist/`.

**Lessons:** The default package manager isn't always the right
default. For a single-user appliance with no untrusted contributors,
pnpm's stricter posture costs nothing and removes a real attack
surface.

### 2026-05-13 — Vanilla JS → React + Vite + TypeScript

**Decision:** Replace the vanilla-JS-no-build frontend with React +
Vite + TypeScript in a separate `frontend/` directory.
**Rationale:** v2 UI redesign expanded scope (Ambient screen added,
immersive Conversation with history toggle, traveling wave packet,
persistence layer). The "UI scope is small" rationale of the
original vanilla decision no longer applies.
**Cost:** Node.js required for dev and build. `node_modules/` adds
~100 MB to the dev environment. Production kiosk runs only Python +
Chromium.
**Lessons:** "Familiar tools first, exotic only when justified"
still holds — but "familiar" includes React for a four-screen
stateful UI, not just because it's the JS default.

### 2026-05-13 — Memory architecture: short/long-term + facts + fastembed

**Decision:** Restructure memory into three layers — short-term
(SQLite ring buffer for the last 20 turns), long-term (ChromaDB for
semantic recall), and structured facts (`role: "fact"` chunks in
long-term). Swap the embedder to
`paraphrase-multilingual-MiniLM-L12-v2` via fastembed (ONNX). No
parallel `profile.json` file.
**Rationale:** Pure-similarity recall has a continuity gap (the
previous turn isn't always similar to the new one). Short-term
solves that. Facts give structured access to name, onboarding
marker, future preferences without polluting conversational recall.
The multilingual embedder fixes weak Spanish recall.
**Cost:** +130 MB deps (fastembed + ONNX model). One-time model
download on first launch (~30 s).
**Alternatives rejected:**
- **Mem0** (NousResearch): 5 s/turn latency for fact extraction,
  English-leaning output. See `docs/superpowers/specs/mem0-spike/`.
- **Hermes-Agent** (NousResearch): full task-agent runtime, optimizes
  a problem we don't have in v2. Parked for v3 at
  `docs/superpowers/specs/2026-05-12-hermes-agent-spike-scope.md`.

### 2026-05-12 — vLLM → llama.cpp
**Decision:** Use llama.cpp (`llama-server`) as the LLM runtime instead
of vLLM. Model stays Qwen 3.5-9B Q4_K_M (GGUF).
**Rationale:** Samantha is single-user, single-stream — vLLM's batching
engine, Ollama's daemon layer, both optimize for problems we don't
have. vLLM is also CUDA-only, which blocks all Mac-side development.
llama.cpp runs natively on Mac (Metal) and Linux (CUDA) with the same
model file and the same OpenAI-compatible HTTP API, so the Python
client is runtime-agnostic.
**Cost:** None (Phase 4 not yet implemented when changed). Phase 7
systemd unit becomes `samantha-llamacpp.service` instead of
`samantha-vllm.service`. Pydeps lose `vllm`; gain only `httpx`.
**Lessons:** Pick the runtime that's cheapest to develop against;
optimize for production throughput only when there's a real workload.

### 2026-05 — Ubuntu Frame → Chromium kiosk
**Decision:** Replace Ubuntu Frame + WPE WebKit + snap (v2) with
Chromium in `--kiosk` mode launched by systemd (v3).
**Rationale:** Ubuntu Frame is purpose-built for kiosk apps but the
snap packaging adds significant complexity for a single-user,
single-device personal project. WPE WebKit may lack some modern browser
APIs needed by Three.js. Chromium kiosk is the most widely-deployed
Linux kiosk solution (digital signage worldwide), uses standard tools
(systemd, openbox, X11), and supports all modern web APIs out of the
box.
**Cost:** None (Ubuntu Frame was decided but not yet implemented).
**Lessons:** Architecture decisions should follow the principle of
"familiar tools first, exotic only when justified."

### 2026-05 — Ubuntu Server 24.04 LTS (not Ubuntu Core)
**Decision:** Use Ubuntu Server 24.04 LTS as base, not Ubuntu Core.
**Rationale:** Ubuntu Core's all-snap model is more rigid and harder to
debug. Server gives us familiar Linux semantics with the same LTS
support (until 2034 with Ubuntu Pro). Ubuntu Frame works on both.

### 2026-04 — Local-only architecture (no remote iPad)
**Decision:** Drop the originally planned iPad client + Mac mini server
architecture. Go fully monolithic on a single mini-PC.
**Rationale:** Simpler, fewer moving parts, no pairing flow, no
networking.

### 2026-04 — macOS → Linux
**Decision:** Move from Mac mini M4 Pro (planned) to Minisforum AtomMan
G7 Ti SE running Linux.
**Rationale:** User preferred Linux for full control. Cheaper hardware.

### 2026-05 — Qwen 3.5-9B as default model
**Decision:** Use Qwen 3.5-9B as the default model.
**Rationale:** Fits comfortably in 8GB VRAM. Generation released in
2026. Strong in Spanish.

### 2026-05 — Horizontal wave replaces orb
**Decision:** Samantha is represented by a horizontal animated line,
not a sphere/orb.
**Rationale:** User feedback during mockup iteration; the line feels
more "Her" than the orb.
