"""Short passages he asks a person to read aloud, to learn their voice.

`locutor.Locutor.vector()` (task 4) refuses anything under about a
second of audio, and `encuentro.Encuentro`'s `PIDIENDO` used to ask for
a sample by saying "dígame algo, lo que quiera" — which leaves a person
improvising with no idea whether three words will do. They say
something short, it is refused, and they are asked again with no
explanation of what was wrong: a bad first minute with a machine that
is about to become theirs.

What this module gives him instead: something to hand over and read,
not a blank prompt to fill in. Every passage in `LECTURAS`:

- Is roughly ten to fifteen words — comfortably longer than the second
  `Locutor` needs, read aloud in about three or four seconds.
- Is ordinary and neutral: the weather, the kitchen, the street outside
  — nothing anybody would feel silly saying out loud in their own
  home, and nothing that reads like a legal notice.
- Assigns no gender to whoever reads it.

Twenty of them, not one: a voiceprint centroid built from the same
sentence three times is a centroid of that sentence as much as of the
voice (`voz.Huellas` averages raw samples), so `elegir` hands out
distinct passages across one pairing rather than repeating one.
"""

from __future__ import annotations

import random

LECTURAS: tuple[str, ...] = (
    "El café está listo desde hace un rato en la cocina.",
    "Hoy el cielo tiene ese azul que solo dura una tarde.",
    "El perro del vecino ladra cada vez que pasa el cartero.",
    "En verano el pan se pone duro antes de la hora de comer.",
    "La lluvia empezó justo cuando salíamos a dar un paseo.",
    "Dejé las llaves encima de la mesa, junto a la fruta.",
    "El tren de las nueve siempre llega con algo de retraso.",
    "Compré naranjas, pan y un poco de queso para la semana.",
    "El jardín necesita agua, pero todavía es pronto para regarlo.",
    "Anoche se fue la luz durante casi media hora entera.",
    "El gato duerme casi todo el día encima del sofá.",
    "Hace tiempo que no vemos una tormenta como la de ayer.",
    "El pescado fresco huele distinto al que llevan varios días.",
    "La plaza se llena de gente los sábados por la mañana.",
    "El reloj de la cocina va un poco adelantado, como siempre.",
    "Se nota que el otoño ya está cerca por las mañanas.",
    "La radio del coche solo coge bien esa emisora antigua.",
    "El vecino de arriba riega las plantas todos los días.",
    "Hoy no ha hecho tanto frío como decían por la mañana.",
    "El mercado cierra antes los martes, no sé muy bien por qué.",
)


def elegir(n: int) -> list[str]:
    """`n` passages from `LECTURAS`, distinct from each other whenever
    that many distinct ones exist.

    Never raises, whatever `n` is: a negative or zero `n` gives an
    empty list, and an `n` larger than `len(LECTURAS)` gives every
    passage once — shuffled — followed by more passages chosen the same
    way, rather than refusing. That branch is not expected to matter in
    practice (`n_muestras` is a handful), but nothing about how many
    samples a pairing asks for should be able to break the reading
    material.
    """
    n = max(0, n)
    if n <= len(LECTURAS):
        return random.sample(LECTURAS, n)
    primera_vuelta = list(LECTURAS)
    random.shuffle(primera_vuelta)
    return primera_vuelta + elegir(n - len(LECTURAS))
