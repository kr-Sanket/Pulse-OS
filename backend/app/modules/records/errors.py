"""Domain errors raised by the records module."""


class RecordError(Exception):
    """Base for all records domain errors."""

    def __init__(self, detail: str = "Medical record operation failed.") -> None:
        super().__init__(detail)
        self.detail = detail


class RecordNotFoundError(RecordError):
    def __init__(self, detail: str = "Medical record not found.") -> None:
        super().__init__(detail)


class RecordCategoryNotFoundError(RecordError):
    def __init__(self, detail: str = "Record category not found.") -> None:
        super().__init__(detail)


class DuplicateCategoryCodeError(RecordError):
    def __init__(self, detail: str = "A record category with this code already exists.") -> None:
        super().__init__(detail)


class InvalidRecordPatientError(RecordError):
    def __init__(self, detail: str = "Target patient does not exist.") -> None:
        super().__init__(detail)


class InvalidRecordOriginError(RecordError):
    def __init__(self, detail: str = "Invalid record origin configuration.") -> None:
        super().__init__(detail)


class InvalidRecordHospitalError(RecordError):
    def __init__(self, detail: str = "Uploading hospital does not exist.") -> None:
        super().__init__(detail)


class InvalidRecordDoctorError(RecordError):
    def __init__(self, detail: str = "Uploading doctor does not exist.") -> None:
        super().__init__(detail)


class RecordValidationError(RecordError):
    def __init__(self, detail: str = "Medical record validation failed.") -> None:
        super().__init__(detail)
