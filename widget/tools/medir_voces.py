"""Whether a voice is telling: the tool that decides task 4's two questions.

Records N spoken utterances per person, embeds each one with `Locutor`
(`pyannote/embedding` over onnxruntime — see
`docs/superpowers/specs/2026-09-06-probe-locutor.md`), and reports the
numbers that settle two questions: is the same person recognised as
himself reliably (part A, gates the founding act), and can two people
who sound alike be told apart at all (part B, sisters of 16 and 17 —
same age, same sex, same house, same accent). If the second answers no,
the family half of the plan falls back to phones — a supported outcome,
not a failure — and part A is unaffected either way.

Two subcommands, because the two things they need are different:

    grabar   records new utterances and appends them to disk, THEN
             prints the report over everything on disk so far.
    informe  reprints the report from what is already on disk. No
             microphone, no model of any kind unless `--reembed` is
             given. This is what lets the floor (`voz.PISO_POR_DEFECTO`)
             and the margin (`voz.MARGEN_POR_DEFECTO`) be chosen, and a
             different embedding model be compared, without calling
             anybody back into the room.

Run only after freeing the microphone — `jarvis-widget.service` holds it
while it is running:

    systemctl --user stop jarvis-widget.service

and start it again once you are done. The tool repeats this in Spanish
when it starts recording, because a PortAudio failure with no
explanation reads as a broken model rather than a busy device:
«El widget tiene que estar parado para soltar el micrófono.»

Both the raw vectors AND the audio of every utterance are kept, under
`~/.jarvis/medicion/`, so the household never has to be gathered again —
not to redo the arithmetic with a different floor, and not to try
`--reembed` against a different model (CAM++ is a live alternative;
`docs/superpowers/specs/2026-09-06-probe-locutor.md`). Vectors cannot be
re-embedded from nothing; audio can be re-embedded from what is kept.

Nothing here touches `voz.PISO_POR_DEFECTO` or `voz.MARGEN_POR_DEFECTO`
— those are chosen from this tool's OUTPUT, by the step that writes the
finding, and inventing them here would defeat the entire point of
measuring first.
"""

from __future__ import annotations

import argparse
import itertools
import queue
import re
import sys
import time
import wave
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jarvis_widget.audio import Microphone
from jarvis_widget.locutor import Locutor
from jarvis_widget.personas import CASA, es_valida
from jarvis_widget.vad import INPUT_RATE, SileroDetector, UtteranceDetector
from jarvis_widget.voz import MARGEN_POR_DEFECTO, Huellas, coseno

BASE_POR_DEFECTO = Path.home() / ".jarvis" / "medicion"

# The turn he will actually hear — not a paragraph. Task brief, step 2a.
_FRASE_POR_DEFECTO = "Jarvis, ¿qué hora es?"

_AVISO_MICROFONO = (
    "El widget tiene que estar parado para soltar el micrófono:\n"
    "    systemctl --user stop jarvis-widget.service\n"
    "y se puede arrancar de nuevo al terminar:\n"
    "    systemctl --user start jarvis-widget.service"
)

# <persona>__<seq de 3 cifras>__<condición>. La condición nunca lleva
# guión bajo (`_sanear_condicion` sólo deja letras, dígitos y guiones),
# así que el separador doble no es ambiguo con nombres de persona
# razonables.
_RE_NOMBRE = re.compile(r"^([a-z0-9][a-z0-9_-]*)__(\d{3})__([a-z0-9-]+)$")

# Cuánto esperar sin ninguna señal de voz antes de recordar, en voz alta,
# que el micrófono correcto importa. No aborta: sólo avisa y sigue
# esperando, porque la persona puede simplemente estar tardando.
_SEGUNDOS_ENTRE_AVISOS = 12.0


@dataclass(eq=False)
class Muestra:
    """One embedded utterance, with enough to group and re-find it."""

    persona: str
    condicion: str
    seq: int
    vector: np.ndarray
    ruta_audio: Path | None


# --------------------------------------------------------------------
# Nombres de archivo
# --------------------------------------------------------------------


def _sanear_condicion(cruda: str) -> str:
    limpia = re.sub(r"[^a-z0-9]+", "-", cruda.strip().casefold()).strip("-")
    return limpia or "estandar"


