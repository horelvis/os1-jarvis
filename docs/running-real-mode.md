# Running Samantha in real mode

> **Status: verified 2026-08-07** on the dev Mac against a separate GPU box;
> re-verified 2026-08-22 with everything — backend, GPU, container and Hermes
> — on a single machine, which is how it runs now. This describes how startup
> works *today*. It is
> expected to change — Phase 11 moves the voice loop server-side, and the
> improvement sweep on `improvement-sweep-2026-08-04` is still in flight.
> Anything below marked **measured** was observed directly; anything marked
> **unverified** was not exercised.

## What has to be running

Samantha in real mode is three moving parts, only one of which is the backend
itself.

| Piece | Where | Required for | Started how |
|---|---|---|---|
| FastAPI backend | `127.0.0.1:7777` | everything | `python -m samantha.api` |
| CosyVoice 3 | same box, `:8093` | any speech output | `docker compose up -d` |
| LLM | X.AI Grok API (default) | conversation | nothing to start — it's a remote API |

Two things you do **not** need for a normal run:

- **llama-server** (`:8000`) is the *alternative* to the Grok API,
  not a companion to it. Start it only if you want a fully local LLM; then
  point `SAMANTHA_LLM_SERVER_URL` at it and leave the API key empty.
- **hermes-agent** (`:8642`) is only used when `llm_provider=hermes`. The
  default is `openai`, so leave it down.

## The env-var trap

`~/.samantha/.env` exists and holds the xAI credential as **`XAI_API_KEY`**.

Two independent problems with that, both **measured**:

1. **Nothing loads that file.** `config.py` reads environment variables only
   (`os.environ.get(f"SAMANTHA_{key}")`, `config.py:114`). There is no
   `python-dotenv` anywhere in the project. The file is inert unless you
   source it yourself.
2. **The name doesn't match.** The backend reads `SAMANTHA_LLM_API_KEY`
   (`config.py:130`), not `XAI_API_KEY`.

Symptom when this bites: `real_llm.py:220` only attaches the `Authorization`
header when the key is non-empty, so the request goes out unauthenticated,
x.ai rejects it, and the browser shows *"Se me ha ido el hilo. ¿Me lo dices
otra vez?"*. The backend is fine; it simply has no credential.

Until this is reconciled, bridge it at launch:

```bash
export SAMANTHA_LLM_API_KEY=$(grep '^XAI_API_KEY=' ~/.samantha/.env | cut -d= -f2- | tr -d '"'"'"'"'"'"'"'"')
```

## Startup sequence

**1. CosyVoice on the 4090** (skip if you only want text chat):

```bash
cd <repo>/tts-server/cosyvoice
docker compose up -d
docker compose logs -f cosyvoice
```

Wait for `Uvicorn running on http://0.0.0.0:50000`. The healthcheck allows a
120 s `start_period` because model load is slow; a first-time `docker compose
build` is 10–15 min. Requires `~/.samantha/cosyvoice3` (weights, ~2 GB) and
`~/.samantha/voices/ref/samantha.wav` present **on that host**.

**2. Backend on the Mac:**

```bash
cd backend
export SAMANTHA_MODE=real
export SAMANTHA_LLM_API_KEY=<see the env-var trap above>
.venv/bin/python -m samantha.api
```

Binds `127.0.0.1:7777` (from `config.host`/`config.port`). It serves both the
API and the built frontend, so `http://localhost:7777/` is the whole app.

**Ready check — poll, do not sleep.** First start loads the fastembed model;
a fixed `sleep` will race it and give you a misleading empty response:

```bash
until curl -fsS http://127.0.0.1:7777/ping >/dev/null 2>&1; do sleep 1; done
```

**Measured:** ~7 s to first `200` on a warm model cache.

**3. Frontend.** Already built into `frontend/dist/` and served by the backend
— nothing else to run. For UI work with hot reload instead:

```bash
cd frontend && pnpm dev     # :5173, proxies /chat /speak /ping /profile /ws to :7777
```

Never `npm` here — pnpm only.

## Verifying it actually works

Each of these was **measured** on 2026-08-07.

```bash
curl -s http://127.0.0.1:7777/ping
# {"status":"ok","version":"0.1.0","mode":"real","has_profile":true}
```

