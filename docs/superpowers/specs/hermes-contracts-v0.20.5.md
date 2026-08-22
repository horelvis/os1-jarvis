# Hermes contracts, captured from source — v0.20.5

**Date:** 2026-08-22
**Method:** `git clone https://github.com/NousResearch/hermes-agent.git`,
checked out at commit `fcbd1076a93841fa88855acce810e342a5b78101` (tag
`v2026.8.19`, `pyproject.toml` version `0.20.5`) — see "How this was
installed" below for why this replaced the brief's literal Step 1
command. Every quote in this document is verbatim from that checkout;
file paths and line numbers are given so they can be re-verified against
the same commit.

This document supersedes
`docs/superpowers/specs/2026-08-21-hermes-herald-capability-map.md`
wherever the two disagree — that map was built from web-fetched docs and
partial reads; this was read straight from the pinned source. See
**Corrections** at the end for every place they diverge.

**Quoting convention:** every method/class **signature** below is
verbatim, character-for-character, from the pinned commit. Docstrings
are sometimes condensed for length — where that happens it's noted
inline, but not every elision is marked with `...`, so treat prose
around a code block as paraphrase and the code block's signatures (not
necessarily every line of every docstring) as the source of truth. If a
docstring detail matters for an implementation decision, re-read it
from `agent/memory_provider.py` / `gateway/platforms/base.py` /
`hermes_cli/plugins.py` directly rather than trusting the condensed
version here.

---

## How this was installed

The brief's Step 1 (`uv tool install hermes-agent --with mcp
--with-editable ./backend`) does not work, for two independent reasons,
neither of which is specific to this machine:

1. **PyPI's `hermes-agent` is stale.** Latest on PyPI is `0.19.0`
   (= source tag `v2026.7.20`). It **predates the streaming-TTS feature
   entirely** — `tools/tts_streaming.py` does not exist in that
   checkout, confirmed by `find_spec('tools.tts_streaming')` returning
   `None` and a filesystem search of the installed package turning up
   nothing. Installing from PyPI silently gets you a Hermes that cannot
   do the one thing this whole plugin plan depends on.
2. **`uv tool install` from git source is explicitly blocked upstream.**
   `uv tool install "git+https://github.com/NousResearch/hermes-agent.git@v2026.8.19"`
   fails at the build-wheel step with:

   ```
   RuntimeError: Building wheels or sdists for hermes-agent is not
   supported.
   Hermes is distributed via the shell installer, Docker image, or Nix.
   See: https://hermes-agent.nousresearch.com/docs/getting-started/installation

   If you are developing, use an editable install instead:
     uv sync          # or: uv pip install -e .
   ```

   This is intentional on their end (`hermes_cli`/setup.py raises it on
   purpose) — Hermes is not meant to be `pip install`-ed as a library.

The documented distribution channel is `curl -fsSL
https://hermes-agent.nousresearch.com/install.sh | bash`, which clones
the repo to `~/.hermes/hermes-agent/` and builds a venv with `uv sync
--locked`. That installer also bootstraps Node.js, ripgrep, and ffmpeg
via Homebrew/apt, which on this machine (Intel Mac, macOS Ventura 13.5,
Homebrew Tier 3 — no bottles) meant compiling LLVM, ffmpeg, and Node
from source. Attempted and abandoned after 20+ minutes without
finishing; it also consumed enough disk that the machine's shared APFS
container dropped to ~140MB free, and twice broke system `git` when the
runaway background build was killed mid-cleanup (both times repaired
and confirmed working: `git --version` → 2.40.1, `brew doctor` clean).
**Ruling (team lead, 2026-08-22): no more installers that write outside
this repo or scratch on this machine — no `brew`, no `curl | bash`,
nothing system-modifying.** That closes off the shell installer as an
option here entirely; Docker or Nix would be the way to get a full
Hermes runtime on this machine if one is ever needed.

**What this task actually needed, and what worked within that
constraint:** reading the contracts only requires the source tree, not
a runtime.

```bash
git clone https://github.com/NousResearch/hermes-agent.git /tmp/hermes-src
cd /tmp/hermes-src
git checkout fcbd1076a93841fa88855acce810e342a5b78101   # tag v2026.8.19
```

