# He works on the projects, and asks — design (v2)

> **Status:** design, agreed with the user 2026-08-27. Supersedes the
> interaction half of `2026-08-26-samantha-code-design.md`; what that
> document decided about projects, the typed line and the band as a
> terminal stands and is not repeated here.
> The implementation plan follows from this document.

## What was wrong with v1

The user, 2026-08-27, asked and answered:

- **The console is noisy.** `summarise()` renders the stream almost
  raw — one `· Bash: <command>` per tool call, paths cut at 200
  characters, the same line twice. Watching it is not the same as
  seeing the work.
- **He never asks.** The delegation path that actually shipped —
  Hermes' `claude-code` skill over `terminal`, `claude -p` with
  permissions bypassed — is one-shot. A question Claude Code would
  have asked is decided alone; a decision that was the user's is made
  by nobody. This was the point of the feature ("what earns the
  voice") and the terminal path structurally cannot deliver it.

Explicitly NOT a problem: JARVIS' closing line. The user did not ask
for the final relay to change.

Three moments must reach the user, all three chosen explicitly:
Claude Code's own questions, anything irreversible before it runs,
and a checkpoint when the work ends. The question travels by voice
(and sits, literal, on the band); the answer comes back spoken or
typed, whichever the moment wants.

## The shape: asynchronous, and the model never carries the answer

Three processes, all of which already exist. Nothing new runs.

```
you (voice or the typed line)
  │
strip ──ws──► gateway (Hermes)
                │ model: a2a_call("codigo", task)        ① start
                ▼
              code-a2a bridge (:9910, own venv, SDK inside)
                │ accepts and returns `working` AT ONCE
                │ — the voice turn ends in seconds: «En ello, señor»
                │
   samantha_code plugin ◄──stream──┘                     ② watch
                │ typed SDK events (the tee'd file retires)
                ├─► milestones → `console` frames → the band
                │
                └─► question / gate / ending              ③ ask
                      inject_message ──► JARVIS says it, his words
                                          (the literal question on the band)
your answer ──► kiosk adapter ──► bridge                 ④ answer
   (while a question is pending, input goes straight to the bridge;
    open with «Jarvis…» and it goes to JARVIS as always)
```

Why each leg is the way it is, each pinned to something measured:

- **Starting is `a2a_call`** because it is the one custom-shaped tool
  this model fills correctly (verified end to end, PROGRESS
  2026-08-26 noche III). Our own tools get `args={}` six times out of
  six (§12, 2026-08-26); the answer path therefore never depends on
  the model filling anything.
- **The call does not block.** The bridge returns the task in
  `TASK_STATE_WORKING` immediately. A blocking `a2a_call` was
  considered and rejected: a task is minutes long, the kiosk watchdog
  closes a turn at 90 s, and a held turn folds everything else said
  into the run («Redirected current run», §5).
- **The plugin drives, not the model.** It subscribes to the bridge's
  stream (the `message/stream` route that already exists), renders
  milestones, and holds the one piece of state that matters: whether
  a question is pending.
- **Questions reach JARVIS by injection**, the mechanism the vision
  alerts verified: a *user*-role message asking him to relay the
  question in his own words. He speaks; the literal text is already
  on the band, so his paraphrase cannot lose the substance.
- **Answers are routed by the adapter, deterministically.** While a
  question is pending, the next client input — spoken or typed — is
  delivered to the bridge and does not open a Hermes turn. An input
  opening with the wake word goes to JARVIS as always and the
  question stays pending. No widget change is needed for voice:
  JARVIS just spoke the question aloud, so the 30-second no-name
  window is already open.
- **Fallback:** a box without the bridge keeps the v1 path — skills
  over `terminal`, the tee'd file, the follower — and loses exactly
  milestones and questions. On THIS box the platform steering
  (skill/hint) points delegation at `a2a_call`.

## The console: milestones, not commands

Classification lives in the bridge (`stream.py`, extended over the
SDK's typed events); the plugin only renders Spanish and pushes. The
model is deliberately not involved: an LLM call per event costs VRAM
and latency (§0's budget), and the voice stays reserved for judgement
— the user's decision of the 26th, kept.

| SDK event | line on the band |
|---|---|
| first Read/Grep/Glob of a phase | «Leyendo el proyecto…» — once, not per file |
| Edit/Write on a file | «Editando vad.py» — once per file, not per edit |
| Bash running tests | «Pasando los tests…», then «Tests: 12 pasan» / «2 fallan» |
| any other Bash | «Ejecutando: <short verb>» — never the whole command |
| assistant text (progress) | its first sentence, trimmed — the one near-literal line |
| question / gate | the **literal** question, marked, held until answered |
| ending | «— terminado: 2 ficheros, tests en verde» (or the failure) |

Hard rules: never the same line twice in a row, never JSON, never a
200-character path. The `console` frame's `reset`/`done` flags (in
the working tree as of this design) stay as they are.

## The three moments

**a) Claude Code asks.** Two forms, both covered. If it ends its turn
asking in text, the bridge leaves the task in
`TASK_STATE_INPUT_REQUIRED` carrying the question — that is plain A2A
and plain SDK resume. If it calls its `AskUserQuestion` tool, the
`PreToolUse` hook sees the call (the hook sees everything; the
permission callback sees nothing — measured, spike 2026-08-26), holds
it, and emits the question event. Either way: inject → JARVIS speaks
→ literal text on the band → your answer routes back → the session
continues. *How exactly an answer is returned into a held
`AskUserQuestion` is the one unmeasured piece; the implementation
plan opens with a one-hour probe, as the SDK spike did.*

**b) Before the irreversible.** The same hook, against a short policy
configurable in `samantha-config.yaml`: `git push`, recursive
deletes, `sudo` — `git commit` only if the user adds it. JARVIS:
«Quiere hacer push a barndoor, ¿le dejo?». Yes releases the tool; no
denies it with a reason and the assistant works on without it. **No
answer within 5 minutes denies it** and the closing line says so — a
push granted by silence would be worse than one that waits. Anything
not listed runs without asking, or every Edit becomes an
interruption. This partially reverses «full scope, including `push`»
(§12, 2026-08-26) and is recorded as such in the decision log.

