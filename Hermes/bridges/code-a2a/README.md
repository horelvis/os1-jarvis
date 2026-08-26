# code-a2a — the coding assistant, over A2A

JARVIS hands work to a coding assistant, and does it through the open
[A2A protocol](https://a2a-protocol.org) rather than by shelling out.

## Why A2A and not a subprocess

Because of what comes next. The user's reason, 2026-08-26: *"por el
futuro uso de opencode"*. With A2A, another assistant is another server
speaking the same protocol — JARVIS never learns it happened, and
`assistants.py` gains a line. With a subprocess in a Hermes plugin, each
new assistant would be another adapter inside the brain.

It costs a service that would not otherwise exist, and it moves work
rather than removing it: this server does inside itself exactly what
that plugin would have done. What is bought is that Hermes needs **no
new code at all** — its `a2a` toolset already ships `a2a_call`,
`a2a_discover` and `a2a_orchestrate`.

## Run it

```bash
python server.py --port 9910 --root ~/git --assistant claude
```

- `--root` is the boundary as well as the list: projects are the
  directories under it, and the assistant is never run anywhere else.
- `--assistant` picks from `assistants.py`; omitted, it takes the first
  one installed.

## Tell Hermes about it

Nothing to write, only to configure:

```yaml
# .hermes/home/config.yaml
a2a_agents:
  codigo:
    url: "http://127.0.0.1:9910"
    timeout: 900
    capabilities: [code, development, tests]
```

and enable the toolset for the strip:

```yaml
platform_toolsets:
  samantha_kiosk:
    - a2a          # a2a_call, a2a_discover, …
```

Then it is a sentence: *"Jarvis, en barndoor arregla el log de la cámara
cuando se cae"* — he calls `a2a_call`, this runs the assistant there,
and what comes back is one line for him to say.

## What it does

| method | what happens |
|---|---|
| `GET /.well-known/agent-card.json` | the card; `/.well-known/agent.json` answers too, for pre-1.0 clients |
| `message/send` · `SendMessage` | run to completion, answer with the finished Task |
| `message/stream` · `SendStreamingMessage` | SSE: the Task, then a status update per line, then the terminal state |
| `tasks/get` · `GetTask` | look a task up |
| `tasks/cancel` · `CancelTask` | mark one cancelled |

**Both spellings of every method are accepted, and that is load-bearing.**
The v1.0 specification names them `SendMessage` / `SendStreamingMessage`;
Hermes' client sends `message/send` / `message/stream`. Answering only
one is how two correct implementations fail to meet.

## What it is not

- **Not authenticated.** It binds to localhost and runs the user's own
  assistant with the user's own credentials. Do not put it on a
  network.
- **Not multi-turn.** One request, one answer. When the assistant needs
  a decision it comes back as text; the reply is the next task.
- **Not sandboxed.** The assistant runs with `--dangerously-skip-permissions`
  — the user's decision of 2026-08-26, taken with the risk stated, and
  the recorded alternative does not work unattended: under `acceptEdits`
  two commands and the edit itself were refused, and the assistant ended
  up describing a fix it could not apply.

## The recording

`tests/fixtures/stream.jsonl` is 38 real events from Claude Code fixing
a deliberately broken test. The classifier in `stream.py` is tested
against it rather than against an idea of the format — which is how
`permission_denied` turned out to be an event that matters, and how the
`text` / `tool_use` split inside one `assistant` message was found.
