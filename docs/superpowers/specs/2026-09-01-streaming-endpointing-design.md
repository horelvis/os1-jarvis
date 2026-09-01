# He stops waiting for you to finish — streaming endpointing, design

> **Status:** design, agreed with the user 2026-09-01, after a spike the
> user asked for before any design was written. Every number below was
> measured on this box against this user's voice; nothing is quoted from
> a vendor.
>
> **It amends CLAUDE.md §2.6 without replacing it.** faster-whisper
> `large-v3-turbo` remains the transcriber, unchanged, with its
> `initial_prompt` intact. What is added is a second, much smaller
> engine that never transcribes anything a human reads.

## The problem, stated as a measurement

After you stop speaking, JARVIS waits **1.2 s of silence**
(`vad.py:_SILENCE_SECONDS`) and only then transcribes. CLAUDE.md §2.6
records that transcription as 0.23 s for 3.5 s of speech; measured again
on 2026-09-01 against these recordings it is **61–135 ms**, and barely
grows with the utterance — 134 ms for a 23.5 s buffer.

So the transcription is between 5% and 16% of the wait, depending on
which number you take. **The pause is the rest**, and a faster STT
engine — the obvious reading of "replace Whisper" — buys almost nothing.
This design attacks the pause.

**And the pause cannot simply be shortened.** It was 0.7 s until
2026-08-26, when the user reported "se cortan palabras cuando se habla"
and the dumps showed one sentence arriving as two turns: a breath
mid-sentence is routinely longer than 0.7 s. Lowering the threshold
alone re-introduces exactly that defect. What makes it lowerable is
having **text** with which to tell a breath from an ending.

## What is being built

A second engine — **Vosk `small-es`, 39 MB, Apache 2.0, on the CPU** —
transcribes the utterance as it arrives. Its text is used for one
decision only: *has this person finished?* It never reaches Hermes, is
never spoken, and is never shown.

When the VAD sees **0.35 s** of silence it asks the rule. If the partial
reads as a finished thought, the turn closes there. If not, nothing
happens and the existing **1.2 s** threshold closes it exactly as today.

**Measured gain: 880 ms per turn**, on this user's voice.

## The measurement that decided it, and it inverts the obvious answer

Three engines, the same audio, the same rule. On the user's own
recording of 2026-09-01, which carries six internal pauses of
0.26–0.61 s:

| | good closes | **cuts** | cost per partial | licence |
|---|---|---|---|---|
| **Vosk small-es** | 2 | **0** | **1–2 ms** | **Apache 2.0** |
| Moonshine small-streaming-es | 1 | 1 | 136–574 ms | non-commercial + attribution |
| faster-whisper (GPU) | **0** | **2** | 61–135 ms | MIT |

**The best transcriber is the worst endpointer, for precisely the reason
it is the best transcriber.** At the user's mid-sentence pause, Whisper
wrote

> «…habrá que comprobar que estén encendidas y **con red.**»

— a clean, complete, correctly punctuated Spanish sentence. The rule
closed the turn. The user had not finished; what followed was "No
Jarvis, lo que quieres es que busques unas de otro proveedor". Vosk, at
the same instant, wrote

> «…que estén encendidas **y**»

and waited.

Whisper *completes* the sentence it heard. Vosk leaves it hanging where
the speaker left it. **For deciding whether somebody has finished, the
engine that cannot punctuate is the one that tells the truth.**

That is what makes the split architectural rather than a cost saving:
the two engines are good at opposite things, and the fluency that makes
Whisper the right final transcriber is what disqualifies it as the
endpointer.

## What was rejected, and why

**One engine instead of two — rejected on the wake word.** With
Moonshine as the final transcriber, JARVIS would not have answered
either real sentence in which the user called him by name: his name came
back as «ya luis» and «yardi», and `wake.py`'s 0.6 similarity ratio
rejects both. Vosk salvages one of two, by luck. Only Whisper with its
`initial_prompt` gets both. Being ignored is the one failure a wake word
cannot afford, so no single-engine design survives.

