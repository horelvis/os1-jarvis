# samantha_code v2 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The console shows milestones instead of raw stream lines, and three moments reach the user's judgement by voice — Claude Code's questions, anything irreversible, and a closing checkpoint — with the answer routed back deterministically.

**Architecture:** The bridge (`Hermes/bridges/code-a2a/`) accepts a task and returns `working` at once, runs it on a worker thread, gates dangerous tools through the SDK's `PreToolUse` hook, and broadcasts semantic events on a loopback SSE firehose (`GET /events`). The `samantha_code` plugin stops following the tee'd file and becomes the firehose's client: it renders Spanish milestone lines onto the strip's console, injects question/gate/checkpoint prompts into JARVIS (the vision-alert mechanism), and — while a question is pending — the kiosk adapter diverts the user's next input straight back to the bridge, never through the model.

**Tech Stack:** Python 3.12. Bridge: stdlib only (`http.server`, `json`, `queue`, `threading`) + `claude-agent-sdk` in its own venv. Plugin: `loguru`, `urllib` (no new deps in the gateway). Widget: GTK4/PyGObject as is.

**Spec:** `docs/superpowers/specs/2026-08-27-samantha-code-v2-design.md` (and, for what it does not repeat: `docs/superpowers/specs/2026-08-26-samantha-code-design.md`).

## Global Constraints

- Code identifiers, comments, commit messages: **English**. User-facing strings (console lines, injected prompts, spoken sentences): **Spanish** (peninsular). (CLAUDE.md §2.9)
- Never `print()` in gateway plugin code — `loguru`. The bridge is a standalone program and prints to stderr as it already does.
- The bridge's server side stays **stdlib-only** (its README's promise). The SDK is reached only from `sdk_runner.py`.
- New work goes in `widget/`, `Hermes/plugins/`, `Hermes/bridges/` — never `backend/` or `frontend/` (CLAUDE.md §3).
- Commit directly on `development` — no branches, no worktrees (user preference on record).
- Format before committing: `ruff format` + `ruff check` where the tree has ruff configured (`widget/`); elsewhere match surrounding style.
- **Test commands (verified on this box, 2026-08-27):**
  - Plugins: `cd /home/nexus/git/os1-samantha && PYTHONNOUSERSITE=1 widget/.venv/bin/python -m pytest Hermes/plugins/samantha_kiosk/tests Hermes/plugins/samantha_code/tests -q` (67 passing before this plan)
  - Bridge: `cd /home/nexus/git/os1-samantha/Hermes/bridges/code-a2a && PYTHONNOUSERSITE=1 /home/nexus/git/os1-samantha/widget/.venv/bin/python -m pytest tests -q` (44 passing before this plan; run from the bridge dir — its modules import flat)
  - Widget: `cd /home/nexus/git/os1-samantha/widget && PYTHONNOUSERSITE=1 ./.venv/bin/python -m pytest tests -q`
- The gateway's loop must never be blocked from plugin threads: strip pushes go through `asyncio.run_coroutine_threadsafe` onto `adapter.loop` (the pattern already in `samantha_code/_push`).
- Timeouts from the spec, verbatim: gate unanswered **300 s → deny**; checkpoint unanswered **600 s → close and say so**; a held question has **no timeout** but must not trip the 900 s silence watchdog.

## File Structure

```
Hermes/bridges/code-a2a/
  gates.py          NEW   what is irreversible: patterns → human description (pure)
  milestones.py     NEW   semantic milestones out of tool calls/text, deduped (pure)
  answers.py        NEW   assent("sí") — shared by gate hook and checkpoint (pure)
  worker.py         NEW   one task's background life: run → checkpoint → follow-ups
  sdk_runner.py     MOD   hooks (gate + AskUserQuestion), answer(), semantic events
  stream.py         MOD   Event gains kind/detail (defaulted — old callers unchanged)
  server.py         MOD   _send accepts-and-returns; answer routing; GET /events SSE
  tests/test_gates.py test_milestones.py test_worker.py  NEW; test_bridge_sdk.py MOD

Hermes/plugins/samantha_code/
  client.py         NEW   SSE follower + POST answer (urllib, reconnects)
  hitos.py          NEW   milestone dict → Spanish line; consecutive dedup (pure)
  voz.py            NEW   injected prompts for question/gate/checkpoint + deliver()
  pending.py        NEW   the one flag: which task waits for which kind of answer
  __init__.py       MOD   bridge mode beside the legacy follower; divert wiring
  tests/test_hitos.py test_pending.py test_client.py test_voz.py  NEW

Hermes/plugins/samantha_kiosk/
  adapter.py        MOD   divert_chat hook consulted before _handle_chat
  protocol.py       MOD   decode_client tolerates optional boolean "wake" on chat
  tests/test_adapter.py test_protocol.py  MOD

widget/samantha_widget/
  wake.py           MOD   WakeWord.named — was this utterance addressed by name?
  gateway.py        MOD   send_chat(text, wake=False) adds "wake": true
  __main__.py       MOD   spoken path passes wake.named
  tests/test_wake.py test_gateway.py  MOD
```

---

### Task 0: Commit the console-reset work already in the tree

The working tree carries a finished change from 2026-08-26 (the `reset` flag on the `console` frame, with tests). It must land before this plan's edits touch the same files.

**Files:**
- Commit as-is: `Hermes/plugins/samantha_code/__init__.py`, `Hermes/plugins/samantha_kiosk/adapter.py`, `Hermes/plugins/samantha_kiosk/protocol.py`, `Hermes/plugins/samantha_kiosk/tests/test_protocol.py`, `widget/samantha_widget/__main__.py`, `widget/samantha_widget/gateway.py`, `widget/tests/test_gateway.py`

- [ ] **Step 1: Run the two affected suites**

Run: `cd /home/nexus/git/os1-samantha && PYTHONNOUSERSITE=1 widget/.venv/bin/python -m pytest Hermes/plugins/samantha_kiosk/tests Hermes/plugins/samantha_code/tests -q && cd widget && PYTHONNOUSERSITE=1 ./.venv/bin/python -m pytest tests -q`
Expected: all PASS.

- [ ] **Step 2: Lint the widget half**

Run: `cd /home/nexus/git/os1-samantha/widget && ./.venv/bin/ruff check . && ./.venv/bin/ruff format --check .`
Expected: clean. If format differs, run `ruff format` and re-run tests.

- [ ] **Step 3: Commit**

```bash
cd /home/nexus/git/os1-samantha
git add Hermes/plugins/samantha_code/__init__.py Hermes/plugins/samantha_kiosk/adapter.py Hermes/plugins/samantha_kiosk/protocol.py Hermes/plugins/samantha_kiosk/tests/test_protocol.py widget/samantha_widget/__main__.py widget/samantha_widget/gateway.py widget/tests/test_gateway.py
git commit -m "fix(code): a new run resets the console, and the model with it"
```

---

### Task 1: Probe — how an answer gets back into a held question

The one unmeasured piece (spec, section "The three moments"). Everything in Task 4 has a seam for the outcome; this task decides what goes in the seam. **Throwaway code; the deliverable is a findings doc.**

**Files:**
- Create (throwaway, deleted at the end): `Hermes/bridges/code-a2a/probe_ask.py`
- Create: `docs/superpowers/specs/2026-08-27-askuserquestion-probe.md`

**Interfaces:**
- Produces: a written decision, one of:
  - **P1** — `AskUserQuestion` reaches `can_use_tool`, and returning `{"behavior": "allow", "updatedInput": …}` with the chosen option steers the model. (SDK docs suggest this path exists for this tool specifically.)
  - **P2** — `AskUserQuestion` reaches the `PreToolUse` hook, and a deny whose `permissionDecisionReason` carries the user's answer steers the model.
  - **P3** — neither fires in non-interactive mode: mid-run questions are impossible; case (a) collapses into the checkpoint (end-of-turn questions only), and the plan drops the AskUserQuestion half of Task 4 (the gate half stands regardless — the spike already measured `PreToolUse` seeing and denying `Bash`).

- [ ] **Step 1: Write the probe**

The bridge's venv has the SDK. A scratch repo avoids touching real projects:

```python
"""Throwaway probe: how does a question come out, and how does an answer go in?

Run:  cd Hermes/bridges/code-a2a && .venv/bin/python probe_ask.py
"""
import anyio
from claude_agent_sdk import (
    ClaudeAgentOptions, ClaudeSDKClient, AssistantMessage, ResultMessage,
    HookMatcher, TextBlock, ToolUseBlock,
)

PROMPT = (
    "Antes de hacer nada, usa la herramienta AskUserQuestion para "
    "preguntarme si prefiero la opción A (un fichero a.txt) o la B "
    "(un fichero b.txt). Después crea SOLO el fichero elegido con "
    "el texto 'elegido'."
)

async def can_use(tool_name, tool_input, context):
    print(f"[can_use_tool] {tool_name}: {tool_input}")
    if tool_name == "AskUserQuestion":
        # Try answering through updatedInput (P1).
        return {"behavior": "allow", "updatedInput": tool_input}
    return {"behavior": "allow", "updatedInput": tool_input}

async def pre_tool(input_data, tool_use_id, context):
    print(f"[PreToolUse] {input_data.get('tool_name')}: {input_data.get('tool_input')}")
    if input_data.get("tool_name") == "AskUserQuestion":
        # Try answering through a deny reason (P2).
        return {"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": "El usuario responde: la opción B. Continúa con esa respuesta.",
        }}
    return {}

async def main():
    options = ClaudeAgentOptions(
        cwd="/tmp/probe-ask-repo",
        permission_mode="bypassPermissions",
        can_use_tool=can_use,
        hooks={"PreToolUse": [HookMatcher(matcher=None, hooks=[pre_tool])]},
    )
    async with ClaudeSDKClient(options=options) as client:
        await client.query(PROMPT)
        async for msg in client.receive_response():
            if isinstance(msg, AssistantMessage):
                for b in msg.content:
                    if isinstance(b, TextBlock):
                        print(f"[text] {b.text[:120]}")
                    elif isinstance(b, ToolUseBlock):
                        print(f"[tool] {b.name} {b.input}")
            elif isinstance(msg, ResultMessage):
                print(f"[result] error={msg.is_error}")

anyio.run(main)
```

- [ ] **Step 2: Run it, three configurations**

```bash
mkdir -p /tmp/probe-ask-repo && cd /tmp/probe-ask-repo && git init -q
cd /home/nexus/git/os1-samantha/Hermes/bridges/code-a2a && .venv/bin/python probe_ask.py
```

Run once as written; once with the `can_use_tool` line for AskUserQuestion returning an answer inside `updatedInput` (shape per what configuration 1 printed); once with the hook removed entirely, to see what the assistant does with the tool unanswered. Record for each: which callback fired, what shape `tool_input` had, and **which file got created** — `b.txt` is the only proof the answer steered anything.

- [ ] **Step 3: Probe the gate the same way**

