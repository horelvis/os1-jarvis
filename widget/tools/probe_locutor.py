"""Does a speaker-embedding model run on this box, on onnxruntime alone?

Run by hand:

    PYTHONNOUSERSITE=1 widget/.venv/bin/python widget/tools/probe_locutor.py <model.onnx>

Answers four questions and prints what it saw: does onnxruntime load it,
what shape does it want, what shape does it return, and how long does one
utterance take on the CPU. Nothing is written and no microphone is opened.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import onnxruntime as ort


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("uso: probe_locutor.py <model.onnx>", file=sys.stderr)
        return 2
    ruta = Path(argv[1])
    if not ruta.is_file():
        print(f"no existe: {ruta}", file=sys.stderr)
        return 2

    print(f"modelo: {ruta} ({ruta.stat().st_size / 1e6:.1f} MB)")
    sesion = ort.InferenceSession(str(ruta), providers=["CPUExecutionProvider"])

    for entrada in sesion.get_inputs():
        print(f"  entrada: {entrada.name} {entrada.shape} {entrada.type}")
    for salida in sesion.get_outputs():
        print(f"  salida:  {salida.name} {salida.shape} {salida.type}")

    # Three seconds of 16 kHz silence is enough to learn the shapes and
    # the cost. It is NOT enough to say anything about accuracy — that is
    # task 4, and it needs real voices.
    muestras = np.zeros((1, 16000 * 3), dtype=np.float32)
    nombre = sesion.get_inputs()[0].name
    empezado = time.monotonic()
    salida = sesion.run(None, {nombre: muestras})[0]
    tardado = time.monotonic() - empezado
    print(f"  embedding: {np.asarray(salida).shape} en {tardado * 1000:.0f} ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
