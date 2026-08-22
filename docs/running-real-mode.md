# Running Samantha in real mode

> **Status: verified 2026-08-07** on the dev Mac (192.168.100.19) against the
> 4090 box (192.168.100.58). This describes how startup works *today*. It is
> expected to change — Phase 11 moves the voice loop server-side, and the
> improvement sweep on `improvement-sweep-2026-08-04` is still in flight.
> Anything below marked **measured** was observed directly; anything marked
> **unverified** was not exercised.

## What has to be running

Samantha in real mode is three moving parts, only one of which is the backend
itself.

| Piece | Where | Required for | Started how |
|---|---|---|---|
| FastAPI backend | dev Mac, `127.0.0.1:7777` | everything | `python -m samantha.api` |
| CosyVoice 3 | 4090 box, `:8093` | any speech output | `docker compose up -d` |
| LLM | X.AI Grok API (default) | conversation | nothing to start — it's a remote API |

Two things you do **not** need for a normal run:

- **llama-server** (`:8000` on the 4090) is the *alternative* to the Grok API,
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

## Installing Hermes locally (for the plugin work)

**Status: verified 2026-08-22**, dev Mac (Intel, macOS Ventura 13.5).
Full captured contracts:
[`docs/superpowers/specs/hermes-contracts-v0.20.5.md`](superpowers/specs/hermes-contracts-v0.20.5.md).