Everything in this document was read from that checkout. A `hermes`
CLI runtime is possible on top of it (`uv sync --python 3.11` builds a
pure-Python venv for hermes-agent itself with no native compilation —
confirmed working, see `hermes --version`/`hermes plugins list` output
below) but is **not required** to capture contracts, and this task
does not depend on it.

`uv` itself needed upgrading regardless: the `uv` on this machine was
0.8.15 and failed with `TOML parse error ... failed to parse "14 d" as
year` on `exclude-newer = "14 days"` in Hermes' `pyproject.toml`, then a
second parse error on `uv.lock`. `uv self update` (0.8.15 → 0.12.5)
fixed both with no other changes. (This is a `uv` version bump inside
scratch tooling, not a system install, so it doesn't fall under the
no-installers ruling — flagging in case that reasoning is wrong.)

**Do not combine this with `--with-editable <repo>/backend`.** That was
tried initially and pulls in `backend`'s `pipecat-ai[silero]`
dependency, which drags in `numba`, which on Intel Mac resolves to an
`llvmlite` version with no `x86_64` wheel and tries to build LLVM from
source — the thing that triggered the disk/git trouble above.
**Ruling (team lead): this is not Hermes' fault and not worth pinning
around** — `pipecat-ai` is dead weight from an abandoned voice-pipeline
approach that this plan deletes. Don't merge the two dependency trees;
see "Getting `samantha` importable" below for the actual answer.

**Getting `samantha` importable — UNRESOLVED for a real Hermes plugin
environment.** What's confirmed instead, cheaply, using the repo's own
venv and touching nothing Hermes-related:

```
$ PYTHONPATH="<repo>/backend" backend/.venv/bin/python -c \
  "import samantha.tts; print(samantha.tts.OUTPUT_SAMPLE_RATE)"
2026-08-22 09:04:14.263 | DEBUG | samantha.config:_load_env_file:49 - Loaded env overrides from /Users/horelvis/.samantha/.env
24000
```

`PYTHONPATH` (or an equivalent `sys.path` insert at plugin load time)
is the likely mechanism for the real `samantha_voice` plugin too — a
Hermes plugin directory under `~/.hermes/plugins/` presumably needs
`backend` on its path, not a merged `pip install -e` dependency tree
with Hermes' own deps. This was **not chased further** here; Tasks 2-4
need to settle it properly before assuming either direction works.

`hermes --version` below is from the plain `uv sync` runtime (no
`backend`, no `samantha` import inside it — that combination is the one
being avoided, per the ruling above):

```
$ /tmp/hermes-src/.venv/bin/hermes --version
Hermes Agent v0.20.5 (2026.8.19) · upstream 9098f677
Install directory: /private/tmp/hermes-src
Install method: git
Python: 3.11.9
OpenAI SDK: 1.99.1
```

`0.20.5` is at/above the brief's `0.20.5` floor and matches
`pyproject.toml`'s `version = "0.20.5"` exactly (line 5). **Pin this
commit** (`fcbd1076a93841fa88855acce810e342a5b78101`, tag `v2026.8.19`)
for everything that follows — Hermes ships multiple releases a week.

---

## Contract 1 — `StreamingTTSProvider`

Source: `tools/tts_streaming.py`, lines 1–220 (module docstring through
the registry helpers; the four cloud providers that follow at lines
220–488 are reference implementations, not part of the contract).

```python
class StreamingTTSProvider(ABC):
    """Yields raw int16, little-endian, mono PCM chunks at ``sample_rate``."""

    sample_rate: int = 24000
    channels: int = 1
    sample_width: int = 2  # bytes/sample (int16)

    def __init__(self, tts_config: Dict, section: Dict):
        self.tts_config = tts_config
        self.section = section

    @staticmethod
    @abstractmethod
    def available() -> bool:
        """True when this provider's credentials/SDK are usable right now."""

    @abstractmethod
    def stream(self, text: str) -> Iterator[bytes]:
        """Yield PCM chunks for ``text``. Raise on failure (caller logs)."""


_REGISTRY: Dict[str, type[StreamingTTSProvider]] = {}


def register(name: str) -> Callable[[type[StreamingTTSProvider]], type[StreamingTTSProvider]]:
    def _wrap(cls: type[StreamingTTSProvider]) -> type[StreamingTTSProvider]:
        _REGISTRY[name] = cls
        return cls
    return _wrap
```

