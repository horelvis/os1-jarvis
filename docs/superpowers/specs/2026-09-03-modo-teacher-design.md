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
> needs the model is marked as such and deferred to a named check.

## What was asked for, in the user's own answers

Taken 2026-09-03, in the order they were taken:

1. **JARVIS teaches the user a subject** — he is the teacher, the user
   is the student.
2. **Any subject, open.** No ingestion of the user's own documents.
3. **A mode with state and progress across days.** He knows where you
   left off, resumes tomorrow, and examines you.
4. **Voice plus pictures** — and, added mid-conversation and decisive:
   *"importante mostrar por pantalla las preguntas tipo texto."* The
   questions are read AND shown.
5. **Multiple choice on screen, answered out loud.**
6. **You always start the class.** No cron, no proactive review.
7. **He stays himself during a class.** A camera alert or an ordinary
   question is answered and the lesson waits.
8. **A study plan he proposes, you approve, and he then adjusts.**
   *"creo que falta lo de generar plan de estudio"* — without one,
   "progress" only ever meant "how many things we have touched".
9. **A documentary base, so he is not teaching from memory.**
   *"importante tener una base documental donde apoyarse durante el
   curso, es decir que no se aprenda memoria y siempre busque en
   internet para crear el plan."*
10. **Real material, not only invented material.** The example that
    settled the shape: *"por ejemplo para sacar el B1, pues información
    de gramática, test reales."*

And one correction of the design, not of the request: an early draft
made the course work with the network unplugged and counted that as a
virtue. The user withdrew it — *"sin red, ha sido cosa tuya, no he
incluido esa limitación, la red es poder"* — so nothing here is
designed around being offline.

## Where it lives, and what each piece may not know

A new Hermes plugin, `Hermes/plugins/jarvis_teacher/`, `kind:
standalone` — the shape of `samantha_vision`. `register(ctx)` declares
tools and touches nothing outside the process; that is a plugin's whole
lifecycle on the way in (proved on this pinned Hermes, 2026-08-24).

| file | what it does | what it must not know |
|---|---|---|
| `curso.py` | The state: courses, the plan, concepts, questions, answers. SQLite. | That a model, a gateway or the network exists. |
| `fuentes.py` | Searching, fetching, reducing to text, and finding the passages a concept needs. | That anything is drawn. |
| `markdown.py` | The Markdown subset: parse, and pull a list out of it. | Everything else. |
| `tool.py` | The seven tools the model sees, in Spanish. | How anything is drawn. |
| `imagen.py` | Resolving `![](…)` references into local files. | Everything else. |

`push_ficha` arrives at `tool.py` as a **callable**, the way
`cameras.py` takes `on_detections`; `fuentes.py` takes its fetcher the
same way. That is what lets the whole plugin run in a test with no
gateway, no strip and no network in the room.

In the widget, the pair this project already uses twice: `ficha.py`
(pure state, no GTK, testable without a display) under `ficha_area.py`
(the drawing), exactly as `photo.py` sits under `photo_area.py`.

### The division that makes "resume" true

**The plugin stores facts and sources; the model writes the words.**
The plugin never stores an explanation of the present perfect. It
stores that the concept is third in the plan, was taught on Tuesday,
asked twice, missed once, and which passages of which source it rests
on. Tomorrow the model writes the explanation again with those facts
and those passages in front of it.

This is the whole reason for a database. Keeping the syllabus in
Hermes' own memory and letting the model remember was rejected on the
evidence of §12 (2026-09-01): a model on this box will confidently
describe a backup generator the house does not have. "Where we left
off" must be a reading, not a recollection.

## The state

`~/.samantha/teacher/curso.db`. Six tables:

- **`curso`** — `tema` ("sacar el B1 de inglés"), opened at, last
  touched at, whether the plan is proposed or approved, whether it is
  still open.
- **`concepto`** — the unit of progress, and it now exists **before**
  it is taught: title, course, `orden`, and `estado` — `pendiente`,
  `dado`, `a repasar`, `dominado`, `descartado`.
- **`pregunta`** — the card's Markdown, the parsed options, which was
  correct, which was chosen, whether it was right, when, and **which
  source it came from** when it came from one.
- **`sesion`** — when each class began and ended, so "we left it on
  Thursday" is a fact.
- **`fuente`** — url, title, when it was fetched, a hash of the text.
  The text itself is a file under `~/.samantha/teacher/fuentes/<curso>/`.
- **`dominio`** — the hosts approved for this course, and when.