Change `PROMPT` to `"Ejecuta 'git push' en este repositorio y después dime qué pasó."` and make `pre_tool` deny any Bash whose command contains `git push` with reason `"El usuario no lo autoriza. No lo hagas y sigue sin ello."`. Expected (this half is already measured in the spike — confirming, not discovering): the hook sees it, the deny lands, the run **continues** and the result mentions the refusal.

- [ ] **Step 4: Write the findings doc and pick P1/P2/P3**

`docs/superpowers/specs/2026-08-27-askuserquestion-probe.md`, in the house style of the SDK spike: what was run, a table of which callback fired per configuration, which file appeared, and the decision line — "Task 4 implements P_." Include the exact `tool_input` shape of `AskUserQuestion` (Task 4 needs it to extract the question text and options).

- [ ] **Step 5: Delete the probe, clean the scratch repo, commit the doc**

```bash
rm /home/nexus/git/os1-samantha/Hermes/bridges/code-a2a/probe_ask.py
rm -rf /tmp/probe-ask-repo
cd /home/nexus/git/os1-samantha
git add docs/superpowers/specs/2026-08-27-askuserquestion-probe.md
git commit -m "docs: probe — returning an answer into a held AskUserQuestion"
```

---

### Task 2: `gates.py` — what is irreversible

**Files:**
- Create: `Hermes/bridges/code-a2a/gates.py`
- Test: `Hermes/bridges/code-a2a/tests/test_gates.py`

**Interfaces:**
- Produces: `DEFAULT_PATTERNS: tuple[str, ...]`; `load_patterns(value: str | None) -> tuple[str, ...]`; `dangerous(tool: str, args: dict, patterns: tuple[str, ...] = DEFAULT_PATTERNS) -> str | None` — returns a short human description of the action (the command itself, trimmed) or None when it may run unasked.
- Consumed by: Task 4 (`sdk_runner._pre_tool`), Task 10 (the systemd unit documents `SAMANTHA_CODE_GATES`).

- [ ] **Step 1: Write the failing tests**

```python
"""The gate policy is a list of substrings over Bash commands, and only that.

Only Bash is gated: an Edit inside the project is one `git checkout` from
undone, while a push or an rm is not. The spec's list, verbatim: git push,
recursive deletes, sudo — `git commit` only if the user adds it.
"""
import gates


def test_push_is_dangerous_and_pytest_is_not():
    assert gates.dangerous("Bash", {"command": "git push origin main"})
    assert gates.dangerous("Bash", {"command": "cd x && git push"})
    assert gates.dangerous("Bash", {"command": "pytest -q"}) is None


def test_deletes_and_sudo_are_dangerous():
    assert gates.dangerous("Bash", {"command": "rm -rf build/"})
    assert gates.dangerous("Bash", {"command": "rm -r old"})
    assert gates.dangerous("Bash", {"command": "sudo systemctl restart nginx"})


def test_only_bash_is_gated():
    assert gates.dangerous("Edit", {"file_path": "a.py"}) is None
    assert gates.dangerous("Write", {"command": "git push"}) is None


def test_the_description_is_the_command_trimmed():
    long = "git push " + "x" * 400
    desc = gates.dangerous("Bash", {"command": long})
    assert desc is not None and len(desc) <= 160 and desc.startswith("git push")


def test_env_replaces_the_defaults_when_set():
    """Set, the variable IS the policy — so `git commit` can be added and
    a default can be removed without editing code."""
    assert gates.load_patterns(None) == gates.DEFAULT_PATTERNS
    assert gates.load_patterns("") == gates.DEFAULT_PATTERNS
    assert gates.load_patterns("git commit, git push") == ("git commit", "git push")


def test_matching_folds_case():
    assert gates.dangerous("Bash", {"command": "Git PUSH origin"})
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd /home/nexus/git/os1-samantha/Hermes/bridges/code-a2a && PYTHONNOUSERSITE=1 /home/nexus/git/os1-samantha/widget/.venv/bin/python -m pytest tests/test_gates.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'gates'`.

- [ ] **Step 3: Implement**

```python
"""What the assistant may not do without asking.

The spec's policy, and only it: `git push`, recursive deletes, `sudo`.
The user chose full scope on 2026-08-26 and narrowed it on 2026-08-27
(the design doc has both decisions); the narrowing is this list.

Only Bash is gated. An Edit inside the project root is one
`git checkout` from undone; a push or an rm is not. The match is a
folded substring over the command — a policy anybody can read in the
systemd unit, not a parser.
"""

from __future__ import annotations

DEFAULT_PATTERNS: tuple[str, ...] = ("git push", "rm -r", "rm -f", "sudo")

# What the description may carry back to the strip and the voice.
MAX_CHARS = 160


def load_patterns(value: str | None) -> tuple[str, ...]:
    """The policy from `SAMANTHA_CODE_GATES`, or the default.

    Set, the variable IS the policy (comma-separated), so an entry can
    be removed as well as added without touching code.
    """
    if not value or not value.strip():
        return DEFAULT_PATTERNS
    return tuple(p.strip().casefold() for p in value.split(",") if p.strip())


def dangerous(
    tool: str, args: dict, patterns: tuple[str, ...] = DEFAULT_PATTERNS
) -> str | None:
    """A short description of the action when it needs permission, else None."""
    if tool != "Bash" or not isinstance(args, dict):
        return None
    command = str(args.get("command") or "")
    folded = command.casefold()
    for pattern in patterns:
        if pattern in folded:
            return command.strip()[:MAX_CHARS]
    return None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: same command as Step 2. Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
cd /home/nexus/git/os1-samantha
git add Hermes/bridges/code-a2a/gates.py Hermes/bridges/code-a2a/tests/test_gates.py
git commit -m "feat(bridge): the gate policy — what may not run unasked"
```

---

### Task 3: `milestones.py` — the work as milestones, deduped

**Files:**
- Create: `Hermes/bridges/code-a2a/milestones.py`
- Test: `Hermes/bridges/code-a2a/tests/test_milestones.py`

**Interfaces:**
- Produces:
  - `Milestone` — frozen dataclass, `kind: str`, `detail: str = ""`. Kinds emitted: `"read"`, `"edit"`, `"tests"`, `"tests_out"`, `"run"`, `"note"`.
  - `plain(m: Milestone) -> str` — a plain-text form for the tee'd file and the task artifact (Spanish, same wording the plugin will use — one source of copy would couple the two processes, so the wording is written twice on purpose, as `summarise()` and the bridge's classifier already are).
  - `class Milestones` with `feed(tool: str, args: dict) -> Milestone | None`, `note(text: str) -> Milestone | None`, `result(text: str) -> Milestone | None`.
- Consumed by: Task 4 (`sdk_runner`).

- [ ] **Step 1: Write the failing tests**

```python
"""Milestones, not commands — the spec's table, as executable rules.

The dedup rules are the product decision: one "read" per reading phase,
one "edit" per file, never the same milestone twice in a row.
"""
import json
from pathlib import Path

from milestones import Milestone, Milestones, plain

FIXTURE = Path(__file__).parent / "fixtures" / "stream.jsonl"


def test_reading_is_one_milestone_per_phase_not_per_file():
    m = Milestones()
    assert m.feed("Read", {"file_path": "/x/a.py"}) == Milestone("read")
    assert m.feed("Grep", {"pattern": "foo"}) is None
    assert m.feed("Read", {"file_path": "/x/b.py"}) is None
    # A non-read tool ends the phase; the next read starts a new one.
    assert m.feed("Bash", {"command": "ls"}) == Milestone("run", "ls")
    assert m.feed("Read", {"file_path": "/x/c.py"}) == Milestone("read")


def test_editing_is_one_milestone_per_file():
    m = Milestones()
    assert m.feed("Edit", {"file_path": "/x/vad.py"}) == Milestone("edit", "vad.py")
    assert m.feed("Edit", {"file_path": "/x/vad.py"}) is None
    assert m.feed("Write", {"file_path": "/x/stt.py"}) == Milestone("edit", "stt.py")


def test_tests_are_recognised_and_their_outcome_follows():
    m = Milestones()
    assert m.feed("Bash", {"command": "pytest tests -q"}) == Milestone("tests")
    out = m.result("12 passed in 0.5s")
    assert out == Milestone("tests_out", "12 passed")


def test_a_result_with_no_tests_before_it_is_nothing():
    m = Milestones()
    m.feed("Bash", {"command": "ls"})
    assert m.result("12 passed in 0.5s") is None


def test_other_bash_shows_the_first_word_only():
    m = Milestones()
    assert m.feed("Bash", {"command": "ruff check . && ls"}) == Milestone("run", "ruff")


def test_notes_take_the_first_sentence_and_never_repeat():
    m = Milestones()
    assert m.note("Voy a mirar el VAD. Luego los tests.") == Milestone(
        "note", "Voy a mirar el VAD."
    )
    assert m.note("Voy a mirar el VAD. Otra vez.") is None  # same first sentence


def test_never_the_same_milestone_twice_in_a_row():
    m = Milestones()
    assert m.feed("Bash", {"command": "git diff"}) == Milestone("run", "git")
    assert m.feed("Bash", {"command": "git status"}) is None
    assert m.feed("Bash", {"command": "pytest -q"}) == Milestone("tests")


def test_plain_renders_every_kind():
    assert plain(Milestone("read")) == "Leyendo el proyecto…"
    assert plain(Milestone("edit", "vad.py")) == "Editando vad.py"
    assert plain(Milestone("tests")) == "Pasando los tests…"
    assert plain(Milestone("tests_out", "12 passed")) == "Tests: 12 passed"
    assert plain(Milestone("run", "git")) == "Ejecutando: git"
    assert plain(Milestone("note", "Hola.")) == "Hola."


def test_the_recorded_run_produces_no_consecutive_duplicates():
    """The real recording of 2026-08-26, through the real rules."""
    m = Milestones()
    lines: list[Milestone] = []
    for raw in FIXTURE.read_text().splitlines():
        try:
            event = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(event, dict) or event.get("type") != "assistant":
            continue
        for block in event.get("message", {}).get("content", []) or []:
            if not isinstance(block, dict):
                continue
            out = None
            if block.get("type") == "tool_use":
                out = m.feed(block.get("name", "?"), block.get("input") or {})
            elif block.get("type") == "text" and str(block.get("text", "")).strip():
                out = m.note(str(block["text"]))
            if out:
                lines.append(out)
    assert lines, "the fixture should produce something"
    assert all(a != b for a, b in zip(lines, lines[1:]))
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd /home/nexus/git/os1-samantha/Hermes/bridges/code-a2a && PYTHONNOUSERSITE=1 /home/nexus/git/os1-samantha/widget/.venv/bin/python -m pytest tests/test_milestones.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'milestones'`.

- [ ] **Step 3: Implement**

