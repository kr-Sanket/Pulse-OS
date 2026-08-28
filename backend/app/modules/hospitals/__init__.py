"""Hospitals module: hospital organization management and lookup."""

from app.modules.hospitals.models import Hospital, HospitalStatus
from app.modules.hospitals.service import HospitalService

__all__ = ["Hospital", "HospitalService", "HospitalStatus"]
