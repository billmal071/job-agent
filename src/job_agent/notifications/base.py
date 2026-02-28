"""Abstract notifier base class."""

from __future__ import annotations

from abc import ABC, abstractmethod


class Notifier(ABC):
    """Abstract base for notification channels."""

    @abstractmethod
    def send(self, title: str, message: str, event_type: str = "") -> bool:
        """Send a notification. Returns True if successful."""

    def should_notify(self, event_type: str, triggers: list[str]) -> bool:
        """Check if this event type should trigger a notification."""
        return event_type in triggers
