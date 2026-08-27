"""What the band says for each firehose event. Pure; no gateway.

The wording deliberately duplicates `milestones.plain()` in the bridge:
two processes, two vocabularies, no import across the seam — the same
stance `live.summarise` documents against `bridges/code-a2a/stream.py`.
"""

from __future__ import annotations

_LINES = {
    "read": "Leyendo el proyecto…",
    "tests": "Pasando los tests…",
}


def render(event: dict) -> str | None:
    """One firehose payload → one console line, or None to drop it."""
    what = event.get("event")
    if what == "milestone":
        kind = event.get("kind") or ""
        detail = str(event.get("detail") or "")
        if kind in _LINES:
            return _LINES[kind]
        if kind == "edit":
            return f"Editando {detail}"
        if kind == "run":
            return f"Ejecutando: {detail}"
        if kind == "tests_out":
            # "errors" before "error": the plural contains the singular
            # as a substring, and the singular is already valid Spanish
            # (no translation needed) — replacing it first would leave
            # a stray "s" on the plural.
            spanish = (
                detail.replace("passed", "pasan")
                .replace("failed", "fallan")
                .replace("errors", "errores")
            )
            return f"Tests: {spanish}"
        if kind == "note":
            return detail or None
        return str(event.get("text") or "") or None
    if what == "ask":
        text = str(event.get("text") or "")
        qkind = event.get("qkind")
        if qkind == "question":
            return f"? {text}"
        if qkind == "gate":
            return f"? Quiere: {text}"
        return None  # the checkpoint is the voice's; the band shows the end line
    return None


class Dedup:
    """Consecutive repeats out — belt to the bridge's braces."""

    def __init__(self) -> None:
        self._last: str | None = None

    def feed(self, line: str) -> str | None:
        if line == self._last:
            return None
        self._last = line
        return line
