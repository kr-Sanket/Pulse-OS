"""Domain errors raised by the hospitals module."""


class HospitalError(Exception):
    """Base for all hospitals domain errors."""

    def __init__(self, detail: str = "Hospital operation failed.") -> None:
        super().__init__(detail)
        self.detail = detail


class DuplicateHospitalIdError(HospitalError):
    def __init__(self, detail: str = "A hospital with this identifier already exists.") -> None:
        super().__init__(detail)


class HospitalNotFoundError(HospitalError):
    def __init__(self, detail: str = "Hospital not found.") -> None:
        super().__init__(detail)


class HospitalValidationError(HospitalError):
    def __init__(self, detail: str = "Hospital validation failed.") -> None:
        super().__init__(detail)