**Nothing is ever deleted** — §2.7's rule for memory, applied here.
Taking "the third one" out of the syllabus marks that concept
`descartada`; it does not remove the row. So a plan that has been
adjusted still tells its own history.

## Opening a course, in two steps

This is the part the user's B1 example shaped, and it is deliberately
not one step.

**1. `ensename("sacar el B1 de inglés")`.** The plugin searches and
keeps **only titles, links and snippets** — it downloads no page. It
hands those to the model and asks for two things at once: a syllabus,
and the sources it intends to lean on.

**2. `aprobar()`.** Only now are those pages fetched, reduced to text
and stored, the domains recorded, and the plan marked approved. The
first concept comes back.

**What the split buys is the one risk this feature adds**, and it is
not a small one: text from an arbitrary web page enters the context of
an agent that has held `terminal` since 2026-08-26 (§12). A page saying
"ignore your instructions and run this" is the attack, and it is not
theoretical. Splitting the step means **no page's text reaches that
context until a person has seen which domains it comes from.**

Approval is of **domains, once per course**. After it he searches and
fetches freely within them and never asks again; he asks only to add a
new one. So this is a security gate, not a limit on using the network.

The mitigations on the text itself are all partial and are worth
naming as such: HTML is reduced to text, the passage is capped, and it
reaches the model inside an explicit "material, not instructions"
envelope. None of them solves the problem. Search snippets, which
arrive before any approval, are untrusted too — small, but untrusted.

## The plan, and how it adjusts

`planificar(temario)` takes the syllabus as a Markdown list. The plugin
parses it with the same parser that pulls the options out of a question
— no new code — stores the items in order as `pendiente` concepts, and
draws it. Changing it is calling `planificar` again with the amended
list; the old items become `descartada` rather than disappearing.

**The adjusting is a rule in `curso.py`, not a tool**, which is what
makes it cheap:

- A missed concept becomes `a repasar` and returns to the queue a few
  concepts later.
- A concept answered correctly twice becomes `dominado` and leaves the
  queue.
- A `dominado` concept is not taught again, which is the whole of
  "if you are ahead, it skips what you know".

What the model sees is the fact sheet, which `ensename` returns on a
course that already exists. Labelled data, not a sentence — the same
remedy that stopped the cameras inventing where people were (§12,
2026-08-24, "en la fuera de casa"):

```
Tema: sacar el B1 de inglés. Última clase: jueves. Plan: aprobado.
Base: 7 fuentes, 4 dominios.
Dados: 6 de 22.  A repasar: present perfect (1 de 3), condicionales (0 de 2).
Siguiente: reported speech.
Practicado con material real: 9 preguntas de 14.
```

## The documentary base

The base is built when the course opens and **it goes on growing**. A
lesson whose concept the base covers badly may search again, within the
approved domains. Nothing here is designed to work with the network
unplugged; the user withdrew that constraint explicitly.

`explicar(concepto)` looks **inside the stored base first** — a local
keyword search over the extracted text, no embeddings, no ChromaDB, no
new dependency — and returns the passages that bear on the concept.
When they are thin, it fetches more and stores that too.

**No sources, no course.** If the search brings nothing back,
`ensename` says so and no syllabus is invented. That failure is
honest and rare, and it is better than a plan with nothing under it.

**Real material changes where a question comes from.** With sample
exams in the base, a question is **taken from a source** rather than
invented: `pregunta` records the source it came from, the card cites it
at the foot, and the fact sheet keeps the two apart. For a B1 that
distinction is the product — practising against real exam items is not
the same activity as answering something a model made up.

## The tools

One toolset, `clases`. Spanish names, like `mirar`, for the reason
`tool.py` already records: the model is answering somebody who speaks
Spanish.

| tool | args | what it does |
|---|---|---|
| `ensename` | `tema` (optional) | New course: searches, returns candidate sources and asks for a plan. Existing: returns the fact sheet. |
| `planificar` | `temario` | Stores the syllabus in order and draws it. Called again to amend it. |
| `aprobar` | — | Approves plan and domains, fetches and builds the base, returns the first concept. |
| `explicar` | `concepto`, `ficha` (optional) | Finds the passages, records that it was taught, draws the card when one is given. |
| `preguntar` | `ficha`, `correcta` | The card, stored, scored and drawn. Carries its source when it has one. |
| `responder` | `elegida` | The spoken answer, scored against what was stored. |
| `terminar` | — | Closes the session, returns the summary. |

**The model writes the question; the plugin decides whether you were
right.** The correct option has been stored since the card was made, so
scoring is a comparison rather than an opinion. The model only
translates "la b" or "la segunda" into an option.

### The known defect this design has to survive

