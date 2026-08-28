"""Domain errors raised by the doctors module."""


class DoctorError(Exception):
    """Base for all doctors domain errors."""

    def __init__(self, detail: str = "Doctor operation failed.") -> None:
        super().__init__(detail)
        self.detail = detail


class DuplicateDoctorError(DoctorError):
    def __init__(self, detail: str = "A doctor profile already exists for this user.") -> None:
        super().__init__(detail)


class DuplicateRegistrationNumberError(DoctorError):
    def __init__(
        self, detail: str = "A doctor with this registration number already exists."
    ) -> None:
        super().__init__(detail)


class DoctorNotFoundError(DoctorError):
    def __init__(self, detail: str = "Doctor profile not found.") -> None:
        super().__init__(detail)


class InvalidDoctorUserError(DoctorError):
    def __init__(self, detail: str = "User is not eligible to be registered as a doctor.") -> None:
        super().__init__(detail)


class InvalidHospitalError(DoctorError):
    def __init__(self, detail: str = "Specified hospital does not exist.") -> None:
        super().__init__(detail)


class DoctorValidationError(DoctorError):
    def __init__(self, detail: str = "Doctor validation failed.") -> None:
        super().__init__(detail)