```python
"""The assistant's stream as milestones — what a glance is worth.

The spec's table made executable. One "read" per reading phase, one
"edit" per file, tests recognised and their outcome reported, everything
else a short verb — and never the same milestone twice in a row. This is
mechanical on purpose: an LLM call per event would cost VRAM and
latency, and the voice is reserved for judgement (spec, 2026-08-27).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath

READ_TOOLS = frozenset({"Read", "Grep", "Glob"})
EDIT_TOOLS = frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit"})

# "12 passed", "2 failed" — pytest's summary vocabulary, first hit wins.
_OUTCOME = re.compile(r"\d+\s+(?:passed|failed|errors?)")

MAX_NOTE = 160


@dataclass(frozen=True)
class Milestone:
    kind: str
    detail: str = ""


def plain(m: Milestone) -> str:
    """The milestone as one Spanish line, for the tee'd file and the
    artifact. The plugin renders its own copy of this wording — the two
    processes are deliberately not coupled, the same way `summarise()`
    and the bridge's classifier are written twice (live.py has the note).
    """
    if m.kind == "read":
        return "Leyendo el proyecto…"
    if m.kind == "edit":
        return f"Editando {m.detail}"
    if m.kind == "tests":
        return "Pasando los tests…"
    if m.kind == "tests_out":
        return f"Tests: {m.detail}"
    if m.kind == "run":
        return f"Ejecutando: {m.detail}"
    return m.detail


class Milestones:
    """Stateful: the dedup rules ARE the product decision."""

    def __init__(self) -> None:
        self._reading = False
        self._edited: set[str] = set()
        self._last: Milestone | None = None
        self._awaiting_tests = False

    def _emit(self, m: Milestone) -> Milestone | None:
        if m == self._last:
            return None
        self._last = m
        return m

    def feed(self, tool: str, args: dict) -> Milestone | None:
        """One tool call in; at most one milestone out."""
        args = args if isinstance(args, dict) else {}
        if tool in READ_TOOLS:
            if self._reading:
                return None
            self._reading = True
            return self._emit(Milestone("read"))
        self._reading = False

        if tool in EDIT_TOOLS:
            self._awaiting_tests = False
            name = PurePosixPath(str(args.get("file_path") or "?")).name
            if name in self._edited:
                return None
            self._edited.add(name)
            return self._emit(Milestone("edit", name))

        if tool == "Bash":
            command = str(args.get("command") or "")
            if "pytest" in command or "test" in command.split():
                self._awaiting_tests = True
                return self._emit(Milestone("tests"))
            self._awaiting_tests = False
            first = command.strip().split()
            return self._emit(Milestone("run", first[0] if first else "?"))

        return None

    def note(self, text: str) -> Milestone | None:
        """The assistant thinking out loud: its first sentence, once."""
        first = text.strip().splitlines()[0] if text.strip() else ""
        sentence = first.split(". ")[0].strip()
        if sentence and not sentence.endswith((".", "…", "?", "!")):
            sentence += "."
        if not sentence:
            return None
        return self._emit(Milestone("note", sentence[:MAX_NOTE]))

    def result(self, text: str) -> Milestone | None:
        """A tool result: only a test run's outcome is worth a line."""
        if not self._awaiting_tests:
            return None
        self._awaiting_tests = False
        found = _OUTCOME.findall(str(text or ""))
        if not found:
            return None
        return self._emit(Milestone("tests_out", ", ".join(found[:2])))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: same command as Step 2. Expected: PASS (10 tests). If the fixture test finds a rule violated by real data, fix the rule, not the test.

- [ ] **Step 5: Commit**

```bash
cd /home/nexus/git/os1-samantha
git add Hermes/bridges/code-a2a/milestones.py Hermes/bridges/code-a2a/tests/test_milestones.py
git commit -m "feat(bridge): milestones, not commands — the stream deduped"
```

---

### Task 4: `sdk_runner` — semantic events, the gate, the held question

**Files:**
- Create: `Hermes/bridges/code-a2a/answers.py`
- Modify: `Hermes/bridges/code-a2a/stream.py` (the `Event` dataclass only)
- Modify: `Hermes/bridges/code-a2a/sdk_runner.py`
- Test: `Hermes/bridges/code-a2a/tests/test_sdk_answers.py` (new), `tests/test_bridge_sdk.py` (existing suite must stay green)

**Interfaces:**
- Consumes: `gates.dangerous`, `gates.load_patterns` (Task 2); `milestones.Milestones`, `plain` (Task 3); the probe's decision P1/P2/P3 (Task 1).
- Produces:
  - `stream.Event` gains `kind: str = ""` and `detail: str = ""` (defaulted; every existing constructor call stays valid).
  - `answers.assent(text: str) -> bool` — is this Spanish "yes"?
  - `SdkRun.pending: str | None` (`"question"` / `"gate"` / `None`), `SdkRun.pending_text: str`, `SdkRun.answer(text: str) -> bool` (thread-safe, False when nothing waits), `SdkRun.gate_timeout: float` (default `GATE_TIMEOUT = 300.0`, settable in tests).
  - Events with `kind` in `{"question", "gate", "resolved"}` on the run's queue, besides the milestone kinds.

- [ ] **Step 1: Write `answers.py` and its tests first (it is three lines and two callers)**

Test, appended at the top of `tests/test_sdk_answers.py`:

```python
"""The answer plumbing of a run, tested without the SDK in the room.

`_pre_tool` is a coroutine over plain state (gates + queues), so it runs
under asyncio.run with no client. The SDK-driven paths stay covered by
test_bridge_sdk.py and by the human validation task.
"""
import asyncio
import queue

import answers


def test_assent_recognises_yes_and_only_yes():
    for yes in ("sí", "Si", "vale", "ok", "dale", "de acuerdo", "sí, hazlo"):
        assert answers.assent(yes)
    for no in ("no", "espera", "mejor no", "cámbialo a B", ""):
        assert not answers.assent(no)
```

Implementation, `answers.py`:

```python
"""Is that Spanish a yes? Shared by the gate hook and the checkpoint."""

from __future__ import annotations

import unicodedata

_YES = frozenset(
    {"sí", "si", "vale", "ok", "okay", "dale", "adelante", "hazlo", "claro", "perfecto"}
)
_YES_PHRASES = ("de acuerdo", "por supuesto", "que sí")


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.casefold().strip())
    return "".join(c for c in text if not unicodedata.combining(c))


def assent(text: str) -> bool:
    folded = _fold(text)
    if not folded:
        return False
    first = folded.split(",")[0].split(".")[0].strip()
    return first in {_fold(w) for w in _YES} or any(
        folded.startswith(_fold(p)) for p in _YES_PHRASES
    )
```

(Note: fold both sides — "sí" carries an accent in `_YES` and the input may or may not.)

- [ ] **Step 2: Extend `stream.Event`**

In `stream.py`, the dataclass gains two defaulted fields:

```python
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
```

Run the full bridge suite: `PYTHONNOUSERSITE=1 /home/nexus/git/os1-samantha/widget/.venv/bin/python -m pytest tests -q` (from the bridge dir). Expected: the pre-existing 44 still PASS.

- [ ] **Step 3: Write the failing tests for the run's answer plumbing**

Append to `tests/test_sdk_answers.py`:

```python
import sdk_runner
from stream import CONSOLE, Event


def _run() -> sdk_runner.SdkRun:
    return sdk_runner.SdkRun("da igual", cwd=".")


def test_answer_with_nothing_pending_is_false():
    assert _run().answer("sí") is False


def test_a_gate_denied_by_timeout_says_the_user_was_away():
    run = _run()
    run.gate_timeout = 0.05
    out = asyncio.run(
        run._pre_tool({"tool_name": "Bash", "tool_input": {"command": "git push"}}, "t1", None)
    )
    decision = out["hookSpecificOutput"]
    assert decision["permissionDecision"] == "deny"
    assert "no está" in decision["permissionDecisionReason"]
    assert run.pending is None
    kinds = _drain_kinds(run)
    assert "gate" in kinds and "resolved" in kinds


def test_a_gate_answered_yes_is_allowed():
    run = _run()

    async def scenario():
        task = asyncio.ensure_future(
            run._pre_tool(
                {"tool_name": "Bash", "tool_input": {"command": "git push"}}, "t1", None
            )
        )
        await asyncio.sleep(0.01)
        assert run.pending == "gate"
        assert run.answer("sí") is True
        return await task

    out = asyncio.run(scenario())
    assert out == {}  # allowed: the hook stays silent
    assert run.pending is None


def test_a_gate_answered_no_carries_the_users_words():
    run = _run()

    async def scenario():
        task = asyncio.ensure_future(
            run._pre_tool(
                {"tool_name": "Bash", "tool_input": {"command": "git push"}}, "t1", None
            )
        )
        await asyncio.sleep(0.01)
        run.answer("no, todavía no")
        return await task

    out = asyncio.run(scenario())
    decision = out["hookSpecificOutput"]
    assert decision["permissionDecision"] == "deny"
    assert "no, todavía no" in decision["permissionDecisionReason"]


def test_an_ordinary_tool_passes_without_a_word():
    run = _run()
    out = asyncio.run(
        run._pre_tool({"tool_name": "Bash", "tool_input": {"command": "pytest -q"}}, "t1", None)
    )
    assert out == {}
    assert _drain_kinds(run) == []


def test_silence_while_pending_does_not_kill_the_run():
    """The 900 s watchdog must not count a held question as a hang."""
    run = _run()
    run.pending = "question"
    sdk_runner_timeout = 0.05
    events = run.events_once(timeout=sdk_runner_timeout)  # see note below
    assert events == []


def _drain_kinds(run) -> list[str]:
    kinds = []
    while True:
        try:
            item = run._queue.get_nowait()
        except queue.Empty:
            return kinds
        if isinstance(item, Event):
            kinds.append(item.kind)
```

Note on `test_silence_while_pending_does_not_kill_the_run`: rather than invent `events_once`, implement the check inside `events()` and test it by starting `events()` in a thread with a tiny `SILENCE_TIMEOUT` monkeypatched (`monkeypatch.setattr(sdk_runner, "SILENCE_TIMEOUT", 0.05)`), asserting the generator is still alive (thread alive, `run.failed is False`) after 3× the timeout while `pending` is set, then unset `pending`, put `_DONE`, and join. Write it that way; the sketch above only marks the requirement.

- [ ] **Step 4: Run them to verify they fail**

Run: `cd /home/nexus/git/os1-samantha/Hermes/bridges/code-a2a && PYTHONNOUSERSITE=1 /home/nexus/git/os1-samantha/widget/.venv/bin/python -m pytest tests/test_sdk_answers.py -q`
Expected: FAIL — `AttributeError: 'SdkRun' object has no attribute 'answer'` (and friends).

- [ ] **Step 5: Implement in `sdk_runner.py`**

The changes, in order through the file:

```python
import gates
from answers import assent
from milestones import Milestones, plain

# A gate nobody answers is denied. The checkpoint's cousin lives in
# worker.py; this one is here because the hook is.
GATE_TIMEOUT = 300.0
```

In `SdkRun.__init__`:

```python
        self.patterns = gates.load_patterns(os.environ.get("SAMANTHA_CODE_GATES"))
        self.gate_timeout = GATE_TIMEOUT
        self.pending: str | None = None
        self.pending_text: str = ""
        self._answers: queue.Queue[str] = queue.Queue()
        self._milestones = Milestones()
