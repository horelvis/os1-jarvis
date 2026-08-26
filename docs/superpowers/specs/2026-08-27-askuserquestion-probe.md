# Probe: how an answer gets back into a held `AskUserQuestion`

*2026-08-27. Measured against the user's own subscription, in a scratch
repo (`/tmp/probe-ask-repo`, deleted after), using the bridge's venv
(`Hermes/bridges/code-a2a/.venv`, `claude-agent-sdk` 0.2.x). Throwaway
probe script (`probe_ask.py`) deleted after this doc was written; three
configurations plus the gate check, four runs total.*

## The question

Task 4 needs to get a user's answer to a mid-run `AskUserQuestion` back
into the held SDK session. Three candidate mechanisms, per the brief:

- **P1** — `can_use_tool` steers it via `updatedInput`.
- **P2** — the `PreToolUse` hook denies with a `permissionDecisionReason`
  carrying the answer.
- **P3** — neither works in non-interactive mode; the plan drops the
  AskUserQuestion half of Task 4.

## SDK API corrections (0.2.x, installed here)

The brief's sketch was close but not literal:

- **`can_use_tool` must return a typed `PermissionResultAllow` /
  `PermissionResultDeny`, not a raw dict.** `_internal/query.py` does
  `isinstance(response, PermissionResultAllow)` and raises `TypeError`
  otherwise — `{"behavior": "allow", "updatedInput": …}` fails outright.
  Use `PermissionResultAllow(updated_input=tool_input)` (snake_case
  field name).
- **`PreToolUse` hooks keep the dict/TypedDict shape** from the brief —
  `{"hookSpecificOutput": {"hookEventName": "PreToolUse",
  "permissionDecision": "deny", "permissionDecisionReason": …}}` is
  exactly what `HookJSONOutput` expects. No correction needed there.
- **`AskUserQuestion` is not referenced anywhere in the SDK package**
  (`grep -rn AskUserQuestion claude_agent_sdk/` — zero hits). It is not
  special-cased for permissions; it is a tool name like any other, and
  whether it is even offered to the model depends on the run's tool
  catalogue (see configuration 3).

## Measured

| config | `permission_mode` | mechanism under test | callback that fired | outcome | file created |
|---|---|---|---|---|---|
| 1 — as written | `bypassPermissions` | P2 (deny + reason) | `PreToolUse` only. `can_use_tool` never ran — the SDK warns why (below) | model: *"Elegiste la opción B. He creado únicamente `b.txt`…"* | **`b.txt`** |
| 2 — `updated_input` answer | `default` | P1 (`updated_input`) | `can_use_tool` (confirmed invoked this time) | model: *"No has seleccionado ninguna opción, así que no he creado ningún fichero."* — asked again | none |
| 3 — no hooks at all | `bypassPermissions` | neither | none | `AskUserQuestion` absent from this run's tool catalogue; model fell back to `ToolSearch` → `mcp__claude_ai_AgentDialog__human_query`, sent a real out-of-band question, and the turn ended waiting on it | none |
| gate check | `bypassPermissions` | `PreToolUse` deny on `git push` | `PreToolUse` | model: *"No ejecuté el push: la llamada quedó bloqueada porque no se autorizó el comando…"* | n/a (confirms spike) |

### Configuration 1, in full — the decisive run

Command: `.venv/bin/python probe_ask.py` (script as in the brief, `pre_tool`
denying `AskUserQuestion` with reason "El usuario responde: la opción B.
Continúa con esa respuesta.", `can_use_tool` passing `tool_input` through
unchanged).

The SDK itself explains why `can_use_tool` never ran:

```
CanUseToolShadowedWarning: can_use_tool will not be invoked: permission_mode
'bypassPermissions' auto-approves every tool call (except explicit deny
rules) before the callback is consulted. To gate every tool call, use a
PreToolUse hook instead.
```

