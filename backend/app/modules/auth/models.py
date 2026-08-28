"""auth-owned tables. The ``users`` table is private to this module — other modules
reach identities through the auth service layer, never by querying it directly
(docs/SYSTEM_ARCHITECTURE.md isolation rule 1).
"""

from enum import StrEnum

from sqlalchemy import Enum, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.modules.auth.domain import Role


class UserStatus(StrEnum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


def _enum_values(enum_cls: type[StrEnum]) -> list[str]:
    return [member.value for member in enum_cls]


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Identity principal (docs/DOMAIN_MODEL.md §1): auth-provider subject, exactly one
    role, account status, verified contact points. Never owns medical data — profiles do.
    """

    __tablename__ = "users"

    firebase_uid: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    # Stored as plain VARCHAR (non-native enum, no CHECK): values are guaranteed by the
    # typed application layer, and adding a role must not require a constraint migration.
    role: Mapped[Role] = mapped_column(
        Enum(Role, name="user_role", native_enum=False, length=20, values_callable=_enum_values),
        nullable=False,
    )
    status: Mapped[UserStatus] = mapped_column(
        Enum(
            UserStatus,
            name="user_status",
            native_enum=False,
            length=20,
            values_callable=_enum_values,
        ),
        nullable=False,
        default=UserStatus.ACTIVE,
    )
    phone: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(255))
