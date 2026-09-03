# Teacher mode — JARVIS teaches a subject, design

> **Status:** design, agreed with the user 2026-09-03. Architectural: a
> new Hermes plugin, a fifth frame on the kiosk protocol, and a new
> drawn area in the widget.
>
> **It extends CLAUDE.md §2.3 (what the band holds) and §1.1 (what
> leaves the house). It contradicts nothing.** No browser, no webview,
> no new top-level directory.
>
> **Written while JARVIS was down** — the GPU was in use elsewhere — so
> nothing here was measured against the live gateway. Every claim that
> needs the model or the network is marked as such and deferred to a
> named check. Everything else is buildable and testable on a box with
> no GPU, no network, no display and no gateway.

## What was asked for, in the user's own answers

Seven decisions, taken 2026-09-03, in the order they were taken:

1. **JARVIS teaches the user a subject** — he is the teacher, the user
   is the student.
2. **Any subject, open.** "Enséñame X" and he builds the syllabus as he
   goes. No ingestion of the user's own documents.
3. **A mode with state and progress across days.** He knows where you
   left off, resumes tomorrow, and examines you.
4. **Voice plus pictures** — and, added mid-conversation and decisive:
   *"importante mostrar por pantalla las preguntas tipo texto."* The
   questions are read AND shown.
5. **Multiple choice on screen, answered out loud.** The statement and
   its options are visible; you say "la b" or the answer itself.
6. **You always start the class.** No cron, no proactive review, no
   "¿repasamos cinco minutos?".
7. **He stays himself during a class.** A camera alert or an ordinary
   question is answered and the lesson waits. Nothing is silenced.

And one revision of §4, taken after the design had been presented:
**the card is a Markdown document, and Markdown carries images of its
own.** That replaced a structured card (statement + options + one
image) with a single string, and removed an image subsystem in favour
of a rule about references.

## Where it lives, and what each piece may not know

A new Hermes plugin, `Hermes/plugins/jarvis_teacher/`, `kind:
standalone` — the shape of `samantha_vision`. `register(ctx)` declares
tools and touches nothing outside the process; that is a plugin's whole
lifecycle on the way in (proved on this pinned Hermes, 2026-08-24).

| file | what it does | what it must not know |
|---|---|---|
| `curso.py` | The state: courses, concepts, questions, answers. SQLite. | That a model or a gateway exists. |
| `markdown.py` | The Markdown subset: parse, and the option list. | That anything is drawn. |
| `tool.py` | The five tools the model sees, in Spanish. | How anything is drawn. |
| `imagen.py` | Resolving `![](…)` references into local files. | Everything else. |

`push_ficha` arrives at `tool.py` as a **callable**, the way
`cameras.py` takes `on_detections`. That is what lets the whole plugin
run in a test with no gateway and no strip in the room.

In the widget, the pair this project already uses twice:
`ficha.py` (pure state, no GTK, testable without a display) under
`ficha_area.py` (the drawing), exactly as `photo.py` sits under
`photo_area.py`.

### The division that makes "resume" true

**The plugin stores facts; the model writes the content.** The plugin
never stores an explanation of Newton's third law. It stores that the
concept was taught on Tuesday, asked twice, and missed once. Tomorrow
the model writes the explanation again with those facts in front of it.

This is the whole reason for a database. Option B in brainstorming —
keep the syllabus in Hermes' own memory and let the model remember —
was rejected on the evidence of §12 (2026-09-01): a model on this box
will confidently describe a backup generator the house does not have.
"Where we left off" must be a reading, not a recollection.

## The state

`~/.samantha/teacher/curso.db`. Four tables:

- **`curso`** — `tema`, opened at, last touched at, whether it is still
  open.
- **`concepto`** — the unit of progress: a short title, its course, when
  it was explained.
- **`pregunta`** — the Markdown of the card, the parsed options, which
  was correct, which was chosen, whether it was right, when. Points at a
  concept.
- **`sesion`** — when each class began and ended, so "we left it on
  Thursday" is a fact.

**Nothing is ever deleted** — §2.7's rule for memory, applied here. A
concept missed three times keeps its three rows, which is exactly what
makes "this one keeps catching you out" expressible.

The file belongs to this plugin alone. It touches neither Hermes'
`state.db` (sessions) nor ChromaDB (unused since August, §2.7).

## The tools

One toolset, `clases`. Spanish names, like `mirar`, for the reason
`tool.py` already records: the model is answering somebody who speaks
Spanish.

| tool | args | what it does |
|---|---|---|
| `ensename` | `tema` (optional) | Opens a course or resumes the last open one. Returns the fact sheet. |
| `explicar` | `concepto`, `ficha` (optional) | Records that this concept was taught today, and draws it when a card is given. |
| `preguntar` | `ficha`, `correcta` | The model writes the card; the plugin stores it and draws it. |
| `responder` | `elegida` | The spoken answer. The plugin scores it against what it stored. |
| `terminar` | — | Closes the session, returns the summary. |

