"""Domain errors raised by the consent module."""


class ConsentError(Exception):
    """Base for all consent domain errors."""

    def __init__(self, detail: str = "Consent operation failed.") -> None:
        super().__init__(detail)
        self.detail = detail


class ConsentDeniedError(ConsentError):
    """Raised when an actor attempts to access medical content without an active grant."""

    def __init__(self, detail: str = "Access denied: no active consent grant found.") -> None:
        super().__init__(detail)


class AccessRequestNotFoundError(ConsentError):
    def __init__(self, detail: str = "Access request not found.") -> None:
        super().__init__(detail)


class ConsentGrantNotFoundError(ConsentError):
    def __init__(self, detail: str = "Consent grant not found.") -> None:
        super().__init__(detail)


class InvalidAccessRequestError(ConsentError):
    def __init__(self, detail: str = "Invalid access request configuration.") -> None:
        super().__init__(detail)


class InvalidConsentStateError(ConsentError):
    def __init__(
        self, detail: str = "Access request cannot be decided in its current state."
    ) -> None:
        super().__init__(detail)


class UnauthorizedConsentActionError(ConsentError):
    def __init__(
        self, detail: str = "User is not authorized to perform this consent action."
    ) -> None:
        super().__init__(detail)