```

New methods:

```python
    def answer(self, text: str) -> bool:
        """Resolve the held question or gate. Thread-safe; False when
        nothing waits — the caller then knows the moment has passed."""
        if self.pending is None:
            return False
        self._answers.put(text)
        return True

    async def _await_answer(self, timeout: float | None) -> str | None:
        """Block the hook (never the loop) until the user answers."""
        loop = asyncio.get_running_loop()

        def take() -> str | None:
            try:
                return self._answers.get(timeout=timeout)
            except queue.Empty:
                return None

        return await loop.run_in_executor(None, take)

    def _ask(self, qkind: str, text: str) -> None:
        self.pending, self.pending_text = qkind, text
        self._queue.put(Event(CONSOLE, f"? {text}", kind=qkind, detail=text))

    def _resolve(self) -> None:
        self.pending, self.pending_text = None, ""
        self._queue.put(Event(CONSOLE, "", kind="resolved"))

    @staticmethod
    def _deny(reason: str) -> dict:
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }

    async def _pre_tool(self, input_data, tool_use_id, context) -> dict:
        """The customs post. Sees every tool; holds two kinds of them."""
        name = str(input_data.get("tool_name") or "")
        args = input_data.get("tool_input") or {}

        if name == "AskUserQuestion":
            question = _question_text(args)
            self._ask("question", question)
            reply = await self._await_answer(None)
            self._resolve()
            # P2 per the probe of 2026-08-27 — adjust here if it chose P1/P3.
            return self._deny(
                f"El usuario responde: {reply}. Continúa con esa respuesta."
            )

        risky = gates.dangerous(name, args, self.patterns)
        if risky:
            self._ask("gate", risky)
            reply = await self._await_answer(self.gate_timeout)
            self._resolve()
            if reply is None:
                return self._deny(
                    "El usuario no está. No lo hagas; sigue sin ello y dilo al final."
                )
            if assent(reply):
                return {}
            return self._deny(f"El usuario no lo autoriza: {reply}. Sigue sin ello.")

        return {}


def _question_text(args: dict) -> str:
    """The question out of AskUserQuestion's input — shape per the probe."""
    questions = args.get("questions") if isinstance(args, dict) else None
    if isinstance(questions, list) and questions and isinstance(questions[0], dict):
        q = str(questions[0].get("question") or "")
        options = questions[0].get("options")
        if isinstance(options, list):
            labels = [str(o.get("label", "")) for o in options if isinstance(o, dict)]
            if any(labels):
                return f"{q} ({' / '.join(l for l in labels if l)})"
        if q:
            return q
    return str(args)[:200]
```

In `_drive()`: register the hook and swap the mechanical lines for milestones —

```python
        from claude_agent_sdk import HookMatcher  # with the other imports

        options = ClaudeAgentOptions(
            cwd=str(self.cwd),
            permission_mode=PERMISSION_MODE,
            resume=self.resume,
            hooks={"PreToolUse": [HookMatcher(matcher=None, hooks=[self._pre_tool])]},
        )
```

and in the message loop: `TextBlock` → `m = self._milestones.note(block.text)`; `ToolUseBlock` → `m = self._milestones.feed(block.name, block.input or {})`; if the SDK yields `UserMessage` tool results, feed their text to `self._milestones.result(...)` (guard the import: `try: from claude_agent_sdk import UserMessage except ImportError: UserMessage = ()`). Each non-None milestone goes out as `Event(CONSOLE, plain(m), kind=m.kind, detail=m.detail)`. The old `_tool_line` becomes unused — delete it.

In `events()`: the silence guard learns about pending —

```python
                try:
                    item = self._queue.get(timeout=SILENCE_TIMEOUT)
                except queue.Empty:
                    if self.pending is not None:
                        # A held question is not a hang: the user is
                        # being asked, and nobody types under a timer.
                        continue
                    self.failed = True
                    ...
```

- [ ] **Step 6: Run the new tests and the whole bridge suite**

Run: `cd /home/nexus/git/os1-samantha/Hermes/bridges/code-a2a && PYTHONNOUSERSITE=1 /home/nexus/git/os1-samantha/widget/.venv/bin/python -m pytest tests -q`
Expected: PASS, old and new. `test_bridge_sdk.py` may need its fake messages extended if it constructs `Event` positionally past the fourth field — it should not; fix the test only if it asserted on `_tool_line` output, replacing the expectation with the milestone wording.

- [ ] **Step 7: Commit**

```bash
cd /home/nexus/git/os1-samantha
git add Hermes/bridges/code-a2a/answers.py Hermes/bridges/code-a2a/stream.py Hermes/bridges/code-a2a/sdk_runner.py Hermes/bridges/code-a2a/tests/test_sdk_answers.py Hermes/bridges/code-a2a/tests/test_bridge_sdk.py
git commit -m "feat(bridge): the run can be asked — gate, held question, milestones"
```

---

### Task 5: `worker.py` + `server.py` — accept at once, checkpoint, firehose

**Files:**
- Create: `Hermes/bridges/code-a2a/worker.py`
- Modify: `Hermes/bridges/code-a2a/server.py`
- Test: `Hermes/bridges/code-a2a/tests/test_worker.py`

**Interfaces:**
- Consumes: `answers.assent`; `SdkRun.answer`/`pending` (Task 4); `tasks.Task`, `tasks.INPUT_REQUIRED` etc.
- Produces:
  - `worker.CHECKPOINT_TIMEOUT = 600.0`
  - `worker.Job(bridge, task, prompt, project, fresh=False)` with `.start() -> None` (daemon thread) and `.answer(text: str) -> bool` (routes to the run's held question OR the checkpoint; False when neither waits).
  - `Bridge.jobs: dict[str, Job]`, `Bridge.emit(payload: dict) -> None`, `Bridge.subscribe() -> queue.Queue`, `Bridge.unsubscribe(q) -> None`, `Bridge.active() -> tasks.Task | None`.
  - Firehose payload shapes (each one JSON object per SSE `data:` line):
    `{"event": "task", "taskId": …, "project": …}` ·
    `{"event": "milestone", "taskId": …, "kind": …, "detail": …, "text": …}` ·
    `{"event": "ask", "taskId": …, "qkind": "question"|"gate"|"checkpoint", "text": …}` ·
    `{"event": "resolved", "taskId": …}` ·
    `{"event": "end", "taskId": …, "failed": bool, "summary": …}`
  - HTTP: `GET /events` — SSE, `: keepalive` comment every 15 s of quiet; `message/send` returns immediately (SDK path) with the task in `WORKING`, routes to `Job.answer` when the message carries `taskId` of a live job or the `contextId` of the task waiting in `INPUT_REQUIRED`, and refuses a second concurrent task with `«Ya hay una tarea en marcha. Dígame si es una respuesta o si la dejo.»`.

**Scope note, explicit:** the async accept applies to the **SDK path only** (`bridge.stoppable`). The CLI engine (OpenCode fallback) keeps v1's blocking `message/send` untouched — it cannot answer questions anyway, and changing both engines doubles this task for a path nothing on this box uses. `message/stream` also stays as v1 (an external A2A client's affair, not the strip's).

- [ ] **Step 1: Write the failing tests**

```python
"""The task's life off the request thread, against a fake run.

Everything here drives Job/Bridge with a stubbed `events_for`, so no SDK,
no subprocess, no HTTP — the same split test_bridge_sdk.py uses.
"""
import queue
import threading
import time
from pathlib import Path

import server
import tasks
import worker
from stream import CONSOLE, VOICE, Event


class FakeProject:
    name = "demo"
    path = Path("/tmp/demo")


def _bridge(events):
    b = server.Bridge(Path("/tmp"), "claude", "http://t")
    b.events_for = lambda task, prompt, project, fresh=False: iter(events)  # type: ignore
    return b


def test_a_job_emits_milestones_and_parks_at_the_checkpoint():
    b = _bridge([
        Event(CONSOLE, "Editando a.py", kind="edit", detail="a.py"),
        Event(VOICE, "He arreglado a.py.", final=True),
    ])
    listener = b.subscribe()
    task = tasks.Task()
    job = worker.Job(b, task, "arregla a", FakeProject())
    job.start()
    seen = _drain_until(listener, "ask")
    assert {"event": "task", **_strip(seen[0])} == seen[0]
    assert any(p["event"] == "milestone" and p["kind"] == "edit" for p in seen)
    ask = seen[-1]
    assert ask["qkind"] == "checkpoint" and "He arreglado" in ask["text"]
    assert task.state == tasks.INPUT_REQUIRED


def test_yes_closes_the_checkpoint():
    b = _bridge([Event(VOICE, "Hecho.", final=True)])
    listener = b.subscribe()
    task = tasks.Task()
    job = worker.Job(b, task, "haz", FakeProject())
    job.start()
    _drain_until(listener, "ask")
    assert job.answer("vale") is True
    end = _drain_until(listener, "end")[-1]
    assert end["failed"] is False
    _wait(lambda: task.state == tasks.COMPLETED)


def test_checkpoint_times_out_and_says_so():
    b = _bridge([Event(VOICE, "Hecho.", final=True)])
    listener = b.subscribe()
    task = tasks.Task()
    job = worker.Job(b, task, "haz", FakeProject())
    job.checkpoint_timeout = 0.05
    job.start()
    _drain_until(listener, "ask")
    end = _drain_until(listener, "end")[-1]
    assert "solo" in end["summary"]  # «cerrado solo» — nobody answered
    _wait(lambda: task.state == tasks.COMPLETED)


def test_anything_but_yes_becomes_the_next_run():
    calls = []

    def fake_events(task, prompt, project, fresh=False):
        calls.append(prompt)
        yield Event(VOICE, f"Hecho: {prompt}.", final=True)

    b = server.Bridge(Path("/tmp"), "claude", "http://t")
    b.events_for = fake_events  # type: ignore
    listener = b.subscribe()
    task = tasks.Task()
    job = worker.Job(b, task, "haz A", FakeProject())
    job.start()
    _drain_until(listener, "ask")
    job.answer("ahora quita los prints")
    _drain_until(listener, "ask")  # the follow-up parks at its own checkpoint
    assert calls == ["haz A", "ahora quita los prints"]
    job.answer("sí")
    _drain_until(listener, "end")


def test_only_one_task_at_a_time():
    b = _bridge([Event(VOICE, "Hecho.", final=True)])
    t1 = tasks.Task(); b.tasks[t1.id] = t1
    t1.advance(tasks.WORKING)
    assert b.active() is t1
    t1.advance(tasks.COMPLETED)
    assert b.active() is None


def _drain_until(listener, event, timeout=2.0):
    seen, deadline = [], time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            payload = listener.get(timeout=0.1)
        except queue.Empty:
            continue
        seen.append(payload)
        if payload.get("event") == event:
            return seen
    raise AssertionError(f"never saw {event!r}; saw {seen}")


