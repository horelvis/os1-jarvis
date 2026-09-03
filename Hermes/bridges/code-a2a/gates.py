"""What the assistant may not do without asking.

The spec's policy, and only it: `git push`, recursive deletes, `sudo`.
The user chose full scope on 2026-08-26 and narrowed it on 2026-08-27
(the design doc has both decisions); the narrowing is this list.

Only Bash is gated. An Edit inside the project root is one
`git checkout` from undone; a push or an rm is not. The match is a
folded substring over the command — a policy anybody can read in the
systemd unit, not a parser.
"""

from __future__ import annotations

DEFAULT_PATTERNS: tuple[str, ...] = ("git push", "rm -r", "rm -f", "sudo")

# What the description may carry back to the strip and the voice.
MAX_CHARS = 160


def load_patterns(value: str | None) -> tuple[str, ...]:
    """The policy from `JARVIS_CODE_GATES`, or the default.

    Set, the variable IS the policy (comma-separated), so an entry can
    be removed as well as added without touching code.
    """
    if not value or not value.strip():
        return DEFAULT_PATTERNS
    return tuple(p.strip().casefold() for p in value.split(",") if p.strip())


def dangerous(
    tool: str, args: dict, patterns: tuple[str, ...] = DEFAULT_PATTERNS
) -> str | None:
    """A short description of the action when it needs permission, else None."""
    if tool != "Bash" or not isinstance(args, dict):
        return None
    command = str(args.get("command") or "")
    folded = command.casefold()
    for pattern in patterns:
        if pattern in folded:
            return command.strip()[:MAX_CHARS]
    return None
