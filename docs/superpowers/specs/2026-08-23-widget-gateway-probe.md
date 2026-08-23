# What the gateway does with a kiosk turn — measured

**Date:** 2026-08-23
**Plan:** `docs/superpowers/plans/2026-08-23-samantha-widget-voice-turn.md` Task 1
**Design:** `docs/superpowers/specs/2026-08-23-samantha-widget-gtk4-design.md` §5.1, §9
**Tool:** `widget/tools/probe_gateway.py`

The question this task existed to answer — *does anything other than the
widget produce audio for a kiosk turn?* — is **yes**. It also turned up
four things nobody asked about, three of which change plan 2.

---

## 0. Getting a gateway at all

The gateway was not running, and `run-gateway.sh` refused to start with
"a gateway is already running under systemd for this profile". That
gateway was **the machine's personal Hermes**
(`~/.hermes/hermes-agent/venv`), not the one pinned in this repo — the
exact situation commit `bd37645` ("pin Hermes inside the repo instead of
borrowing the machine's") was written to prevent. It was the old remote
access to Samantha; the user had it stopped and disabled.

`samantha-hermes.service` then failed to start with

    samantha-kiosk: no frontend at /home/nexus/frontend/dist

**This is a bug in the committed unit**, not a local misconfiguration.
systemd starts the process in `%h`, and the adapter's default static
root is the *relative* path `frontend/dist`, which `.resolve()` turns
into `~/frontend/dist`. Fixed by adding `WorkingDirectory=` to the unit
rather than one `Environment=` per relative path.

---

## 1. Audio: yes, and it was leaving the house

Two `⚠️ Couldn't deliver the audio attachment.` frames arrived in the
first real turn, and the gateway log showed:

    [samantha_kiosk] send_voice fallback: native audio send unavailable
    for .../cache/audio/tts_20260823_101837_632683.mp3

So Hermes synthesised, then failed to deliver it because the text-only
adapter has no audio path. The cache file is the interesting part:

    MPEG ADTS, layer III, v2, 48 kbps, 24 kHz, Monaural

**That is Edge TTS — Microsoft's cloud.** CosyVoice yields PCM/WAV.
Samantha's words were being sent to Microsoft to be spoken. This is
case 3 in `samantha_voice/plugin.yaml`'s privacy note, word for word:
*"tts.provider set to anything but cosyvoice. The default is edge, so
this MUST be set explicitly."* It was not set — the repo's
`.hermes/home/config.yaml` had no `tts:` section at all.

**It was not auto-TTS.** `voice.auto_tts` defaults to `False`
(`hermes_cli/config_defaults.py:1780`) and was never enabled. The agent
*chose* to speak, through its own `text_to_speech` tool — the reply
literally announced it: "Te cuento algo corto, en voz alta."

### The fix, and the proof it worked

Added to `.hermes/home/config.yaml` (git-ignored, so this is per-machine
configuration and has to be redone on the appliance):

```yaml
tts:
  provider: cosyvoice
  streaming:
    provider: cosyvoice
```

Cache emptied, gateway restarted, one more turn. The new file:

    RIFF (little-endian) data, WAVE audio, Microsoft PCM, 16 bit,
    mono 24000 Hz

PCM at 24 kHz is CosyVoice, and 24000 is exactly
`samantha.tts.OUTPUT_SAMPLE_RATE`. Nothing leaves the LAN now.

### What plan 2 must still decide

The widget synthesises for itself (spec §5.1), so the gateway
synthesising *as well* is wasted GPU and a second voice waiting to
happen — today it only fails silently because the adapter cannot carry
audio. Options, in order of how much they change:

1. Leave it. Harmless while the adapter is text-only, and the `⚠️` frame
   is filtered as system chatter (§3 below). Wasteful.
2. Take `text_to_speech` away from the agent, so it never tries.
3. Give the adapter an audio path and let the gateway do the speaking —
   which is plan 3b of the old design, and what spec §5.1 deliberately
   walked away from.

Recommendation: **(1) now, (2) when it starts costing something.**

---

## 2. Hermes answers as Hermes, not as Samantha

Verbatim, first real reply:

> Sí, te oigo. Soy Hermes, tu asistente. Con /help ves los comandos.

Spec §9 flagged this as inherited and known
(`samantha_kiosk/plugin.yaml` marks it out of scope for plan 3a). It is
still true, and it is the first thing the user will hear. The prose
quality itself is fine — "El mar nunca se queda quieto. Aunque lo mires
en calma, debajo sigue moviéndose." is a good Samantha sentence — but
the identity is wrong and it offers slash commands to a person with no
keyboard.

**This, not latency, is the most likely reason the widget fails to
convince.** It belongs to plan 3, and it is a persona problem, not a
widget problem.

---

## 3. The gateway talks to itself, in English, with emoji

Four system messages arrived as ordinary `token` frames, indistinguishable
from her actual words:

| Trigger | Text |
|---|---|
| first turn on a new channel | `📬 No home channel is set for Samantha_Kiosk … Type /sethome` |
| second turn while the first ran | `↪ Redirected current run (iteration 1/9223372036854775807)` |
| first redirect | `💡 First-time tip — I redirected the current run…` |
| every turn that synthesises | `⚠️ Couldn't deliver the audio attachment.` |
| interrupting | `⚡ Interrupting current task. I'll respond to your message shortly.` |

**The very first turn never reached the model at all** — it was consumed
by the `/sethome` prompt.

A widget that speaks everything it receives would read these out, in
English, including the number 9223372036854775807. Plan 2 needs a filter:
drop a frame whose text starts with one of a known set of leading
markers (`📬 ↪ 💡 ⚠️ ⚡`) before it reaches the clause chunker. Cheap,
and it fails safe — the worst case is staying quiet about something that
was not hers to say.

---

## 4. `done` does not mean the turn is over

Every one of those system messages was followed by its own
`{"type": "done", "thinking_ms": 0}`. One turn produced **six** `done`
frames. Plan 2's `TurnMachine` treats `done` as "go back to idle", and
its `ClauseChunker.flush()` fires there — so as written, the wave would
settle and the buffer would flush several times mid-turn.

Also note `thinking_ms` is `0` on all of them, so it cannot be used to
tell a real completion from a system one.

**Plan 2 Task 7 must change:** `done` after a filtered system frame is
not a turn boundary. The simplest rule that matches what was observed:
a `done` only settles the turn if at least one *unfiltered* token
arrived since the last settle.

---

## 5. Frames, for the record

A clean turn, once the channel had settled:

```
-> {"type":"chat","message":"Dime en voz alta una frase corta sobre la lluvia.","user_id":"primary"}
<- {"type":"token","token":"La lluvia no pide permiso. Llega, lava todo un poco, y se va."}
<- {"type":"done","thinking_ms":0}
<- {"type":"token","token":"⚠️ Couldn't deliver the audio attachment."}
<- {"type":"done","thinking_ms":0}
```

Tokens arrive as **whole messages, not word by word**. The clause
chunker still earns its place — a long reply arrives as several such
messages — but the latency win it was designed for is smaller than
assumed, because the first token only appears once the model has
finished composing that message.

Authorization worked with no configuration: `user_id: "primary"` matched
the adapter's default allowlist, and no `Origin` header was accepted
exactly as `adapter.py:565-570` promises.
