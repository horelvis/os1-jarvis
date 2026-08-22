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

## Not verified

- Whether Chromium's Web Speech API (the STT path) can reach Google's servers
  from this machine — never exercised.
- A full browser round trip: mic → transcript → LLM → speech.
- The exact HTTP status x.ai returns for an unauthenticated request (inferred
  as 401, never sent).
- Anything on the kiosk box itself; this covers the Mac + 4090 dev setup only.
