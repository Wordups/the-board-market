"""The Board Market — Triggers (publisher side)

Fires events to the Takeoff stateless router. See docs/EVENTS.md for the
contract. Fire-and-forget: never blocks main flow, never raises.
"""

from .emit import emit, EventSeverity
from .types import EVENT_TYPES

__all__ = ["emit", "EventSeverity", "EVENT_TYPES"]