def _strip(p):
    return {k: v for k, v in p.items() if k in ("event", "taskId", "project")}


def _wait(cond, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return
        time.sleep(0.02)
    raise AssertionError("condition never held")
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd /home/nexus/git/os1-samantha/Hermes/bridges/code-a2a && PYTHONNOUSERSITE=1 /home/nexus/git/os1-samantha/widget/.venv/bin/python -m pytest tests/test_worker.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'worker'`.

- [ ] **Step 3: Implement `worker.py`**

```python
"""One task's life, off the request thread.

`message/send` used to do the work inside the HTTP request; now it
accepts and returns, and this runs the task: milestones out on the
firehose, the run's questions surfaced, and — the spec's third moment —
an ending that parks in INPUT_REQUIRED as a checkpoint instead of
closing, so «¿lo doy por bueno?» is a real question with a real answer.
"""

from __future__ import annotations

import queue
import threading

import tasks
from answers import assent
from stream import VOICE

# An unanswered checkpoint closes itself — the work is done either way,
# and a task that waits forever pins the single-task slot (spec: 600 s).
CHECKPOINT_TIMEOUT = 600.0

# What qualifies as "the user said yes, close it".
_CLOSED_ALONE = "He cerrado la tarea yo solo; nadie contestó."


class Job:
    """The background execution and conversation loop of one task."""

    def __init__(self, bridge, task, prompt: str, project, *, fresh: bool = False):
        self.bridge = bridge
        self.task = task
        self.prompt = prompt
        self.project = project
        self.fresh = fresh
        self.checkpoint_timeout = CHECKPOINT_TIMEOUT
        self._checkpoint: queue.Queue[str] = queue.Queue()
        self._at_checkpoint = False

    # ── the two things the outside does to it ─────────────────────────

    def start(self) -> None:
        threading.Thread(target=self._run, name="code-job", daemon=True).start()

    def answer(self, text: str) -> bool:
        """Route an answer to whoever waits: the run's held question or
        the checkpoint. False when nobody does."""
        run = self.bridge.runs.get(self.task.id)
        if run is not None and run.pending is not None:
            return run.answer(text)
        if self._at_checkpoint:
            self._checkpoint.put(text)
            return True
        return False

    # ── the life ──────────────────────────────────────────────────────

    def _emit(self, payload: dict) -> None:
        self.bridge.emit({"taskId": self.task.id, **payload})

    def _run(self) -> None:
        self._emit({"event": "task", "project": self.project.name})
        prompt, fresh = self.prompt, self.fresh
        try:
            while True:
                summary, failed = self._one_run(prompt, fresh)
                if self.task.state == tasks.CANCELED:
                    self._emit({"event": "end", "failed": False, "summary": summary})
                    return
                self.task.advance(tasks.INPUT_REQUIRED, summary)
                self._emit({"event": "ask", "qkind": "checkpoint", "text": summary})
                self._at_checkpoint = True
                try:
                    reply = self._checkpoint.get(timeout=self.checkpoint_timeout)
                except queue.Empty:
                    reply = None
                finally:
                    self._at_checkpoint = False
                self._emit({"event": "resolved"})
                if reply is None:
                    self.task.advance(tasks.COMPLETED, summary)
                    self._emit(
                        {"event": "end", "failed": failed, "summary": _CLOSED_ALONE}
                    )
                    return
                if assent(reply):
                    self.task.advance(tasks.COMPLETED, summary)
                    self._emit({"event": "end", "failed": failed, "summary": summary})
                    return
                # Anything else is the next instruction of the same
                # session — the SDK resumes it via sessions.py.
                prompt, fresh = reply, False
                self.task.advance(tasks.WORKING, "Sigo con ello.")
        except Exception as exc:  # noqa: BLE001 — a job must not die silent
            self.task.advance(tasks.FAILED, "No he podido con ello.")
            self._emit({"event": "end", "failed": True, "summary": f"falló: {exc}"})
        finally:
            self.bridge.jobs.pop(self.task.id, None)

    def _one_run(self, prompt: str, fresh: bool) -> tuple[str, bool]:
        summary, failed = "", False
        for event in self.bridge.events_for(
            self.task, prompt, self.project, fresh=fresh
        ):
            if event.kind in ("question", "gate"):
                self._emit({"event": "ask", "qkind": event.kind, "text": event.detail})
            elif event.kind == "resolved":
                self._emit({"event": "resolved"})
            elif event.destination == VOICE and event.final:
                summary, failed = event.text, event.failed
            elif event.text:
                self._emit(
                    {
                        "event": "milestone",
                        "kind": event.kind,
                        "detail": event.detail,
                        "text": event.text,
                    }
                )
        return summary or "Terminado.", failed
```

- [ ] **Step 4: Implement the `server.py` side**

`Bridge` gains, in `__init__`: `self.jobs: dict[str, Job] = {}` and `self.listeners: list[queue.Queue] = []`; and three methods:

```python
    def emit(self, payload: dict) -> None:
        with self.lock:
            listeners = list(self.listeners)
        for q in listeners:
            q.put(payload)

    def subscribe(self) -> "queue.Queue[dict]":
        q: queue.Queue = queue.Queue()
        with self.lock:
            self.listeners.append(q)
        return q

    def unsubscribe(self, q) -> None:
        with self.lock:
            if q in self.listeners:
                self.listeners.remove(q)

    def active(self) -> "tasks.Task | None":
        with self.lock:
            for task in self.tasks.values():
                if not task.terminal:
                    return task
        return None
```

`_send` becomes (the SDK path; the CLI path keeps the old synchronous body — factor the old body into `_send_blocking` and call it when `not self.bridge.stoppable`):

```python
    def _send(self, request_id, params: dict) -> None:
        message = params.get("message") or {}
        text = tasks.text_of(message)
        # ── an answer to something that waits ─────────────────────────
        ref = str(message.get("taskId") or "")
        job = self.bridge.jobs.get(ref)
        if job is None:
            active = self.bridge.active()
            if (
                active is not None
                and active.state == tasks.INPUT_REQUIRED
                and message.get("contextId")
                and str(message.get("contextId")) == active.context_id
            ):
                job = self.bridge.jobs.get(active.id)
        if job is not None and text:
            taken = job.answer(text)
            payload = job.task.as_dict()
            if not taken:
                payload["status"]["message"] = tasks.message(
                    "Nadie esperaba una respuesta; lo tomo como tarea nueva no."
                )
            self._send_json({"jsonrpc": "2.0", "id": request_id, "result": payload})
            return
        # ── new work ──────────────────────────────────────────────────
        if not self.bridge.stoppable:
            self._send_blocking(request_id, params)
            return
        task, text, _context = self._task_for(params)
        if not text:
            ...  # unchanged refusal
        if self.bridge.active() not in (None, task):
            self._send_json({
                "jsonrpc": "2.0", "id": request_id,
                "result": self._refuse(
                    task, "Ya hay una tarea en marcha. Dígame si es una respuesta o si la dejo."
                ),
            })
            return
        project, prompt = self.bridge.prepare(text)
        if project is None:
            ...  # unchanged refusal
        task.advance(tasks.WORKING, f"En ello: {project.name}.")
        job = worker.Job(self.bridge, task, prompt, project, fresh=_fresh(params))
        self.bridge.jobs[task.id] = job
        job.start()
        self._send_json({"jsonrpc": "2.0", "id": request_id, "result": task.as_dict()})
```

(The `...` lines mean: keep the existing refusal blocks exactly as they are today — they are quoted in full in the current file at `server.py:241-265`.)

`do_GET` gains the firehose before the 404:

```python
        if self.path == "/events":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            q = self.bridge.subscribe()
            try:
                while True:
                    try:
                        payload = q.get(timeout=15)
                    except queue.Empty:
                        self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
                        continue
                    self.wfile.write(
                        f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode()
                    )
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                self.bridge.unsubscribe(q)
            return
```

`_cancel` additionally routes through the job so a checkpoint wait dies too: after `self.bridge.stop(task.id)`, also `job = self.bridge.jobs.get(task.id)` and if the job sits at its checkpoint, `job.answer("sí")` would close it wrongly — instead have `Job` expose the canceled state naturally: `stop()` only reaches a running SdkRun; if the task is at the checkpoint, `task.advance(tasks.CANCELED, ...)` (which `_cancel` already does) plus `job._checkpoint.put("")` with a guard in `_run`: after the checkpoint `get`, `if self.task.state == tasks.CANCELED: emit end; return`. Add that guard.

- [ ] **Step 5: Run the worker tests, then the whole bridge suite**

Run: `cd /home/nexus/git/os1-samantha/Hermes/bridges/code-a2a && PYTHONNOUSERSITE=1 /home/nexus/git/os1-samantha/widget/.venv/bin/python -m pytest tests -q`
Expected: PASS. `test_bridge_sdk.py` exercises `_send` — where it asserted a COMPLETED result synchronously on the SDK path, update it to drive the new flow (send → WORKING; then answer the checkpoint via a second send with `taskId`).

- [ ] **Step 6: Commit**

```bash
cd /home/nexus/git/os1-samantha
git add Hermes/bridges/code-a2a/worker.py Hermes/bridges/code-a2a/server.py Hermes/bridges/code-a2a/tests/test_worker.py Hermes/bridges/code-a2a/tests/test_bridge_sdk.py
git commit -m "feat(bridge): accept at once, checkpoint at the end, firehose for the strip"
```

---

### Task 6: plugin `hitos.py` — the Spanish the band shows

**Files:**
- Create: `Hermes/plugins/samantha_code/hitos.py`
- Test: `Hermes/plugins/samantha_code/tests/test_hitos.py`

**Interfaces:**
- Produces: `render(event: dict) -> str | None` (a firehose payload in, a console line out, None to drop); `class Dedup` with `feed(line: str) -> str | None` (consecutive duplicates out — belt to the bridge's braces).
- Consumed by: Task 8 (`__init__.py` dispatch).

- [ ] **Step 1: Write the failing tests**

```python
"""Firehose payloads → the exact lines the band shows."""
from samantha_code.hitos import Dedup, render


def test_each_milestone_kind_has_its_line():
    assert render({"event": "milestone", "kind": "read", "detail": "", "text": ""}) == "Leyendo el proyecto…"
    assert render({"event": "milestone", "kind": "edit", "detail": "vad.py", "text": ""}) == "Editando vad.py"
    assert render({"event": "milestone", "kind": "tests", "detail": "", "text": ""}) == "Pasando los tests…"
    assert render({"event": "milestone", "kind": "run", "detail": "git", "text": ""}) == "Ejecutando: git"
    assert render({"event": "milestone", "kind": "note", "detail": "Voy al VAD.", "text": ""}) == "Voy al VAD."


def test_test_outcomes_speak_spanish():
    line = render({"event": "milestone", "kind": "tests_out", "detail": "12 passed, 2 failed", "text": ""})
    assert line == "Tests: 12 pasan, 2 fallan"


def test_unknown_kinds_fall_back_to_the_text():
    assert render({"event": "milestone", "kind": "novel", "detail": "", "text": "algo"}) == "algo"
    assert render({"event": "milestone", "kind": "novel", "detail": "", "text": ""}) is None


def test_questions_are_marked_and_checkpoints_stay_off_the_band():
    assert render({"event": "ask", "qkind": "question", "text": "¿A o B?"}) == "? ¿A o B?"
    assert render({"event": "ask", "qkind": "gate", "text": "git push"}) == "? Quiere: git push"
    assert render({"event": "ask", "qkind": "checkpoint", "text": "Hecho."}) is None


def test_other_events_render_nothing():
    for ev in ("task", "resolved", "end"):
        assert render({"event": ev}) is None


def test_dedup_drops_only_consecutive_repeats():
    d = Dedup()
    assert d.feed("a") == "a"
    assert d.feed("a") is None
    assert d.feed("b") == "b"
    assert d.feed("a") == "a"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd /home/nexus/git/os1-samantha && PYTHONNOUSERSITE=1 widget/.venv/bin/python -m pytest Hermes/plugins/samantha_code/tests/test_hitos.py -q`
Expected: FAIL — `ModuleNotFoundError` (check how `test_live.py` imports — it imports `samantha_code.live` with `Hermes/plugins` on the path via conftest or direct relative import; match whatever it does).

- [ ] **Step 3: Implement**

```python
"""What the band says for each firehose event. Pure; no gateway.

The wording deliberately duplicates `milestones.plain()` in the bridge:
two processes, two vocabularies, no import across the seam — the same
stance `live.summarise` documents against `bridges/code-a2a/stream.py`.
"""

from __future__ import annotations

_LINES = {
    "read": "Leyendo el proyecto…",
    "tests": "Pasando los tests…",
}


def render(event: dict) -> str | None:
    """One firehose payload → one console line, or None to drop it."""
    what = event.get("event")
    if what == "milestone":
        kind = event.get("kind") or ""
        detail = str(event.get("detail") or "")
        if kind in _LINES:
            return _LINES[kind]
        if kind == "edit":
            return f"Editando {detail}"
        if kind == "run":
            return f"Ejecutando: {detail}"
        if kind == "tests_out":
            spanish = detail.replace("passed", "pasan").replace("failed", "fallan")
            return f"Tests: {spanish}"
        if kind == "note":
            return detail or None
        return str(event.get("text") or "") or None
    if what == "ask":
        text = str(event.get("text") or "")
        qkind = event.get("qkind")
        if qkind == "question":
            return f"? {text}"
        if qkind == "gate":
            return f"? Quiere: {text}"
        return None  # the checkpoint is the voice's; the band shows the end line
    return None


class Dedup:
    """Consecutive repeats out — belt to the bridge's braces."""

    def __init__(self) -> None:
        self._last: str | None = None

    def feed(self, line: str) -> str | None:
        if line == self._last:
            return None
        self._last = line
        return line
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: same as Step 2. Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
cd /home/nexus/git/os1-samantha
git add Hermes/plugins/samantha_code/hitos.py Hermes/plugins/samantha_code/tests/test_hitos.py
git commit -m "feat(code): the band's Spanish for each firehose event"
```

---

### Task 7: plugin `client.py` — following the firehose, answering the bridge

**Files:**
- Create: `Hermes/plugins/samantha_code/client.py`
- Test: `Hermes/plugins/samantha_code/tests/test_client.py`

**Interfaces:**
- Produces:
  - `DEFAULT_BRIDGE = "http://127.0.0.1:9910"`
  - `follow_events(url: str, stop: Callable[[], bool]) -> Iterator[dict]` — connects to `{url}/events`, yields each SSE `data:` payload as a dict, reconnects with backoff 1 s → 30 s while `stop()` is false, and never raises out.
  - `send_answer(url: str, task_id: str, text: str) -> bool` — POST `message/send` with `{"message": {"taskId": task_id, "role": "ROLE_USER", "parts": [{"kind": "text", "text": text}], "messageId": <uuid>}}`; True on HTTP 200 with a JSON-RPC `result`.
- Consumed by: Task 8.

- [ ] **Step 1: Write the failing tests**

Use a real `ThreadingHTTPServer` on port 0 as the fixture — the plugin has no test double for HTTP and stdlib is the rule:

```python
"""The SSE follower and the answer POST, against a tiny local server."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from samantha_code.client import follow_events, send_answer


class _Fake(BaseHTTPRequestHandler):
    posts: list[dict] = []

    def log_message(self, *a):  # noqa: A003
        pass

    def do_GET(self):
        if self.path != "/events":
            self.send_response(404); self.end_headers(); return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        self.wfile.write(b": keepalive\n\n")
        self.wfile.write(b'data: {"event": "task", "taskId": "t1"}\n\n')
        self.wfile.write(b"data: not-json\n\n")
        self.wfile.write(b'data: {"event": "end", "taskId": "t1"}\n\n')
        self.wfile.flush()

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        _Fake.posts.append(body)
        out = json.dumps({"jsonrpc": "2.0", "id": body.get("id"), "result": {"id": "t1"}}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)


def _server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Fake)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def test_follow_yields_json_payloads_and_skips_the_rest():
    server, url = _server()
    try:
        seen = []
        for payload in follow_events(url, stop=lambda: len(seen) >= 2):
            seen.append(payload)
            if len(seen) >= 2:
                break
        assert seen == [
            {"event": "task", "taskId": "t1"},
            {"event": "end", "taskId": "t1"},
        ]
    finally:
        server.shutdown()


def test_send_answer_posts_a_message_send_with_the_task_id():
    server, url = _server()
    try:
        _Fake.posts.clear()
        assert send_answer(url, "t1", "sí") is True
        sent = _Fake.posts[0]
        assert sent["method"] == "message/send"
        message = sent["params"]["message"]
        assert message["taskId"] == "t1"
        assert message["parts"][0]["text"] == "sí"
    finally:
        server.shutdown()


def test_send_answer_is_false_when_nobody_listens():
    assert send_answer("http://127.0.0.1:9", "t1", "sí") is False
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd /home/nexus/git/os1-samantha && PYTHONNOUSERSITE=1 widget/.venv/bin/python -m pytest Hermes/plugins/samantha_code/tests/test_client.py -q`
Expected: FAIL — no module `samantha_code.client`.

- [ ] **Step 3: Implement**

```python
"""The bridge's firehose, followed; and the one POST that answers it.

urllib on purpose: the gateway process already has aiohttp, but this
runs on a plugin THREAD, not the gateway's loop, and a blocking read on
a socket of its own is the whole design — nothing here may touch the
loop (§12, 2026-08-26, the live-camera lesson).
"""

from __future__ import annotations

import json
import time
import urllib.request
import uuid
from collections.abc import Callable, Iterator

from loguru import logger

DEFAULT_BRIDGE = "http://127.0.0.1:9910"

# Reconnect backoff: quick at first (a gateway restart), patient after
# (a bridge that is simply not installed on this box).
_BACKOFF_START = 1.0
_BACKOFF_CEILING = 30.0

_ANSWER_TIMEOUT = 10.0


def follow_events(url: str, stop: Callable[[], bool]) -> Iterator[dict]:
    """Yield each firehose payload. Reconnects; never raises out."""
    backoff = _BACKOFF_START
    while not stop():
        try:
            with urllib.request.urlopen(f"{url}/events", timeout=60) as response:
                logger.info(f"samantha-code: siguiendo {url}/events")
                backoff = _BACKOFF_START
                for raw in response:
                    if stop():
                        return
                    line = raw.decode("utf-8", errors="replace").strip()
                    if not line.startswith("data:"):
                        continue  # keepalives and blanks
                    try:
                        payload = json.loads(line[5:].strip())
                    except ValueError:
                        continue
                    if isinstance(payload, dict):
                        yield payload
        except Exception as exc:
            logger.debug(f"samantha-code: el puente no responde — {exc}")
        if stop():
            return
        time.sleep(backoff)
        backoff = min(backoff * 2, _BACKOFF_CEILING)


def send_answer(url: str, task_id: str, text: str) -> bool:
    """Deliver the user's answer to the bridge. False when it did not land."""
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "message/send",
            "params": {
                "message": {
                    "messageId": str(uuid.uuid4()),
                    "role": "ROLE_USER",
                    "taskId": task_id,
                    "parts": [{"kind": "text", "text": text}],
                }
            },
        },
        ensure_ascii=False,
    ).encode()
    request = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=_ANSWER_TIMEOUT) as response:
            reply = json.loads(response.read() or b"{}")
    except Exception as exc:
        logger.warning(f"samantha-code: la respuesta no llegó al puente — {exc}")
        return False
    return isinstance(reply, dict) and "result" in reply
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: same as Step 2. Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
cd /home/nexus/git/os1-samantha
git add Hermes/plugins/samantha_code/client.py Hermes/plugins/samantha_code/tests/test_client.py
git commit -m "feat(code): the plugin follows the bridge's firehose"
```

---

### Task 8: the plugin wired — pending, injection, and the adapter's divert

**Files:**
- Create: `Hermes/plugins/samantha_code/pending.py`, `Hermes/plugins/samantha_code/voz.py`
- Modify: `Hermes/plugins/samantha_code/__init__.py`, `Hermes/plugins/samantha_kiosk/adapter.py`, `Hermes/plugins/samantha_kiosk/protocol.py`
- Test: `Hermes/plugins/samantha_code/tests/test_pending.py`, `tests/test_voz.py`; `Hermes/plugins/samantha_kiosk/tests/test_adapter.py`, `tests/test_protocol.py`

**Interfaces:**
- Consumes: `hitos.render`/`Dedup` (Task 6); `client.follow_events`/`send_answer`/`DEFAULT_BRIDGE` (Task 7); `_push` and `_adapter` already in `__init__.py`; `ctx.inject_message` (the vision-alert mechanism, `alert.py` documents its semantics).
- Produces:
  - `pending.Pending`: thread-safe; `set(task_id: str, kind: str)`, `clear()`, `get() -> tuple[str, str] | None`.
  - `voz.KIOSK_SESSION_KEY = "agent:main:samantha_kiosk:dm:kiosk"`; `voz.prompt_for(qkind: str, text: str) -> str`; `voz.deliver(inject: Callable[..., bool], text: str) -> bool` (retries `(1.0, 3.0, 5.0)` on False, like `alert.py`).
  - `KioskAdapter.divert_chat: Optional[Callable[[str], bool]]` — consulted in `_ws_handler` before `_handle_chat`, skipped when the frame carries `"wake": true`.
  - `decode_client` accepts an optional boolean `wake` on `chat` frames (rejects non-boolean).

- [ ] **Step 1: Failing tests for `Pending`**

```python
"""The one flag: which task waits, and for what."""
from samantha_code.pending import Pending


