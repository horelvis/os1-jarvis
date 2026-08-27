"""samantha-code — the assistant's work, visible on the strip.

**It registers no tools, and that is the design.** An earlier version of
this plugin offered one, and the model called it with no arguments at
all — `args={}`, `user_task="None"`, measured six times, which is the
same failure §4 records for `mirar`. Delegating coding is done through
the skills Hermes already ships (`claude-code`, `opencode`, `codex`),
which are written on `terminal`, and the model fills THOSE arguments
correctly.

So this plugin does the one thing those skills cannot: show the work
while it happens, and bring the user back into it when his judgement is
needed. `terminal` returns when the command ends, so a task that takes
four minutes is four minutes of nothing on screen.

What it follows is the bridge's firehose (`bridges/code-a2a`, on
:9910): one loopback SSE stream carrying semantic events rather than
raw output. Milestones become one Spanish line each on the strip's
console; the three moments that need a person — the assistant's own
question, anything irreversible, and the closing checkpoint — become a
prompt injected into the strip's session, so the user is ASKED, out
loud, in his voice.

With `settings.bridge` emptied it falls back to v1: the tee-file
follower below, for a box running the CLI path with no bridge on it.

Nothing here sits in the path of a turn. If the bridge is not up the
follower reconnects forever; if the strip is not connected the lines are
dropped. The assistant works either way — what is lost is watching it.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

from loguru import logger

from . import client, hitos, pending, voz
from .live import DEFAULT_LIVE, follow, summarise

# The kiosk platform, hard-coded for the reason `samantha_vision`
# hard-codes it: a setting naming the platform would let the contents of
# somebody's repository be routed elsewhere by a config change
# (§12, 2026-08-25).
KIOSK_PLATFORM = "samantha_kiosk"

def _adapter():
    """The strip's adapter, or None."""
    try:
        from gateway.config import Platform
        from gateway.run import _gateway_runner_ref

        runner = _gateway_runner_ref()
        if runner is None:
            return None
        return getattr(runner, "adapters", {}).get(Platform(KIOSK_PLATFORM))
    except Exception:
        return None


def _push(text: str, *, done: bool = False, reset: bool = False) -> None:
    """Put one line on the strip, from a thread that is not the loop's.

    Two threads call this and neither is the gateway's: v1's tee-file
    follower (`watch`) and v2's firehose dispatcher
    (`_run_bridge_mode`), plus the answer path inside the latter.

    Scheduled onto the GATEWAY's loop, never the caller's: those threads
    outlive every turn, and the loop a turn brings with it stops the
    moment that turn ends — the bug that cost the live camera a day
    (§12, 2026-08-26).
    """
    import asyncio

    adapter = _adapter()
    if adapter is None:
        return
    loop = getattr(adapter, "loop", None)
    push = getattr(adapter, "push_console", None)
    if loop is None or push is None or loop.is_closed():
        return
    try:
        asyncio.run_coroutine_threadsafe(push(text, done=done, reset=reset), loop)
    except RuntimeError:
        pass


def watch(path: Path, stop: threading.Event) -> None:
    """Follow the file and put what appears on the strip."""
    logger.info(f"samantha-code: mirando {path}")
    for kind, text in follow(path, stop.is_set):
        if kind == "start":
            # A reset, not an ANSI clear. The escape sequence wiped the
            # terminal widget and left the MODEL holding the last run's
            # lines — and the model is what decides how tall the strip
            # is, so a short run sat in a box built for the long one
            # before it (seen 2026-08-26).
            _push("", reset=True)
            continue
        if kind == "end":
            # The run is over. The strip keeps the last lines up for a
            # minute and then puts itself away — the console is the one
            # thing on the band with no natural end of its own (a photo
            # fades, a live view hits its ceiling), so it is told.
            _push("", done=True)
            continue
        line = summarise(text)
        if line:
            _push(line + "\n")


