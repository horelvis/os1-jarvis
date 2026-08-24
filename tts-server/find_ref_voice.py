"""Pesca 10 candidatas de voz para clonar Samantha.

Stream del dataset (sin descargar los 50 GB enteros): filtra a mujer +
acento de España, duración 4-10 s, y guarda WAV + transcripción.

Uso:
    python find_ref_voice.py --count 10 --out ~/.samantha/ref-candidates
"""

from __future__ import annotations

import argparse
from pathlib import Path

import soundfile as sf
from datasets import load_dataset


def is_female(row: dict) -> bool:
    g = (row.get("gender") or "").lower()
    return "female" in g or g == "feminine"


def is_spain(row: dict) -> bool:
    """Common Voice usa 'variant' (castellano) y/o 'accent' libre."""
    variant = (row.get("variant") or "").lower()
    accent = (row.get("accent") or "").lower()
    return (
        "castellano" in variant
        or "españa" in accent
        or "european spanish" in accent
        or "castile" in accent
    )


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--count", type=int, default=10)
    p.add_argument("--out", type=Path, default=Path("./ref-candidates"))
    p.add_argument("--min-seconds", type=float, default=4.0)
    p.add_argument("--max-seconds", type=float, default=10.0)
    args = p.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    print("Streaming Common Voice 17 (es, validated)...")
    ds = load_dataset(
        "fsicoli/common_voice_17_0",
        "es",
        split="train",
        streaming=True,
        trust_remote_code=True,
    )

    n = 0
    for row in ds:
        if n >= args.count:
            break
        if not is_female(row) or not is_spain(row):
            continue
        audio = row["audio"]
        arr, sr = audio["array"], audio["sampling_rate"]
        dur = len(arr) / sr
        if not (args.min_seconds <= dur <= args.max_seconds):
            continue

        n += 1
        idx = f"{n:02d}"
        sf.write(str(args.out / f"cand-{idx}.wav"), arr, sr)
        (args.out / f"cand-{idx}.txt").write_text(
            row["sentence"] + "\n", encoding="utf-8"
        )
        print(f'  [{idx}] {dur:.1f}s — "{row["sentence"][:80]}"')

    print(f"\nGuardados {n} candidatos en {args.out.resolve()}")
    print("Escucha cada cand-NN.wav y dime el número que prefieres.")


if __name__ == "__main__":
    main()