`resolve_streaming_provider(tts_config, preferred=None)` (same file,
~line 176) picks a provider by `tts.streaming.provider` config
(`auto` walks a hard-coded priority list `["elevenlabs", "gemini",
"openai", "xai"]`; a pinned name returns that streamer or `None`; unset
falls back to the configured non-streaming TTS provider). "We never
silently swap to a different provider just to get streaming" is a
direct quote from its docstring — matches the capability map's
description exactly.

This matches the capability map's §2 quote closely — confirmed, not
corrected.

Also in this file (not previously documented): an **interruption
latch**. `mark_speech_interrupted()` / `take_speech_interrupted()`
(lines ~57–78) let the surface flag a barge-in; the next turn's submit
path prepends `SPEECH_INTERRUPTED_NOTE` — *"[Note: the user interrupted
your previous spoken reply before it finished.]"* — to the model-bound
message, with a 120s TTL. This is API-call-local, never persisted. This
is the exact mechanism §4c of the capability map inferred existed
("the release notes describe the softer mechanism") — now confirmed
from source, and it does **not** trim the assistant's stored message to
what was actually spoken, exactly as §4c predicted.

`SentenceChunker` (same file, ~line 89) is the shared sentence-boundary
cutter — strips `<think>` blocks, merges fragments under `min_len=20`
chars into the next sentence. Worth knowing if Samantha's own
spoken-text shaping needs to compose with it rather than duplicate it.

---

## Contract 2 — `MemoryProvider`

Source: `agent/memory_provider.py`, lines 1–260 (module docstring
through `sync_turn`) plus `get_config_schema` (330–349) and
`save_config` (352–367); `get_tool_schemas` / `handle_tool_call` /
`shutdown` and the remaining optional hooks (367–404) are summarized,
not quoted in full, below.

```python
class MemoryProvider(ABC):
    """Abstract base class for memory providers."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def is_available(self) -> bool:
        """... Should not make network calls — just check config and installed deps."""

    @abstractmethod
    def initialize(self, session_id: str, **kwargs) -> None:
        """Called once at agent startup.

        kwargs always include:
          - hermes_home (str): The active HERMES_HOME directory path.
            Use this for profile-scoped storage instead of hardcoding
            ~/.hermes.
          - platform (str): "cli", "telegram", "discord", "cron", etc.
        kwargs may also include:
          - agent_context (str): "primary", "subagent", "cron", or "flush".
            Providers should skip writes for non-primary contexts.
          - agent_identity, agent_workspace, parent_session_id,
            user_id, user_id_alt
        """

    def unavailable_reason(self) -> str: ...          # default ""
    def system_prompt_block(self) -> str: ...          # default ""

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        """Called before each API call. Return formatted text to inject,
        or "" if nothing relevant. Should be fast."""
        return ""

    def queue_prefetch(self, query: str, *, session_id: str = "") -> None: ...
    def recall_status(self) -> Optional[RecallStatus]: ...  # default None

    def sync_turn(
        self,
        user_content: str,
        assistant_content: str,
        *,
        session_id: str = "",
        messages: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """Called after each turn. Should be non-blocking."""

    @abstractmethod
    def get_tool_schemas(self) -> List[Dict[str, Any]]: ...
    def handle_tool_call(self, tool_name, args, **kwargs) -> str: ...
    def shutdown(self) -> None: ...

    def get_config_schema(self) -> List[Dict[str, Any]]:
        """Return config fields this provider needs for setup.
        Used by 'hermes memory setup' to walk the user through
        configuration. Each field dict may carry: key, description,
        secret (default False), required (default False), default,
        choices, type (text/integer/number/boolean), minimum, maximum,
        step, url, env_var. Return [] if no config needed."""
        return []

    def save_config(self, values: Dict[str, Any], hermes_home: str) -> None:
        """Write non-secret config to the provider's native location.
        Called by 'hermes memory setup' after collecting user inputs;
        ``values`` holds only non-secret fields (secrets go to .env).
        Providers with native config files should override this; env-var-
        only providers can leave the default no-op. Every new memory
        provider plugin MUST implement one of: save_config() for native
        config files, OR env-var-only config (get_config_schema() fields
        all carry env_var, this stays no-op)."""
```

