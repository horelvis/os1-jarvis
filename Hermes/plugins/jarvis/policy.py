"""Server-owned admission policy for JARVIS turns.

This is deliberately independent of Hermes internals: the adapter can prove
what it admitted even when its no-Hermes test shim is in use. Profile routing
and tool enforcement still require the explicit Hermes configuration documented
in ``jarvis-config.yaml``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

CASA = "casa"
ORELVIS = "orelvis"

# The existing JARVIS platform toolsets. Keep this list here rather than
# inheriting a process-wide default, which could silently widen mobile access.
FULL_TOOLSETS = (
    "memory",
    "session_search",
    "cronjob",
    "todo",
    "clarify",
    "camaras",
    "web",
    "a2a",
    "codigo",
    "terminal",
    "clases",
    "file",
)


class PolicyError(ValueError):
    """The principal or server policy cannot be admitted safely."""


@dataclass(frozen=True)
class PolicySnapshot:
    """The policy fixed at admission, never supplied by a client frame."""

    principal: str
    profile: str
    toolsets: tuple[str, ...]
    local_only: bool
    fingerprint: str


class PolicyResolver:
    """Resolve only explicitly approved principals and detect live mutation."""

    def __init__(self, config: dict[str, Any] | None) -> None:
        self._config = config if isinstance(config, dict) else {}
        self._fingerprint = self._fingerprint_for(self._config)

    @staticmethod
    def _fingerprint_for(config: dict[str, Any]) -> str:
        try:
            encoded = json.dumps(
                config, sort_keys=True, separators=(",", ":"), default=str
            )
        except (TypeError, ValueError) as exc:
            raise PolicyError("policy configuration cannot be serialized") from exc
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def _assert_unchanged(self) -> None:
        if self._fingerprint_for(self._config) != self._fingerprint:
            raise PolicyError("policy changed after the mobile listener started")

    def desktop_principal(self) -> str:
        configured = self._config.get("desktop_principal", CASA)
        if configured in {CASA, ORELVIS}:
            return configured
        return CASA

    def admit_desktop(self) -> PolicySnapshot:
        # Desktop/legacy input has no per-person authentication. It stays
        # available during migration, but its client identity is never trusted.
        return self._snapshot(self.desktop_principal())

    def admit_mobile(self, principal: str) -> PolicySnapshot:
        self._assert_unchanged()
        if not self.local_provider_ready():
            raise PolicyError("the required local model provider is not verified")
        return self._snapshot(principal)

    def _snapshot(self, principal: str) -> PolicySnapshot:
        if principal == ORELVIS:
            toolsets = FULL_TOOLSETS
        elif principal == CASA:
            toolsets = ()
        else:
            raise PolicyError("principal has no JARVIS policy")
        return PolicySnapshot(
            principal=principal,
            profile=principal,
            toolsets=toolsets,
            local_only=True,
            fingerprint=self._fingerprint,
        )

    def local_provider_ready(self) -> bool:
        """Require the current JARVIS local Gemma endpoint, never a fallback."""
        provider = self._config.get("local_provider")
        if not isinstance(provider, dict):
            return False
        if provider.get("provider") != "custom:local":
            return False
        if provider.get("model") != "qwen3.8-27b":
            return False
        base_url = provider.get("base_url")
        if not isinstance(base_url, str):
            return False
        try:
            parsed = urlsplit(base_url)
        except ValueError:
            return False
        return parsed.scheme == "http" and parsed.hostname in {
            "127.0.0.1",
            "::1",
            "localhost",
        }