Do **not** `uv tool install hermes-agent` — PyPI is stuck at a stale
`0.19.0` that predates the streaming-TTS module this project needs, and
`uv tool install` from a git URL is explicitly blocked by Hermes' own
build backend ("Hermes is distributed via the shell installer, Docker
image, or Nix"). Use the developer path Hermes' own error message
recommends instead:

```bash
git clone https://github.com/NousResearch/hermes-agent.git ~/hermes-src
cd ~/hermes-src
git checkout <pinned-commit>          # v2026.8.19 / pyproject 0.20.5 as of 2026-08-22
```

That's enough to read source (what Task 1 needed). If you also want a
runtime — `hermes --version`, `hermes plugins list` — `uv sync --python
3.11` builds one (needs `uv self update` first; 0.8.15 can't parse this
repo's `pyproject.toml`/`uv.lock`). **Do not** add `--with-editable
<repo>/backend` to get `samantha` importable inside it — that pulls in
`backend`'s `pipecat-ai[silero]` dependency, which drags in `numba`,
which on Intel Mac resolves to an `llvmlite` version with no `x86_64`
wheel and tries to build LLVM from source. That's not a Hermes problem;
`pipecat-ai` itself is dead weight from an abandoned approach this
project is dropping, so don't pin around it — just don't combine the
two environments.

**Getting `samantha` importable inside a Hermes plugin environment is
UNRESOLVED.** The cheap workaround, confirmed from the repo's own venv
without touching Hermes at all:

```bash
PYTHONPATH="<repo>/backend" backend/.venv/bin/python -c \
  "import samantha.tts; print(samantha.tts.OUTPUT_SAMPLE_RATE)"   # 24000
```

`PYTHONPATH` is the likely answer for the real plugin runtime too — a
plugin under `~/.hermes/plugins/samantha_voice/` presumably needs
`sys.path` or `PYTHONPATH` pointed at `<repo>/backend` at plugin load
time, not a `pip install -e` merge of the two dependency trees. Whoever
picks up the plugin task should settle this properly; it wasn't chased
further here.

Avoid the shell installer (`install.sh`) entirely on a daily-driver
machine — it builds Node.js, ripgrep, and ffmpeg via Homebrew, and on a
Tier-3 Homebrew platform (no bottles) that means compiling LLVM/ffmpeg
from source. Attempting it here ran 20+ minutes without finishing,
nearly filled the disk, and twice broke system `git` when the runaway
background build was killed mid-cleanup (repaired both times). The
plain `git clone` above is the only install step this project should
run against this machine; nothing that writes outside the repo or
scratch, no `brew`, no `curl | bash`.

Verify a Hermes runtime, if you built one via `uv sync`:

```bash
.venv/bin/hermes --version         # Hermes Agent v0.20.5 (2026.8.19)
.venv/bin/hermes plugins list      # NOT bare `hermes plugins` — that opens an interactive TUI
```

### Hermes plugin dependencies (manual install)

Hermes parses `python_dependencies` declared in plugin manifests but does
**not** install them automatically — it only warns when one is missing, and
the plugin still appears as "enabled" in `hermes plugins list` (which reads
the manifest file only, never probes the runtime). Missing imports fail at
runtime with `ModuleNotFoundError`.

**Install manually into the Hermes venv** before running a plugin that needs
them. The form is:

```bash
cd ~/hermes-src
uv pip install --python .venv/bin/python <package> [<package> ...]
```

Packages needed so far:
- `loguru` (already installed in venv)
- `aiohttp` (version 3.14.3, installed 2026-08-22)

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
~/hermes-src/.venv/bin/hermes plugins enable samantha-kiosk
```

It prompts to grant tool-override capability — decline (`n`/Enter), same as
`samantha-voice`'s `allow_tool_override: false`. This writes to
`~/.hermes/config.yaml`'s `plugins.enabled` list; it's a one-time step per
machine, not per session. `hermes plugins doctor samantha_kiosk` confirms
runtime discovery/import/registration but does **not** confirm enablement —
only `hermes plugins list` shows enabled/not-enabled state.

**3. Environment and start command:**

```bash
export SAMANTHA_KIOSK_STATIC_ROOT="$(pwd)/frontend/dist"   # default: frontend/dist
export SAMANTHA_KIOSK_PORT=7777                             # default: 7777
export PYTHONPATH="$(pwd)/backend:$(pwd)"                   # samantha.* imports
~/hermes-src/.venv/bin/hermes gateway
```

Expected in the log: `samantha-kiosk: serving <dist-path> on :7777`.

**Undocumented-by-the-plan fourth requirement — user authorization.** The
kiosk plugin registers as a generic Hermes platform (`Platform("samantha_kiosk")`)
and does not declare its own `allowed_users_env`/`allow_all_env`, so the
gateway's default-deny authz gate applies. Without an allowlist, every chat
message is silently dropped with `Unauthorized user: primary (primary) on
samantha_kiosk` in the gateway log and the WebSocket client hangs forever —
no `error` frame, no closed socket, nothing. **Measured**: a raw WS client
sending `{"type":"chat","message":"...","user_id":"primary"}` got zero
frames back until this was set. Fix — also export before `hermes gateway`:

```bash
export GATEWAY_ALLOWED_USERS=primary   # must match the `user_id` field the kiosk sends
```

(`GATEWAY_ALLOW_ALL_USERS=true` also works and is what the "no allowlist
configured" warning at gateway startup suggests, but it's global across
every platform Hermes has enabled, not scoped to the kiosk — prefer the
allowlist form for a dev box that might grow other plugins later.)

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

**Measured caveat:** the reply comes from Hermes' stock `~/.hermes/SOUL.md`
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

- **The interface loads but nothing comes back.** The WebSocket connected
  but dispatch didn't. Check the gateway log for `handle_message`. If
  instead you see `Unauthorized user: ... on samantha_kiosk`, it's the
  authz gap above, not a dispatch bug — set `GATEWAY_ALLOWED_USERS`.
- **A blank page.** `SAMANTHA_KIOSK_STATIC_ROOT` is wrong, or `pnpm build`
  was not run. Confirm with the two `curl` checks in step 4 above — a 404
  on the JS/CSS asset (not just `/`) is the same failure and easier to miss
  by eye, since the page still paints a blank body successfully.
- **The reply arrives all at once rather than streaming.** Expected for
  this plan. `send()` delivers the finished reply as a single `token`
  frame; token-level streaming is plan 3b.

**Known log noise, not a failure:** if the WebSocket client disconnects
right after receiving `done` (a raw test client does this; a real browser
tab sitting open does not), the gateway can log one
`[samantha_kiosk] Error handling message: 'NoneType' object has no
attribute 'success'` from `gateway/platforms/base.py:_send_with_retry` —
it's a redundant delivery attempt finding nobody connected. It doesn't
affect the reply already delivered before the socket closed.

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
