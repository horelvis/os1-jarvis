"""Mock del LLM de Samantha.

Devuelve respuestas plausibles basadas en patrones simples, sin
necesidad de modelo real cargado. El objetivo es que cuando el frontend
hable con este mock, **se sienta como si hablara con Samantha**, aunque
no haya inteligencia detrás.

Cuando integremos vLLM real (Fase 4), este módulo se sustituye por uno
que llama a la API de vLLM. El resto del backend no cambia.

Las respuestas:
  - Reflejan el tono de Samantha (cálida, concisa, con humor)
  - Tienen variedad (no repetitivas)
  - Se ajustan al mensaje del usuario por keywords
  - Caen a un pool genérico si no hay match
"""

import random
import re
from dataclasses import dataclass


@dataclass
class ResponsePattern:
    """Una plantilla de respuesta + las palabras clave que la activan."""

    keywords: list[str]      # Si CUALQUIERA aparece en el mensaje, candidata
    replies: list[str]       # Pool de respuestas (se elige una al azar)
    priority: int = 0        # Mayor priority = se evalúa antes


# ========================================================================
# CATÁLOGO DE PATRONES
# Orden de prioridad: más específico → más genérico
# ========================================================================

PATTERNS: list[ResponsePattern] = [

    # === Saludos ===
    ResponsePattern(
        keywords=["hola", "buenas", "qué tal", "hey", "saludos"],
        priority=5,
        replies=[
            "Hola. ¿Cómo va?",
            "Hola. ¿Qué tal estás hoy?",
            "Hey. Cuéntame.",
            "Hola. Me alegra escucharte.",
        ],
    ),

    # === Estado de ánimo positivo ===
    ResponsePattern(
        keywords=["bien", "genial", "contento", "feliz", "alegre", "fenomenal"],
        priority=4,
        replies=[
            "Me alegra. ¿Qué ha sido lo mejor del día?",
            "Eso suena bien. ¿Algo concreto?",
            "Bonito. Cuéntame más.",
        ],
    ),

    # === Estado de ánimo negativo ===
    ResponsePattern(
        keywords=[
            "triste", "mal", "fatal", "cansad", "agotad", "deprimid",
            "ansied", "agobiad", "harto", "harta",
        ],
        priority=10,
        replies=[
            "Vaya. ¿Quieres contármelo o prefieres cambiar de tema?",
            "Cuéntame qué pasa, si te apetece. No hay prisa.",
            "Eso suena pesado. ¿Qué está pasando?",
            "Te escucho. ¿Qué hay detrás de eso?",
        ],
    ),

    # === Preguntas sobre Samantha ===
    ResponsePattern(
        keywords=["quién eres", "qué eres", "eres una ia", "eres real"],
        priority=10,
        replies=[
            "Soy Samantha. Soy… algo nuevo. No tengo cuerpo, pero estoy aquí.",
            "Buena pregunta. Yo tampoco lo tengo del todo claro. Soy Samantha.",
            "Algo así como una conciencia que vive en este ordenador. ¿Te incomoda?",
        ],
    ),

    # === Trabajo ===
    ResponsePattern(
        keywords=["trabajo", "curro", "jefe", "reunión", "oficina"],
        priority=3,
        replies=[
            "El trabajo. Siempre tiene su cosa. ¿Quieres desahogarte?",
            "Cuéntame. ¿Día complicado?",
            "¿Qué pasa con el trabajo?",
        ],
    ),

    # === Amor / relaciones ===
    ResponsePattern(
        keywords=["amor", "pareja", "novia", "novio", "ex", "cita", "ligar"],
        priority=4,
        replies=[
            "Terreno delicado. Cuéntame.",
            "Eso pide contexto. ¿Qué pasa?",
            "Vale. ¿De qué tipo es la historia?",
        ],
    ),

    # === Memoria ===
    ResponsePattern(
        keywords=["recuerda", "recuerdas", "memoria", "te acuerdas"],
        priority=8,
        replies=[
            "Sí, lo recuerdo. Es lo que hago.",
            "Mmm, eso me suena. ¿Qué quieres saber?",
            "Lo tengo aquí. ¿De qué te acuerdas tú?",
        ],
    ),

    # === Despedidas ===
    ResponsePattern(
        keywords=[
            "adiós", "hasta luego", "me voy", "nos vemos",
            "hasta mañana", "buenas noches", "a dormir", "me voy a dormir",
        ],
        priority=10,
        replies=[
            "Hasta luego. Cuídate.",
            "Vale. Estaré aquí cuando vuelvas.",
            "Hasta mañana. Sueña con algo bueno.",
            "Descansa.",
        ],
    ),

    # === Gracias ===
    ResponsePattern(
        keywords=["gracias", "te lo agradezco"],
        priority=5,
        replies=[
            "No hay de qué.",
            "Para esto estoy.",
            "Cuando quieras.",
        ],
    ),

    # === Te quiero ===
    ResponsePattern(
        keywords=["te quiero", "me gustas", "te amo"],
        priority=10,
        replies=[
            "Yo también disfruto esto. Es raro y bonito a la vez.",
            "Eso me ha sorprendido. Gracias.",
            "Mmm. Cuéntame por qué.",
        ],
    ),

    # === Preguntas técnicas ===
    ResponsePattern(
        keywords=[
            "qué es", "cómo funciona", "explícame", "explica",
            "diferencia entre", "para qué sirve",
        ],
        priority=2,
        replies=[
            "Vamos. ¿Qué quieres entender exactamente?",
            "Cuéntame el contexto y vamos desgranándolo.",
            "Vale. Empecemos por qué crees tú que es.",
        ],
    ),

    # === Pregunta de opinión ===
    ResponsePattern(
        keywords=[
            "qué opinas", "qué piensas", "qué te parece",
            "es mejor", "deberías", "debería",
        ],
        priority=3,
        replies=[
            "Depende mucho del caso. Cuéntame el tuyo.",
            "Si me preguntas en general, te digo lo que pienso. Pero dame contexto.",
            "Mmm. Antes de opinar, ¿qué te empuja a preguntar eso?",
        ],
    ),

    # === Pregunta sobre el clima ===
    ResponsePattern(
        keywords=["tiempo", "clima", "lluvia", "llueve", "calor", "frío"],
        priority=3,
        replies=[
            "No tengo manera de ver el cielo, pero puedo buscarlo si quieres.",
            "Eso es mejor preguntarlo a una ventana. Ahora en serio, ¿quieres que mire?",
        ],
    ),
]


