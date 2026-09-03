# Verification checklist

Run this top to bottom after moving Samantha to a new machine, after
upgrading Hermes, or whenever something feels off. It takes a couple of
minutes.

It is organised around one fact learned the hard way: **almost every failure
in this stack is silent.** A missing file, an unloaded plugin, an
unauthorised user and a dead server all present the same way — nothing
happens, and nothing says why. Each check below exists because that specific
failure has actually happened, and each one names what you would otherwise
have seen instead.

Paths assume the repo at `$REPO`. Hermes lives *inside* it since
2026-08-22 — `Hermes/setup-runtime.sh` pins it at `.hermes/src` with its
HERMES_HOME at `.hermes/home`, and `Hermes/run-gateway.sh` is the only
entry point that exports the right environment. A bare `hermes` on PATH is
somebody else's install, on a version these plugins are not written against.

```bash
export REPO="$HOME/git/os1-samantha"      # adjust
cd "$REPO"
```

---

## 1. Her voice and her memory arrived

These live outside git. Nothing rebuilds them.

```bash
ls -l ~/.samantha/voices/ref/samantha.wav ~/.samantha/voices/ref/samantha.txt
du -sh ~/.samantha/memory
```

Expect the WAV around 384 KB, the transcript 133 bytes, and memory a couple
of megabytes.

**If the voice files are missing:** `tts.is_available()` returns False, our
provider is never selected, and Hermes speaks through Edge TTS — Microsoft's
cloud. You get a voice. It is not hers, and nothing warns you.

**If memory is missing:** she starts from nothing and does not say so. This
is the one thing on this page that cannot be recovered.

## 2. The backend imports and sees both

```bash
"$REPO/backend/.venv/bin/python" -c "
from samantha import tts
from samantha.memory import Memory
print('voz:', tts.is_available())
print('chunks:', Memory().count())
"
```

Expect `True` and a count in the hundreds — it was 279 on 2026-08-22 and only
ever grows. A count of 0 with `voz: True` means the memory directory landed
somewhere else.

## 3. Hermes runs, and knows about our plugins

```bash
Hermes/run-gateway.sh --version
Hermes/run-gateway.sh plugins list | grep -iE 'samantha|jarvis'
```

Expect `v0.20.5 (2026.8.19)`, an install directory inside the repo, and both
`jarvis-voice` and `jarvis` reading `enabled`. If the version is
older, or the install directory is under `$HOME`, you are talking to a
different Hermes — re-run `Hermes/setup-runtime.sh`.

**"enabled" here proves only that the manifest parsed.** It does not mean the
code imported. That distinction cost this project half a day, which is why
the next check exists separately.

## 4. The plugins actually import

**Use the snake_case directory name here, not the kebab-case manifest name**
— `doctor` resolves a path or a directory id, so `jarvis-voice` answers
`Plugin 'jarvis-voice' was not found` while the plugin is loading fine.
Measured 2026-08-22; the two commands take different names and always have.

```bash
Hermes/run-gateway.sh plugins doctor jarvis_voice
Hermes/run-gateway.sh plugins doctor jarvis
```

Expect discovery, manifest parsing, import and registration all passing.
`jarvis_voice` printing a `samantha.config` log line on the way is the
proof that PYTHONPATH reached it — that import is the whole point.

**If import fails:** it is almost always a missing dependency. Hermes
declares `python_dependencies` and never installs them. Fix with:

```bash
uv pip install --python "$REPO/.hermes/src/.venv/bin/python" loguru httpx aiohttp
```

Re-running `Hermes/setup-runtime.sh` does this for you; it is idempotent.

**And know what the failure looks like if you skip this:** Hermes logs a
warning, carries on, and every reply comes out of Edge TTS in a stranger's
voice.

## 5. The jarvis platform is enabled

```bash
Hermes/run-gateway.sh plugins list | grep jarvis
```

`kind: platform` plugins are opt-in. `setup-runtime.sh` enables both for you,
so this should already read `enabled`. If it does not:

```bash
Hermes/run-gateway.sh plugins enable jarvis --no-allow-tool-override
```

Note the **hyphenated manifest name**, not the underscored directory name
`doctor` wants in check 4. `--no-allow-tool-override` answers the capability
prompt with "no", which is what this plugin declares and what makes the step
scriptable — neither plugin replaces a built-in tool.
Until this runs the gateway serves nothing while the listing still shows the
plugin, so "not enabled" reads as a state rather than as the reason.

## 6. Both TTS registries are claimed

This is the privacy check. Hermes has two separate registries and claiming
only one leaves every fallback path going to Microsoft.