**Moonshine, though it was the candidate the user named.** Three
findings, in the order they landed:

1. It **does** have biasing — `set_keyterms`, better designed than
   `initial_prompt`: a term list with adjustable `keyterm_boost`,
   changeable mid-stream. A web search said otherwise and was wrong; it
   described the older `moonshine` package.
2. **The biasing does not recover his name.** With "Jarvis" in the
   keyterm list the transcription was **identical, character for
   character**, to the run without it.
3. For the endpointing job it is 100–500× more expensive than Vosk and
   carries the **Moonshine Community License** — non-commercial, and
   requiring a visible "Powered by Moonshine AI". Compatible with a
   house (the user's framing, 2026-08-30: "es para el hogar"), but the
   attribution would have to live in the README, since §1.3 forbids
   badges on screen. Paying in licence terms for quality that no human
   reads.

**sherpa-onnx** was the favourite on paper — real hotwords, ONNX on CPU
(already this project's runtime, via Silero), Apache 2.0 — and **has no
Spanish streaming model**: Bengali, Chinese, Korean, English, and
Chinese-English bilingual. **Parakeet** is the fastest available and is
English-only.

## Architecture

`stt.py` is not touched. The text that reaches Hermes is byte-identical
to today's, with the same hint, the same vocabulary and the same
hallucination filter.

```
mic ─► vad.py ──────────────────────────────► stt.py (Whisper, GPU) ─► Hermes
        │  UtteranceDetector                    unchanged
        │
        ├─ 0.35 s of silence → ask ──► endpoint.py
        │                                CompletionRule  (pure)
        │                                VoskPartials    (39 MB, CPU)
        │                              ← close / keep waiting
        └─ 1.2 s of silence → close anyway (today's policy, unchanged)
```

**`endpoint.py`, split the way `vad.py` already is** — policy separated
from model, because that split is what made the VAD testable:

- **`CompletionRule`** — pure. Text in, boolean out. No engine, no file,
  no import beyond the standard library. Tested phrase by phrase.
- **`VoskPartials`** — the model. The only half that needs 39 MB on
  disk, and the only half that can fail at load.

**`vad.py` gains a short trigger beside the long one.** `UtteranceDetector`
already tracks `_silence_seconds`; it gains a second threshold at 0.35 s
at which it consults an injected callback, defaulting to "never close" so
the detector's existing tests describe unchanged behaviour.

**Failure is silence, not an error.** If Vosk will not load, the callback
answers "keep waiting" forever and the widget behaves exactly as it does
today, one log line poorer. That is deliberate: this feature makes him
faster, and a faster feature must never be able to make him deaf. The
lesson is 2026-08-30's, where a model override left Whisper no VRAM and
the failure was invisible for three days.

## The rule

Choosing Vosk simplifies it, because **Vosk emits no punctuation at
all**. The terminator and ellipsis branches measured during the spike
only ever fired for Whisper and are dead code here. What remains:

> A partial is a finished thought when it has at least two words **and**
> its last word is not a Spanish function word that cannot end a
> sentence.

**That word list is therefore the entire rule, and it is the riskiest
part of this plan.** It is Spanish, not engineering, and the spike's
first draft already shows the failure mode: it contained `es`, and "¿qué
hora es?" is a complete sentence. That costs no cut — the 1.2 s fallback
still closes it — but it silently forfeits the gain on a very common
question form.

The list must be built on one distinction, and only the first class is
admitted:

- **cannot end a sentence** — `el`, `del`, `en`, `con`, `y`, `que`, `mi`,
  `muy`… → admit
- **usually does not end one, but can** — `es`, `hay`, `no`, `también`,
  `más` → **reject from the list**

## The second thing the same engine fixes: interrupting him

**Reported by the user, 2026-09-01: "no se calla, sigue hablando."**
Folded into this design rather than given its own, because the cure is
the engine this design already installs.

**The mechanism cannot work, and that is measured rather than
suspected.** While he speaks, `__main__.py` drops every frame under
`SAMANTHA_WIDGET_BARGE_RMS` (0.05) so his own voice returning through
the room cannot open a turn. The measurements of 2026-08-26:

| | RMS |
|---|---|
| the user's voice | 0.054–0.088 |
| his echo, speakers away from the microphone | 0.027–0.035 |
| his echo, speakers beside it | **0.178** |

In the good case a person clears the threshold by **0.004**. In the bad
case his echo is *louder than the person* and no threshold exists that
separates them — the file says so in its own comment. Speaking normally
instead of loudly, turning the volume up, or nudging a speaker is enough
to stop existing. This is not a mis-tuned constant; it is a single
scalar asked to separate two things that are not always separable by
loudness.

**The fix inverts what the threshold is for.** `echo.py` already exploits
the unfair advantage that the widget knows exactly what it just said —
but it applies that after the fact, to a finished transcript. With Vosk
transcribing continuously, the same comparison can be made *while* he
talks: words matching what he is currently saying are his echo and are
dropped; different words are a person, and he stops.

So the RMS gate stops having to separate echo from person — impossible —
and only has to separate sound from silence, which is trivial. It drops
to a low floor and is no longer what decides.

**Cost, stated:** reaction is slower. The gate answers in one 32 ms
frame; Vosk needs roughly 300 ms of speech before there are words to
compare, so he talks a little longer over an interruption than he does
today in the cases where today works at all. The trade is a mechanism
that works at any volume and any speaker position against one that
works in a 0.004 window.

**This amends CLAUDE.md §2.8**, which describes the RMS gate as the
barge-in mechanism, and §8 requires that to be a stated decision rather
than a side effect. `SAMANTHA_WIDGET_BARGE_RMS` survives as the silence
floor, with a much lower default.

## Testing

`CompletionRule` being pure, it is table-driven, and today's recordings
supply the first rows as fixed cases:

| partial | expected |
|---|---|
| «…habrá que comprobar que estén encendidas y» | wait |
| «…de otro proveedor que no son las que había antes» | close |
| «hola ya veis que pueda se» | wait |
| «¿qué hora es?» | close (the `es` regression) |

The barge-in half is likewise split so its policy is pure: given what he
is currently saying and what the microphone is hearing, is this his echo
or a person? That is `echo.py`'s existing comparison against a live
partial rather than a finished transcript, so it is tested the same way
— text in, verdict out, no audio.

Above that, `UtteranceDetector` driven by a scripted probe — the pattern
`vad.py` already supports — and one regression test fixing that when the
rule never says yes, the 1.2 s threshold still closes the turn.

**The user's WAV files do not enter the repository.** `os1-samantha` is
public. What is versioned is the derived trace — the partial's text and
the millisecond it appeared — which is what the tests need and carries
no voice.

## Costs, stated

- **A second STT engine in the widget's dependency tree**, 39 MB of
  model plus the `vosk` wheel. It runs at RTF 0.05 — 5% of one core —
  and loads in 0.1 s, so it costs nothing at runtime and something in
  supply chain.
- **A new class of bug: the premature cut.** It measured zero on this
  sample, and the sample is one long recording plus four August clips.
  It is the failure the user has already reported once, from the other
  direction, and the 1.2 s fallback bounds how wrong the rule can be but
  does not bound this.
- **The rule is Spanish-specific and hand-written.** Nothing about it
  generalises, and it will need revisiting when somebody talks to him
  differently than this user does.

## Out of scope, deliberately

- **Replacing Whisper.** Measured and rejected above; §2.6 stands.
- **Speculative dispatch** — sending the partial to the gateway before
  the turn closes and cancelling if speech resumes. It buys the same
  second by a different route and was set aside on 2026-09-01 in favour
  of this; it remains the alternative if the rule proves too blunt.
- **Using the partial to drop speech not addressed to him** before
  Whisper runs. Real saving, but it moves the "not for me" decision onto
  the worse text, and that decision is already the one that costs a turn
  when it is wrong.
- **Showing the partial on the strip.** §1.3, and it is a separate
  question.