`mode` must read `real`. `has_profile: true` means the store is paired and the
UI will boot straight to **ambient**, not onboarding.

```bash
curl -s http://127.0.0.1:7777/profile | head -c 200
# {"name":"Hore","onboarding_completed_at":1778679577,"answers":[...]}
```

Speech — use a **long** sentence deliberately (see gotchas):

```bash
curl -s -X POST http://127.0.0.1:7777/speak \
  -H "Content-Type: application/json" \
  -d '{"text":"Hoy he estado pensando en lo que me contaste el otro día, y se me ha quedado dando vueltas toda la tarde."}' \
  -o /tmp/speak.pcm -w "%{http_code} %{size_download}B %{time_total}s\n"
```

Expect `200`, `content-type: audio/pcm`, chunked. **Measured:** 336 000 bytes
= 7.00 s of 24 kHz mono int16 in 4.4 s wall clock; peak 31132/32767, RMS 5234.
A `200` alone proves nothing — a silent buffer looks identical at the HTTP
layer, so check the amplitude if you are debugging.

## Known gotchas

**A dead CosyVoice does not fail fast.** `tts.is_available()` (`tts.py:78-84`)
only checks that the URL is configured and the two reference files exist on
disk — it never probes the network. With the container down it still returns
`True`, so `/speak` skips its 503 path and sits in `client.stream()` against a
dead host for up to **60 s** (all four httpx timeout legs use
`tts_cosyvoice_timeout_s`) before failing as a 500. The user-visible symptom
is Samantha freezing for a minute rather than erroring. Not yet fixed.

**Text normalization is degraded.** CosyVoice logs
`no frontend is avaliable` at startup because modelscope returns 403 for
`pengzhendong/wetext` (no auth token). Synthesis works, but numbers,
abbreviations and symbols are not expanded — expect "2026", "Dr.", "%" to be
read oddly. **Measured** at container start.

**Short text degrades quality; isolated single words sometimes fail.**
CosyVoice zero-shot conditions on the reference transcript (~130 chars, ~173
once the server prepends its own prefix). When `tts_text` is much shorter the
server logs "this may lead to bad performance" and returns audio anyway — it
does **not** crash (an earlier version of this document said hifigan crashed;
measurement on 2026-08-22 disproved it). What does fail is an isolated
one-or-two-word utterance, intermittently and content-specifically: `'No.'`
failed 2 of 6 calls and bare `'No'` 1 of 6, while `'Sí.'`, `'Ya.'` and
`'No, claro.'` never failed in 6 each, and nothing between 10 and 80 chars
failed in 76 calls. The failure arrives as `peer closed connection without
sending complete message body` (an httpx `RemoteProtocolError`), not as the
empty-body case. Use whole sentences when testing by hand.

**Time-to-first-audio is the whole reply.** The CosyVoice log shows a single
`yield speech len 7.0` — audio is delivered in one piece at the end, not
progressively, so chunked transfer buys nothing. **Measured:** rtf 0.27,
3.85 s GPU time for 7 s of speech, ~0.5 s backend+network overhead on top.
In conversation that latency stacks on top of the LLM's, so expect several
seconds of silence per turn until sentence-level flushing lands.

## Testing against the real memory store

The backend defaults to `~/.samantha/memory` — the **real** store (263
long-term chunks as of 2026-08-07). Memory is append-only by design; Samantha
never forgets. Every test turn is written there permanently.

To exercise the full path without polluting it:

```bash
export SAMANTHA_MEMORY_PERSIST_DIR=/tmp/samantha-test-memory
```

The trade-off is that you lose recall against the real history, which is
often the thing you actually want to test. Decide per session.

To test **onboarding**, the profile must be absent — the app boots to ambient
whenever a profile exists. `DELETE /profile` clears the name and the
onboarding marker (the six answer chunks survive; nothing is truly deleted).
That endpoint is currently unauthenticated; the improvement sweep puts it
behind `SAMANTHA_ADMIN_TOKEN`.

## Moving Samantha to another machine

Cloning the repo is not enough. Two things live outside git in
`~/.samantha/`, and without them nothing works — one of them is
irreplaceable.

