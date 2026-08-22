# samantha-voice — decision record

**Date:** 2026-08-22
**Branch:** `samantha-on-hermes-2026-08-22`, 27 commits from 7369b7c.
Deliberately unmerged until plans 2 and 3 exist.
**Plan:** `docs/superpowers/plans/2026-08-22-samantha-voice-plugin.md`
**Design:** `docs/superpowers/specs/2026-08-22-samantha-on-hermes-design.md`

Why this file exists: the execution ledger lives in `.superpowers/`, which is
git-ignored. The measured findings were promoted into the design spec, but the
*decisions* and the reasoning behind them were not, and plans 2 and 3 are
written from them. Everything below survived at least one review; several
reversed a reviewer, and two reversed me.

---

## The five things worth knowing before touching this code

**1. The premise the plan was written on was false.** The plan said CosyVoice's
hifigan vocoder crashes on text much shorter than its reference prompt. It does
not: the server logs `this may lead to bad performance` and proceeds. Measured
against the live server, nothing between 10 and 80 characters failed in 76
calls. The real failure is content-specific and intermittent — the isolated
word "no" failed 2 of 6 attempts while `Sí.`, `Ya.` and `No, claro.` never did
— and it arrives as `peer closed connection without sending complete message
body`, an httpx transport error, not the HTTP-200-with-empty-body case
`backend/samantha/tts.py` detects. The guard still earns its place, because
merging fixes the real failure. Only the reason changed.

**2. The effective reference prompt is ~173 characters, not 130.** The server
prepends `"You are a helpful assistant.<|endofprompt|>"` to `prompt_text`
before comparing. Any "relative to the reference" arithmetic that uses the
file's own length is wrong.

**3. An `httpx.AsyncClient` may only be used on the event loop that created
it.** This cost half the voice and was invisible for most of a day. The bridge
runs each clause on a new loop in a worker thread; `tts.py` cached a client in
a module global; every clause after the first used a client whose loop was
dead. Measured: 7 of 15 clauses yielded zero bytes. After the fix — explicit
client ownership per path, leaving the FastAPI backend's shared pool intact —
0 of 15. It hid behind `provider.stream()`'s `except`, which logs "clause
failed, skipping": the policy that stops one bad clause killing a reply also
concealed a defect losing half of them. All 32 tests stayed green throughout,
because they monkeypatch a fake with no event loops.

**4. Hermes' house failure mode is silent fall-through to a default.** A plugin
that fails to load is a WARNING in a log, and then Microsoft's Edge TTS
speaking Samantha's words in a stranger's voice. A plan-2 memory provider that
fails to load means Hermes' own memory, silently, while Samantha's store goes
stale. The user ruled on 2026-08-22 that our plugins must fail loudly, with a
**pre-recorded** voice announcement — pre-recorded because a broken voice
plugin cannot announce in her voice, and using the default TTS to announce it
would mean speaking through Microsoft to say we do not want to.

**5. A dead CosyVoice produces silence, not an error.** Observed when the 4090
was powered off mid-measurement: all 15 clauses swallowed, nothing raised. On
an appliance you cannot tell thinking from dead. The whole-file path does not
have this problem — it propagates into an error envelope. The distinction to
implement is "a clause failed" versus "no clause in this entire turn produced
audio".

---

## Rulings

Numbered as in the ledger. Each says what it costs if wrong.

1-3 (pre-flight, before any task ran) — branch in place rather than a worktree,
because `backend/.venv` is ~1.9 GB with an editable install bound to this
directory. Two defects found in the plan by reading it against itself: the
bridge leaked a thread on every barge-in and its test could not detect that,
and the provider did not call `super().__init__()`.

**4. No system-modifying installers.** An implementer ran Hermes' official
`curl | bash`, which tried to brew-build LLVM and ffmpeg from source on a
Homebrew Tier-3 Mac and broke system git twice via an interrupted cleanup.
Repaired and independently verified. *Cost if wrong: none; it only slows the
dev-environment path.*

**5. Drop `--with-editable ./backend`.** The llvmlite/numba wheel failure was
ours, not Hermes' — `pipecat-ai[silero]`, which this design deletes. Pinning
around it would have been pinning to keep dead weight alive.

**6. Capture contracts from a `git clone`, no runtime.** Reading source does
not need a working install, and Hermes 0.20.5 will not pip-install at all
(PyPI is frozen at 0.19.0 and lacks the contract entirely).

**7. The Hermes checkout must live somewhere durable.** It was in `/tmp`, which
macOS purges, at 994 MB. Now `~/hermes-src`; its venv had `/private/tmp` baked
into shebangs and needed repair after the move.

