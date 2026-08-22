# samantha-kiosk (plan 3a) — decision record

**Date:** 2026-08-22
**Branch:** `samantha-on-hermes-2026-08-22`
**Plan:** `docs/superpowers/plans/2026-08-22-samantha-kiosk-adapter-text.md`
**Design:** `docs/superpowers/specs/2026-08-22-samantha-on-hermes-design.md` §5
**Companion:** `docs/superpowers/specs/2026-08-22-samantha-voice-decision-record.md`
— plan 1's record. Read it first; several of its lessons are why this plan is
shaped the way it is.

Why this file exists: the execution ledger lives in `.superpowers/`, which is
git-ignored. On another machine none of the reasoning below survives — only
the code. This is the part worth carrying.

---

## What plan 3a is, and what it deliberately is not

It builds a `kind: platform` Hermes plugin that serves Samantha's built OS1
interface and holds one WebSocket to it, carrying **text only**. Plan 3b adds
audio in both directions, interruption and the §6 trim. Plan 3c does
onboarding, the frontend cleanup and the deletion of the FastAPI app.

Design §5 mixed all three — a Python adapter, a frontend rework and a deletion
pass. Splitting was the first decision: each of the three produces working
software on its own, and the deliverable here is a screen you can type into.

**The decision that saved the most work:** the design's §5.1 invents a
WebSocket protocol. We did not build it. `frontend/src/core/types.ts:37-45`
already defines a small typed one — `chat`/`listen` up, `token`/`done`/
`transcription`/`error` down — so the adapter speaks *that*, and plan 3a needs
zero frontend changes and can be tested against the real interface from the
first task. Audio frames join it in 3b as binary frames without changing the
text format. (`transcription` has no encoder yet on purpose: it is an
audio-path message and belongs to 3b.)

---

## What we learned about Hermes that the contracts document did not say

Each of these cost a round or would have.

- **`irc` is the registration template but the WRONG serving template.** It
  dials out. `gateway/platforms/api_server.py` is the only in-tree adapter
  that *listens*, so its `web.Application` / `AppRunner` / `TCPSite` lifecycle
  is what a kiosk copies.
- **`register_platform()` requires `check_fn`.** No default. Omitting it, as
  the plan's first draft did, raises `TypeError` at plugin load.
- **`BasePlatformAdapter.__init__` takes `(config, platform)`**, but the
  one-argument factory `lambda cfg: KioskAdapter(cfg)` is still correct: the
  subclass builds its own `Platform` and passes it up, exactly as
  `plugins/platforms/irc/adapter.py:126-128` does.
- **`Platform` lives in `gateway.config`**, not `gateway.platforms.base`.
- **`get_chat_info` is abstract**; `build_source` is concrete and uses
  `self.platform`. A no-Hermes test shim therefore needs stand-ins for
  `Platform`, `MessageEvent`, `MessageType`, `build_source` and
  `SessionSource` — not just the base class.
- **Configuration is read environment-first**, then the config dict, then a
  default (`irc/adapter.py:133-142`). Reading only the config dict — the
  plan's first draft again — leaves the manifest's declared environment
  variables doing nothing at all.
- **`kind: platform` plugins are opt-in.** `hermes plugins list` showing
  "not enabled" is not an error, and the gateway serves nothing until it is
  enabled.
- **`aiohttp` is not in Hermes' virtualenv.** Its own listening adapter treats
  it as optional and guards on it. Declaring `python_dependencies` does
  nothing — Hermes warns and never installs. Same lesson as `loguru` in plan
  1, which is why it got a task of its own here.
- **`AppRunner.addresses` is the public way to discover a bound port.**
  `site._server.sockets` also works but is a private attribute two layers
  deep.
- **`hermes plugins list` proves only that the manifest parsed.**
  `hermes plugins doctor <name>` is what proves the module imported. The gap
  between those two cost plan 1 half a day.

---

## Rulings

Numbered as in the ledger. Each says what it costs if wrong.

**1. Read configuration environment-first.** Found in the pre-flight scan: the
plan's Task 3 read only the config dict while Task 4's manifest declared
environment variables and Task 5 exported them. Nothing connected the two, so
the kiosk would have silently served the default directory on the default
port and we would have found out at the manual test. *Cost if wrong: the
kiosk ignores its own documented environment.*

**2. Do not trust the plan's port-discovery code.** It reached into aiohttp
private attributes; the tests bind to port 0 and depend on discovering the
real port, so being wrong fails every adapter test at once. The implementer
verified and used the public `AppRunner.addresses` instead. *Cost if wrong:
loud and cheap.*

