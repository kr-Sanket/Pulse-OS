"""notifications module — owns its routers, services, repositories, schemas, and models.

See docs/SYSTEM_ARCHITECTURE.md for module responsibilities and isolation rules, and
ADR-031 for in-app delivery and persistence decisions.
"""

from app.modules.notifications.models import Notification, NotificationEventType
from app.modules.notifications.repository import NotificationRepository
from app.modules.notifications.router import router
from app.modules.notifications.service import NotificationService

__all__ = [
    "Notification",
    "NotificationEventType",
    "NotificationRepository",
    "NotificationService",
    "router",
]
