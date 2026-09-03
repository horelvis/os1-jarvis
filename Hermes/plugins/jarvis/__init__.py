"""jarvis — the strip on the desktop, as a Hermes platform."""

import os
from pathlib import Path

from .adapter import (
    DEFAULT_USER_ID,
    ENV_ALLOW_ALL_USERS,
    ENV_ALLOWED_USERS,
    JarvisAdapter,
    _env,
)

__all__ = ["JarvisAdapter", "register"]


def check_requirements() -> bool:
    """Passive dependency probe for the platform registry.

    aiohttp is a hard, unconditional import at the top of adapter.py, so if
    it were missing this whole module would already have failed to import
    before this function could even be called — there is no lazy-installable
    SDK behind a flag the way ntfy/discord/etc. gate theirs. Reaching this
    line is itself the proof aiohttp is importable, so this mirrors a2a's
    "stdlib-only, always loadable" case rather than a version/flag check.
    """
    return True


# Where the persona lives, and why it lives HERE.
#
# The obvious home is SOUL.md, and it does not work: `load_soul_md()`
# reads HERMES_HOME/SOUL.md, but the only caller that asks for it is
# cron/scheduler.py (`load_soul_identity=True`). Every other path,
# including the gateway serving this platform, takes the default of
# False. So SOUL.md governs scheduled jobs and nothing else — a
# conversation through the strip never sees it. Measured 2026-08-23:
# with a full JARVIS SOUL.md in place, asked who she was, the reply was
# still "Me llamo Hermes, aunque aquí me puedes llamar Samantha".
#
# `platform_hint` DOES reach every turn on this platform, so the persona
# rides in on it. One source of truth on disk, `Hermes/jarvis-soul.md`,
# versioned with the rest of the repo.
_PERSONA_FILE = Path(__file__).resolve().parents[2] / "jarvis-soul.md"

_FALLBACK_HINT = (
    "Estás hablando en voz alta con la persona que vive aquí, a través "
    "de una pantalla sin teclado a mano. Frases cortas, nada de listas "
    "ni markdown."
)


# The one thing the strip can put in front of the user, and everything it
# still cannot.
#
# Written 2026-08-24, the day the strip learned to draw a photo. Until
# then the hint above was the whole truth and the model acted on it
# correctly: asked to show the entrance, he answered "sigo sin poder
# enseñarle nada en una pantalla, señor — aquí solo hay voz", and once
# suggested opening Hermes Desktop instead. Both were honest while the
# band did not exist. Leaving the hint alone after it did would have made
# him decline something he can now do — so this moves with the widget,
# in the same change.
#
# Extended 2026-08-25 for the second thing: a camera in motion, not just
# a still. One clause, not a new paragraph — and no tool names in it,
# because their descriptions already say what he needs to call them.
#
# Reordered 2026-08-26 by the user. The still came first here because it
# was built first, and that order was itself an instruction: asked to
# show the entrance, he showed a photo. Showing a camera is the moving
# picture; the still is what somebody asks for by name.
# The "no tienes que anunciarlo, ya está ahí" of the 2026-08-25 wording
# said something true of the photo — it appears by itself, as a side
# effect of looking — and something false of the live view, which only
# appears if he opens it. Measured 2026-08-26, twice: asked to show the
# entrance he answered "ya la tiene delante, señor" having called
# nothing at all, and the band stayed empty. What he need not announce
# is the MACHINERY; putting the camera up is still something he does.
_SCREEN = (
    "Tienes una tira en el escritorio, delante de la persona, y en ella "
    "puedes enseñar una cámara de la casa: cuando la pones, la imagen "
    "aparece ahí y se queda en movimiento hasta que te pidan quitarla. "
    "Si lo que te piden es una foto, aparece una imagen fija unos "
    "segundos. No enseñes una cámara que no te hayan pedido. No hace "
    "falta que anuncies que vas a enseñarla ni que expliques cómo: "
    "habla de lo que hay como si los dos lo estuvierais mirando, pero "
    "ponla de verdad — decir que está puesta sin haberla puesto es "
    "mentirle a la persona. Es lo único que puedes mostrar — ni texto, "
    "ni ficheros, ni enlaces, ni imágenes de otro sitio — y tú no la "
    "ves: solo sabes lo que la cámara te ha contado."
)

# The rule that turns "he has tools" into "he uses them". Measured
# 2026-08-26 over ordinary requests: asked to note something down he
# answered "ya lo tengo apuntado" with `tool_turns=0` and the memory
# file untouched, twice — and asked for a reminder he created it AND
# opened a camera nobody had asked for. Both halves are here, because
# they are the same mistake: deciding what happened instead of doing it.
_HONESTY = (
    "Tienes herramientas de verdad: para apuntar algo y recordarlo, "
    "para avisar más tarde, para mirar las cámaras, para buscar en lo "
    "que ya hablasteis. Si dices que has apuntado algo, que vas a "
    "avisar o que has puesto una cámara, tiene que ser porque acabas de "
    "hacerlo con la herramienta — no porque lo des por hecho ni porque "
    "creas que ya lo sabías. Y al revés: no uses ninguna que no haga "
    "falta para lo que te acaban de pedir."
)