**3. Substituted my own verification for a dead re-reviewer** on Task 1's fix.
The agent went idle without delivering; rather than spend a round-trip on a
3 KB diff I ran the five decode behaviours against the committed code —
executed, not read. The specific risk the re-review existed to catch was the
new `user_id` guard rejecting `listen`, which carries none; it does not.
*Cost if wrong: a validation defect reaches Task 3, where the adapter's own
tests exercise the same decoder through a real socket.*

**4. Same substitution for Task 2**, whose entire output is a package in a
virtualenv plus a paragraph of documentation. Recorded as a pattern rather
than allowed to become a habit: everything from Task 3 on carries real code
and got a real review. *Cost if wrong: an unchecked documentation paragraph.*

**5. The one-argument adapter factory stays.** An implementer worried that the
real base `__init__(config, platform)` would break `lambda cfg:
KioskAdapter(cfg)`. It does not — see the Hermes findings above. *Cost if
wrong: registration raises at gateway start, loudly, on the first run.*

**6. Task 3's review ran while Task 4 was dispatched**, both touching
`adapter.py`. Rather than risk a fix round colliding with Task 4's work, Task
3's findings went to Task 4's implementer as part of its round — same file,
same agent, one diff. *Cost if wrong: a Task 3 finding is reviewed inside Task
4's review rather than its own.*

**7. The socket-swap race was my fault, not the implementer's.** The plan's
Task 3 Step 5 carried a debugging hint: "if the replace test hangs, close the
previous socket before reassigning, not after." An implementer applied it
pre-emptively without ever seeing a hang, and it turned a race-free swap into
a racy one. The mechanism, pinned down against aiohttp 3.14.1's `web_ws.py`:
`close()` sets `.closed` **synchronously** before its own await, so a third
connection arriving mid-close sees `.closed` already True, skips closing,
writes `self._ws` — and then the earlier handler resumes and overwrites it
unconditionally. A live, connected socket ends up untracked: its messages are
still processed, but replies go out of the wrong socket. Fixed by restoring
the atomic ordering; the hint is now a dated correction in the plan rather
than deleted, because a plan is also the record of what we got wrong. *Cost if
wrong: a concurrency bug that only appears on a double-refresh, which on a
single-user kiosk is rare and silent.*

**8. Leave the work portable, not "stable on the 4090."** The user's ruling.
Push the branch, and lift the reasoning out of the git-ignored ledger — which
is what this file is.

**The test that caught the race is worth copying.** Open/closed state alone
cannot distinguish the bug, because in the broken case *both* sockets stay
open. The test tracks server-side socket creation order by identity and
asserts `self._ws` is the newest. It was run against the pre-fix code first
and failed exactly as predicted, then passed five times running.

---

## What the whole-plan review changed (2026-08-22, one fix wave)

Three of these came from reading the **real** `BasePlatformAdapter` instead of
the plugin's own no-Hermes test shim. That is the structural lesson: the shim
lets the suite run on a laptop with no Hermes, and its risk is that it can be
wrong about the real contract while every test stays green. It was.

**`send()` must return a `SendResult`.** It returned `None`. The base declares
`-> SendResult` and `_send_with_retry` reads `result.success` unguarded, so
this raised inside Hermes on **every reply** — not, as the ledger and
`docs/running-real-mode.md` both claimed, only on a client that disconnected
after `done`. Per turn it cost: FAILURE reported to `on_processing_complete`
for turns that succeeded, no delivery bookkeeping, a dead retry path, and
Hermes' own English "Sorry, I encountered an error (AttributeError)" pushed
onto the OS1 screen as a second `token`+`done` pair. Invisible only because
the frontend had already dropped its handlers. *A wrong diagnosis written into
the docs is worse than no diagnosis: it teaches the next reader to ignore the
symptom.*

**Every accepted `chat` frame now ends in exactly one `done` or one `error`.**
The review traced ten distinct ways a turn could reach nothing — an unwired
message handler (zero log output, permanently), an unauthorized user (DEBUG
only), a session-key mismatch, `hermes pause`, a socket open in Python and
dead on the wire, a `ValueError` out of `connect()`. The terminal symptom is
the same for all ten and it is not cosmetic: `wsClient.chat()` has no timeout,
`ConversationScreen` clears `busy` only in a `finally`, and the STT commit is
gated on `busy` — so a missing `done` kills **voice input** too, until a page
reload. The adapter is the layer that knows a turn was accepted, so it arms a
watchdog per turn (`SAMANTHA_KIOSK_TURN_TIMEOUT`, default **90 s**) and pushes
`error("Algo se ha quedado a medias. ¿Me lo repites?")` if nothing closed it.
90 s because a warm turn is seconds and the long tail is an agentic turn with
several tool calls; `HERMES_AGENT_TIMEOUT` (1800 s) is an idle-session reaper,
not a per-turn budget, and is the wrong number to copy. A reply that arrives
*after* the apology is dropped rather than pushed — by then the frontend may
have re-armed its handlers for the next turn, where the stray `done` would
resolve the wrong promise with the wrong text.

