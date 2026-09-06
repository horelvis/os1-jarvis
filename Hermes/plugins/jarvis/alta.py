"""Asking, out loud, to pair a phone.

Enrolment mints a permanent credential for a named person — the amo's
holds `terminal` — and until 2026-09-06 it required a shell on this box
(`widget/tools/enrolar.py`). That requirement WAS the gate: whoever
could run it was already sitting at the machine. Asking by voice removes
it, so the gate has to be rebuilt here, in the only two places that can
know anything trustworthy about who is asking.

**Who may ask: the amo, and nobody else.** The widget already resolves
who is speaking on every turn (`__main__.persona_de`) — the voiceprint
at the desk, the token on a phone — and sends it as the turn's
`chat_id`. Neither of those is something a client asserts about itself,
which is what makes it worth checking. A guest in the room resolves to
`CASA`, and `CASA` is refused here like anyone else.

**Ambiguity refuses.** `quien` is `None` when the adapter cannot say
which chat is asking: no turn open, or several at once. That is not a
reason to fall back to the amo — it is the one case where guessing
hands a credential to the wrong person, so it is a refusal.

**And this is only half of the gate.** The widget refuses independently
when the signal arrives, from its own first-hand knowledge of who last
spoke, because a request reaching it is not evidence of who sent it.
Either layer alone stops this; both exist because the thing being
protected is a credential rather than a convenience.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Callable

from loguru import logger

CASA = "casa"

RUTA_CASA = Path.home() / ".jarvis" / "casa.json"
RUTA_PENDIENTE = Path.home() / ".jarvis" / "enrolamiento.json"

# Spanish, in his voice: these reach the user through his own reply.
_HECHO = "Listo. El código está en la tira y dura cinco minutos."
_NO_ERES_TU = "Eso sólo puedo hacerlo si me lo pide el amo de la casa."
_SIN_CASA = "Todavía no sé de quién es esta casa, así que no puedo dar de alta a nadie."
_MAL_NOMBRE = "Ese nombre no me sirve para un teléfono. Dime otro."


def amo(casa: Path | None = None) -> str | None:
    """Who owns this house, or None when that cannot be established.

    Never raises and never guesses. A missing file, a corrupt one, an
    unreadable disk and a house with no amo all answer the same thing,
    deliberately: the alternative is an unreadable register opening
    enrolment to whoever happens to be talking.
    """
    try:
        datos = json.loads((casa or RUTA_CASA).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.debug(f"alta: no he podido leer el registro — {exc}")
        return None
    quien = datos.get("amo") if isinstance(datos, dict) else None
    return quien if isinstance(quien, str) and quien else None


def _normalizar(nombre: str) -> str:
    """A person id from a spoken name.

    Deliberately NOT importing `jarvis_widget.personas`: this package is
    loaded inside the gateway, which does not have the widget on its
    path. Kept to the same shape — lowercase, no spaces — and anything
    that does not survive becomes empty rather than `CASA`, so a bad
    name is refused instead of quietly becoming nobody.
    """
    limpio = "".join(c for c in (nombre or "").strip().casefold() if c.isalnum())
    return limpio


def hacer_alta(
    nombre: str,
    *,
    quien: str | None,
    casa: Path | None = None,
    pendiente: Path | None = None,
    señal: Callable[[], None] | None = None,
) -> str:
    """Open the enrolment window for `nombre`, if `quien` may ask.

    Returns what he should say. Writes nothing and signals nobody unless
    the request passes — a refused request that left a pending file
    behind would be consumed by the NEXT signal, whoever sent that one.
    """
    dueño = amo(casa)
    if dueño is None:
        return _SIN_CASA
    if quien is None or quien != dueño:
        logger.warning(f"alta: rechazada, la pidió {quien!r} y el amo es {dueño!r}")
        return _NO_ERES_TU

    persona = _normalizar(nombre)
    if not persona or persona == CASA:
        # `casa` is the identity of an unattributable turn. A phone
        # paired to it would hold the credential of "nobody".
        return _MAL_NOMBRE

    destino = pendiente or RUTA_PENDIENTE
    destino.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(destino, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump({"persona": persona, "escrito": time.time()}, handle)

    (señal or _señal_al_widget)()
    return f"{_HECHO} Es para {persona}."


def _señal_al_widget() -> None:
    """The same SIGUSR1 `widget/tools/enrolar.py` sends, from here.

    `check=False` for the same reason it is there: a widget that is not
    running is not an error worth raising into a turn, and the pending
    file will be read whenever one starts.
    """
    subprocess.run(
        ["systemctl", "--user", "kill", "-s", "USR1", "jarvis-widget.service"],
        check=False,
    )
