"""Open the enrolment window for ONE named person.

    PYTHONNOUSERSITE=1 widget/.venv/bin/python widget/tools/enrolar.py marta

Writes who it is for and signals the running widget, which puts the QR
on the strip. Deliberately a deliberate act at this keyboard: the QR
itself now carries that person's token in cleartext (`enrol.sobre`),
and with a roster that secret belongs to a named person — the father's
holds `terminal`.

An already-enrolled phone never needs this again.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jarvis_widget.personas import CASA, normalizar

PENDIENTE = Path.home() / ".jarvis" / "enrolamiento.json"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("uso: enrolar.py <persona>", file=sys.stderr)
        return 2
    persona = normalizar(argv[1])
    if persona == CASA and argv[1].strip().casefold() != CASA:
        print(f"«{argv[1]}» no es un nombre válido", file=sys.stderr)
        return 2

    PENDIENTE.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(PENDIENTE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump(
            # "consola": having a shell here is the gate, and always
            # was. The widget applies its amo check only to the
            # spoken path — see `__main__.pendiente_de_alta`.
            {"persona": persona, "escrito": time.time(), "origen": "consola"},
            handle,
        )

    subprocess.run(
        ["systemctl", "--user", "kill", "-s", "USR1", "jarvis-widget.service"],
        check=False,
    )
    print(f"ventana abierta para {persona}; el QR está en la tira")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