def _parsear_nombre(stem: str) -> tuple[str, int, str] | None:
    coincidencia = _RE_NOMBRE.match(stem)
    if coincidencia is None:
        return None
    persona, seq, condicion = coincidencia.groups()
    return persona, int(seq), condicion


def _siguiente_seq(base: Path, persona: str) -> int:
    directorio = base / "vectores"
    if not directorio.is_dir():
        return 1
    maximo = 0
    for ruta in directorio.glob(f"{persona}__*.npy"):
        analizado = _parsear_nombre(ruta.stem)
        if analizado is not None and analizado[0] == persona:
            maximo = max(maximo, analizado[1])
    return maximo + 1


def _guardar(
    base: Path, persona: str, condicion: str, seq: int, pcm: bytes, vector: np.ndarray
) -> tuple[Path, Path]:
    audio_dir = base / "audio"
    vector_dir = base / "vectores"
    audio_dir.mkdir(parents=True, exist_ok=True)
    vector_dir.mkdir(parents=True, exist_ok=True)

    nombre = f"{persona}__{seq:03d}__{condicion}"
    ruta_audio = audio_dir / f"{nombre}.wav"
    ruta_vector = vector_dir / f"{nombre}.npy"

    with wave.open(str(ruta_audio), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(INPUT_RATE)
        w.writeframes(pcm)
    np.save(ruta_vector, vector)
    return ruta_audio, ruta_vector


def _cargar_vectores(base: Path) -> list[Muestra]:
    directorio = base / "vectores"
    muestras: list[Muestra] = []
    if not directorio.is_dir():
        return muestras
    for ruta in sorted(directorio.glob("*.npy")):
        analizado = _parsear_nombre(ruta.stem)
        if analizado is None:
            print(f"  (se ignora, nombre inesperado: {ruta.name})", file=sys.stderr)
            continue
        persona, seq, condicion = analizado
        vector = np.load(ruta)
        ruta_audio = base / "audio" / f"{ruta.stem}.wav"
        muestras.append(
            Muestra(
                persona,
                condicion,
                seq,
                vector,
                ruta_audio if ruta_audio.is_file() else None,
            )
        )
    return muestras


def _cargar_desde_audio(base: Path, locutor: Locutor) -> list[Muestra]:
    directorio = base / "audio"
    muestras: list[Muestra] = []
    if not directorio.is_dir():
        return muestras
    for ruta in sorted(directorio.glob("*.wav")):
        analizado = _parsear_nombre(ruta.stem)
        if analizado is None:
            print(f"  (se ignora, nombre inesperado: {ruta.name})", file=sys.stderr)
            continue
        persona, seq, condicion = analizado
        with wave.open(str(ruta), "rb") as w:
            pcm = w.readframes(w.getnframes())
        vector = locutor.vector(pcm)
        if vector is None:
            print(
                f"  (descartada al reincrustar, demasiado corta: {ruta.name})",
                file=sys.stderr,
            )
            continue
        muestras.append(Muestra(persona, condicion, seq, vector, ruta))
    return muestras


# --------------------------------------------------------------------
# Grabar
# --------------------------------------------------------------------


def _vaciar(cola: "queue.Queue") -> None:
    while True:
        try:
            cola.get_nowait()
        except queue.Empty:
            return


def _grabar_persona(
    persona: str,
    condicion: str,
    frase: str,
    n: int,
    base: Path,
    locutor: Locutor,
    detector: UtteranceDetector,
    eventos: "queue.Queue[tuple[str, bytes | None]]",
) -> None:
    print(f"\n--- {persona} ---")
    seq = _siguiente_seq(base, persona)
    ya_grabadas = seq - 1
    if ya_grabadas:
        print(
            f"  ({ya_grabadas} muestra(s) ya guardada(s) para {persona}; se añaden {n} más)"
        )

    conseguidas = 0
    while conseguidas < n:
        _vaciar(eventos)
        print(f"  [{conseguidas + 1}/{n}] diga cuando quiera: «{frase}»")
        empezado_impreso = False
        ultimo_aviso = time.monotonic()
        pcm: bytes | None = None
        while pcm is None:
            try:
                tipo, dato = eventos.get(timeout=0.5)
            except queue.Empty:
                ahora = time.monotonic()
                if ahora - ultimo_aviso >= _SEGUNDOS_ENTRE_AVISOS:
                    print(
                        "      (sigo esperando; compruebe que el micrófono es el correcto)"
                    )
                    ultimo_aviso = ahora
                continue
            if tipo == "empezo" and not empezado_impreso:
                print("      grabando…")
                empezado_impreso = True
            elif tipo == "utterance":
                pcm = dato

        assert pcm is not None
        segundos = len(pcm) / 2 / INPUT_RATE
        vector = locutor.vector(pcm)
        if vector is None:
            print(f"      descartada, demasiado corta ({segundos:.2f} s) — repita")
            continue

        ruta_audio, _ = _guardar(base, persona, condicion, seq, pcm, vector)
        print(f"      hecho ({segundos:.2f} s) → {ruta_audio.relative_to(base)}")
        seq += 1
        conseguidas += 1


def cmd_grabar(args: argparse.Namespace) -> int:
    if args.n < 1:
        print("--n tiene que ser al menos 1", file=sys.stderr)
        return 2

    personas: list[str] = []
    for crudo in args.personas:
        candidato = crudo.strip().casefold()
        if candidato == CASA or not es_valida(candidato):
            print(
                f"«{crudo}» no es un nombre de persona válido "
                "(minúsculas, dígitos, guiones; «casa» está reservado)",
                file=sys.stderr,
            )
            return 2
        personas.append(candidato)

    condicion = _sanear_condicion(args.condicion)
    base: Path = args.dir

    locutor = Locutor()
    if not locutor.listo:
        print(
            "no se pudo cargar el modelo de locutor "
            "(revise JARVIS_WIDGET_LOCUTOR_MODEL o ~/.jarvis/models/pyannote_embedding.onnx)",
            file=sys.stderr,
        )
        return 2

    try:
        probe = SileroDetector()
    except FileNotFoundError as exc:
        print(f"no se pudo cargar el modelo de VAD: {exc}", file=sys.stderr)
        return 2

    detector = UtteranceDetector(probe)
    eventos: "queue.Queue[tuple[str, bytes | None]]" = queue.Queue()

    def on_frame(frame: bytes) -> None:
        antes = detector.speaking
        resultado = detector.push(frame)
        if detector.speaking and not antes:
            eventos.put(("empezo", None))
        if resultado is not None:
            eventos.put(("utterance", resultado))

    mic = Microphone(on_frame)
    print(_AVISO_MICROFONO)
    try:
        mic.start()
    except Exception as exc:
        print(
            f"no se pudo abrir el micrófono ({exc!r}).\n{_AVISO_MICROFONO}",
            file=sys.stderr,
        )
        return 2

    interrumpido = False
    try:
        for persona in personas:
            _grabar_persona(
                persona, condicion, args.frase, args.n, base, locutor, detector, eventos
            )
    except KeyboardInterrupt:
        print("\ninterrumpido; lo grabado hasta ahora queda guardado", file=sys.stderr)
        interrumpido = True
    finally:
        mic.stop()

    print(
        "\nmicrófono cerrado. Puede reiniciar el widget:\n"
        "    systemctl --user start jarvis-widget.service"
    )

    if interrumpido:
        return 130

    muestras = _cargar_vectores(base)
    if muestras:
        _imprimir_informe(muestras, _rango(0.30, 0.90, 0.05), MARGEN_POR_DEFECTO)
    return 0


# --------------------------------------------------------------------
# Informe
# --------------------------------------------------------------------


def _rango(minimo: float, maximo: float, paso: float) -> list[float]:
    pasos = round((maximo - minimo) / paso)
    return [round(minimo + i * paso, 10) for i in range(pasos + 1)]


def _centroide(vectores: list[np.ndarray]) -> np.ndarray:
    return np.mean(np.stack(vectores), axis=0).astype(np.float32)


def _centroides_loo(
    muestra: Muestra, indice: dict[str, list[Muestra]]
) -> dict[str, np.ndarray]:
    """Centroids for scoring ONE utterance: leave-it-out of its own person's.

    Scoring an utterance against a centroid that was built partly FROM
    it inflates its own similarity — worst for the person with the
    fewest samples. Every other person's centroid is unaffected, since
    the utterance was never theirs.
    """
    centroides: dict[str, np.ndarray] = {}
    for persona, lista in indice.items():
        if persona == muestra.persona:
            resto = [m.vector for m in lista if m is not muestra]
            if not resto:
                # Only sample this person has: no leave-one-out centroid
                # exists, so this person is not a candidate for THIS
                # utterance. Huellas({}) already answers CASA safely if
                # nothing else is enrolled either.
                continue
            centroides[persona] = _centroide(resto)
        else:
            centroides[persona] = _centroide([m.vector for m in lista])
    return centroides


def _tabla_confusion(
    muestras: list[Muestra],
    indice: dict[str, list[Muestra]],
    pisos: list[float],
    margen: float,
) -> list[tuple[float, int, int, int, Counter]]:
    filas = []
    for piso in pisos:
        correctas = rechazadas = equivocadas = 0
        ejemplos: Counter = Counter()
        for m in muestras:
            centroides = _centroides_loo(m, indice)
            resultado = Huellas(centroides).quien(m.vector, piso=piso, margen=margen)
            if resultado == m.persona:
                correctas += 1
            elif resultado == CASA:
                rechazadas += 1
            else:
                equivocadas += 1
                ejemplos[(m.persona, resultado)] += 1
        filas.append((piso, correctas, rechazadas, equivocadas, ejemplos))
    return filas


def _imprimir_informe(
    muestras: list[Muestra], pisos: list[float], margen: float
) -> None:
    indice: dict[str, list[Muestra]] = defaultdict(list)
    for m in muestras:
        indice[m.persona].append(m)
    personas = sorted(indice)

    print("\n=== Muestras encontradas ===")
    for p in personas:
        lista = indice[p]
        condiciones = Counter(m.condicion for m in lista)
        detalle = ", ".join(f"{c}: {n}" for c, n in sorted(condiciones.items()))
        print(f"  {p}: {len(lista)} muestra(s) ({detalle})")

    print("\n=== Similitud entre centroides (persona frente a persona) ===")
    if len(personas) < 2:
        print("  sólo hay una persona todavía; no hay comparación cruzada que hacer")
    else:
        centroides_completos = {
            p: _centroide([m.vector for m in indice[p]]) for p in personas
        }
        for a, b in itertools.combinations(personas, 2):
            similitud = coseno(centroides_completos[a], centroides_completos[b])
            print(f"  {a} frente a {b}: {similitud:.3f}")

    print("\n=== Dispersión dentro de cada persona ===")
    for p in personas:
        vectores = [m.vector for m in indice[p]]
        if len(vectores) < 2:
            print(
                f"  {p}: sólo {len(vectores)} muestra(s), no hay dispersión que calcular"
            )
            continue
        pares = [coseno(a, b) for a, b in itertools.combinations(vectores, 2)]
        print(
            f"  {p}: media {sum(pares) / len(pares):.3f}, "
            f"mínima {min(pares):.3f}, máxima {max(pares):.3f} (N={len(vectores)})"
        )

    print("\n=== Margen por muestra (mejor candidato frente al segundo) ===")
    print(
        f"  {'persona':<10} {'condición':<14} {'#':>3}  {'mejor':<18} {'segundo':<18} margen"
    )
    for m in sorted(muestras, key=lambda m: (m.persona, m.condicion, m.seq)):
        centroides = _centroides_loo(m, indice)
        puntuaciones = sorted(
            ((coseno(m.vector, c), persona) for persona, c in centroides.items()),
            reverse=True,
        )
        if not puntuaciones:
            print(
                f"  {m.persona:<10} {m.condicion:<14} {m.seq:03d}  "
                f"(sin candidato — única muestra de {m.persona})"
            )
            continue
        mejor_score, mejor_persona = puntuaciones[0]
        mejor_txt = f"{mejor_persona} {mejor_score:.3f}"
        if len(puntuaciones) > 1:
            segundo_score, segundo_persona = puntuaciones[1]
            segundo_txt = f"{segundo_persona} {segundo_score:.3f}"
            margen_txt = f"{mejor_score - segundo_score:.3f}"
        else:
            segundo_txt = "—"
            margen_txt = "—"
        print(
            f"  {m.persona:<10} {m.condicion:<14} {m.seq:03d}  "
            f"{mejor_txt:<18} {segundo_txt:<18} {margen_txt}"
        )

    print(f"\n=== Confusiones por piso (margen de referencia={margen:.2f}) ===")
    print("  la columna que importa es «equivocadas»: nunca debe tratarse como ruido")
    print(
        f"  {'piso':>5}  {'correctas':>9}  {'casa':>6}  {'equivocadas':>11}  {'total':>5}"
    )
    for piso, correctas, rechazadas, equivocadas, ejemplos in _tabla_confusion(
        muestras, indice, pisos, margen
    ):
        total = correctas + rechazadas + equivocadas
        linea = f"  {piso:>5.2f}  {correctas:>9}  {rechazadas:>6}  {equivocadas:>11}  {total:>5}"
        if ejemplos:
            detalle = ", ".join(f"{a}→{b} x{n}" for (a, b), n in ejemplos.items())
            linea += f"   ({detalle})"
        print(linea)


def cmd_informe(args: argparse.Namespace) -> int:
    if args.floor_step <= 0 or args.floor_min > args.floor_max:
        print(
            "rango de piso inválido (revise --floor-min/--floor-max/--floor-step)",
            file=sys.stderr,
        )
        return 2

    base: Path = args.dir
    if args.reembed:
        locutor = Locutor(args.modelo) if args.modelo else Locutor()
        if not locutor.listo:
            print("no se pudo cargar el modelo para reincrustar", file=sys.stderr)
            return 2
        muestras = _cargar_desde_audio(base, locutor)
    else:
        muestras = _cargar_vectores(base)

    if not muestras:
        print(
            f"no hay medidas guardadas en {base} — "
            "ejecute antes: medir_voces.py grabar <persona>",
            file=sys.stderr,
        )
        return 1

    pisos = _rango(args.floor_min, args.floor_max, args.floor_step)
    _imprimir_informe(muestras, pisos, args.margen)
    return 0


# --------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------


def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="medir_voces.py",
        description=(
            "Mide si una voz se reconoce como suya de forma fiable, y si "
            "dos voces parecidas se pueden distinguir (tarea 4)."
        ),
        epilog=_AVISO_MICROFONO,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="modo", required=True)

    grabar = sub.add_parser(
        "grabar",
        help="graba N frases de una o más personas, y luego imprime el informe",
        epilog=_AVISO_MICROFONO,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    grabar.add_argument(
        "personas",
        nargs="+",
        help="nombre de cada persona a grabar, una o varias, en orden",
    )
    grabar.add_argument(
        "--n",
        type=int,
        default=10,
        help="cuántas frases grabar por persona (por defecto 10)",
    )
    grabar.add_argument(
        "--condicion",
        default="estandar",
        help="etiqueta de la condición: distancia, tele, cansado, susurro… (por defecto «estandar»)",
    )
    grabar.add_argument(
        "--frase", default=_FRASE_POR_DEFECTO, help="qué decir en cada grabación"
    )
    grabar.add_argument(
        "--dir",
        type=Path,
        default=BASE_POR_DEFECTO,
        help="dónde guardar audio y vectores",
    )
    grabar.set_defaults(func=cmd_grabar)

    informe = sub.add_parser(
        "informe",
        help="recalcula el informe a partir de lo ya guardado — sin micrófono",
    )
    informe.add_argument(
        "--dir",
        type=Path,
        default=BASE_POR_DEFECTO,
        help="dónde están audio y vectores",
    )
    informe.add_argument("--floor-min", type=float, default=0.30, dest="floor_min")
    informe.add_argument("--floor-max", type=float, default=0.90, dest="floor_max")
    informe.add_argument("--floor-step", type=float, default=0.05, dest="floor_step")
    informe.add_argument(
        "--margen",
        type=float,
        default=MARGEN_POR_DEFECTO,
        help=f"margen de referencia para la tabla de confusiones (por defecto {MARGEN_POR_DEFECTO})",
    )
    informe.add_argument(
        "--reembed",
        action="store_true",
        help="en vez de los vectores guardados, vuelve a incrustar el audio guardado",
    )
    informe.add_argument(
        "--modelo",
        type=Path,
        default=None,
        help="modelo .onnx para --reembed (por defecto el de JARVIS_WIDGET_LOCUTOR_MODEL)",
    )
    informe.set_defaults(func=cmd_informe)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = construir_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
