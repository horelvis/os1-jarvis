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

Paths assume the repo at `$REPO` and Hermes at `~/hermes-src`.

```bash
export REPO="$HOME/git/os1-samantha"      # adjust
export HERMES="$HOME/hermes-src"
export PYTHONPATH="$REPO/backend:$REPO"
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
"$HERMES/.venv/bin/hermes" --version
"$HERMES/.venv/bin/hermes" plugins list | grep -i samantha
```

Expect 0.20.5 or later and both `samantha-voice` and `samantha-kiosk`.

**"enabled" here proves only that the manifest parsed.** It does not mean the
code imported. That distinction cost this project half a day, which is why
the next check exists separately.

## 4. The plugins actually import

```bash
"$HERMES/.venv/bin/hermes" plugins doctor samantha-voice
"$HERMES/.venv/bin/hermes" plugins doctor samantha-kiosk
```

Expect discovery, manifest parsing, import and registration all passing.

**If import fails:** it is almost always a missing dependency. Hermes
declares `python_dependencies` and never installs them. Fix with:

```bash
uv pip install --python "$HERMES/.venv/bin/python" loguru aiohttp
```

**And know what the failure looks like if you skip this:** Hermes logs a
warning, carries on, and every reply comes out of Edge TTS in a stranger's
voice.

## 5. The kiosk platform is enabled

```bash
"$HERMES/.venv/bin/hermes" plugins list | grep samantha-kiosk
```

`kind: platform` plugins are opt-in. If it says "not enabled":

```bash
"$HERMES/.venv/bin/hermes" plugins enable samantha-kiosk
```

Note the **hyphenated manifest name**, not the underscored directory name.
Until this runs the gateway serves nothing while the listing still shows the
plugin, so "not enabled" reads as a state rather than as the reason.

## 6. Both TTS registries are claimed

This is the privacy check. Hermes has two separate registries and claiming
only one leaves every fallback path going to Microsoft.

```bash
cd "$HERMES" && ./.venv/bin/python -c "
from tools.tts_streaming import resolve_streaming_provider
from agent.tts_registry import get_provider
import Hermes.plugins.samantha_voice
cfg = {'provider':'cosyvoice','streaming':{'provider':'cosyvoice'}}
print('streaming :', type(resolve_streaming_provider(cfg)).__name__)
print('whole-file:', type(get_provider('cosyvoice')).__name__)
"
```

Expect `CosyVoiceStreamingProvider` and `CosyVoiceSyncProvider`.

**Anything else — `None`, or an ElevenLabs/OpenAI/Edge class — means audio is
leaving the house.** `Hermes/plugins/samantha_voice/plugin.yaml` lists the
four configuration routes that can still cause this even when the plugin
loads correctly.

## 7. CosyVoice answers, and produces real audio

```bash
curl -sS -o /dev/null -w 'http %{http_code}\n' http://192.168.100.58:8093/ --max-time 5
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

## 8. The kiosk serves the interface

With the gateway running (see `running-real-mode.md`):

```bash
curl -sS -o /dev/null -w '/        %{http_code}\n' http://localhost:7777/
curl -sS    http://localhost:7777/ | grep -o '/assets/[^"]*' | head -1
```

Then fetch the asset path that command printed and confirm it is 200 as well.

**A 200 on `/` with a 404 on the asset is a blank screen** — the most easily
missed failure here, because the page "loads".

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
  Hermes/plugins/samantha_voice/tests Hermes/plugins/samantha_kiosk/tests -q
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
- **No audio in the kiosk.** Text only until plan 3b.
- **Clause-by-clause speech sounds flatter** than whole-utterance synthesis.
  Known, measured, and a deliberate trade for latency.