**Registration:** "Plugins ship in `plugins/memory/<name>/` and are
activated via the `memory.provider` config key" (module docstring,
line ~19). "The `MemoryManager` enforces a one-external-provider limit"
(line 4) — this is the source of the capability map's "`kind:
exclusive`, single-select" claim; confirmed, though the word
"exclusive" itself is a `kind` value defined in `hermes_cli/plugins.py`
(§ below), not in this file.

**Not in the capability map at all — worth flagging as new surface:**

- `prefetch()` returns a plain `str` to inject, not a structured
  object. The capability map's gloss ("This is `gather_context()`") is
  our own annotation for what we'd map it to, not something the
  contract says.
- A whole family of **optional hooks** past line 260:
  `on_turn_start(turn_number, message, **kwargs)`,
  `on_session_end(messages)`, `on_session_switch(new_session_id,
  **kwargs)`, `on_pre_compress(messages) -> str`, `on_memory_write(...)`,
  `on_delegation(task, result, **kwargs)`, `backup_paths() -> list[str]`.
  None of these appear in the capability map; `on_session_end` in
  particular is a plausible integration point for anything that wants
  end-of-session batch writes distinct from per-turn `sync_turn`.
- A module-level **trivial-prompt gate**: `TRIVIAL_PROMPT_RE` /
  `is_trivial_prompt(text)` (lines ~66–96). Bare greetings,
  acknowledgements ("ok", "gracias" — well, English list shown, no
  Spanish variants), and empty/slash-command input are classified
  trivial and **`MemoryManager` skips `prefetch`/injection for them
  entirely** ("saving a blocking network round-trip"). This directly
  affects how often Samantha's memory gets consulted per turn, and it's
  an English-only regex — worth checking whether it fires correctly (or
  at all) against Spanish trivial turns ("vale", "gracias", "hola").
- `RecallStatus` (`provider_label`, `count`, `glyph`) drives a
  deterministic "🧠 recalled N memories" UI indicator, independent of
  whether the model chooses to mention recall. Not previously
  documented.

---

## Contract 3 — `MessageType` / `MessageEvent`

Source: `gateway/platforms/base.py`, lines 2278–2345.

```python
class MessageType(Enum):
    """Types of incoming messages."""
    TEXT = "text"
    LOCATION = "location"
    PHOTO = "photo"
    VIDEO = "video"
    AUDIO = "audio"
    VOICE = "voice"
    DOCUMENT = "document"
    STICKER = "sticker"
    COMMAND = "command"  # /command style


class ProcessingOutcome(Enum):
    """Result classification for message-processing lifecycle hooks."""
    SUCCESS = "success"
    FAILURE = "failure"
    CANCELLED = "cancelled"


@dataclass
class MessageEvent:
    """Incoming message from a platform. Normalized representation
    that all adapters produce."""
    text: str
    message_type: MessageType = MessageType.TEXT
    user_id: Optional[str] = None
    user_name: Optional[str] = None
    source: SessionSource = None
    raw_message: Any = None
    message_id: Optional[str] = None
    platform_update_id: Optional[int] = None
    media_urls: List[str] = field(default_factory=list)
    media_types: List[str] = field(default_factory=list)
    reply_to_message_id: Optional[str] = None
    reply_to_text: Optional[str] = None
    reply_to_author_id: Optional[str] = None
    reply_to_author_name: Optional[str] = None
    reply_to_is_own_message: bool = False
    # (fields continue past line 2345 — reply threading and
    #  allow_gateway_control per the capability map; not re-quoted here,
    #  their existence is unchanged from the map's description)
