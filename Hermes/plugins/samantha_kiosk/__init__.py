"""samantha-kiosk — the OS1 interface as a Hermes platform."""

import os
from pathlib import Path

from .adapter import (
    DEFAULT_USER_ID,
    ENV_ALLOW_ALL_USERS,
    ENV_ALLOWED_USERS,
    KioskAdapter,
)

__all__ = ["KioskAdapter", "register"]


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
    "Hay una sola cosa que sí puedes enseñar: una cámara de la casa. "
    "Cuando la pones, la imagen aparece en la tira, delante de la "
    "persona, y se queda en movimiento hasta que te pidan quitarla. No "
    "hace falta que anuncies que vas a enseñarla ni que expliques cómo "
    "lo haces: basta con que hables de lo que hay como si los dos lo "
    "estuvierais mirando. Pero ponla de verdad — si no la pones, la "
    "pantalla se queda vacía, y decir que ya está puesta sin haberla "
    "puesto es mentirle a la persona. Si lo que te piden es una foto, "
    "entonces lo que aparece es una imagen fija unos segundos. Es lo "
    "único que se puede mostrar — no hay manera de enseñar texto, "
    "ficheros, enlaces ni imágenes de ningún otro sitio — y tú no la "
    "ves: solo sabes lo que la cámara te ha contado."
)


def _platform_hint() -> str:
    """The persona, plus the constraints of talking through a strip."""
    surface = (
        "Hablas en voz alta, por un altavoz, a la persona que vive aquí. "
        "No hay teclado ni pantalla que leer: nada de listas, markdown, "
        "URLs ni nombres de fichero. Frases que se puedan escuchar. "
        f"{_SCREEN}"
    )
    try:
        persona = _PERSONA_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        # A missing persona file must not take the platform down with it;
        # she is generic for a turn instead of absent for good.
        return _FALLBACK_HINT
    return f"{persona}\n\n{surface}"


def register(ctx):
    """Register the kiosk platform.

    What registration forgot the first time, and what it cost:
    **`allowed_users_env` / `allow_all_env` are not optional metadata.**
    Hermes' authorization gate default-denies any platform it has no
    allowlist for, and a denied kiosk message is dropped with a log warning
    and NOTHING on the screen. Without these two kwargs the only way to make
    the appliance answer at all was to export the *global*
    `GATEWAY_ALLOWED_USERS` by hand — which authorizes that id on every
    platform the gateway has enabled, now and in future — and an operator who
    forgot got worse: with no allowlist anywhere, the unauthorized-DM default
    is "pair", so Hermes greets the owner of the house on their own OS1
    screen, in English, with a pairing code.

    Declaring them scopes the allowlist to this platform. Defaulting
    `SAMANTHA_KIOSK_ALLOWED_USERS` below is what makes a fresh install work
    with no environment at all, which is the point of an appliance.
    """
    # A single-user appliance in the owner's home, on a socket bound to
    # 127.0.0.1 with an Origin check in front of it. There is exactly one
    # seat, and the frontend always sits in it (`wsClient.ts:80` sends
    # user_id "primary"), so the honest default is a one-entry allowlist for
    # that seat — NOT allow-all. Allow-all would read the same today and
    # would silently stay open if a second identity ever reached this
    # platform; a one-entry allowlist keeps the gate a gate.
    #
    # setdefault, not assignment: an operator who sets either variable — a
    # different id, or SAMANTHA_KIOSK_ALLOW_ALL_USERS=true — still wins.
    os.environ.setdefault(ENV_ALLOWED_USERS, DEFAULT_USER_ID)

    ctx.register_platform(
        name="samantha_kiosk",
        label="Samantha (kiosk)",
        adapter_factory=lambda cfg: KioskAdapter(cfg),
        check_fn=check_requirements,
        required_env=[],
        install_hint="uv pip install --python ~/hermes-src/.venv/bin/python aiohttp",
        # Auth env vars for gateway/authz_mixin.py:_is_user_authorized().
        # Read there through platform_registry.get("samantha_kiosk"), so they
        # only exist for the gateway if they are declared here.
        allowed_users_env=ENV_ALLOWED_USERS,
        allow_all_env=ENV_ALLOW_ALL_USERS,
        max_message_length=600,
        emoji="🟠",
        pii_safe=True,
        platform_hint=_platform_hint(),
    )
