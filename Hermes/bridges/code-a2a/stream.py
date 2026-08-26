"""Reading what the code assistant emits, and deciding what to do with it.

`claude -p --output-format stream-json` writes one JSON object per line.
This turns those into two streams with very different destinations:

- **the console on the strip** gets nearly everything, as lines — it is
  there to be glanced at;
- **his voice** gets only what needs the user's judgement, which is the
  whole product decision of the design (`docs/superpowers/specs/
  2026-08-26-samantha-code-design.md`, point 3): *"quizás solo audio las
  sugerencias o preguntas del asistente de código."*

The shape below is not guessed. It was recorded from a real task on
2026-08-26 — `tests/fixtures/stream.jsonl`, 38 events of fixing a
deliberately broken test — and the tests read that file rather than a
hand-written idea of what the assistant emits.

What that recording taught, and it changed the design:

- **`permission_denied` is a real event**, and in non-interactive mode
  it is where the work STOPS. Two commands and the edit were refused,
  and the assistant ended up describing the fix it could not apply. It
  is a question in everything but name, so it goes to the voice.
- **The final `result` carries the whole answer** as text, plus
  `is_error`, `num_turns` and `total_cost_usd`. One line, spoken.
- **`assistant` messages carry `text` AND `tool_use`** in the same
  `content` array. The text is what he is thinking out loud; the tool
  uses are the machinery, and §1 says the machinery is never narrated —
  they go to the console and no further.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

# What a line is for.
CONSOLE = "console"  # show it on the strip
VOICE = "voice"  # say it out loud — it needs a decision
NOTHING = "nothing"  # neither


@dataclass(frozen=True)
class Event:
    """One line of the assistant's output, and where it goes."""

    destination: str
    text: str
    # Set on the final event of a run, so the session knows it is over.
    final: bool = False
    failed: bool = False
    # Semantic milestones and questions carry what they are, so the
    # plugin can render its own words instead of parsing ours.
    kind: str = ""
    detail: str = ""


def parse(line: str) -> dict | None:
    """One line of JSONL, or None when it is not one.

    A process writes warnings to stdout sometimes — the recording has a
    stdin warning in it — and a stream reader that raises on those is a
    stream reader that dies in the first minute.
    """
    line = line.strip()
    if not line or not line.startswith("{"):
        return None
    try:
        parsed = json.loads(line)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _tool_line(block: dict) -> str:
    """One console line for a tool call: what it is doing, briefly."""
    name = block.get("name", "?")
    args = block.get("input") or {}
    detail = ""
    if isinstance(args, dict):
        for key in ("command", "file_path", "pattern", "path", "skill", "prompt"):
            if args.get(key):
                detail = str(args[key])
                break
    return f"· {name}: {detail}"[:200] if detail else f"· {name}"


def classify(event: dict) -> list[Event]:
    """Everything this event should produce, in order."""
    kind = event.get("type")
    subtype = event.get("subtype")

    if kind == "system" and subtype == "permission_denied":
        # The work has stopped and somebody has to decide. The tool name
        # is in it, but he does not say tool names out loud (§1) — what
        # he says is that he is stuck and why.
        reason = event.get("decision_reason") or event.get("message") or ""
        return [
            Event(CONSOLE, f"! sin permiso: {reason}"[:200]),
            Event(VOICE, str(reason)[:300]),
        ]

    if kind == "result":
        text = str(event.get("result") or "").strip()
        failed = bool(event.get("is_error")) or subtype != "success"
        # The console gets a CLOSING LINE, not the text. Claude Code's
        # final `result` repeats the last thing the assistant said, so
        # writing both put the whole summary on the strip twice —
        # visible in a screenshot 2026-08-26. The words still reach the
        # voice, which is where they belong; the console only needs to
        # show that it is over.
        closing = "— terminado" if not failed else "— terminado con errores"
        return [
            Event(CONSOLE, closing),
            Event(VOICE, text or "Terminado, señor.", final=True, failed=failed),
        ]

    if kind == "assistant":
        out: list[Event] = []
        for block in event.get("message", {}).get("content", []) or []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text":
                text = str(block.get("text") or "").strip()
                if text:
                    out.append(Event(CONSOLE, text))
            elif block.get("type") == "tool_use":
                out.append(Event(CONSOLE, _tool_line(block)))
        return out

    if kind == "user":
        # Tool results coming back. The first line is enough to follow
        # what happened; the rest is a file's contents.
        for block in event.get("message", {}).get("content", []) or []:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                content = block.get("content")
                if isinstance(content, list):
                    content = " ".join(
                        str(c.get("text", "")) for c in content if isinstance(c, dict)
                    )
                first = str(content or "").strip().splitlines()
                if first:
                    return [Event(CONSOLE, f"  {first[0]}"[:200])]
        return []

    # init, thinking_tokens, rate limits, hooks: noise.
    return []