**The model writes the question; the plugin decides whether you were
right.** The correct option has been stored since the card was made, so
scoring is a comparison rather than an opinion. The model only
translates "la b" or "la segunda" into an option.

**The fact sheet is the whole of "resuming".** `ensename` returns
labelled data, not a sentence — the same remedy that stopped the
cameras inventing where people were (§12, 2026-08-24, "en la fuera de
casa"):

```
Tema: astronomía. Última clase: jueves.
Dados: 6 conceptos.  Flojos: la tercera ley (1 de 3), paralaje (0 de 2).
Sin dar aún: nada — el temario lo pones tú.
```

### The known defect this design has to survive

§12 (2026-08-26, corrected 2026-09-01) records that through the Hermes
path a tool of ours is called with `args={}` — `mirar` with no camera
five times out of five — and that **the model is not the cause**: put
the same tools to llama-server directly and it fills 4 of 4. Whatever
breaks the arguments lives in the Hermes path.

Three consequences, all designed in rather than discovered:

- **`preguntar` takes two arguments, not four.** The options are not a
  field; they are the bullet list inside the Markdown, which the plugin
  parses. Fewer arguments is less surface against the defect.
- **`ensename` with no `tema` resumes the last open course**, which is
  the commonest case anyway. Empty args degrade into the right
  behaviour rather than into an error.
- **`preguntar` with no `ficha`, or with a `ficha` whose options cannot
  be parsed, draws nothing.** It returns "repite la pregunta con las
  opciones en una lista" to the model. A broken card is never shown.

**The check that settles it needs the live gateway and is therefore
deferred:** register a two-argument tool on the real gateway and see
what arrives. It cannot be the first task, because the box has no GPU
free. It is the switch-on check. If the arguments do not survive, the
fallback is one argument in a fixed format, and the defensive path
above is already the behaviour when they do not.

## The screen: the card is a Markdown document

A fifth server-to-client frame on the kiosk protocol, sibling of
`photo` and `console`. `decode_client` is untouched — the strip never
sends one.

```json
{"type": "ficha",
 "md": "## ¿Qué mantiene a la Luna en órbita?\n\n![](/…/img/ab12.jpg)\n\n- Su propia velocidad\n- **La gravedad de la Tierra**\n- El viento solar\n",
 "espera": true, "correcta": null, "elegida": null}
```

**One frame serves both things drawn here**, and `espera` is the whole
difference. A question (`espera: true`) waits — it does not fade, it
holds for five minutes, and it comes back with `correcta` and `elegida`
filled. An explanation (`espera: false`) is a diagram or a formula put
up while he talks: it fades on its own after a minute, like a photo,
and nothing is waiting on it. This is what makes decision 4 — voice
plus pictures — true of the explaining and not only of the examining.

### A declared subset, drawn with GTK

There is no browser here and §3 says there will not be one. The blocks
become widgets inside the band that already knows how to grow:
`Gtk.Label` with Pango markup for text, `Gtk.Picture` for an image.

**In the subset:** paragraphs, a heading, **bold**, *italic*, `code`,
bullet lists, and `![](…)`.
**Out of it:** tables, HTML, links (there is nothing to click here), and
everything else — shown as the literal text it is rather than pretending
it was understood.

**No new dependency.** The subset is ours and is about a hundred lines
of parser in `markdown.py`, pure and testable without a display. A full
CommonMark library would be asking permission (§8) to render what we
have decided not to render.

### How it behaves

- **An explanation goes after a minute; a question does not.** The
  ceiling differs because the waiting does.
- **The height is decided by the content**, exactly as the console has
  done since 2026-08-26: three lines in a box built for twenty is mostly
  empty box, and it showed. Ceiling the same as the live camera, 480 px
  of strip.
- **It does not fade while the question is open.** A photo goes after
  15 s because you have seen it; a question stays while you think. But
  §1.5 says there are no windows here, so there is a ceiling: **five
  minutes** unanswered and it closes itself, the way the live view
  closes at 120 s.
- **The correction is visible.** On `responder`, the same frame returns
  with `correcta` and `elegida` filled: the right option is marked and
  so is yours. Six seconds, then it goes.
- **A press dismisses it**, as a photo has since 2026-08-25.
  `XShapeCombineRectangles` in `ewmh.py` already keeps the band from
  swallowing the desktop's clicks (§12, 2026-09-01 — CLAUDE.md's
  2026-08-25 entry still calls this deferred, and it is not).

### The band conflict, decided here

The band is one. The user's rule is that during a class everything
still comes in and the lesson waits. So when a camera pushes a photo
over an open question, **the card is covered, not cleared**. When the
photo or the live view goes, the question comes back exactly as it was.
That is "la clase espera" made literal.