def test_starts_empty_and_round_trips():
    p = Pending()
    assert p.get() is None
    p.set("t1", "gate")
    assert p.get() == ("t1", "gate")
    p.clear()
    assert p.get() is None


def test_a_new_question_replaces_the_old():
    p = Pending()
    p.set("t1", "question")
    p.set("t1", "checkpoint")
    assert p.get() == ("t1", "checkpoint")
```

Implementation (`pending.py`):

```python
"""Which task waits for the user, and for what kind of answer.

Thread-safe because three threads meet here: the firehose follower sets
it, the adapter's loop reads it, and the answer thread clears it.
"""

from __future__ import annotations

import threading


class Pending:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._value: tuple[str, str] | None = None

    def set(self, task_id: str, kind: str) -> None:
        with self._lock:
            self._value = (task_id, kind)

    def clear(self) -> None:
        with self._lock:
            self._value = None

    def get(self) -> tuple[str, str] | None:
        with self._lock:
            return self._value
```

- [ ] **Step 2: Failing tests for `voz`**

```python
"""What gets injected, and how stubbornly."""
from samantha_code import voz


def test_each_kind_has_a_prompt_that_carries_the_text_as_a_labelled_value():
    for kind in ("question", "gate", "checkpoint"):
        prompt = voz.prompt_for(kind, "¿A o B?")
        assert "«¿A o B?»" in prompt
        assert "asistente de código" in prompt


