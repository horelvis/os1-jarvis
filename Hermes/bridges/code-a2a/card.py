"""The Agent Card: what this bridge says it can do.

Served at `/.well-known/agent-card.json`, which is where an A2A v1.0
client looks, and also at `/.well-known/agent.json`, which is where
pre-1.0 clients look. Hermes' own client answers both paths for the same
reason, and answering both costs one line.

The card is the whole of the discovery story: a peer fetches it, reads
the skills, and knows whether this agent is worth calling. So the skills
are written for a reader, not for a schema — `a2a_orchestrate` fans a
task out to "every peer advertising a capability", and the capability
names here are what it matches on.
"""

from __future__ import annotations

PROTOCOL_VERSION = "1.0"


def build(url: str, assistant: str, projects_root: str) -> dict:
    """The card this bridge publishes.

    `assistant` is named in the description rather than hidden: whoever
    is calling deserves to know whose judgement is doing the work, and
    it changes when the machine changes.
    """
    return {
        "id": "jarvis-code-bridge",
        "name": "Asistente de código",
        "description": (
            f"Trabaja en los proyectos de {projects_root} con {assistant}: "
            "lee el código, lo cambia, ejecuta las pruebas y cuenta qué ha "
            "hecho. Una tarea por mensaje; el proyecto se nombra en el "
            "propio mensaje."
        ),
        "provider": {"name": "samantha", "url": url},
        "protocolVersion": PROTOCOL_VERSION,
        "version": "0.1.0",
        "capabilities": {
            "streaming": True,
            "pushNotifications": False,
            "extendedAgentCard": False,
        },
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain"],
        "skills": [
            {
                "id": "code",
                "name": "Escribir y arreglar código",
                "description": (
                    "Cambios en un repositorio: arreglar un fallo, añadir "
                    "una prueba, refactorizar, ejecutar la batería."
                ),
                "tags": ["code", "development", "tests"],
                "examples": [
                    "En os1-samantha, arregla el test de vad que falla",
                    "En barndoor, añade un log cuando la cámara se caiga",
                ],
            },
            {
                "id": "explain",
                "name": "Explicar código",
                "description": "Leer un repositorio y responder sobre él.",
                "tags": ["code", "research"],
                "examples": ["¿Por qué falla el test de vad en os1-samantha?"],
            },
        ],
        # Both spellings: v1.0 calls this `interfaces`, and Hermes'
        # client reads `supportedInterfaces`. Publishing one and not the
        # other is how two correct implementations fail to meet.
        "interfaces": [
            {
                "url": url,
                "protocolBinding": "JSONRPC",
                "protocolVersion": PROTOCOL_VERSION,
            }
        ],
        "supportedInterfaces": [
            {
                "url": url,
                "protocolBinding": "JSONRPC",
                "protocolVersion": PROTOCOL_VERSION,
            }
        ],
        "securitySchemes": {},
        "security": [],
    }