**c) When the work ends.** The bridge does not close into
`completed`: it leaves `input-required` carrying the summary. JARVIS:
«Ha terminado: X. ¿Lo doy por bueno?». «Sí / vale» closes it;
anything else is the next message of the same session — the
continuity the SDK already provides. No answer within 10 minutes
closes it alone, and he says so.

**Cost, stated:** Hermes' session does not see the routed answers.
What JARVIS remembers of the exchange is what the closing injection
carries. Accepted — the alternative routes the answer through the
model that loses arguments.

## Safety and errors

- The existing bounds stand: cwd inside `~/git/<project>`, no
  `--add-dir`, one active session, sessions expire (the SDK's two
  days, plus the bridge's inactivity close).
- `bypassPermissions` stays for everything outside the gate policy;
  the hook is the only customs post. The spike's finding, applied:
  the gate is the hook, not the callback.
- Vision's rule throughout — a failure costs the feature, never the
  house: bridge down → `a2a_call` fails and JARVIS says so in one
  sentence; stream drops → the plugin retries with backoff and the
  band says «he perdido de vista el trabajo» while the task runs on;
  injection with no session → three retries and drop, as the cameras
  do; question pending with the strip disconnected → the voice
  already carried it, and a spoken answer still lands. The child dies
  with the session; the orphaned-assistant test in the bridge stays.

## Testing

- **Bridge:** one real recording of typed SDK events as a fixture →
  the milestone classifier, the non-blocking `message/send`, the gate
  with a simulated answer, the timeout that denies.
- **Plugin:** the pending/answered state machine, pure, no gateway;
  the injection retries.
- **Adapter:** the routing — pending diverts, «Jarvis…» does not,
  no-pending sends everything to Hermes.
- **End to end:** a human with a keyboard and a real repository, as
  it was for the camera. The `AskUserQuestion` probe is task one of
  the plan.

## What this is not

Unchanged from v1, and worth repeating once: not a second brain (the
assistant codes, JARVIS carries the conversation), not tied to Claude
Code (the bridge speaks A2A; another assistant is another entry in
`assistants.py`), not a terminal you type into (the band shows; the
typed line and the voice are where words go in).
