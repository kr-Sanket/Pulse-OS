"""Doctors module: clinician management, hospital affiliation, and profile read."""

from app.modules.doctors.models import Doctor
from app.modules.doctors.service import DoctorService

__all__ = ["Doctor", "DoctorService"]