```

This matches the capability map's §1 quote exactly — `AUDIO`/`VOICE`
members, `media_urls`/`media_types`, confirmed unchanged. Not a
correction.

---

## Contract 4 — `PluginContext.register_platform`

Source: `hermes_cli/plugins.py`, lines 2778–2818 (decorator + signature
+ docstring; body continues to ~2853 registering into
`platform_registry`).

```python
@_serialized_replacement
def register_platform(
    self,
    name: str,
    label: str,
    adapter_factory: Callable,
    check_fn: Callable,
    validate_config: Callable | None = None,
    required_env: list | None = None,
    install_hint: str = "",
    **entry_kwargs: Any,
) -> Optional[PluginRegistration]:
    """Register a gateway platform adapter.

    The adapter_factory receives a ``PlatformConfig`` and returns a
    ``BasePlatformAdapter`` subclass instance.

    ``check_fn`` is a PASSIVE dependency probe — "are deps importable
    right now?".  It must never install anything: status displays and
    config loading call it freely.  If your platform's SDK is
    lazy-installable, pass the ACTIVE installer separately as
    ``ensure_deps_fn`` (forwarded via ``entry_kwargs``); the gateway
    calls it from ``create_adapter()`` when ``check_fn`` is False,
    right before connecting the platform.

    Extra keyword arguments are forwarded to ``PlatformEntry`` (e.g.
    ``setup_fn``, ``emoji``, ``allowed_users_env``, ``platform_hint``,
    ``ensure_deps_fn``).  Unknown keys raise TypeError from the
    dataclass constructor.

    Example::

        ctx.register_platform(
            name="irc",
            label="IRC",
            adapter_factory=lambda cfg: IRCAdapter(cfg),
            check_fn=lambda: True,
            emoji="💬",
            setup_fn=irc_interactive_setup,
        )
    """
```

(The docstring's own `Example::` above is a minimal illustration, not
the real `irc` plugin's actual call — that one is longer, quoted next.)

Confirmed real end-to-end against `plugins/platforms/irc/adapter.py`
(lines 953–989 at this commit) — the template the capability map cited
still exists. Its actual `register(ctx)` call, in full:

```python
def register(ctx):
    ctx.register_platform(
        name="irc",
        label="IRC",
        adapter_factory=lambda cfg: IRCAdapter(cfg),
        check_fn=check_requirements,
        validate_config=validate_config,
        is_connected=is_connected,
        required_env=["IRC_SERVER", "IRC_CHANNEL", "IRC_NICKNAME"],
        install_hint="No extra packages needed (stdlib only)",
        setup_fn=interactive_setup,
        env_enablement_fn=_env_enablement,
        cron_deliver_env_var="IRC_HOME_CHANNEL",
        standalone_sender_fn=_standalone_send,
        allowed_users_env="IRC_ALLOWED_USERS",
        allow_all_env="IRC_ALLOW_ALL_USERS",
        max_message_length=450,
        emoji="💬",
        pii_safe=False,
        allow_update_command=True,
        platform_hint="...",
    )
```

`irc`'s `plugin.yaml` (`kind: platform`, `requires_env`/`optional_env`
with `name`/`description`/`prompt`/`password` per entry, no
`manifest_version`/`api_version`) also verified unchanged.

`kind` values confirmed live in `hermes_cli/plugins.py`:
`standalone` (default, line 1063), `backend`, `exclusive` (line 3950,
memory providers), `platform` (line 3996), `model-provider` (line
3968) — exactly the five the capability map listed.

---

## Contract 5 (not in the brief, but load-bearing) — streaming-TTS
## adapter methods on `BasePlatformAdapter`

The brief's Step 3 only asked to `grep -rn "streaming_tts"
gateway/platforms/base.py`, which surfaces this contract — capturing it
in full because **every signature in the capability map's §1 quote of
it is wrong** in a way that would break a naive implementation. See
Corrections below for the diff; this section is the corrected version.

Source: `gateway/platforms/base.py`, lines 588–622 (`AudioFormat` /
`StreamingTTSHandle`) and 4611–4655 (the five methods on
`BasePlatformAdapter`).

```python
@dataclass
class AudioFormat:
    """Declared PCM format for a streaming-TTS session.

    All chunks delivered via ``write_streaming_tts`` must conform to this
    format: raw little-endian PCM at the declared sample rate, channels,
    and sample width.
    """
    sample_rate: int = 24000
    channels: int = 1
    sample_width: int = 2  # bytes per sample (int16 = 2)


@dataclass
class StreamingTTSHandle:
    """Opaque handle returned by ``begin_streaming_tts``.

    Adapters may subclass or extend this with platform-specific state
    (track IDs, buffers, etc.).  The base fields are used by the consumer
    for bookkeeping and cancellation.
    """
    chat_id: str = ""
    audio_format: AudioFormat = field(default_factory=AudioFormat)
    audible: bool = False   # True once the first PCM chunk has been written
    aborted: bool = False   # True after abort_streaming_tts; late chunks dropped