**Her voice — `~/.samantha/voices/ref/`.** Two files: `samantha.wav`
(~384 KB, the zero-shot reference CosyVoice clones from) and
`samantha.txt` (133 bytes, its transcript, which is sent on every
synthesis call for prosodic conditioning). Without both,
`tts.is_available()` returns False, so `resolve_streaming_provider`
never selects our provider at all and Hermes falls through to its
default — which is Edge TTS, Microsoft's cloud. The failure is silent:
you get a voice, just not hers.

**Her memory — `~/.samantha/memory/`.** About 2.4 MB: the ChromaDB
store and the SQLite ring buffer. Her name, the onboarding answers, and
every conversation you have had. The store is append-only by design and
there is no export path — this directory *is* the record. **Copy it
before anything else, and keep a copy.** Losing it is losing her, and
nothing in the repository can rebuild it.

**Also worth copying, but regenerable:**
`~/.samantha/voices/announcements/sin-voz.pcm` — the pre-recorded clip
she plays when synthesis is unreachable (see
`Hermes/plugins/samantha_voice/announce.py`, whose docstring carries the
one-command recipe to record it again).

**Do not copy** `~/.samantha/qwen3-tts/` (~6.5 GB). It is a model from
the abandoned vllm-omni path and nothing reads it.

```bash
# on the old machine
tar czf samantha-state.tgz -C ~ .samantha/voices/ref .samantha/memory \
    .samantha/voices/announcements

# on the new one
tar xzf samantha-state.tgz -C ~
ls ~/.samantha/voices/ref/samantha.wav ~/.samantha/memory
```

`~/.samantha/.env` is not in that list on purpose: it holds API keys.
Move it deliberately, by hand, or set the variables fresh on the new
machine.

## Installing Hermes (inside the project)

**Status: verified 2026-08-22** on the 4090 box (Linux). Hermes lives *in the
repo* as of that date. One command installs it:

```bash
Hermes/setup-runtime.sh
```

It clones `hermes-agent` into `.hermes/src` at the commit this project is
written against, builds its venv on Python 3.11, installs the three
dependencies Hermes declares but never installs (`loguru`, `httpx`,
`aiohttp`), creates `.hermes/home` as HERMES_HOME with the two plugins
symlinked in, and enables both. It is idempotent — re-run it after moving the
pin. `.hermes/` is gitignored; the pin itself lives in the script.

The pin is `v2026.8.19` = commit `fcbd1076a93841fa88855acce810e342a5b78101`,
whose `pyproject.toml` reads `0.20.5`. Note that `git ls-remote --tags` prints
the *annotated tag object's* hash (`b05e680e…`), not the commit — ask for
`"v2026.8.19^{}"` to get the one above.

Run it through the wrapper, never a bare `hermes`:

```bash
Hermes/run-gateway.sh                 # starts the gateway
Hermes/run-gateway.sh --version       # v0.20.5 (2026.8.19), install dir in-repo
Hermes/run-gateway.sh plugins list    # both samantha-* reading "enabled"
```

The wrapper exports `HERMES_HOME=.hermes/home` and
`PYTHONPATH=<repo>/backend:<repo>`. Both are load-bearing: without the first,
Hermes reads whatever personal `~/.hermes` the machine's owner has (a
different version, a shared `state.db`); without the second, the plugins
cannot import `samantha.tts` and Hermes logs a warning and carries on with
the whole-file path falling through to Edge TTS.

**`samantha` importable inside a plugin — RESOLVED.** An earlier version of
this document left this open. `PYTHONPATH` was indeed the answer, and
`run-gateway.sh` is where it now lives. **Measured 2026-08-22:**
`Hermes/run-gateway.sh plugins doctor samantha_voice` prints a
`samantha.config` log line and then "runtime discovery, manifest parsing,
import, and registration passed".

Two naming traps, both measured:

- `plugins enable` / `plugins list` take the **kebab-case manifest name**
  (`samantha-voice`); `plugins doctor` takes the **snake_case directory name**
  (`samantha_voice`) and answers `not found` for the other.
- `plugins enable` prompts for tool-override capability. `--no-allow-tool-override`
  answers "no" without a prompt, which is what both plugins declare.

**What is NOT touched:** the machine owner's `~/.hermes`, their
`~/.local/bin/hermes`, and any gateway already running under them. Samantha's
Hermes and the owner's are separate installs with separate state.

