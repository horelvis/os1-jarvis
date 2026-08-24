"""samantha-vision — throwaway probe for "how does a plugin speak first?"."""

from .probe_deliver import schedule_probe

__all__ = ["register"]


def register(ctx):
    """Arm the probe.

    ``register()`` is the ONLY entry point a plugin gets: there is no
    lifecycle hook that fires once the gateway is up (see PROBE.md), so a
    plugin that wants to act later has to start its own timer here.
    """
    schedule_probe(ctx)