**8. Re-verify the whole Corrections section, not three spot fixes.** Two of
the contract document's corrections were checked and both were fabricated —
claims that the capability map was wrong where it was right. The unchecked ones
had no earned trust. *Cost if wrong: one extra pass over a document three plans
are built on.*

**9. Finding A's root cause was my plan, not the implementer.** Task 2's
`git add` named two files and omitted the package markers its own first step
created.

**10. Fold a Low finding into an existing round** when it edits the same
docstring a Medium requires rewriting.

**11. Correct my own documents through a dispatched agent, not by editing
them.** They are what two later plans are written from; a controller edit skips
every check. That discipline is what surfaced `interrupted=True` being dead
code upstream. *Cost if wrong: three extra round-trips on documentation.*

**12. Accept not guarding the bridge's read loop.** httpx already bounds every
read at 60 s for the real client; the residual drip-feed case belongs to
`tts.py`'s timeout configuration, not to a generic adapter that should not
hardcode a value. The implementer argued this and was right.

**13. The shutdown path's worst case is ~61 s, not ~1.1 s** — `stop.set()` does
not interrupt an in-flight `await`. Not a leak: the thread always dies. Bounded
delay, deliberate, near-instant in practice because a live stream delivers the
next chunk in milliseconds.

**14. `bytes_yielded_per_clause` never resets, and that is only correct because
Hermes builds a fresh provider per speaking turn** (`tools/tts_tool.py:4069`,
called inside the speaking routine). If a future Hermes caches the streamer,
the trim points at the wrong text and corrupts Samantha's permanent memory with
no error raised. Documented in the code with the citation so it can be
re-checked on upgrade.

**15. Merge across calls with a `_pending` buffer.** The guard as designed could
never fire: Hermes calls `stream()` once per already-atomic clause, and a
one-item merge always falls through. The tail loss this introduces is not a
regression — a too-short clause was already being dropped — but see 17.

**16. Delete `safe_clauses` and its seven passing tests.** Nothing called it.
Keeping it because it was expensive to build is sunk cost, and dead code in a
plugin is worse than absent code: the next reader assumes it is the active
guard, which is exactly the mistake I made designing it.

**17. Rejected "accepted trade-off" on the unclosed-tag hold.** An unclosed
`<laughter>` silenced the rest of the turn. A dropped laugh is a blemish;
stopping mid-reply reads as a crash. Capped the buffer at 400 characters so the
blast radius returns to one clause.

**18. Rejected putting pyenv's entire site-packages on PYTHONPATH** to satisfy
a missing dependency. It shadows Hermes' own packages with another Python's.
The answer is to install into Hermes' venv, and for plans 2 and 3 to declare
`python_dependencies` in the manifest. **PYTHONPATH alone is not enough: our
code's dependencies must exist in Hermes' environment.** `httpx` was already
there; `loguru` was not; plan 2 will need chromadb, fastembed and numpy.

**19. Fixed the stale-loop bug despite the fix budget being spent.** That
budget exists to stop review loops spinning, not to ship a voice that drops
half its sentences.

**And one I got wrong.** I parked a test as "redundant"; the final review
defended it. It is the only artifact recording that `[laughter]` deliberately
stays out of the hold condition, and it fails in one second anyone who
"improves" that. The reviewer was right.

---

## For plans 2 and 3

- **Two registration idioms coexist in this package and one is invisible** —
  import side effect in `provider.py`, `ctx.register_tts_provider` callback in
  `__init__.py`. A module `__init__.py` does not import will silently never
  register. Write the rule down in the package.
- **`bytes_yielded_per_clause`'s keys are not the assistant's text.** They are
  markdown-stripped by Hermes, merged with an inserted space, and a stranded
  tail is absent entirely. Plan 3 cannot reconstruct "what was spoken" by
  concatenation or substring match.
- **Trim granularity is the merged clause, not the clause.** Design §6 promises
  clause granularity; buffering makes it up to `MAX_PENDING_CHARS`. Correct §6
  before plan 3 is written against it.
- **Bytes yielded ≠ bytes heard.** The speaker path prefetches up to three
  sentences ahead of playback.
- **Hermes already ships a web dashboard** (`hermes_cli/web_server.py`, ~19k
  lines, WebSocket, audio, and it calls `resolve_streaming_provider`). That is
  close to plan 3's brief. Read it before writing plan 3 — but weigh that
  depending on 19k lines of someone's internals is far more fragile than the
  documented platform-adapter contract, and that the OS1 interface is the
  product and must not be made to look like Hermes.