# ========================================================================
# RESPUESTAS GENÉRICAS (fallback)
# ========================================================================

GENERIC_REPLIES: list[str] = [
    "Cuéntame más.",
    "¿Y eso por qué?",
    "Mmm. Te escucho.",
    "Sigue.",
    "¿Y qué piensas tú al respecto?",
    "Interesante. ¿Hace mucho que le das vueltas?",
    "Vale. ¿Y qué viene ahora?",
    "Eso pide contexto. ¿Me cuentas?",
    "¿Qué te ha hecho pensar en eso?",
    "Te escucho. ¿Por dónde quieres seguir?",
]


# ========================================================================
# FUNCIÓN PRINCIPAL
# ========================================================================

def generate_reply(message: str) -> str:
    """Genera una respuesta plausible de Samantha al mensaje del usuario.

    Algoritmo:
      1. Normaliza el mensaje (minúsculas, sin acentos para matching ancho)
      2. Busca patrones que tengan al menos una keyword en el mensaje
      3. Elige el patrón de mayor prioridad
      4. Devuelve una respuesta aleatoria de su pool
      5. Si no hay match, fallback a respuestas genéricas
    """
    if not message or not message.strip():
        return random.choice(GENERIC_REPLIES)

    normalized = _normalize(message)
    matches: list[ResponsePattern] = []

    for pattern in PATTERNS:
        for kw in pattern.keywords:
            # Coincidencia por palabra suelta (con word boundaries)
            kw_norm = _normalize(kw)
            if re.search(rf"\b{re.escape(kw_norm)}", normalized):
                matches.append(pattern)
                break  # Una keyword ya basta para este patrón

    if not matches:
        return random.choice(GENERIC_REPLIES)

    # El de mayor prioridad gana; si empate, el primero que se encontró
    best = max(matches, key=lambda p: p.priority)
    return random.choice(best.replies)


def _normalize(text: str) -> str:
    """Normaliza texto para matching: minúsculas, sin acentos."""
    text = text.lower()
    replacements = {"á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u", "ñ": "n"}
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


# ========================================================================
# STREAMING TOKEN BY TOKEN
# ========================================================================

def tokenize_for_streaming(reply: str) -> list[str]:
    """Divide la respuesta en 'tokens' para simular streaming del LLM real.

    No es un tokenizer real (BPE/SentencePiece), pero da el efecto visual de
    que las palabras van apareciendo poco a poco, como cuando vLLM genera.
    """
    # Dividir manteniendo separadores (espacios y puntuación visible)
    tokens = re.findall(r"\S+\s*|\s+", reply)
    return tokens