```

```python
# ------------------------------------------------------------------
# Streaming TTS adapter contract (#60671)
# ------------------------------------------------------------------
# Voice-capable adapters (LiveKit, Discord voice, …) override these to
# accept PCM audio chunks while the LLM is still generating.  The default
# implementations report "unsupported" so existing adapters are
# source-compatible and keep the whole-file auto-TTS fallback.

def supports_streaming_tts(self, chat_id: str, audio_format: AudioFormat) -> bool:
    """Return True when this adapter can accept streaming PCM for *chat_id*.
    Default: False (whole-file auto-TTS path remains). Override to opt in."""
    return False

async def begin_streaming_tts(
    self,
    chat_id: str,
    audio_format: AudioFormat,
    metadata: Optional[Dict[str, Any]] = None,
) -> Optional[StreamingTTSHandle]:
    """Open a streaming-audio session for *chat_id*.
    Returns an opaque handle passed to subsequent write/finish/abort
    calls, or None to decline (caller falls back to whole-file TTS)."""
    return None

async def write_streaming_tts(self, handle: StreamingTTSHandle, chunk: bytes) -> None:
    """Write one PCM chunk to the adapter's outbound audio track."""

async def finish_streaming_tts(self, handle: StreamingTTSHandle, *, interrupted: bool = False) -> None:
    """Signal normal end of the audio stream."""

async def abort_streaming_tts(self, handle: StreamingTTSHandle, error: Optional[str] = None) -> None:
    """Abort the stream due to an error or cancellation.
    Must be idempotent: late producer chunks after abort must be
    silently dropped, not raise. Restores adapter state to "not streaming"."""
```

All five default to no-op/False/None on `BasePlatformAdapter`, so the
contract is additive — confirms the capability map's "all five methods
default to no-op" claim.

---

## Step 5 — plugin discovery

The brief's literal command, bare `hermes plugins`, does **not** list
plugins — it launches an interactive TUI and fails non-interactively:

```
$ hermes plugins
Interactive mode requires a terminal.
```

The correct listing command, discovered from `hermes plugins --help`,
is a subcommand:

```
$ hermes plugins list
```

which ran cleanly and printed a table of bundled plugins (`Name /
Status / Version / Description / Source`, ~30 rows: browser-*, chronos,
disk-cleanup, security-guidance, google_meet, kanban/dashboard,
hermes-achievements, spotify, image_gen/*, teams_pipeline, etc.), all
`not enabled` by default with `Source: bundled`. **Use `hermes plugins
list` for later verification, not bare `hermes plugins`.** Other
subcommands relevant later: `install`, `enable`, `disable`,
`capabilities` (declared vs. granted per plugin), `doctor` (validates a
plugin against the real runtime contracts — useful for checking our own
plugin before shipping it), `show`/`info`.

`mkdir -p ~/.hermes/plugins` (the brief's setup step) still matches the
user-plugin discovery path documented in the capability map §4b —
unchanged.

---

## Corrections against `2026-08-21-hermes-herald-capability-map.md`

Treat every item below as source overriding the map. The map was
built from documentation and web-fetched summaries; this document was
read directly from the pinned commit.

1. **Streaming-TTS adapter contract — every signature was wrong.** The
   map's §1 quote:

   ```
   supports_streaming_tts() -> bool
   begin_streaming_tts(handle: StreamingTTSHandle, format: AudioFormat)
   write_streaming_tts(handle: StreamingTTSHandle, pcm_chunk: bytes)
   finish_streaming_tts(handle: StreamingTTSHandle)
   abort_streaming_tts(handle: StreamingTTSHandle)
   ```

   vs. the real contract (Contract 5 above):
   - `supports_streaming_tts` takes `(chat_id, audio_format)`, not
     nothing.
   - `begin_streaming_tts` **returns** `Optional[StreamingTTSHandle]`
     — it does not receive one as a parameter. The map had the data
     flow backwards: the adapter constructs the handle, the caller
     doesn't hand it one.
   - `write_streaming_tts`'s second parameter is named `chunk`, not
     `pcm_chunk`.
   - `finish_streaming_tts` takes a keyword-only `interrupted: bool =
     False` the map didn't mention.
   - `abort_streaming_tts` takes a keyword-only `error: Optional[str] =
     None` the map didn't mention.
   - **All four besides `supports_streaming_tts` are `async def`.**
     The map's code block used bare `def`, which would silently break
     under `await`-based dispatch if copied as-is.

   A plugin author who copy-pasted the map's version would ship
   something that doesn't match the real ABI at all. This is the
   single most important correction in this document — it's the exact
   contract Tasks 2–4 subclass.

2. **The PR citation is likely wrong.** The map cites "PR #73862" for
   this seam. The actual source comment at `gateway/platforms/base.py:588`
   says `(#60671)`. Neither number was independently verified against
   GitHub's PR list (network access to the PR itself wasn't checked),
   but the two numbers disagree and the source comment should be
   trusted over the map's citation if anyone needs to look up review
   history.

