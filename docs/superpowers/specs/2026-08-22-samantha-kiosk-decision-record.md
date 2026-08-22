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
   enabled — it is opt-in.
5. `~/.hermes/config.yaml` with `tts.provider` and `tts.streaming.provider`
   set to `cosyvoice`. The default is `edge`, which is Microsoft's cloud; see
   plan 1's record and `Hermes/plugins/samantha_voice/plugin.yaml` for the
   four ways audio can still leave the house.
6. CosyVoice reachable on the 4090 at `:8093` for anything involving voice.
   Plan 3a is text only and needs none of it.

`docs/running-real-mode.md` carries the commands.