## Images arrive through the Markdown

There is no image subsystem; there is a rule about references.

**The strip never goes to the internet.** If the model writes
`![](https://…)`, the widget does not fetch it — that would open a
connection from the process that draws, with whatever it was handed.
The **plugin** resolves references before the frame is pushed: it
downloads to `~/.samantha/teacher/img/`, checks the size, checks that
it decodes as an image (not the `Content-Type`), gives it a name of our
own, and **rewrites the reference to the local path**.

`push_ficha` validates that path against that spool — not against the
cameras' snapshot directory. They hold different things: one has
pictures of the inside of this house and the other has a diagram of the
solar system. Sharing a spool is exactly the kind of path the
2026-08-25 decision exists not to open.

**A reference that cannot be resolved drops out of the document and the
question is asked anyway** — Ruling 7 from the cameras' `tool.py`: the
picture is a luxury, the question is not.

**And a query leaves the house.** An image search, or the URL of a
lesson image, travels; the conversation does not. This is the aperture
§1.1 already admits for web search, and it goes into §12 rather than
being discovered later.

**Deferred, needs the network but not the GPU:** whether the web search
Hermes ships returns images or only text links. If only links, the
alternative is taking the first image from the page, which is more
fragile. Worth knowing before the rest is written.

## Failure, and the way out

**There is no "mode" to get stuck in.** The widget never learns that a
class is happening: the card is band content, like a photo. An open
course is a row in SQLite and a thread in the conversation. "Ya está"
closes the session; not closing it breaks nothing and leaves the course
open for tomorrow, which is what was asked for.

- **With no strip connected the question is still asked, out loud.** The
  words never depend on the drawing. A multiple choice only heard is
  worse than one seen, and infinitely better than a mute turn.
- **An unanswered question is not a wrong answer.** The five-minute
  ceiling closes it and marks it unanswered. Counting it as a miss would
  poison the list of weak concepts, which is the datum everything else
  depends on.
- **`responder` with nothing open** returns "no hay ninguna" and he
  carries on talking. A second `preguntar` while one is open replaces
  it and marks the previous one unanswered.
- **The database may not take down a turn.** Locked, corrupt or
  unreadable: the tool returns an honest sentence and the conversation
  continues. Nothing in this plugin raises into a turn.
- **The gateway restarts mid-class:** the course survives (it is on
  disk), the pending question does not (it is in memory). It is asked
  again. That is the right split.

**And one task that is not code:** the `platform_hint` has to say he can
teach — and §7 rules, so a session that already exists will not see it
until `/new` + `/approve` through the strip. That trap has already cost
an afternoon.

## Testing

Everything below runs with no GPU, no network, no display and no
gateway.

| what | how |
|---|---|
| `curso.py` | SQLite in `tmp_path`: progress across days, the weak-concept ranking, unanswered ≠ missed. |
| `markdown.py` | The subset; anything outside it comes out literal; options parsed from the list. |
| `ficha.py` | Height from content and capped; covered by a photo and returned when it goes; the five minutes waiting against the minute not waiting; the correction state. |
| `tool.py` | Handlers with a fake `push_ficha`: empty args degrade, an image that will not download does not cost the question. |
| `protocol.py` / adapter | The frame's shape pinned; `decode_client` untouched; a path outside the spool refused. |

**What no test settles**, listed as such per §2.3:

- **The appearance.** `ffmpeg -f x11grab`, confirmed with `xwininfo
  -name JARVIS` so that what was photographed is the strip.
- **`preguntar`'s two arguments against the real gateway.** Waits for
  the GPU.
- **Whether Hermes' web search returns images.** Needs the network.

## Costs, stated

- **A fourth kind of content in the band**, and the first that has to be
  covered and restored rather than simply replaced. That is a small
  stack in the widget where there was none.
- **A Markdown parser of our own.** A subset is a promise to keep it a
  subset; the temptation to grow it into a renderer is real and is
  refused here in advance.
- **A second spool of downloaded files** on this box, with its own
  validation, deliberately not shared with the cameras'.
- **A query leaves the house per lesson image.** §1.1's aperture, widened
  by exactly one more use.
- **A fifth frame on a contract** that had one type in it until August
  and will now have five. Every one of them is server-to-client, and
  `decode_client` still has two.

## Out of scope, deliberately

- **The phone.** The lesson is the desk's. The phone page stays a button
  you hold. Teaching there is its own design.
- **He never starts a class.** No cron, no spaced-repetition ambush, no
  offer during a pause. Decision 6 above.
- **The user's own material** — PDFs, notes, a book. Decision 2: open
  subjects, from what the model knows.
- **Generated images.** Search only. Generation needs an external model
  and sends a description of the lesson out of the house for a diagram.