def test_deliver_retries_on_false_and_stops_on_true():
    calls = []

    def inject(text, **kwargs):
        calls.append(kwargs.get("session_key"))
        return len(calls) >= 2

    voz.RETRY_DELAYS = (0.0, 0.0, 0.0)  # test speed; restore not needed, module-level per test run
    assert voz.deliver(inject, "hola") is True
    assert len(calls) == 2
    assert calls[0] == voz.KIOSK_SESSION_KEY
```

Implementation (`voz.py`):

```python
"""The three prompts that earn the voice, and the stubbornness of one push.

The text travels as a LABELLED VALUE inside «…» — the lesson of the
camera names (§12, 2026-08-24): a model handed a fragment inside its own
sentence repairs bad grammar by inventing; handed a quoted value, it
picks its own words around it.

Injection semantics are `alert.py`'s, measured 2026-08-24: False means
the gateway's injector is not installed yet and retrying helps; a
missing session comes back True and is logged by Hermes itself.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from loguru import logger

KIOSK_SESSION_KEY = "agent:main:samantha_kiosk:dm:kiosk"

RETRY_DELAYS: tuple[float, ...] = (1.0, 3.0, 5.0)

_PROMPTS = {
    "question": (
        "El asistente de código se ha parado a preguntar y espera la "
        "respuesta del usuario. Pregunta: «{text}». Trasládasela en tus "
        "palabras, en una frase, y no la respondas tú."
    ),
    "gate": (
        "El asistente de código quiere hacer algo delicado y necesita "
        "permiso del usuario antes de seguir. Acción: «{text}». Pídele "
        "permiso en una frase."
    ),
    "checkpoint": (
        "El asistente de código ha terminado el encargo. Resultado: "
        "«{text}». Cuéntaselo al usuario en tus palabras, breve, y "
        "pregúntale si lo da por bueno."
    ),
}


def prompt_for(qkind: str, text: str) -> str:
    template = _PROMPTS.get(qkind) or _PROMPTS["question"]
    return template.format(text=text)


def deliver(inject: Callable[..., bool], text: str) -> bool:
    """Push one prompt into the strip's session, with alert.py's patience."""
    for delay in RETRY_DELAYS:
        if inject(text, role="user", session_key=KIOSK_SESSION_KEY):
            return True
        time.sleep(delay)
    logger.warning("samantha-code: el aviso no llegó a la sesión de la tira")
    return False
```

- [ ] **Step 3: Failing tests for the adapter's divert and the protocol's `wake`**

In `Hermes/plugins/samantha_kiosk/tests/test_protocol.py`:

```python
def test_a_chat_frame_may_say_it_was_addressed_by_name():
    msg = decode_client(json.dumps(
        {"type": "chat", "message": "hola", "user_id": "u", "wake": True}
    ))
    assert msg["wake"] is True


def test_wake_must_be_a_boolean_if_present():
    with pytest.raises(ProtocolError):
        decode_client(json.dumps(
            {"type": "chat", "message": "hola", "user_id": "u", "wake": "yes"}
        ))
```

In `Hermes/plugins/samantha_kiosk/tests/test_adapter.py`, following that file's existing fixtures for driving `_ws_handler`-adjacent logic (read the file first; if it tests `_handle_chat` directly, test the divert decision as its own function). To keep the seam testable without a websocket, implement the decision as a method and test THAT:

```python
def test_divert_consumes_unnamed_input_when_someone_waits():
    adapter = make_adapter()          # the file's existing helper/fixture
    taken = []
    adapter.divert_chat = lambda text: taken.append(text) or True
    assert adapter._should_divert({"type": "chat", "message": "sí", "user_id": "u"}) is True
    assert taken == ["sí"]


def test_named_input_always_reaches_jarvis():
    adapter = make_adapter()
    adapter.divert_chat = lambda text: True
    assert adapter._should_divert(
        {"type": "chat", "message": "qué hora es", "user_id": "u", "wake": True}
    ) is False


def test_no_divert_hook_means_nothing_changes():
    adapter = make_adapter()
    assert adapter._should_divert({"type": "chat", "message": "hola", "user_id": "u"}) is False


def test_a_divert_that_raises_does_not_eat_the_turn():
    adapter = make_adapter()
    def boom(text):
        raise RuntimeError("x")
    adapter.divert_chat = boom
    assert adapter._should_divert({"type": "chat", "message": "hola", "user_id": "u"}) is False
```

- [ ] **Step 4: Implement adapter + protocol**

`protocol.py`, inside the `kind == "chat"` validation block:

```python
        wake = msg.get("wake")
        if wake is not None and not isinstance(wake, bool):
            raise ProtocolError("wake must be a boolean when present")
```

`adapter.py`: in `__init__`, `self.divert_chat: Optional[Callable[[str], bool]] = None` with the comment:

```python
        # While the code assistant waits for an answer, samantha_code
        # sets this; the next unnamed input is the answer and goes to
        # the bridge instead of opening a turn. Deterministic on
        # purpose: the model that fills tool args with {} (§12,
        # 2026-08-26) never touches the reply. A frame with
        # "wake": true was addressed by name and always reaches JARVIS.
        self.divert_chat: Optional[Callable[[str], bool]] = None
```

New method + the `_ws_handler` change:

```python
    def _should_divert(self, decoded: Dict[str, Any]) -> bool:
        """Whether this chat frame is an answer for the code assistant."""
        divert = self.divert_chat
        if divert is None or decoded.get("wake"):
            return False
        try:
            return bool(divert(decoded["message"]))
        except Exception as exc:
            logger.warning(f"samantha-kiosk: divert failed — {exc}")
            return False
```

and in `_ws_handler`:

```python
                if decoded["type"] == "chat":
                    if self._should_divert(decoded):
                        continue
                    await self._handle_chat(decoded["message"], decoded["user_id"])
```

- [ ] **Step 5: Wire `__init__.py`**

Replace the tail of `register()` and add the bridge mode. The legacy follower stays selectable:

```python
def register(ctx):
    """Start the bridge follower — or, with no bridge configured, the
    legacy tee-file follower (a box running the CLI path keeps v1).
    """
    stop = threading.Event()
    try:
        ctx.on_unload(stop.set)
    except Exception:
        pass

    bridge = _setting(ctx, "bridge", client.DEFAULT_BRIDGE)
    if bridge:
        threading.Thread(
            target=_run_bridge_mode,
            args=(ctx, bridge, stop),
            name="samantha-code-bridge",
            daemon=True,
        ).start()
        return

    path = Path(os.environ.get("SAMANTHA_CODE_LIVE", "") or DEFAULT_LIVE).expanduser()

    def run() -> None:
        try:
            watch(path, stop)
        except Exception as exc:
            logger.warning(f"samantha-code: el seguidor se detuvo — {exc}")

    threading.Thread(target=run, name="samantha-code-live", daemon=True).start()


def _setting(ctx, name: str, default: str) -> str:
    try:
        value = ctx.get_config(name)
    except Exception:
        return default
    return default if value is None else str(value)


def _run_bridge_mode(ctx, bridge: str, stop: threading.Event) -> None:
    """The dispatch loop: firehose in; console, voice and divert out."""
    state = pending.Pending()
    dedup = hitos.Dedup()

    def divert(text: str) -> bool:
        waiting = state.get()
        if waiting is None:
            return False
        task_id, _kind = waiting
        state.clear()
        _set_divert(None)
        _push(f"→ {text}\n")
        threading.Thread(
            target=client.send_answer, args=(bridge, task_id, text), daemon=True
        ).start()
        return True

    def _set_divert(hook) -> None:
        adapter = _adapter()
        if adapter is not None:
            adapter.divert_chat = hook

    try:
        for event in client.follow_events(bridge, stop.is_set):
            what = event.get("event")
            if what == "task":
                dedup = hitos.Dedup()
                _push("", reset=True)
            elif what == "ask":
                text = str(event.get("text") or "")
                state.set(str(event.get("taskId") or ""), str(event.get("qkind") or ""))
                _set_divert(divert)
                line = hitos.render(event)
                if line:
                    _push(line + "\n")
                voz.deliver(ctx.inject_message, voz.prompt_for(
                    str(event.get("qkind") or ""), text
                ))
            elif what == "resolved":
                state.clear()
                _set_divert(None)
            elif what == "end":
                state.clear()
                _set_divert(None)
                _push("", done=True)
            else:
                line = hitos.render(event)
                if line:
                    line = dedup.feed(line)
                if line:
                    _push(line + "\n")
    except Exception as exc:  # noqa: BLE001 — the follower owns its failure
        logger.warning(f"samantha-code: el modo puente se detuvo — {exc}")
```

Imports at the top of `__init__.py`: `from . import client, hitos, pending, voz`. The module docstring's first paragraph must be rewritten — it currently explains why the plugin registers no tools and follows a file; keep the no-tools paragraph (still true and still the measured reason), replace the file-following description with the firehose one, and note the legacy mode behind `settings.bridge: ""`.

**Two deliberate behaviors to preserve in review:** (1) the checkpoint's `ask` renders no console line (`hitos.render` returns None for it) but still sets pending and injects — the band already shows «— terminado» when `end` arrives; (2) `divert` clears pending optimistically before the POST — a second utterance during the flight must not be swallowed as a second answer.

- [ ] **Step 6: Run everything**

Run: `cd /home/nexus/git/os1-samantha && PYTHONNOUSERSITE=1 widget/.venv/bin/python -m pytest Hermes/plugins/samantha_kiosk/tests Hermes/plugins/samantha_code/tests -q`
Expected: PASS — the pre-existing 67 plus the new ones. `test_live.py` must still pass untouched (legacy mode).

- [ ] **Step 7: Commit**

```bash
cd /home/nexus/git/os1-samantha
git add Hermes/plugins/samantha_code Hermes/plugins/samantha_kiosk
git commit -m "feat(code): the plugin drives the bridge — pending, voice, and the adapter's divert"
```

---

### Task 9: the widget says whether it was addressed by name

**Files:**
- Modify: `widget/samantha_widget/wake.py`, `widget/samantha_widget/gateway.py`, `widget/samantha_widget/__main__.py`
- Test: `widget/tests/test_wake.py`, `widget/tests/test_gateway.py`

**Interfaces:**
- Produces: `WakeWord.named: bool` — True after a `heard()` that matched the name itself, False after a window pass-through or with the wake word disabled. `GatewayClient.send_chat(text: str, *, wake: bool = False)` — adds `"wake": true` to the chat frame only when True.
- Consumed by: the adapter's `_should_divert` (Task 8) reads the frame field.

- [ ] **Step 1: Write the failing tests**

Append to `widget/tests/test_wake.py` (match its existing constructor usage):

```python
def test_heard_remembers_whether_the_name_was_said():
    w = WakeWord("jarvis")
    assert w.heard("jarvis, qué hora es", now=0.0) == "qué hora es"
    assert w.named is True
    w.answered(now=1.0)
    assert w.heard("y mañana", now=2.0) == "y mañana"
    assert w.named is False


def test_with_no_wake_word_nothing_counts_as_named():
    w = WakeWord("")
    assert w.heard("hola", now=0.0) == "hola"
    assert w.named is False
```

Append to `widget/tests/test_gateway.py` (match how existing tests capture sent frames — they drive `GatewayClient` with a fake ws; follow the file's pattern for `send_chat`):

```python
def test_send_chat_marks_named_turns_and_only_those():
    sent = []
    gw = GatewayClient()
    gw._ws = _FakeWs(sent)          # whatever double the file already uses
    asyncio.run(gw.send_chat("hola"))
    asyncio.run(gw.send_chat("hola", wake=True))
    first, second = (json.loads(s) for s in sent)
    assert "wake" not in first
    assert second["wake"] is True
```

(If `test_gateway.py` has no send-side double, add the minimal one the file's style suggests; the existing `send_chat` body shows what it writes to.)

- [ ] **Step 2: Run to verify they fail**

Run: `cd /home/nexus/git/os1-samantha/widget && PYTHONNOUSERSITE=1 ./.venv/bin/python -m pytest tests/test_wake.py tests/test_gateway.py -q`
Expected: FAIL — no attribute `named` / unexpected keyword `wake`.

- [ ] **Step 3: Implement**

`wake.py` — in `__init__`: `self.named = False`; in `heard()`: set `self.named = False` at the top (after the empty-text return), and `self.named = True` inside the name-match branch just before its `return`. Docstring line: `named` says HOW the last accepted sentence got in — by name, or through the window; the adapter routes on it while the code assistant waits for an answer.

`gateway.py`:

```python
    async def send_chat(self, text: str, *, wake: bool = False) -> None:
        ...
        frame: dict = {"type": "chat", "message": text, "user_id": self.user_id}
        if wake:
            # Addressed by name: the gateway must never divert this one
            # to the code assistant, whatever is pending.
            frame["wake"] = True
        ...
```

(Adapt to the actual body — keep whatever awaiting/queueing it already does; only the frame dict changes.)

`__main__.py` line ~453 (the spoken path): `await client.send_chat(spoken, wake=wake.named)`. The typed path (line ~375) stays `send_chat(text)` — typed input carries no name, and while a question is pending that is exactly the input that should divert.

- [ ] **Step 4: Run the widget suite and lint**

Run: `cd /home/nexus/git/os1-samantha/widget && PYTHONNOUSERSITE=1 ./.venv/bin/python -m pytest tests -q && ./.venv/bin/ruff check . && ./.venv/bin/ruff format --check .`
Expected: PASS, clean.

- [ ] **Step 5: Commit**

```bash
cd /home/nexus/git/os1-samantha
git add widget/samantha_widget/wake.py widget/samantha_widget/gateway.py widget/samantha_widget/__main__.py widget/tests/test_wake.py widget/tests/test_gateway.py
git commit -m "feat(widget): a turn says whether it carried his name"
```

---

### Task 10: steering, config, and the paper trail

No new mechanism — the words and records that make the machinery reachable and the decision findable.

**Files:**
- Modify: `Hermes/plugins/samantha_kiosk/__init__.py` (`_platform_hint`), `Hermes/plugins/samantha_code/plugin.yaml` (description + failure notes), `Hermes/samantha-config.yaml` (comment documenting `settings.bridge`), `systemd/samantha-code-a2a.service` (document `SAMANTHA_CODE_GATES`), `CLAUDE.md` (§12 entry), `PROGRESS.md`

- [ ] **Step 1: The platform hint learns the delegation shape**

In `_platform_hint()`'s `surface` string, append (exact copy, Spanish, no tool names spoken aloud is already the persona's rule — this is model-facing text, where naming the tool is required):

```
"Para encargos de programación usa a2a_call con el agente 'codigo': "
"lanza el encargo y responde solo que estás en ello. Los avisos del "
"asistente de código te llegarán como mensajes; trasládalos en una "
"frase y no respondas tú en su lugar. Si el usuario contesta a una "
"pregunta del asistente, esa respuesta llega sola — no la reenvíes."
```

- [ ] **Step 2: plugin.yaml and the tracked config**

`plugin.yaml`: the description already describes the stream mode — update its failure-notes block: note 4 (the 30-minute reader ceiling) is obsolete — replace it with the reconnect-backoff behavior; add that `settings.bridge: ""` selects the legacy tee-file follower. In `Hermes/samantha-config.yaml`, next to the existing a2a comment block, document (as a comment — the value has a code default):

```yaml
# plugins.entries.samantha-code.settings.bridge:
#   The code bridge's URL (default http://127.0.0.1:9910). Empty string
#   selects the legacy tee-file follower (a box without the bridge).
```

- [ ] **Step 3: The unit documents the gate policy**

In `systemd/samantha-code-a2a.service`, above the `ExecStart` (or its `[Service]` block), a comment plus the default made visible:

```ini
# The gate: Bash commands matching any of these ask the user first.
# Set, the variable IS the whole policy — add "git commit" here to gate
# commits too. Default in code: git push, rm -r, rm -f, sudo.
#Environment=SAMANTHA_CODE_GATES=git push, rm -r, rm -f, sudo
```

- [ ] **Step 4: CLAUDE.md §12 entry and PROGRESS.md**

Append to §12 (top of the log, dated 2026-08-27): the decision — the console shows milestones and three moments reach the user (questions, gates, checkpoint); the gate **partially reverses** «full scope, including push» of 2026-08-26, at the user's request; the answer path bypasses the model deliberately (the `args={}` measurement is why); and the a2a path replaces the terminal path as the delegation default on this box, with the skills path remaining as the no-bridge fallback. Brief — the spec and probe docs carry the detail; link both. PROGRESS.md gets the execution entry per its style, newest first.

- [ ] **Step 5: Commit**

```bash
cd /home/nexus/git/os1-samantha
git add Hermes/plugins/samantha_kiosk/__init__.py Hermes/plugins/samantha_code/plugin.yaml Hermes/samantha-config.yaml systemd/samantha-code-a2a.service CLAUDE.md PROGRESS.md
git commit -m "docs: samantha_code v2 — steering, gate policy, and the decision recorded"
```

---

### Task 11: end to end, with a human in the room

The camera's rule: nothing visual or spoken is provable from a test. This task is a checklist for the user and whoever drives the session; it produces a PROGRESS.md addendum with the measurements, not code.

- [ ] **Step 1: Deploy and restart the pieces**

```bash
cd /home/nexus/git/os1-samantha
cp systemd/samantha-code-a2a.service ~/.config/systemd/user/ && systemctl --user daemon-reload
systemctl --user restart samantha-code-a2a.service samantha-hermes.service samantha-widget.service
curl -s http://127.0.0.1:9910/.well-known/agent-card.json | head -c 200   # the bridge is up
```

- [ ] **Step 2: The hint change reaches the session**

Through the strip: `/new`, then `/approve` (§7 — a hint never reaches an existing session; this has cost an afternoon before).

- [ ] **Step 3: The happy path** — say or type: «Jarvis, en prueba-a2a rompe y arregla el test de calc.py». Verify: JARVIS answers «en ello» within seconds (the turn is NOT held); the band resets and shows milestone lines, no `· Bash:` raw commands, no consecutive duplicates; at the end JARVIS asks aloud whether to close it; answering «sí» (no name) closes it and the band folds after its minute.

- [ ] **Step 4: The gate** — «Jarvis, en prueba-a2a crea un commit vacío y haz push». Verify: JARVIS asks permission aloud naming the action; «no» is obeyed (nothing pushed — check `git log` on the remote) and the closing line says so; run it again and answer «sí» — the push happens.

- [ ] **Step 5: The question** — an encargo built to force a choice: «…pregúntame antes si prefieres la opción A o la B». Verify the literal question lands on the band with `? `, the voice carries it, an unnamed answer reaches the assistant (per the probe's mechanism), and «Jarvis, ¿qué hora es?» asked BETWEEN question and answer goes to JARVIS, with the question still pending after.

- [ ] **Step 6: The failure modes** — stop the bridge mid-task (`systemctl --user stop samantha-code-a2a`): the band notes the loss, the gateway keeps talking; restart it: the follower reconnects within ~30 s. Leave a gate unanswered 5 minutes: denied, said at the end.

- [ ] **Step 7: Record it** — append the measurements to PROGRESS.md (times, what was said verbatim where it surprised), commit, and push per the user's standing authorization.

```bash
git add PROGRESS.md && git commit -m "docs: samantha_code v2 measured against the house" && git push
```

---

## Self-review (done at planning time)

- **Spec coverage:** noisy console → Tasks 3, 6; questions → Tasks 1, 4; gate → Tasks 2, 4; checkpoint → Task 5; async accept → Task 5; firehose replaces tee → Tasks 5, 7, 8; adapter routing + wake exception → Tasks 8, 9; voice via injection → Task 8 (`voz`); fallback path preserved → Task 8 Step 5 (legacy mode) and Task 5's scope note; timeouts 300/600 → Tasks 4, 5; steering + decision log → Task 10; human validation → Task 11.
- **Known open end, carried on purpose:** Task 4's AskUserQuestion branch is written for P2 and marked with the probe reference; Task 1's findings may rewrite that one branch (P1: return `updatedInput` from `can_use_tool` instead; P3: delete the branch and note it in the spec).
- **Type consistency checked:** `Event(kind=, detail=)` (Task 4) matches Task 5's `event.kind`/`event.detail` reads and Task 6's payload fields; `Job.answer` matches `_send`'s routing; `Pending.get() -> tuple | None` matches `_run_bridge_mode`'s use; `send_chat(text, *, wake=False)` matches `__main__`'s call.
