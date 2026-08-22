"""samantha-kiosk — the OS1 interface as a Hermes platform."""

import os

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
        platform_hint=(
            "Estás hablando en voz alta con la persona que vive aquí, a "
            "través de una pantalla sin teclado a mano. Frases cortas, "
            "nada de listas ni markdown."
        ),
    )