3. **`MemoryProvider` has substantially more surface than documented —
   but the map was RIGHT about `get_config_schema`/`save_config`,
   correcting an earlier draft of this document that wrongly called
   them not found.** The map's §4b.1 lists `name`, `is_available`,
   `initialize`, `prefetch`, `sync_turn`,
   `get_tool_schemas`/`handle_tool_call`, `get_config_schema`/
   `save_config` — all confirmed present, verbatim, in Contract 2 above:
   `get_config_schema()` at `agent/memory_provider.py:330-349`,
   `save_config(values, hermes_home)` at `:352-367`, both unbroken
   methods of `MemoryProvider` (the class runs 104–404 with no
   intervening `class` boundary). An earlier draft of this document
   claimed these "were not found... searched the full 404-line file" —
   that was false; a plain `grep -n "def get_config_schema\|def
   save_config" agent/memory_provider.py` finds both immediately.
   Correcting the record: the map was accurate here, and
   `get_config_schema` is the field-collection contract `hermes memory
   setup` walks — real, usable surface for a config-plugin UX, not
   something to assume unavailable.

   Beyond those two (which the map did list), real source also has
   `system_prompt_block()`, `unavailable_reason()`, `queue_prefetch()`,
   `recall_status()` → `RecallStatus`, and seven optional hooks not in
   the map at all: `on_turn_start`, `on_session_end`,
   `on_session_switch`, `on_pre_compress`, `on_memory_write`,
   `on_delegation`, `backup_paths`.

4. **The trivial-prompt gate is new information, not a correction, but
   is important enough to flag loudly**: `MemoryManager` skips
   `prefetch()` entirely for turns matching `is_trivial_prompt()` — an
   English-only regex covering things like "ok", "thanks", "hi". If
   this gate runs upstream of our provider, Spanish trivial turns
   ("vale", "gracias", "hola") either aren't recognized (so they DO
   trigger prefetch — wasted work, not a correctness bug) or need a
   locale-aware override. Worth checking which, before assuming
   `prefetch()` fires on every turn.

5. **PyPI distribution is stale and non-viable — new information not
   in the map at all.** The map never discusses how Hermes is
   installed (out of scope for a documentation spike), but this blocks
   the install recipe implied throughout: `pip`/`uv install
   hermes-agent` gets `0.19.0`, which **predates
   `tools/tts_streaming.py` existing at all**. Anyone following the
   map's contract descriptions while installing from PyPI would get
   `ModuleNotFoundError` and no explanation why. Install from source at
   a pinned commit (see "How this was installed" above).

6. **`hermes plugins` (bare) does not list plugins** — it launches an
   interactive TUI. The listing command is `hermes plugins list` (or
   `ls`). **This corrects the task-1 brief's Step 5, not the capability
   map** — the map never mentions `hermes plugins` at all
   (`grep -in "hermes plugins" docs/superpowers/specs/2026-08-21-hermes-herald-capability-map.md`
   returns nothing). Filed here anyway since it's the closest thing to
   a "Corrections" home for it. Evidence:
   ```
   $ /tmp/hermes-src/.venv/bin/hermes plugins
   Interactive mode requires a terminal.
   $ /tmp/hermes-src/.venv/bin/hermes plugins list
   [prints a table of ~30 bundled plugins]
   ```

