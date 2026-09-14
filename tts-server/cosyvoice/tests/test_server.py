"""Offline contracts for the real FastAPI overlay, without CosyVoice or GPU."""

import asyncio
import importlib.util
import sys
import unittest
from io import BytesIO
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import numpy as np
from fastapi import BackgroundTasks, UploadFile
from fastapi.testclient import TestClient


class ZeroShotTests(unittest.TestCase):
    def setUp(self) -> None:
        stub = ModuleType("cosyvoice.cli.cosyvoice")
        stub.AutoModel = None
        spec = importlib.util.spec_from_file_location(
            "cosyvoice_overlay", Path(__file__).resolve().parents[1] / "server.py"
        )
        self.server = importlib.util.module_from_spec(spec)
        with (
            patch.dict(sys.modules, {"cosyvoice.cli.cosyvoice": stub}),
            patch.object(sys, "path", list(sys.path)),
        ):
            spec.loader.exec_module(self.server)

    def test_multipart_preserves_spanish_prompt_and_pcm(self) -> None:
        text = "\u00bfQu\u00e9 ocurri\u00f3 el 9/9/2026? Hay 642 caracteres y 3 notas."
        transcript = "Esta es la voz de referencia en espa\u00f1ol."
        custom = "Habla con calma.<|endofprompt|>" + transcript
        for prompt in (transcript, custom):
            with self.subTest(prompt=prompt):
                paths = []

                def inference(
                    tts_text,
                    prompt_text,
                    prompt_wav,
                    *,
                    text_frontend=True,
                    prompt=prompt,
                    paths=paths,
                ):
                    # A generator, like upstream: checks run during streaming.
                    self.assertIs(text_frontend, False)
                    self.assertEqual(tts_text, text)
                    expected = (
                        custom
                        if prompt == custom
                        else self.server._SYS_PREFIX + transcript
                    )
                    self.assertEqual(prompt_text, expected)
                    self.assertEqual(prompt_text.count(self.server._EOP), 1)
                    path = Path(prompt_wav)
                    paths.append(path)
                    self.assertEqual(path.read_bytes(), b"fake reference wav")
                    yield {
                        "tts_speech": SimpleNamespace(
                            numpy=lambda: np.array([-2.0, 0.0, 2.0])
                        )
                    }
                    yield {"tts_speech": SimpleNamespace(numpy=lambda: np.array([0.5]))}

                self.server.cosyvoice = SimpleNamespace(inference_zero_shot=inference)
                with TestClient(self.server.app) as client:
                    response = client.post(
                        "/inference_zero_shot",
                        data={"tts_text": text, "prompt_text": prompt},
                        files={
                            "prompt_wav": (
                                "ref.wav",
                                b"fake reference wav",
                                "audio/wav",
                            )
                        },
                    )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    response.content,
                    np.array([-32767, 0, 32767, 16383], dtype=np.int16).tobytes(),
                )
                self.assertEqual(len(paths), 1)
                self.assertFalse(paths[0].exists())

    def test_stream_failure_is_not_empty_success(self) -> None:
        # Exercise the route's StreamingResponse to record zero PCM before
        # the lazy inference failure, without a client hiding the sent events.
        paths = []
        events = []

        def inference(*args, **kwargs):
            paths.append(Path(args[2]))
            raise AssertionError("normalizer failed")
            yield  # upstream inference is lazy

        self.server.cosyvoice = SimpleNamespace(inference_zero_shot=inference)

        async def exercise() -> None:
            response = await self.server.inference_zero_shot(
                BackgroundTasks(),
                "Hay 3 notas.",
                "Referencia.",
                UploadFile(file=BytesIO(b"fake reference wav")),
            )

            async def send(event):
                events.append(event)

            await response.stream_response(send)

        try:
            with self.assertRaisesRegex(AssertionError, "normalizer failed"):
                asyncio.run(exercise())
            self.assertEqual(
                events, [{"type": "http.response.start", "status": 200, "headers": []}]
            )
        finally:
            # Existing background cleanup does not run on a failed stream.
            for path in paths:
                path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
