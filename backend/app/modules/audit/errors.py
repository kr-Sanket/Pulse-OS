"""Domain errors raised by the audit module."""


class AuditError(Exception):
    """Base for all audit domain errors."""

    def __init__(self, detail: str = "Audit operation failed.") -> None:
        super().__init__(detail)
        self.detail = detail


class AuditEventNotFoundError(AuditError):
    def __init__(self, detail: str = "Audit event not found.") -> None:
        super().__init__(detail)


class AuditIntegrityError(AuditError):
    def __init__(self, detail: str = "Audit event tamper verification failed.") -> None:
        super().__init__(detail)


class AuditValidationError(AuditError):
    def __init__(self, detail: str = "Audit validation failed.") -> None:
        super().__init__(detail)