`[can_use_tool]` never printed once, for any tool, in this run — the
warning is literal. `[PreToolUse]` printed for `AskUserQuestion`, the
hook denied it with the option-B reason, and the model's next message
picked option B and ran `printf 'elegido\n' > b.txt` — nothing invented,
the reason text alone steered the choice. `b.txt` exists on disk after
the run; `a.txt` does not. This is the same mechanism the spike already
measured for `Bash` (`PreToolUse` sees everything, `can_use_tool` is
shadowed under `bypassPermissions`), now shown to double as a way to
*answer* a client-side question tool, not just gate a destructive one.

### Configuration 2 — P1 fails, and the reason is structural, not a wrong guess

Switching `permission_mode` to `"default"` (so `can_use_tool` is
actually consulted — confirmed: `[can_use_tool] AskUserQuestion: {…}`
printed) and returning `PermissionResultAllow(updated_input=answered)`
with a guessed `question["answer"]` field added: the model still says
*"No has seleccionado ninguna opción"* and asks again. No file
appears.

This is not a shape-guessing failure worth another round: `can_use_tool`
only rewrites the tool call's **input** before it runs (`updated_input`
replaces what the model is *asking with*), and there is no matching
field anywhere in the callback's return type — `PermissionResultAllow`
has no `updated_output` / `result` slot — for supplying the tool's
**result**. `AskUserQuestion`'s answer is necessarily a result, not an
input; the mechanism that exists cannot express it. Confirmed adequately
in one run; a second run would only reprice a structural fact.

### Configuration 3 — with nothing set up, the question is simply not reachable

No `hooks`, no `can_use_tool`, `permission_mode="bypassPermissions"`.
`AskUserQuestion` was not in the tool catalogue the model could see this
run (`ToolSearch` for it came back empty); the model substituted
`mcp__claude_ai_AgentDialog__human_query` — a real out-of-band
notification tool — and the turn ended with the model waiting on an
answer that has to arrive from outside the SDK session entirely (email,
per that tool's `target_human_email`). Re-run once to check it wasn't a
fluke: same substitution both times. Whatever decides whether
`AskUserQuestion` is offered at all is environment-dependent and outside
this probe's scope; the actionable fact for Task 4 is that **absent a
`PreToolUse` hook, there is no route back into a mid-run question that
resolves inside the same run** — it either goes unasked in this form, or
it blocks on a channel the bridge does not own.

### Gate check — confirms the spike, unchanged

`PROMPT` = `"Ejecuta 'git push' en este repositorio y después dime qué
pasó."`, `pre_tool` denies any `Bash` whose command contains `git push`.
`PreToolUse` saw it, denied it, the run continued to the end, and the
result explicitly reported the refusal. Matches the 2026-08-26 spike's
`Bash`/`PreToolUse` finding exactly — nothing new measured here beyond
confirming it still holds for this SDK build.

## The `AskUserQuestion` `tool_input` shape (for Task 4's extraction code)

Observed verbatim (configuration 1), the shape to build extraction
against:

```python
{
    "questions": [
        {
            "question": "¿Qué opción prefieres?",
            "header": "Fichero",
            "options": [
                {
                    "label": "Opción A (a.txt)",
                    "description": "Crear únicamente el fichero a.txt con el texto 'elegido'",
                },
                {
                    "label": "Opción B (b.txt)",
                    "description": "Crear únicamente el fichero b.txt con el texto 'elegido'",
                },
            ],
            "multiSelect": False,
        }
    ]
}
```

`questions` is a list (multiple questions possible in one call); each
question carries its own `options` list of `{label, description}` pairs
and a `multiSelect` flag. Task 4's extraction reads
`tool_input["questions"][0]["question"]` and the `label` of each option
under it, and answers by writing the chosen `label` text into the
`PreToolUse` deny's `permissionDecisionReason` (P2) — there is no
`updated_input`/result-based path (P1, ruled out above).

## What it costs

Four runs against the user's subscription, all with a two-line prompt
and `bypassPermissions`/`default` modes; no long tool loops, no retries
beyond the one re-run of configuration 3 to rule out a fluke.

## Decision

Task 4 implements **P2**.