**Do not** `uv tool install hermes-agent` — PyPI is stuck on a stale `0.19.0`
that predates the streaming-TTS module, and Hermes' own build backend blocks
installing from a git URL. And avoid the shell installer (`install.sh`)
entirely: it builds Node, ripgrep and ffmpeg via the system package manager.

`uv` must be recent enough to parse Hermes' `uv.lock`; 0.8.15 cannot. Run
`uv self update` first (0.12.5 verified working).

## Kiosk (OS1 interface served through the Hermes gateway)

**Status: verified 2026-08-22**, dev Mac. This is the plan-3/text-only path:
the OS1 frontend is served by the `samantha-kiosk` Hermes plugin
(`Hermes/plugins/samantha_kiosk/`) instead of the FastAPI backend, and the
one WebSocket the kiosk holds is dispatched into Hermes' own agent, not into
`backend/samantha/real_llm.py`. No audio is involved — that's plan 3b. The
existing FastAPI backend (§ above) is untouched by any of this and can run
at the same time on a different port.

**1. Build the frontend** — pnpm only, never npm (CLAUDE.md §5):

```bash
cd frontend && pnpm install && pnpm build && cd ..
ls frontend/dist/index.html
```

**2. Enable the plugin.** Unlike `samantha-voice`, `kind: platform` plugins
are opt-in and the manifest name is kebab-case (`samantha-kiosk`) even
though the directory is snake_case (`samantha_kiosk`). `hermes plugins list`
shows it as `not enabled` until you run:

```bash
Hermes/run-gateway.sh plugins enable samantha-kiosk --no-allow-tool-override
```

`--no-allow-tool-override` declines the tool-override capability without a
prompt, matching `samantha-voice`'s `allow_tool_override: false`. This writes
to `.hermes/home/config.yaml`'s `plugins.enabled` list — the repo's own
HERMES_HOME, not the machine owner's. `Hermes/setup-runtime.sh` already does
this, so it is normally not needed at all. `hermes plugins doctor samantha_kiosk` confirms
runtime discovery/import/registration but does **not** confirm enablement —
only `hermes plugins list` shows enabled/not-enabled state.

**3. Environment and start command:**

```bash
export SAMANTHA_KIOSK_STATIC_ROOT="$(pwd)/frontend/dist"   # default: frontend/dist
export SAMANTHA_KIOSK_PORT=7777                             # default: 7777
# run-gateway.sh exports PYTHONPATH and HERMES_HOME itself.
Hermes/run-gateway.sh
```

Expected in the log: `samantha-kiosk: serving <dist-path> on :7777`.

**User authorization — no longer an exported variable.** Hermes
default-denies any platform it has no allowlist for, so the first version of
this plugin only answered if you remembered to export the *global*
`GATEWAY_ALLOWED_USERS=primary` by hand. That is fixed in code:
`register()` declares `allowed_users_env="SAMANTHA_KIOSK_ALLOWED_USERS"` and
`allow_all_env="SAMANTHA_KIOSK_ALLOW_ALL_USERS"`, and defaults the former to
`primary` — the `user_id` the frontend sends
(`frontend/src/net/wsClient.ts:80`). **Measured** on Hermes 0.20.5 with every
allowlist variable unset: `_is_user_authorized` returns True for `primary`
and False for anything else. A fresh install needs no authorization
environment at all.

Set `SAMANTHA_KIOSK_ALLOWED_USERS` only to change *which* id may talk; it is
scoped to the kiosk, unlike `GATEWAY_ALLOWED_USERS`, which authorizes that id
on every platform the gateway has enabled, now and in future.

Why this mattered more than a dropped message: with **no** allowlist anywhere,
the unauthorized-DM default is `pair`, and Hermes answers the owner of the
house on their own OS1 screen, in English, with a pairing code.

**4. Verifying the round trip** (done here with a raw `aiohttp` WebSocket
client rather than a browser — this session has no way to open one):

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:7777/            # 200, OS1 index.html
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:7777/assets/<name>.js   # 200 — the exact file index.html references
```

WebSocket, connecting to `ws://localhost:7777/ws` and sending
`{"type":"chat","message":"Hola, ¿qué tal estás?","user_id":"primary"}`:

