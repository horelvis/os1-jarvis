"""Delivery context reaches existing turns without modifying private history."""

from copy import deepcopy

from Hermes.plugins.jarvis import register
from Hermes.plugins.jarvis.delivery import (
    DELIVERY_CONTEXT,
    UNAVAILABLE_DELIVERY,
    delivery_context,
    enforce_delivery,
)


def test_delivery_context_applies_to_existing_jarvis_sessions_only():
    history = [{"role": "assistant", "content": "Se lo enviaré."}]
    original = deepcopy(history)
    assert delivery_context(
        platform="jarvis", is_first_turn=False, conversation_history=history
    ) == {"context": DELIVERY_CONTEXT}
    assert history == original
    assert delivery_context(platform="telegram") is None
    assert delivery_context() is None


def test_registration_uses_the_real_context_hook_without_registering_new_tools():
    class Context:
        def __init__(self):
            self.hooks = {}
            self.tools = []

        def register_hook(self, name, callback):
            self.hooks[name] = callback

        def register_tool(self, **kwargs):
            self.tools.append(kwargs["name"])

        def register_platform(self, **kwargs):
            pass

    context = Context()
    register(context)
    assert (
        context.hooks["pre_llm_call"](platform="jarvis")["context"] == DELIVERY_CONTEXT
    )
    assert context.tools == ["emparejar"]


def test_observed_promises_without_tools_cannot_be_delivered():
    for text in (
        "He estado buscando sobre eso. Le estoy preparando un resumen.",
        "En cuanto lo tenga listo, se lo enviaré.",
        "Sigo trabajando en ello. En un momento le entrego el resumen completo.",
        "Le envío ahora mismo el resumen con lo que he encontrado.",
        "Si desea que busque ofertas, dígamelo y lo haré de inmediato.",
    ):
        assert enforce_delivery(text, toolsets=()) == UNAVAILABLE_DELIVERY


def test_real_summary_or_honest_limitation_is_not_replaced():
    for text in (
        "Resumen de lo hablado: busca un puesto de consultor Alfresco.",
        "No he realizado ninguna búsqueda ni tengo resultados verificados.",
        "No estoy preparando ninguna tarea en segundo plano.",
    ):
        assert enforce_delivery(text, toolsets=()) == text


def test_unknown_or_tool_capable_policy_is_not_treated_as_tool_free():
    text = "He buscado el material y aquí está su resumen."
    assert enforce_delivery(text, toolsets=("web",)) == text
    assert enforce_delivery(text, toolsets=None) == text


def test_tool_free_reply_is_checked_before_any_pcm_is_synthesised(monkeypatch):
    import asyncio

    from Hermes.plugins.jarvis.adapter import AudioFormat, JarvisAdapter
    from Hermes.plugins.jarvis.policy import PolicyResolver

    async def go():
        adapter = JarvisAdapter({})
        policy = PolicyResolver({}).admit_desktop()
        turn = adapter._open_turn("casa", "guard-test", policy=policy, desktop_pcm=True)
        spoken = []

        async def synthesize(_turn, content):
            spoken.append(content)
            return True

        monkeypatch.setattr(adapter, "_send_desktop_pcm", synthesize)
        assert not adapter.supports_streaming_tts("casa", AudioFormat())
        assert await adapter.begin_streaming_tts("casa", AudioFormat()) is None
        result = await adapter.send(
            "casa", "He estado buscando. Se lo enviaré.", reply_to=turn.request_id
        )
        assert result.success
        assert spoken == [UNAVAILABLE_DELIVERY]
        await adapter.disconnect()

    asyncio.run(go())
