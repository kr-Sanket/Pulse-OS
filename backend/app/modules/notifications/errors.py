"""Domain errors for the notifications module (ADR-031)."""


class NotificationError(Exception):
    """Base exception for all notifications domain errors."""


class NotificationNotFoundError(NotificationError):
    """Notification does not exist or does not belong to the requesting recipient."""
