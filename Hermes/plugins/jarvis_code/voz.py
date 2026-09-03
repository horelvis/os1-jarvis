"""The three prompts that earn the voice, and the stubbornness of one push.

The text travels as a LABELLED VALUE inside «…» — the lesson of the
camera names (§12, 2026-08-24): a model handed a fragment inside its own
sentence repairs bad grammar by inventing; handed a quoted value, it
picks its own words around it.

Injection semantics are `alert.py`'s, measured 2026-08-24: False means
the gateway's injector is not installed yet and retrying helps; a
missing session comes back True and is logged by Hermes itself.

And the shape of the API is the guarantee, not our discipline: it can
only push a USER message, so what the user hears is his answer to a
prompt rather than a sentence we wrote for him.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from loguru import logger

JARVIS_SESSION_KEY = "agent:main:jarvis:dm:jarvis"

RETRY_DELAYS: tuple[float, ...] = (1.0, 3.0, 5.0)

_PROMPTS = {
    "question": (
        "El asistente de código se ha parado a preguntar y espera la "
        "respuesta del usuario. Pregunta: «{text}». Trasládasela en tus "
        "palabras, en una frase, y no la respondas tú."
    ),
    "gate": (
        "El asistente de código quiere hacer algo delicado y necesita "
        "permiso del usuario antes de seguir. Acción: «{text}». Pídele "
        "permiso en una frase."
    ),
    "checkpoint": (
        "El asistente de código ha terminado el encargo. Resultado: "
        "«{text}». Cuéntaselo al usuario en tus palabras, breve, y "
        "pregúntale si lo da por bueno."
    ),
    # A statement, not a question — the only one here, and the reason it
    # exists is the bound on the chain (`worker.py`, D4). A run born
    # from a checkpoint answer closes instead of parking at a checkpoint
    # of its own, so there is no question to relay; without this, work
    # the user explicitly asked for would finish in silence and he would
    # think he had been ignored. It asks him for nothing, so nothing is
    # left waiting and no divert is armed.
    "closed": (
        "El asistente de código ha terminado lo que el usuario le pidió "
        "después. Resultado: «{text}». Cuéntaselo en tus palabras, "
        "breve, y no le preguntes nada."
    ),
}


def prompt_for(qkind: str, text: str) -> str:
    template = _PROMPTS.get(qkind) or _PROMPTS["question"]
    return template.format(text=text)


def deliver(inject: Callable[..., bool], text: str) -> bool:
    """Push one prompt into the strip's session, with alert.py's patience.

    Never raises. A gateway going down mid-injection would otherwise take
    the follower thread with it, and then the console goes quiet for the
    rest of the run with nothing said about why.
    """
    for delay in RETRY_DELAYS:
        try:
            accepted = inject(text, role="user", session_key=JARVIS_SESSION_KEY)
        except Exception as exc:  # noqa: BLE001 — the follower must survive it
            # With the stack. This is swallowed so the dispatch loop
            # survives, which is also what makes it invisible otherwise.
            logger.opt(exception=True).warning(
                f"jarvis-code: la inyección falló — {exc}"
            )
            return False
        if accepted:
            return True
        time.sleep(delay)
    logger.warning("jarvis-code: el aviso no llegó a la sesión de la tira")
    return False