**`adapter_factory` is called with a `PlatformConfig`, not a dict.** Found by
running the adapter against the real gateway. `cfg.get("port", 7777)` raises
`AttributeError` on it, inside `create_adapter`'s `except Exception`, which
logs once and returns `None` — the platform never comes up and the screen is
blank. It had never fired because `os.getenv(...) or cfg.get(...)`
short-circuits, and the documented setup exports both variables. The plugin
worked *because someone remembered an env var*, which is the same shape as the
authorization bug below. `irc/adapter.py:130` reads `config.extra` for exactly
this reason.

**Authorization is code now, not a documented workaround.** `register()`
declares `allowed_users_env` / `allow_all_env` and defaults the former to
`primary`, the id `frontend/src/net/wsClient.ts:80` sends. Before, the kiosk
only answered if the operator exported the *global* `GATEWAY_ALLOWED_USERS` —
and an operator who forgot got worse than silence: with no allowlist anywhere
the unauthorized-DM default is `pair`, so Hermes greets the owner of the house
on their own screen, in English, with a pairing code. A one-entry allowlist
rather than allow-all: it reads the same today on a one-seat appliance, but it
keeps the gate a gate if a second identity ever reaches this platform.

**A missing `static_root` is fatal and non-retryable**, like the port
conflict. `add_static` raises `ValueError` on a missing directory, outside the
`try`; the gateway watcher logs that at DEBUG and retries forever on backoff —
the exact shape ruling 7's EADDRINUSE work exists to prevent, reached by the
commoner road (an unbuilt frontend). A present `assets/` with a missing
`index.html` is treated the same: it binds happily and paints a blank page off
a bare 404.

**Smaller, same theme.** `heartbeat=30` on the WebSocket, so a browser killed
without a FIN becomes a normal close instead of a sink that swallows every
reply with no log line. An `Origin` check before `prepare()` — WebSockets are
exempt from the same-origin policy, and because the newest connection wins, a
hostile local page would not merely eavesdrop, it would **evict the kiosk**. A
4000-char cap on `message`, because the socket is an unauthenticated local
listener in front of a metered LLM. `_push` returns whether the frame landed,
so `send()` can report `retryable=True` when the browser is mid-refresh and
earn the reply a free retry instead of losing it.

**Left deliberately.** No client-side timeout — defence in depth, and the
frontend belongs to plan 3c. Hermes' own error text still reaches the screen
in English when the agent itself fails; translating it means intercepting a
string the gateway composes, which is the personality task, not this one.

---

## Picking this up on another machine

The code is in git. The environment is not. A fresh machine needs:

1. Hermes 0.20.5. It will **not** pip-install — PyPI is frozen at 0.19.0 and
   lacks the contracts entirely. `git clone` + `uv sync`, and on Ubuntu their
   official installer may simply work (it does not on a Homebrew Tier-3 Mac,
   which is why this one runs from a checkout at `~/hermes-src`).
2. `loguru` and `aiohttp` installed **into Hermes' own virtualenv** —
   `uv pip install --python <hermes>/.venv/bin/python loguru aiohttp`. Hermes
   never installs declared dependencies.
3. `PYTHONPATH` carrying both `<repo>/backend` and the repo root, so the
   plugins can import `samantha.*`.
4. Both plugins symlinked into `~/.hermes/plugins/`, and the platform one
   enabled — it is opt-in. The command is
   `hermes plugins enable samantha-kiosk`, using the **hyphenated manifest
   name**, not the directory name. It writes a `plugins.enabled` entry plus an
   `entries.samantha-kiosk` block into `~/.hermes/config.yaml`. Until this is
   done the gateway serves nothing, while `hermes plugins list` still shows
   the plugin — "not enabled" there is a state, not an error.
5. `~/.hermes/config.yaml` with `tts.provider` and `tts.streaming.provider`
   set to `cosyvoice`. The default is `edge`, which is Microsoft's cloud; see
   plan 1's record and `Hermes/plugins/samantha_voice/plugin.yaml` for the
   four ways audio can still leave the house.
6. CosyVoice reachable on the 4090 at `:8093` for anything involving voice.
   Plan 3a is text only and needs none of it.

`docs/running-real-mode.md` carries the commands.