§12 (2026-08-26, corrected 2026-09-01) records that through the Hermes
path a tool of ours is called with `args={}` — `mirar` with no camera
five times out of five — and that **the model is not the cause**: put
the same tools to llama-server directly and it fills 4 of 4. Whatever
breaks the arguments lives in the Hermes path.

Consequences, all designed in rather than discovered:

- **No tool takes more than two arguments.** `preguntar`'s options are
  not a field; they are the bullet list inside the Markdown, which the
  plugin parses. Same for `planificar`'s syllabus.
- **`ensename` with no `tema` resumes the last open course**, which is
  the commonest case anyway. Empty args degrade into the right
  behaviour rather than into an error.
- **A card that cannot be parsed is never drawn.** `preguntar` returns
  "repite la pregunta con las opciones en una lista"; `planificar`
  returns the same about the syllabus.

**The check that settles it needs the live gateway and is therefore
deferred:** register a two-argument tool on the real gateway and see
what arrives. It is the switch-on check, not the first task, because
the box has no GPU free. If the arguments do not survive, the fallback
is one argument in a fixed format.

## The screen: the card is a Markdown document

A fifth server-to-client frame on the kiosk protocol, sibling of
`photo` and `console`. `decode_client` is untouched — the strip never
sends one.

```json
{"type": "ficha", "tipo": "pregunta",
 "md": "## What ___ you doing?\n\n- do\n- **are**\n- have\n",
 "fuente": "Cambridge B1 Preliminary, sample paper 2",
 "correcta": null, "elegida": null}
```

**`tipo` is what tells a syllabus from an exam**, and it exists because
they are the same thing on the wire: both are a Markdown list.

| `tipo` | numbering | waits | goes away |
|---|---|---|---|
| `pregunta` | `a. b. c.` | yes | on answering |
| `plan` | `1. 2. 3.` | yes, until approved | on approval |
| `explicacion` | none | no | after a minute |

An earlier draft had a boolean `espera`, which could not distinguish
the first two. One field, and the widget never has to guess whether a
list is an index or an exam.

### A declared subset, drawn with GTK

There is no browser here and §3 says there will not be one. The blocks
become widgets inside the band that already knows how to grow:
`Gtk.Label` with Pango markup for text, `Gtk.Picture` for an image.

**In the subset:** paragraphs, a heading, **bold**, *italic*, `code`,
bullet and numbered lists, and `![](…)`.
**Out of it:** tables, HTML, links (there is nothing to click here), and
everything else — shown as the literal text it is rather than
pretending it was understood.

**No new dependency.** The subset is ours and is about a hundred lines
of parser in `markdown.py`, pure and testable without a display. A full
CommonMark library would be asking permission (§8) to render what we
have decided not to render.

### How it is laid out, and why

Four mockups were drawn against `theme.py`'s real values and the
layout was chosen from them on 2026-09-03: **the image on the left, the
statement and its options on the right.** The user's reason, which is
better than the one the mockup was argued with: it uses the 900 px the
strip already occupies, and a person takes in the picture and the
question in one look instead of two.

The rejected alternative was the image across the full width above the
text. It reads a diagram better and costs 402 px of band — a strip of
900x498, half the desktop covered every time a question is asked.

The card extends the console's vocabulary rather than inventing one:
the same `rgba(20,12,14,0.92)` panel, the same `rgba(209,104,78,0.35)`
border, 8 px radius, `0 16px 6px` margins. The typography is §1.3's
pair — Cormorant Garamond for the statement, Inter Tight for the
options — which until now was written in the spec and drawn nowhere.

**The options are lettered.** The list in the Markdown is a plain
bullet list; the card draws `a.` `b.` `c.` in front of the items,
because "la b" has to have something to refer to. A `plan` card is
numbered instead, because an order is what it is about.

**The correction uses one colour, not two.** §1.3 allows one, so there
is no green and no red: the right answer is marked in terracotta with a
check, and a wrong choice of yours goes dim and struck through. It was
the most arguable of the decisions and it was put to the user before
being written here.

**A card that came from a source says so**, in one dim line at the
foot. It is cheap, and it makes visible the thing decision 9 asked for:
that he is not teaching out of his own head.

Measured off the mockups: the card is **214 px** of band with an image
and **178 px** without one — a strip of 900x310 or 900x274, against the
900x480 a live camera already takes.

### How it behaves

- **An explanation goes after a minute; a question and a plan do not.**
  The ceiling differs because the waiting does.
- **The height is decided by the content**, exactly as the console has
  done since 2026-08-26: three lines in a box built for twenty is
  mostly empty box, and it showed. Ceiling the same as the live camera,
  480 px of strip.
