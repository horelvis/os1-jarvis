# He works on the projects — design

> **Status:** design, agreed with the user 2026-08-26. Not implemented.
> The implementation plan follows from this document.

## What it is

JARVIS opens a working session on one of the user's projects and hands
the actual coding to a code assistant — Claude Code today, deliberately
not only Claude Code. The user says *"hoy trabajamos en barndoor"*, then
types what he wants done. The assistant works; JARVIS stays quiet;
JARVIS speaks only when there is something to decide.

The point, in the user's words: **"así me ayuda en mi trabajo."**

## The five decisions that shape it

Taken with the user on 2026-08-26, in this order, and each one closed a
different design.

1. **JARVIS drives the assistant, not the other way round.** Hermes
   ships `mcp_serve.py`, which would let Claude Code use Hermes' tools;
   that is the opposite direction and was not what was wanted.
2. **The work is asked for in TEXT, in the strip.** Voice is a bad
   channel for paths, file names and fragments, and it is where a
   misheard word now costs a commit. §1.5 says the strip has nothing to
   focus and nothing to click — this bends that, knowingly, the same way
   the three switches did earlier the same day. It stays a strip: a
   line that appears when called and goes away again, never a chat
   window with a history.
3. **The voice is reserved for what needs the user's judgement.** Not
   progress. The user's refinement, and it resolves the tension §1 has
   with any agentic work: *"quizás solo audio las sugerencias o
   preguntas del asistente de código."* He does not narrate the
   machinery, because there is nothing to narrate until a question
   arrives.
4. **Full scope, including `push`.** The user's decision, with the risk
   stated at the time. The bounds are the project root and the session
   expiry below, not a smaller permission.
5. **Projects are the directories under a root** (`~/git`, 26 of them,
   21 real repositories), not a configured list. Nothing to maintain,
   and the root doubles as the boundary of where the assistant may
   work.

## Architecture

A Hermes plugin, `Hermes/plugins/samantha_code/`, built like
`samantha_vision`: it registers tools, owns a subprocess instead of
camera threads, and reaches the strip through the injection path that
already carries camera sightings.

```
strip (typed)  ──ws──►  gateway  ──►  samantha_code
                                          │  claude -p
                                          │  --input-format stream-json
                                          │  --output-format stream-json
                                          │  --session-id <per project>
                                          ▼
                                    the project's directory
                                          │  events
                                          ▼
                                  what deserves the voice?
                                          │  yes
                                    inject_message ──► JARVIS speaks
```

| file | responsibility |
|---|---|
| `projects.py` | the root, its directories, and matching a spoken name to one |
| `session.py` | one working session: which project, the child process, its lifetime |
| `stream.py` | reading the assistant's event stream; deciding what is worth saying |
| `tool.py` | `trabajar_en`, `encargar`, `dejar_el_proyecto` |
| `__init__.py` | registration, config, the push to the strip |

### Naming a project out loud

The same problem the wake word had, and the same answer. Whisper renders
`os1-samantha` as "OS uno Samanta" and `lejepa-difusion` as anything at
all; an exact match would reject most attempts. Matching is a similarity
ratio over the folded name, as in `wake.py`, and — unlike the wake word
— an ambiguous match asks instead of guessing, because opening the wrong
project is a mistake that writes files.

### What earns the voice

The stream carries far more than the user wants to hear. The filter is
the whole product decision of point 3, so it is one module with one job
and its own tests:

| event | voice? |
|---|---|
| the assistant asks something | **yes** — this is what the feature is for |
| it proposes a choice | **yes** |
| it finishes | **yes**, one line: what changed |
| it fails or gives up | **yes** |
| tool calls, file edits, thinking, progress | no |

Answering a question goes back the other way: the user replies out loud,
and the reply is written into the child's stdin as a stream-json
message. That is the whole reason for `--input-format stream-json`
rather than a one-shot `-p`.

### The strip's typed line

A single-line entry that appears on the band, takes one instruction, and
disappears — no history, no scrollback. It is opened deliberately (a
key, or a switch beside the other three), never by focus. `photo.py`
already models the band as pure state with a height the window grows to;
this is a second thing that band can hold.

### The band as a terminal

The user's, and it is better than what this document said first — which
was "that is what the terminal is for". The band above the wave already
grows for a photo and for a live camera; it can hold the assistant's
output the same way. Nothing new appears on the desktop, no window is
opened, and the thing that was true of the camera stays true here: it
grows when there is something to show and goes back to 96 pixels when
there is not.

What that costs and what it buys:

- **It is text, and the band draws with GSK**, which has no text
  primitive of the kind this needs. The band is a widget, so the answer
  is a real GTK child inside it — a scrolling label — rather than
  another hand-drawn thing. It is the first child the band has ever had.
- **The output is a stream, not a frame.** The photo arrives once and
  the video arrives as packets; this arrives as lines, indefinitely. The
  band holds the last N and drops the rest: a scrollback is a window,
  and this is not one.
- **It does not fade.** A photo goes after fifteen seconds because it
  answered a question; a working session is answered when the work ends.
  It closes with the session, with the click the picture already
  answers, or on the ceiling that closes the session anyway.
- **It reuses the protocol shape, not the code.** `photo` and `live` are
  server-to-client frames on the kiosk socket; this is a third. The
  strip already drops frames it does not recognise (2026-08-25), so an
  older widget meets a newer gateway safely.

This changes the split decided earlier: the VOICE still carries only
what needs judgement, but "the work is invisible" is no longer true —
it is on the strip, where the user can glance at it and not have to.

## Safety, such as it is

The user asked for full scope and gets it. What bounds it:

- **The project root.** The child runs with its working directory inside
  `~/git/<project>` and `--add-dir` is not passed, so a project cannot
  reach a sibling.
- **The session expires.** No instruction for an hour closes it. A
  working session that outlives the working day is a process with commit
  rights and nobody watching.
- **One session at a time**, like the live camera view. Two assistants
  writing to two repos on one spoken word is not a thing anybody asked
  for.
- **It says what it did.** The closing line names the project and
  whether anything was pushed. The user hears the consequence even when
  he did not watch the work.

Not in scope, deliberately: reviewing the diff by voice, approving
individual edits, or any permission prompt. The user considered and
rejected the narrower scopes.

## Errors

The rule the vision plugin already follows: a failure costs the feature,
never the house. The child dying, the stream ending mid-sentence, a
project that is not a directory, `claude` missing from PATH — each is
one spoken sentence in his own words and one log line, and the gateway
keeps talking. The subprocess is killed when the session closes or the
plugin unloads; an orphaned assistant with commit rights is the one
outcome worth writing a test against.

## Testing

- `projects.py`, `stream.py` and the session's lifetime are pure enough
  to test without a gateway, a repository or the `claude` binary — the
  split `samantha_vision` already uses.
- The filter gets a recorded stream to work from: real
  `--output-format stream-json` output from one real task, saved as a
  fixture. It is the only way to pin "this deserves the voice" against
  what the assistant actually emits.
- End to end is a human with a keyboard and a real repository, as it was
  for the camera.

## What this is not

- Not a second brain: the assistant does the coding, JARVIS carries the
  conversation. He does not review, judge or summarise the work beyond
  the line he is handed.
- Not tied to Claude Code. The child is a command and a way of reading
  its output; another assistant is another adapter, and the user said so
  from the start ("u otro asistente").
- Not a terminal you can type into. The band SHOWS the assistant's
  output (see above); the instruction still goes in through the strip's
  one-line entry, and nothing is interactive inside the band.
