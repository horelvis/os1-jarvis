"""Ask the kiosk socket one question and print everything it says back.

Not a test — a thing you run by hand, once, to find out what the
gateway actually does with a turn before writing code that assumes it.

The question it exists to answer: does anything OTHER than the widget
produce audio for a kiosk turn? If the gateway's auto-TTS fires too,
Samantha says everything twice, and that is a confusing bug to meet for
the first time with six other new modules in the room (spec §5.1).
"""

import asyncio
import json
import sys

import websockets

URI = "ws://127.0.0.1:7777/ws"


async def main() -> None:
    text = sys.argv[1] if len(sys.argv) > 1 else "Hola, ¿me oyes?"
    async with websockets.connect(URI) as ws:
        await ws.send(
            json.dumps({"type": "chat", "message": text, "user_id": "primary"})
        )
        reply = []
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=120)
            msg = json.loads(raw)
            print(f"  <- {msg}")
            if msg["type"] == "token":
                reply.append(msg["token"])
            elif msg["type"] in {"done", "error"}:
                break
        print("\nFULL REPLY:", "".join(reply))


asyncio.run(main())
