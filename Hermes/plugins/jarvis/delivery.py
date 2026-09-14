"""Current delivery capabilities, injected per turn even in an old session.

The saved system prompt may describe a voice-only strip. Do not erase the
conversation to refresh it: Hermes supports ephemeral pre_llm_call context.
This adds no tools, permissions or external calls.
"""

import re
from typing import Any

DELIVERY_CONTEXT = (
    "Capacidades y entrega vigentes de JARVIS para ESTE turno: "
    "la app muestra tus respuestas como audio con transcripción desplegable. "
    "Puedes entregar un resumen por escrito en esta misma respuesta; no tienes "
    "que enviarlo por otro canal ni esperar a un mensaje futuro. "
    "Si el usuario ya pidió o aceptó un resumen, entrega su contenido ahora "
    "a partir de la información disponible. No vuelvas a ofrecer prepararlo. "
    "Tus mensajes anteriores diciendo que buscaste o que estabas trabajando "
    "no son pruebas de que se haya ejecutado nada. Solo los resultados reales "
    "de herramientas acreditan búsquedas, envíos o trabajos programados. "
    "No afirmes 'he estado buscando', 'sigo trabajando', 'se lo enviaré' ni "
    "'en un momento' si no existe trabajo real que lo respalde. No hay una "
    "tarea en segundo plano creada por el simple hecho de prometerla. "
    "Las herramientas disponibles son exclusivamente las de esta llamada; "
    "la personalidad o el historial no te conceden otras. Si no puedes "
    "verificar ofertas actuales o enlaces, dilo de forma directa, sin "
    "inventarlos ni fingir una búsqueda. Entrega lo que sí puedas resumir "
    "y distingue información de la conversación de resultados verificados. "
    "No pidas otra vez permiso para preparar el resumen: el usuario ya lo "
    "ha solicitado. Si no hay herramienta de búsqueda en esta llamada, "
    "no puedes buscar ahora ni prometer hacerlo después, y no debes ofrecerlo. "
    "Cuando el historial solo contenga promesas y no resultados, explica "
    "que no hay un resumen pendiente ni vacantes verificadas. No inventes "
    "un resumen para aparentar entrega. No termines con 'si quiere', "
    "'dígamelo y buscaré' ni otra oferta que no puedas ejecutar. "
    "Respeta la restricción local del usuario: no envíes su conversación "
    "a servicios externos ni propongas un fallback de nube."
)


def delivery_context(platform: str = "", **_kwargs: Any) -> dict[str, str] | None:
    """Only this surface; independent of user text and existing session age."""
    if platform != "jarvis":
        return None
    return {"context": DELIVERY_CONTEXT}


UNAVAILABLE_DELIVERY = (
    "No he ejecutado esa consulta ni hay un resumen pendiente de envío. "
    "Esta conexión no tiene herramientas de búsqueda o envío; solo puedo "
    "resumir la información que ya esté disponible en la conversación."
)

# Observed unsupported claims, not an attempt to infer arbitrary truth from
# prose. Only enforce when the server's admission policy grants NO tools.
_ACTION_CLAIM = re.compile(
    r"\b(?:he (?:estado buscando|buscado|consultado)|"
    r"(?:le |se lo |lo )?(?:estoy preparando|estoy buscando|estoy trabajando)|"
    r"sigo (?:trabajando|buscando)|se lo enviar[eé]|"
    r"le (?:env[ií]o ahora|entrego)|(?:buscar[eé]|lo har[eé])|"
    r"aqu[ií] tiene el resumen con (?:las posiciones|las oportunidades))\b",
    re.IGNORECASE,
)


def enforce_delivery(content: str, *, toolsets: tuple[str, ...] | None) -> str:
    """Do not voice an action claim impossible under this admitted policy.

    None means uncorrelated/unknown, not a license to guess its permissions.
    Legitimate summaries and statements denying an action pass unchanged.
    """
    if toolsets is None or toolsets:
        return content
    for sentence in re.split(r"[.!?;\n]+", content):
        if re.search(r"\bno\b", sentence, re.IGNORECASE):
            continue
        if _ACTION_CLAIM.search(sentence):
            return UNAVAILABLE_DELIVERY
    return content