```
{"type": "token", "token": "Sigo bien. Si me oyes, dime algo más, lo que sea."}
{"type": "done", "thinking_ms": 0}
```

**Measured caveat:** the reply comes from Hermes' stock `SOUL.md`
persona ("Eres Hermes Agent..."), not from Samantha's personality
(`backend/samantha/personality.py`) — one reply during testing literally
opened with "Soy Hermes, tu asistente." The kiosk plugin routes text into
Hermes' own agent loop, not into `real_llm.py`/Grok. Wiring Samantha's
voice into that loop (system prompt, memory) is not part of this plan;
tasks 1–4 only proved the transport. Whoever picks up personality
integration should start there.

Refresh behavior (close the socket, open a new one, send again) was also
verified — two throwaway sockets opened and closed, then a third socket on
the same `user_id` still got a normal reply (`"Sí, sigo aquí. El refresco
no me ha borrado. ¿Qué necesitas?"`). The `/platform resume samantha_kiosk`
command mentioned in the adapter's source exists for the port-conflict case,
not for this.

**Three failure signatures**, from the plan brief plus the one found above:

- **The interface loads but nothing comes back.** This can no longer hang
  forever: every accepted `chat` frame now ends in exactly one `done` or one
  `error`, and after `SAMANTHA_KIOSK_TURN_TIMEOUT` seconds (default 90) the
  kiosk says *"Algo se ha quedado a medias. ¿Me lo repites?"* on screen and
  logs `samantha-kiosk: no reply within 90s for turn <id>`. That log line is
  the cue to look at the gateway log for the real cause — `Unauthorized user:
  ... on samantha_kiosk`, a session-key mismatch, an unwired message handler,
  or a dispatch error.
- **A blank page.** `SAMANTHA_KIOSK_STATIC_ROOT` is wrong, or `pnpm build`
  was not run. Confirm with the two `curl` checks in step 4 above — a 404
  on the JS/CSS asset (not just `/`) is the same failure and easier to miss
  by eye, since the page still paints a blank body successfully.
- **The reply arrives all at once rather than streaming.** Expected for
  this plan. `send()` delivers the finished reply as a single `token`
  frame; token-level streaming is plan 3b.

**Correction — the `'NoneType' object has no attribute 'success'` line was
NOT log noise.** An earlier version of this document said it fired only when
a client disconnected right after `done`. That diagnosis was wrong. `send()`
returned `None` while `BasePlatformAdapter.send` is declared `-> SendResult`
and `_send_with_retry` reads `result.success` with no guard
(`gateway/platforms/base.py:5558`), so it raised on **every single reply**.
It looked harmless only because `send()` writes both frames before it
returns, so the reply was already on the wire when the exception fired.

What it actually cost, per turn: `_process_message_background` aborted into
its `except BaseException`, so `on_processing_complete` reported FAILURE for
turns that had succeeded; `_record_delivery` never ran, so delivery
bookkeeping was uniformly wrong; the retry and plain-text-fallback paths were
dead code; and Hermes' own error handler then pushed
`"Sorry, I encountered an error (AttributeError)… use /reset"` to the OS1
screen as a second `token`+`done` pair, in English. That last one was
invisible only by luck — the frontend deletes its handlers in the `done`
handler, so the stale pair arrived with nobody listening.

`send()` now returns a real `SendResult`. **Measured** against the real base
class on Hermes 0.20.5: `_send_with_retry(chat_id="kiosk", content="hola")`
returns `SendResult(success=True)` and the browser gets exactly one
`token`+`done`.

Port conflict: if `SAMANTHA_KIOSK_PORT` collides with a running FastAPI
backend, the plugin fails fast (per the fix landing in `adapter.py` during
this work) rather than silently binding — use a different port on either
side; this plan does not remove the FastAPI backend.

## Not verified

- Whether Chromium's Web Speech API (the STT path) can reach Google's servers
  from this machine — never exercised.
- A full browser round trip: mic → transcript → LLM → speech.
- The kiosk's actual browser rendering — the WebSocket/HTTP checks above were
  run from a raw client, not Chromium; `http://localhost:7777/` was never
  opened in an actual browser during this work.
- The exact HTTP status x.ai returns for an unauthenticated request (inferred
  as 401, never sent).
- Anything on the kiosk box itself; this covers the Mac + 4090 dev setup only.
