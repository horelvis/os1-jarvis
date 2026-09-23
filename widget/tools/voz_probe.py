"""La línea de tiempo de un turno de voz, medida.

No es un test: se corre a mano, con la tira parada (el adaptador tiene UN
socket y gana quien conecta último). Manda un turno de voz real
(`audio: pcm_s16le/24000`) y marca cuándo llega cada hito del lado del
gateway:

    envio -> primer token (modelo) -> pcm.start (TTS) -> primer JPCM (audio)

Las otras dos marcas de la spec —fin de voz y transcripción— salen del
journal de la tira; esto mide solo lo que pasa desde que el texto entra al
gateway.

    PYTHONNOUSERSITE=1 widget/.venv/bin/python widget/tools/voz_probe.py \
        "dime una frase corta"
"""

from __future__ import annotations

import asyncio
import json
import sys
import time

import websockets

URI = "ws://127.0.0.1:7777/ws"
PCM_MAGIC = b"JPCM"


async def run(text: str) -> None:
    marks: dict[str, float] = {}
    pcm_bytes = 0
    async with websockets.connect(URI, max_size=None) as ws:
        await ws.send(
            json.dumps(
                {
                    "type": "chat",
                    "message": text,
                    "user_id": "primary",
                    # Marks the turn as a voice turn: Hermes' delta-to-TTS
                    # consumer speaks at the first clause.
                    "audio": "pcm_s16le/24000",
                    "wake": True,
                }
            )
        )
        t0 = time.monotonic()
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=120)
            now = time.monotonic() - t0
            if isinstance(raw, (bytes, bytearray)):
                if bytes(raw[:4]) == PCM_MAGIC:
                    marks.setdefault("primer_pcm", now)
                    marks["ultimo_pcm"] = now
                    pcm_bytes += len(raw)
                continue
            msg = json.loads(raw)
            kind = msg.get("type")
            if kind == "token":
                marks.setdefault("primer_token", now)
            elif kind == "pcm.start":
                marks.setdefault("pcm_start", now)
            elif kind in {"done", "error"}:
                marks["fin"] = now
                break

    print(f"texto: {text!r}")
    for label in ("primer_token", "pcm_start", "primer_pcm", "ultimo_pcm", "fin"):
        if label in marks:
            print(f"  {label:14} +{marks[label]:6.2f}s")
    print(f"  audio PCM recibido: {pcm_bytes} bytes ({pcm_bytes / 2 / 24000:.2f}s)")
    if "primer_pcm" not in marks:
        print("  ** sin audio PCM: el camino de streaming no se activó **")


if __name__ == "__main__":
    texto = sys.argv[1] if len(sys.argv) > 1 else "Dime una frase corta, señor."
    asyncio.run(run(texto))
