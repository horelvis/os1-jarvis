# Spike: `ClaudeSDKClient` (claude-agent-sdk) as the bridge's engine

*2026-08-26. A question, not a plan: should `bridges/code-a2a/runner.py`
keep driving the assistant as a subprocess, or use the official SDK?*

Measured on this box against the user's own subscription. Nothing was
integrated; the throwaway project and venv are gone.

## What it is, and what it is not

`claude-agent-sdk` **0.2.144** installs, imports and runs here with no
API key — it authenticates the way the CLI already does.

It is **not an embedded engine** — a phrase from the analysis the user
brought in ("es el mismo motor de Claude Code embebido"), and one worth
pinning down before a design rests on it, because the same analysis also
said the CLI ships bundled and spoke of "ventajas sobre el subprocess
crudo". Both of those are right. What does not follow is the reading
that the subprocess is gone. Inside, `_internal/transport/
subprocess_cli.py` runs:

    claude --output-format stream-json --verbose …

and parses the lines. That is, to the letter, what `runner.py` already
does. Choosing the SDK does not remove a subprocess or a JSON parser; it
buys what sits on top of them.

## Measured

| | result |
|---|---|
| a real fix, end to end | bug found, edited, tests run — 30.9 s, $0.48 |
| typed messages | `AssistantMessage` / `ToolUseBlock` / `ResultMessage`, `session_id`, cost |
| `interrupt()` | **stops a running task — sent at 8.0 s, stopped at 8.0 s** |
| `can_use_tool` | never consulted for `Bash`, with OR without `allowed_tools` and with `setting_sources=[]` |
| `PreToolUse` hook | saw every call and **denied** one |

## The permission trap, because it inverts the obvious reading

`can_use_tool` reads like the place to decide what the assistant may do.
It is not, and the SDK says so in a warning it raises itself: an
`allowed_tools` entry auto-approves **before** the callback. Measured
here it went further — `Bash` never reached the callback even with no
`allowed_tools` and no settings loaded, while the `PreToolUse` hook saw
everything and could refuse.

**So the gate is the hook.** If the point is for JARVIS to ask out loud
before an `rm` or a `push` — instead of today's
`--dangerously-skip-permissions` — that is a `PreToolUse` hook, not a
permission callback.

## Where it would go

Not a fourth option beside the bridge: **it replaces the engine inside
it**. A2A stays the outward face — that was chosen deliberately for
OpenCode and for agents that are not on this disk (§12, 2026-08-26) —
and `subprocess.Popen` inside `runner.py` becomes `ClaudeSDKClient`.

What that would buy, in the order it matters here:

1. **Stopping him.** Today a launched task runs to the end; there is no
   way to say *"déjalo"*. This is the same gap the voice had.
2. **A session that continues.** `resume` / `session_id` / `fork_session`
   turn *"seguimos con lo de esta mañana"* into a real thing. Every run
   today starts from nothing.
3. **Supervision.** A `PreToolUse` hook is where JARVIS could ask before
   something irreversible.
4. **Typed events** instead of `classify()` guessing at JSON — and the
   console would no longer need the tee'd file.

## What it costs

- **342 MB** of bundled CLI. Avoidable: `ClaudeAgentOptions(cli_path=…)`
  points at the `claude` already installed.
- A dependency inside the gateway, and one that ties that path to Claude
  Code specifically — which is precisely why the A2A face stays.
- `anyio`, and an async client living next to threads that are not.

## Recommendation

Worth doing, for `interrupt()` and the session — not for the parsing,
which works. Not urgent: what exists is verified and in use.

## Taken up, the same evening

Done: `sdk_runner.py` drives the SDK, `sessions.py` keeps a session per
project, and `tasks/cancel` reaches a running assistant instead of only
marking a task. A2A stays the outward face and the CLI stays the
fallback, so a box without the SDK — or with OpenCode instead — behaves
as before. Measured against the house: stopped at 18.1 s inside a
90-second command, and a second run recalling the first "de memoria".