7. **HIGH — a fabricated discrepancy in an earlier draft, now removed:
   `is_connected` was never omitted from the map.** An earlier draft of
   Contract 4 claimed `is_connected=is_connected` "is passed and was
   omitted from the map's copy." That was false — the map has it too:
   ```
   $ grep -n is_connected docs/superpowers/specs/2026-08-21-hermes-herald-capability-map.md
   417:        is_connected=is_connected,
   ```
   Same failure shape as Correction 3's `get_config_schema` claim — an
   invented discrepancy where the map was actually right. The false
   claim has been removed from Contract 4, which now quotes the real
   `irc.register()` call in full instead of a lossy prose restatement,
   so this class of error can't recur silently there.

8. **MEDIUM — Contract 4's `register_platform` quote dropped its
   decorator.** Real source:
   ```
   $ sed -n '2778,2779p' hermes_cli/plugins.py
       @_serialized_replacement
       def register_platform(
   ```
   `@_serialized_replacement` (defined at `hermes_cli/plugins.py:550`,
   docstring "Make snapshot → write → lease attachment one atomic
   transaction") wraps the call in `replacement_coordinator
   .transaction()` — it makes plugin (re)registration atomic against
   concurrent hot-reload/replacement, which is behavior, not
   ornamentation, for anyone calling `register_platform` from a plugin
   that might be reloaded. Now included in Contract 4's code block.

9. **Everything else checked this round and confirmed, not corrected:**
   - `MessageType` members (Contract 3) — map lines 102–112 match
     source `gateway/platforms/base.py:2278-2288` exactly, both lists
     `TEXT, LOCATION, PHOTO, VIDEO, AUDIO, VOICE, DOCUMENT, STICKER,
     COMMAND`.
   - `MessageEvent`'s `metadata` and `allow_gateway_control` fields —
     the map cites both (line ~115); Contract 3's quote stopped before
     line 2345 and only asserted these "unchanged from the map's
     description" without re-showing them. Verified now:
     `grep -n "^    metadata: Dict\|^    allow_gateway_control:"
     gateway/platforms/base.py` returns `2380:    metadata: Dict[str,
     Any] = field(default_factory=dict)` and `2389:
     allow_gateway_control: bool = True` — both present and matching
     the map.
   - The five `kind` values — map line 391-392
     (`grep -n "kind. values:" docs/superpowers/specs/2026-08-21-hermes-herald-capability-map.md`)
     lists `standalone, backend, exclusive, platform, model-provider`;
     source (`hermes_cli/plugins.py` lines 1063/3950/3996/3968) matches.
   - `SentenceChunker`'s existence — map line 75 names it as "the
     existing `SentenceChunker`"; confirmed as a real class at
     `tools/tts_streaming.py:89`. The map does not describe its
     internals (min_len merging, `<think>`-stripping), so there is
     nothing there to contradict — Contract 1's fuller description is
     new information, not a correction.
   - The `StreamingTTSProvider` ABC + `@register("name")` registry
     mechanism (Contract 1's non-signature prose) — map §2 describes
     the same shape (static `available()`, abstract `stream()`,
     `@register` decorator, `resolve_streaming_provider`); source
     matches, already quoted in full in Contract 1.

   **Not independently re-verified this round, called out rather than
   silently assumed:** the map's paraphrase of `register_platform`'s
   overall behavior ("handles adapter creation, config parsing, user
   authorization, env auto-enable, cron delivery, and CLI UI
   integration automatically" — map lines 245-247) was not traced
   through the actual call chain (`platform_registry.register()` and
   downstream) to confirm each clause; only the signature and the
   `irc` template's field-for-field usage were checked. Flagging this
   distinction — checked-in-full vs. plausible-and-unchallenged —
   deliberately, per the standard the rest of this section is now held
   to.

   The map's core architectural read (outbound streaming yes / inbound
   streaming no, the plugin-not-fork recommendation) is unaffected by
   any correction above.

---

## What I could not find / did not verify

- Whether PR #73862 or #60671 (or both, on different repos) is the
  correct upstream reference — not checked against GitHub's PR API.
- Full plugin-discovery search-path precedence (`<repo>/plugins/` vs
  `~/.hermes/plugins/` vs `.hermes/plugins/` vs pip entry points) was
  not re-verified from source this session — only `hermes plugins
  list` was run, which doesn't reveal search order. The capability
  map's description of this is carried forward unverified, not
  corrected.