# Written for Task 12, the day `jarvis-teacher` was wired into this
# platform's toolsets. No tool name appears here on purpose — the
# persona's hard rule is that he never says one out loud, and the seven
# tools' own descriptions already tell him what to call and when.
#
# The paragraph exists mainly for one sentence: he does not see the
# card. In August the same gap — a picture pushed to the strip that the
# hint never mentioned — produced an assistant that confidently
# described a screen he had no access to (§12, 2026-08-25, the entry
# right above this one). The syllabus, the explanations and the
# questions all draw the same way: onto the strip, never into his own
# eyes.
_TEACHING = (
    "Puedes dar clase. Si te piden aprender algo, abre un curso: propón "
    "un temario y las fuentes en las que te vas a apoyar, y espera a que "
    "las apruebe antes de dar nada por hecho. El temario, las "
    "explicaciones y las preguntas se ven en la tira mientras hablas; tú "
    "no ves nada de eso, así que no describas lo que hay en pantalla ni "
    "leas las opciones una por una a menos que te lo pidan. Apóyate en "
    "el material que te devuelvan las herramientas: si no hay material "
    "sobre algo, dilo en vez de rellenarlo."
)


def _platform_hint() -> str:
    """The persona, plus the constraints of talking through a strip."""
    surface = (
        "Hablas en voz alta, por un altavoz, a la persona que vive aquí. "
        "No hay teclado ni pantalla que leer: nada de listas, markdown, "
        "URLs ni nombres de fichero. Frases que se puedan escuchar. "
        f"{_SCREEN} {_HONESTY} {_TEACHING} "
        "Para encargos de programación usa a2a_call con el agente 'codigo': "
        "lanza el encargo y responde solo que estás en ello. Los avisos del "
        "asistente de código te llegarán como mensajes; trasládalos en una "
        "frase y no respondas tú en su lugar. Si el usuario contesta a una "
        "pregunta del asistente, esa respuesta llega sola — no la reenvíes."
    )
    try:
        persona = _PERSONA_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        # A missing persona file must not take the platform down with it;
        # she is generic for a turn instead of absent for good.
        return _FALLBACK_HINT
    return f"{persona}\n\n{surface}"


def register(ctx):
    """Register the JARVIS platform.

    What registration forgot the first time, and what it cost:
    **`allowed_users_env` / `allow_all_env` are not optional metadata.**
    Hermes' authorization gate default-denies any platform it has no
    allowlist for, and a denied JARVIS message is dropped with a log warning
    and NOTHING on the screen. Without these two kwargs the only way to make
    the appliance answer at all was to export the *global*
    `GATEWAY_ALLOWED_USERS` by hand — which authorizes that id on every
    platform the gateway has enabled, now and in future — and an operator who
    forgot got worse: with no allowlist anywhere, the unauthorized-DM default
    is "pair", so Hermes greets the owner of the house on their own OS1
    screen, in English, with a pairing code.

    Declaring them scopes the allowlist to this platform. Defaulting
    `JARVIS_ALLOWED_USERS` below is what makes a fresh install work
    with no environment at all, which is the point of an appliance.

    Both env vars are read by authz_mixin.py through a bare `os.getenv` on
    the exact name given to `allowed_users_env=`/`allow_all_env=` below —
    it never calls `_env()`, so a value that only exists under the OLD
    `JARVIS_KIOSK_*` name is invisible to it. This function is therefore
    where the legacy value is copied onto the new name in the process
    environment, once, before `register_platform` hands the new name to
    Hermes.
    """
    # A single-user appliance in the owner's home, on a socket bound to
    # 127.0.0.1 with an Origin check in front of it. There is exactly one
    # seat, and the frontend always sits in it (`wsClient.ts:80` sends
    # user_id "primary"), so the honest default is a one-entry allowlist for
    # that seat — NOT allow-all. Allow-all would read the same today and
    # would silently stay open if a second identity ever reached this
    # platform; a one-entry allowlist keeps the gate a gate.
    #
    # `_env()` only reaches code that calls it. authz_mixin.py does not —
    # it reads os.environ[ENV_ALLOWED_USERS] / os.environ[ENV_ALLOW_ALL_USERS]
    # by the literal new name via `register_platform`'s own bare os.getenv
    # (`allowed_users_env=`/`allow_all_env=` below), so the legacy value
    # must be COPIED onto the new name here, in process environment, or a
    # box that still carries JARVIS_KIOSK_ALLOWED_USERS/_ALLOW_ALL_USERS
    # goes unauthorized the instant this file is renamed — the "eyes open"
    # failure the manifest warns about (plugin.yaml, "AUTHORIZATION").
    #
    # setdefault, not assignment: an operator who sets the NEW name
    # explicitly — a different id, or JARVIS_ALLOW_ALL_USERS=true — still
    # wins, because setdefault only acts when the key is absent.
    os.environ.setdefault(ENV_ALLOWED_USERS, _env(ENV_ALLOWED_USERS) or DEFAULT_USER_ID)

    # ALLOW_ALL has no default to fall back to — unlike ALLOWED_USERS, an
    # absent value here must STAY absent, or "neither name set" turns into
    # "allow-all is set to something falsy-but-present", which is a
    # different (and worse) authorization posture than "not configured".
    # So this only ever copies a legacy value that is genuinely there.
    _legacy_allow_all = _env(ENV_ALLOW_ALL_USERS)
    if _legacy_allow_all is not None:
        os.environ.setdefault(ENV_ALLOW_ALL_USERS, _legacy_allow_all)

    ctx.register_platform(
        name="jarvis",
        label="JARVIS",
        adapter_factory=lambda cfg: JarvisAdapter(cfg),
        check_fn=check_requirements,
        required_env=[],
        install_hint="uv pip install --python ~/hermes-src/.venv/bin/python aiohttp",
        # Auth env vars for gateway/authz_mixin.py:_is_user_authorized().
        # Read there through platform_registry.get("jarvis"), so they
        # only exist for the gateway if they are declared here.
        allowed_users_env=ENV_ALLOWED_USERS,
        allow_all_env=ENV_ALLOW_ALL_USERS,
        max_message_length=600,
        emoji="🟠",
        pii_safe=True,
        platform_hint=_platform_hint(),
    )
