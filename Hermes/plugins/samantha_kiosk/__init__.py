"""samantha-kiosk — the OS1 interface as a Hermes platform."""

from .adapter import KioskAdapter

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
    ctx.register_platform(
        name="samantha_kiosk",
        label="Samantha (kiosk)",
        adapter_factory=lambda cfg: KioskAdapter(cfg),
        check_fn=check_requirements,
        required_env=[],
        install_hint="uv pip install --python ~/hermes-src/.venv/bin/python aiohttp",
        max_message_length=600,
        emoji="🟠",
        pii_safe=True,
        platform_hint=(
            "Estás hablando en voz alta con la persona que vive aquí, a "
            "través de una pantalla sin teclado a mano. Frases cortas, "
            "nada de listas ni markdown."
        ),
    )
