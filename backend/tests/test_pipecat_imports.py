"""Smoke test: verify pipecat import paths are correct for installed version."""


def test_core_frame_processor_imports():
    from pipecat.frames.frames import AudioRawFrame, Frame, TextFrame  # noqa: F401
    from pipecat.pipeline.pipeline import Pipeline  # noqa: F401
    from pipecat.pipeline.task import PipelineTask  # noqa: F401
    from pipecat.processors.frame_processor import FrameDirection, FrameProcessor  # noqa: F401

    assert True


def test_silero_vad_imports():
    from pipecat.audio.vad.silero import SileroVADAnalyzer  # noqa: F401

    assert True


def test_fastapi_transport_imports():
    # pipecat >= 0.0.89 — new path
    from pipecat.transports.websocket.fastapi import (  # noqa: F401
        FastAPIWebsocketParams,
        FastAPIWebsocketTransport,
    )

    assert True


def test_faster_whisper_imports():
    from faster_whisper import WhisperModel  # noqa: F401

    assert True