def register(ctx):
    """Start the bridge follower — or, with no bridge configured, the
    legacy tee-file follower (a box running the CLI path keeps v1).

    Pure: nothing here touches the network. The thread is a daemon and
    owns its own failure, like the camera threads — a plugin that took
    the gateway down because a socket went away would be a poor trade
    for a convenience. It is a daemon rather than something joined on
    unload because `client.follow_events` sleeps up to 30 s between
    reconnect attempts and does not check `stop` while it sleeps:
    waiting for it would look exactly like a hang.
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
    """One plugin setting, with the default when the gateway has none."""
    try:
        value = ctx.get_config(name)
    except Exception:
        return default
    return default if value is None else str(value)


def _run_bridge_mode(ctx, bridge: str, stop: threading.Event) -> None:
    """The dispatch loop: firehose in; console, voice and divert out."""
    state = pending.Pending()
    dedup = hitos.Dedup()

    def _set_divert(hook) -> None:
        adapter = _adapter()
        if adapter is not None:
            adapter.divert_chat = hook

    def divert(text: str) -> bool:
        """The user's next unnamed words, when something is waiting."""
        waiting = state.get()
        if waiting is None:
            return False
        task_id, _kind = waiting
        # Cleared BEFORE the POST leaves, on purpose: a second utterance
        # while the first is in flight is a turn, not a second answer.
        state.clear()
        _set_divert(None)
        _push(f"→ {text}\n")
        threading.Thread(
            target=client.send_answer,
            args=(bridge, task_id, text),
            name="samantha-code-answer",
            daemon=True,
        ).start()
        return True

    try:
        for event in client.follow_events(bridge, stop.is_set):
            try:
                what = event.get("event")
                if what == "task":
                    # A new run: an empty console, and a dedup that has
                    # forgotten the last run's final line.
                    #
                    # And no question outstanding. If the bridge
                    # restarted while one was, `follow_events` simply
                    # reconnects and the hook is still armed against a
                    # taskId nothing is waiting on — the user's next
                    # unnamed sentence would be echoed to the band,
                    # POSTed into «Nadie esperaba una respuesta.» and
                    # never become a turn. Exactly one sentence, lost
                    # silently, which is the failure this whole path
                    # exists to stop.
                    state.clear()
                    _set_divert(None)
                    dedup = hitos.Dedup()
                    _push("", reset=True)
                elif what == "ask":
                    text = str(event.get("text") or "")
                    qkind = str(event.get("qkind") or "")
                    state.set(str(event.get("taskId") or ""), qkind)
                    _set_divert(divert)
                    line = hitos.render(event)
                    if line:
                        _push(line + "\n")
                    # A checkpoint renders no line — it is the voice's,
                    # and the band already says «— terminado» at `end`.
                    voz.deliver(ctx.inject_message, voz.prompt_for(qkind, text))
                elif what == "resolved":
                    # Whatever was waiting is no longer. The taskId is
                    # not checked because the bridge is single-task:
                    # there is only ever one question outstanding, so a
                    # `resolved` can only be about it.
                    state.clear()
                    _set_divert(None)
                elif what == "end":
                    state.clear()
                    _set_divert(None)
                    # The closing line is written HERE, not by
                    # `hitos.render`, which returns None for `end`. The
                    # band needs it: it is what a checkpoint leaves
                    # behind, since the checkpoint itself is the
                    # voice's and shows nothing. Same wording as v1's
                    # `live.summarise`, deliberately — one console, one
                    # vocabulary, whichever mode fed it.
                    _push(
                        "— terminado con errores\n"
                        if event.get("failed")
                        else "— terminado\n"
                    )
                    _push("", done=True)
                else:
                    line = hitos.render(event)
                    if line:
                        line = dedup.feed(line)
                    if line:
                        _push(line + "\n")
            except Exception as exc:  # noqa: BLE001 — one event, not the run
                # With the stack: this loop runs for the gateway's whole
                # life, and a TypeError from a renamed key would
                # otherwise be one warning line with nowhere to look.
                logger.opt(exception=True).warning(
                    f"samantha-code: evento descartado — {exc}"
                )
    except Exception as exc:  # noqa: BLE001 — the follower owns its failure
        logger.opt(exception=True).warning(
            f"samantha-code: el modo puente se detuvo — {exc}"
        )