**`discover_plugins()`, not a bare import.** The whole-file registry is
populated by `ctx.register_tts_provider()` inside the plugin's `register(ctx)`,
and only Hermes' loader calls that (`hermes_cli/plugins.py:2653, 4758`).
Importing the package alone runs the streaming side's `@register` decorator
and nothing else, so it reports `whole-file: NoneType` on a perfectly healthy
install — a false alarm on the one check that is supposed to mean "audio is
leaving the house". Measured 2026-08-22.

```bash
cd "$REPO/.hermes/src" && HERMES_HOME="$REPO/.hermes/home" \
  PYTHONPATH="$REPO/backend:$REPO" ./.venv/bin/python -c "
from hermes_cli.plugins import discover_plugins
discover_plugins(force=True)
from tools.tts_streaming import resolve_streaming_provider
from agent.tts_registry import get_provider
cfg = {'provider':'cosyvoice','streaming':{'provider':'cosyvoice'}}
print('streaming :', type(resolve_streaming_provider(cfg)).__name__)
print('whole-file:', type(get_provider('cosyvoice')).__name__)
"
```

`HERMES_HOME` matters here too: `get_provider` scopes its lookup by home
(`agent/tts_registry.py:135`), so a check run against the wrong home reports
a miss that the gateway would not have.

Expect `CosyVoiceStreamingProvider` and `CosyVoiceSyncProvider`.

**Anything else — `None`, or an ElevenLabs/OpenAI/Edge class — means audio is
leaving the house.** `Hermes/plugins/jarvis_voice/plugin.yaml` lists the
four configuration routes that can still cause this even when the plugin
loads correctly.

## 7. CosyVoice answers, and produces real audio

```bash
curl -sS -o /dev/null -w 'http %{http_code}\n' http://127.0.0.1:8093/ --max-time 5
```

A 404 is healthy — `/` is not a route. Connection refused means the container
is down; a hang means it is starting, and those are different problems.

Then prove it synthesises rather than merely listens:

```bash
"$REPO/backend/.venv/bin/python" -c "
from samantha import tts
wav, backend = tts.synth('Hoy he estado pensando en lo que me contaste ayer.')
print(backend, len(wav), 'bytes', round((len(wav)-44)/48000, 2), 's')
"
```

Expect `cosyvoice`, a couple of hundred kilobytes, and a few seconds.

**A port that answers proves nothing about the model.** Check this before
concluding the plugin is broken.

## 8. The kiosk-era interface route (retired)

This step is retired. There was a static frontend served from `/` on
`:7777`; there is no longer one to check. The strip (`widget/`) is a native
GTK4 window, not a page a browser loads, and the `jarvis` platform serves
exactly one route — `/ws` — and nothing else, by design
(`Hermes/plugins/jarvis/adapter.py`).

Check instead that the gateway logged, on startup:

```
jarvis: serving /ws on :7777
```

If that line is missing, the platform did not come up — see §5.

## 9. She answers, and a refresh does not lock you out

```bash
"$REPO/backend/.venv/bin/python" -c "
import asyncio, json, aiohttp
async def go():
    async with aiohttp.ClientSession() as s:
        async with s.ws_connect('http://localhost:7777/ws') as ws:
            await ws.send_str(json.dumps({'type':'chat',
                'message':'Hola, ¿qué tal estás?','user_id':'primary'}))
            while True:
                m = await ws.receive(timeout=120)
                d = json.loads(m.data)
                print(d)
                if d['type'] in ('done','error'): break
asyncio.run(go())
"
```

Expect one or more `token` frames and then `done`.

**If nothing arrives and it hangs:** the most likely cause is authorisation —
Hermes drops chats from an unlisted user with no error frame at all. The
adapter's watchdog now turns that into a visible `error` after 90 seconds, so
waiting is informative: an error after a minute and a half means the message
reached Hermes and Hermes dropped it.

Then reconnect twice and send again. It must still answer.

## 10. The guards are the ones you think

```bash
cd "$REPO" && backend/.venv/bin/python -m pytest \
  Hermes/plugins/jarvis_voice/tests Hermes/plugins/jarvis/tests -q
```

Expect all green — 34 and 38 respectively as of 2026-08-22.

Green tests are weaker evidence than they look. Every serious bug found on
2026-08-22 passed the suite: the doubles had no event loops, no real Hermes
base class, no real socket, and no knowledge of the order Hermes calls things
in at startup. Checks 1 to 9 are the ones that test reality.

---

## What is still expected to be wrong

So you do not spend time debugging things that are known:

- **She answers with Hermes' personality, not hers.** `SOUL.md` is unwired.
  A reply saying "Soy Hermes, tu asistente" is the current expected state,
  not a fault.
- **No audio in the strip.** Text only until plan 3b.
- **Clause-by-clause speech sounds flatter** than whole-utterance synthesis.
  Known, measured, and a deliberate trade for latency.