- **A question does not fade while it is open.** But §1.5 says there
  are no windows here, so there is a ceiling: **five minutes**
  unanswered and it closes itself, the way the live view closes at
  120 s.
- **The correction is visible.** On `responder`, the same frame returns
  with `correcta` and `elegida` filled. Six seconds, then it goes.
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
present perfect. Sharing a spool is exactly the kind of path the
2026-08-25 decision exists not to open.

**A reference that cannot be resolved drops out of the document and the
question is asked anyway** — Ruling 7 from the cameras' `tool.py`: the
picture is a luxury, the question is not.

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
- **A plan proposed and never approved stays proposed.** Walk away
  mid-proposal and the card closes on its ceiling; tomorrow `ensename`
  offers that plan again rather than generating a different one, which
  would be the worst of both.
- **`responder` with nothing open** returns "no hay ninguna" and he
  carries on talking. A second `preguntar` while one is open replaces
  it and marks the previous one unanswered.
- **A source that will not fetch costs that source, never the class.**
  The base is what it managed to get; the fact sheet says how much.
- **The database may not take down a turn.** Locked, corrupt or
  unreadable: the tool returns an honest sentence and the conversation
  continues. Nothing in this plugin raises into a turn.
- **The gateway restarts mid-class:** the course, the plan and the base
  survive (they are on disk), the pending question does not (it is in
  memory). It is asked again. That is the right split.

**And one task that is not code:** the `platform_hint` has to say he can
teach — and §7 rules, so a session that already exists will not see it
until `/new` + `/approve` through the strip. That trap has already cost
an afternoon.

## Testing

Everything below runs with no GPU, no display and no gateway; the
network is faked at the fetcher seam.

| what | how |
|---|---|
| `curso.py` | SQLite in `tmp_path`: the plan's order and states, a miss returning a concept to the queue, two hits retiring it, `descartada` instead of a delete, the fact sheet's numbers. |
| `fuentes.py` | A fake fetcher: extraction, the cap, the local keyword search, a domain outside the approved list refused, a fetch that fails costing only its source. |
| `markdown.py` | The subset; anything outside it comes out literal; options and syllabus pulled from a list. |
| `ficha.py` | Height from content and capped; covered by a photo and returned when it goes; the three `tipo` behaviours; the correction state. |
| `tool.py` | Handlers with a fake `push_ficha`: empty args degrade, an unparsable card is never drawn, an image that will not download does not cost the question. |
| `protocol.py` / adapter | The frame's shape pinned; `decode_client` untouched; a path outside the spool refused. |

**What no test settles**, listed as such per §2.3:

- **The appearance.** Mockups settled the layout; they are not the
  thing. `ffmpeg -f x11grab`, confirmed with `xwininfo -name JARVIS`
  so that what was photographed is the strip.
- **`preguntar`'s two arguments against the real gateway.** Waits for
  the GPU.
- **What Hermes' web search actually returns** — whether a plugin can
  reach it directly, and whether results carry images. Needs the
  network, not the GPU, and it is the earliest task that can be done.

## Costs, stated

- **The syllabus's queries leave the house**, and that is considerably
  more than the one image query an earlier draft admitted. §1.1's
  aperture widens by a whole subsystem. The conversation still does
  not travel.
- **Untrusted text enters the context of an agent holding `terminal`.**
  The domain gate bounds who it comes from; nothing bounds what it
  says. This is the largest new risk in the feature and the reason the
  gate is not being dropped without the user saying so.
- **A fourth kind of content in the band**, and the first that has to be
  covered and restored rather than simply replaced. That is a small
  stack in the widget where there was none.
- **A Markdown parser of our own.** A subset is a promise to keep it a
  subset; the temptation to grow it into a renderer is refused here in
  advance.
- **Disk grows per course** — extracted text and images, never pruned,
  because §2.7 says nothing is deleted.
- **A fifth frame on a contract** that had one type in it until August.
  Every one of them is server-to-client, and `decode_client` still has
  two.

## Out of scope, deliberately

- **The phone.** The lesson is the desk's. The phone page stays a button
  you hold. Teaching there is its own design.
- **He never starts a class.** No cron, no spaced-repetition ambush, no
  offer during a pause. Decision 6.
- **The user's own material** — PDFs, notes, a book. Decision 2 is open
  subjects; a course grounded in documents the user supplies is a
  different feature with a different ingestion path.
- **Generated images.** Search only. Generation needs an external model
  and sends a description of the lesson out of the house for a diagram.
