# The name goes — removing "samantha" from everything that runs

> **Status:** design, agreed with the user 2026-09-03. It **reverses**
> the naming half of §12's 2026-08-23 entry ("the name is only changed
> in prose") and completes the concept rename of 2026-08-28.
>
> **Short by intention.** Four scope decisions were taken before it was
> written and no design questions remain; what this document is for is
> the ORDER, the exclusions, and the six traps that a mechanical rename
> walks into. It is a runbook, not an architecture.

## What was decided

1. **Everything** — packages, plugins, systemd units, environment
   variables and `~/.samantha`. No `samantha` survives in anything that
   runs.
2. **`backend/` and `frontend/` are buried, not renamed.** The only
   live module in them is `samantha.tts`, which the widget imports over
   `PYTHONPATH` to reach CosyVoice. It moves into `widget/`; the rest
   goes. This finally closes "plan 3", parked since 2026-08-22, and
   removes 165 occurrences by deletion rather than by renaming code
   that was already condemned.
3. **The repository is renamed too**, `os1-samantha` → `os1-jarvis`,
   local directory and GitHub remote.
4. **Clean cut.** No compatibility aliases: `SAMANTHA_*` and
   `samantha-*.service` stop existing the same day. Anything outside
   this repo that used them breaks, and that is accepted.

## What is NOT renamed, and why

**History is not rewritten.** CLAUDE.md §10 already fixes this rule for
the 2026-08-28 rename: the plans and specs under `docs/superpowers/`
still say `samantha_kiosk` *"because they are the record of the day
they were written"*. The same holds here. Excluded from every
substitution:

- `docs/superpowers/specs/` and `docs/superpowers/plans/` — the record.
- `PROGRESS.md` and CLAUDE.md's §12 entries — likewise. New entries
  describe the rename; old ones keep their words.
- `.hermes/src/` — vendored Hermes, not ours.
- `~/.samantha/dump*`, `code-live.log` — captured artefacts.

CLAUDE.md's §0-§11 ARE updated, because they describe what runs.

## The order, and why it is this one

Each layer leaves the system startable. The order is chosen so that no
step depends on a later one.

1. **Bury `backend/` and `frontend/`.** Move the one live module to
   `widget/samantha_widget/tts.py` (its final name settles in step 2),
   drop `backend/` from the widget's `PYTHONPATH` everywhere it
   appears, delete both trees.
2. **The widget package.** `widget/samantha_widget/` →
   `widget/jarvis_widget/`, and `SAMANTHA_WIDGET_*` → `JARVIS_WIDGET_*`.
3. **The Hermes plugins.** `samantha_vision|voice|code` →
   `jarvis_vision|voice|code`, their manifest ids `samantha-*` →
   `jarvis-*`, the symlinks under `.hermes/home/plugins/`, the two
   loops in `setup-runtime.sh`, and `plugins.enabled` in both the
   tracked and the live config.
4. **The systemd units.** `samantha-*.service` → `jarvis-*.service`.
   Disable the old, install the new, enable, restart — in that order,
   or he stops starting at login.
5. **The data directory.** `~/.samantha` → `~/.jarvis`, by `mv`.
6. **The repository.** Renamed on GitHub by the user, then locally.

## The six traps

Each of these is silent, and each would leave something that looks
healthy and is not.

1. **Substitution order.** Longest first: `samantha_widget` before
   `samantha_vision` before `samantha`. A bare `samantha` pass run
   first mangles every longer name into `jarvis_widget` fragments.
2. **The venvs carry absolute paths.** `widget/.venv/bin/pytest` reads
   `#!/home/nexus/git/os1-samantha/widget/.venv/bin/python3`. Renaming
   the repo breaks every console script in all three venvs
   (`widget/`, `.hermes/src/`, `Hermes/bridges/code-a2a/`). They are
   recreated after step 6, not patched — a rewritten shebang in a venv
   whose `pyvenv.cfg` still points elsewhere is a worse state than a
   missing one.
3. **CosyVoice's container mounts both paths.** `~/.samantha/cosyvoice3`,
   `~/.samantha/voices/ref` and
   `/home/nexus/git/os1-samantha/tts-server/cosyvoice/server.py` are
   bind mounts. The container must be recreated (`down` then `up`), not
   restarted, or it keeps the old paths and CosyVoice serves from a
   directory that no longer exists.
4. **The iPhone CA must be MOVED, never regenerated.** `~/.samantha/certs`
   holds a CA installed as a system root on three iPhones.
   `ensure_certificate` reuses what it finds — so a `mv` preserves it
   and a fresh directory silently mints a new one, which costs
   re-enrolling three phones by hand (§12, 2026-09-01).
5. **`plugins.enabled` is a list, and `apply-config.sh` replaces lists
   wholesale.** The tracked config must carry the new ids before the
   live config is re-applied, or the gateway loads nothing.
6. **`voices/ref/samantha.wav` is data, not code.** It is the clip his
   voice is cloned from. Renaming the file means updating whatever
   points at it in the same commit; leaving it named as it is means the
   name survives in the one place nobody greps. It is renamed, and the
   reference updated.

## What the user does, and when

- **Between steps 5 and 6:** rename the repository on GitHub. Only they
  can. GitHub redirects the old name, so nothing breaks at the instant
  it happens.
- **After step 6:** nothing. The venvs are rebuilt and the services
  restarted by the runbook.

## Verification

The suites are the net for anything importable: 413 widget tests and
200 plugin tests, green after every step. They do NOT cover the units,
the symlinks, the container mounts or the data directory, so each of
those is checked live, the way the teacher mode's own gaps were on
2026-09-03:

- `systemctl --user is-active` on all four units.
- The strip on screen, photographed, and `xwininfo -name JARVIS`.
- `Hermes/run-gateway.sh plugins list` shows four `jarvis-*` plugins.
- A spoken turn answered out loud — the only check that exercises
  llama-server, CosyVoice, Whisper and the gateway at once.
- `git grep -i samantha` returns only the excluded history.

## Cost, stated

- **Anything outside this repo that names him breaks**: scripts,
  aliases, cron entries, the phone bookmarks' hostname if it changes.
  That is what a clean cut means and it was chosen with that said.
- **~9 GB of model data moves**, instantly (same filesystem) but not
  atomically with the config that points at it: between the `mv` and
  the restart, CosyVoice is broken. The window is seconds and the
  runbook closes it in one step.
- **Three venvs are rebuilt**, which costs a few minutes and a network
  download.
- **The old name survives in the history**, deliberately, and a reader
  of `PROGRESS.md` will meet it constantly. §10's glossary line is
  extended to say so rather than pretending otherwise.
