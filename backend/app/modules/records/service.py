"""Records domain service: upload → object storage, metadata queries, presigned downloads.

Read authorization is ADR-013's ordered layers meeting at one seam. Layer 2 — a hospital
reads what it uploaded — is decided here, because only this module knows who uploaded what.
Everything else goes through ``consent.enforce``: a patient reading their own records passes
trivially and is still logged, and a clinician passes only on an active grant
(docs/SYSTEM_ARCHITECTURE.md rule 3). Every read of record content crosses that seam exactly
once, and a refusal is reported as "not found" so existence never leaks.

One read is scoped rather than authorized: the clinician listing (ADR-020) filters a page
by the categories ``consent`` reports as granted, so that a doctor holding a grant can
finally learn which record ids it covers. That is not a second authorization path — the
listing hands out identifiers and a narrow projection, and every record reached from it
still passes ``enforce`` one at a time.

Framework-free; owns no transaction. The object-storage write happens AFTER the metadata
flush, so a DB failure never leaves a file behind, and a storage failure rolls back the
row (an orphan object is only possible if the final request commit itself fails — rare,
harmless, unreferenced).
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Final, Protocol
from uuid import UUID, uuid4

from app.core.queue import JobQueue, QueueUnavailableError
from app.modules.auth.domain import AuthenticatedUser, Role
from app.modules.consent.errors import AccessDeniedError
from app.modules.consent.models import AuditAction
from app.modules.patients.directory import PatientDirectoryService
from app.modules.records.errors import (
    ClinicianNotActiveError,
    ConsentRequiredError,
    EmptyFileError,
    FileTooLargeError,
    HospitalNotVerifiedError,
    InvalidExportRequestError,
    ProfileNotFoundError,
    RecordNotFoundError,
    UnknownCategoryError,
    UnknownPatientError,
    UnsupportedFileTypeError,
)
from app.modules.records.fhir_export import (
    create_fhir_bundle,
    serialize_bundle_to_json,
)
from app.modules.records.models import (
    DoctorStatus,
    Hospital,
    HospitalVerificationStatus,
    MedicalRecord,
    RecordCategory,
    RecordOrigin,
)
from app.modules.records.repository import (
    DoctorRepository,
    HospitalAdminRepository,
    HospitalRepository,
    MedicalRecordRepository,
    RecordCategoryRepository,
    RecordRow,
)
from app.modules.records.storage import ObjectStorage
from app.shared.pagination import (
    DateCursor,
    SortDirection,
    encode_date_cursor,
)
from app.shared.time import utc_now

logger = logging.getLogger(__name__)

#: Accepted medical-document formats (docs/PROJECT_OVERVIEW.md: reports are PDFs/scans).
ALLOWED_CONTENT_TYPES: Final = ("application/pdf", "image/jpeg", "image/png")

#: ``medical_records.original_filename`` is VARCHAR(255). PostgreSQL counts characters,
#: not bytes, so a ``len()`` over the decoded filename is the same measure; validated at the
#: upload boundary so an over-long name is a 422 rather than a database error.
MAX_FILENAME_LENGTH: Final = 255

#: Worker task emitted per upload (ADR-014); the M5 pipeline consumes it.
RECORD_UPLOADED_TASK: Final = "record_uploaded"


class ConsentEnforcer(Protocol):
    """The consent module's authorization choke point, as this module needs it.

    A protocol rather than an import of ``ConsentService`` so the dependency is one method
    wide: records asks whether a read is permitted and consent answers by returning or
    raising, auditing the outcome either way (ADR-013 layer 3, ADR-004).
    """

    async def enforce(
        self,
        requester: AuthenticatedUser,
        *,
        patient_id: UUID,
        category_id: UUID,
        action: AuditAction,
        record_id: UUID | None = None,
        request_context: str | None = None,
    ) -> None: ...


class GrantScope(Protocol):
    """What the consent module says this caller may currently read (ADR-020).

    A second protocol beside ``ConsentEnforcer`` rather than a second method on it, because
    the two have opposite shapes and opposite risks. ``enforce`` returns nothing and raises
    — a caller cannot proceed by ignoring it. This returns a set, which a caller *could*
    misread as permission. Keeping them apart is what makes that mistake ungrammatical:
    there is no way to hold a ``GrantScope`` and accidentally call it to authorize a single
    record, and no way to hold a ``ConsentEnforcer`` and use it to filter a page.

    **This is a filter, never a verdict.** It narrows what a listing offers; it does not
    permit a read. Every record reached from a listing is still authorized one at a time by
    ``ConsentEnforcer.enforce`` (docs/SYSTEM_ARCHITECTURE.md rule 3), which is why a record
    id learned from a listing is worth nothing once the grant behind it is revoked.
    """

    async def granted_category_ids(
        self, requester: AuthenticatedUser, *, patient_id: UUID, at: datetime
    ) -> frozenset[UUID]: ...


class ListingAuditor(Protocol):
    """How a clinician listing reaches the patient's audit trail (ADR-020).

    A third protocol, for the same reason there are two above: a scope query must stay
    free of side effects, and an audit append is nothing but one. Merging them would hide
    a write behind a question and make the scope query unusable anywhere it must not
    touch the trail.

    The audit log belongs to ``consent`` (isolation rule 1), so this module states that a
    listing happened and consent decides what to call it and writes the row.
    """

    async def record_listing(
        self,
        requester: AuthenticatedUser,
        *,
        patient_id: UUID,
        granted_category_ids: frozenset[UUID],
        at: datetime,
        request_context: str | None = None,
    ) -> None: ...


class RecordAuditor(Protocol):
    """How this module records the events ``consent.enforce`` never sees (ADR-022).

    A fourth seam beside ``ConsentEnforcer``, ``GrantScope`` and ``ListingAuditor``, for the
    same reason there are three: each answers a different question, and merging them would
    let a caller reach the wrong one. These two ask nothing — they state that something
    already happened. ``records`` decided; ``consent`` owns the trail and writes it.

    Two purpose-named methods rather than one general "write an event", so this module
    cannot reach the rest of the audit vocabulary. It may record an upload and it may record
    a relationship-authorized read, and there is no third thing it can say.
    """

    async def record_upload(
        self,
        actor: AuthenticatedUser,
        *,
        patient_id: UUID,
        record_id: UUID,
        actor_hospital_id: UUID | None = None,
        request_context: str | None = None,
    ) -> None: ...

    async def record_direct_read(
        self,
        actor: AuthenticatedUser,
        *,
        patient_id: UUID,
        record_id: UUID,
        action: AuditAction,
        allowed: bool,
        actor_hospital_id: UUID | None = None,
        request_context: str | None = None,
    ) -> None: ...


class ExportAuditor(Protocol):
    """How a FHIR clinical record export reaches the patient's audit trail (FHIR-01).

    A fifth seam beside ConsentEnforcer, GrantScope, ListingAuditor, and RecordAuditor.
    Writes RECORD_EXPORTED on success, or ACCESS_DENIED when an unconsented clinician
    attempts to export records.
    """

    async def record_export(
        self,
        requester: AuthenticatedUser,
        *,
        patient_id: UUID,
        granted_category_ids: frozenset[UUID] | None = None,
        at: datetime,
        request_context: str | None = None,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class FileUpload:
    """The validated-at-the-boundary upload payload, already fully read into memory
    (the router enforces the size cap while reading)."""

    filename: str
    content_type: str
    data: bytes


@dataclass(frozen=True, slots=True)
class RecordView:
    record: MedicalRecord
    category: RecordCategory
    hospital: Hospital | None


@dataclass(frozen=True, slots=True)
class RecordPage:
    items: list[RecordView]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class GrantedRecordPage:
    """One page of a clinician's consented view of a patient.

    Carries the granted categories beside the records because the two answer different
    questions and one cannot be inferred from the other: an empty page under a live grant
    ("the patient has nothing in what you were given") and an empty page under no grant
    ("you were given nothing") are clinically different situations that would otherwise
    render identically.
    """

    items: list[RecordView]
    next_cursor: str | None
    granted_categories: list[RecordCategory]
    patient_id: UUID


@dataclass(frozen=True, slots=True)
class DownloadLink:
    url: str
    expires_in_seconds: int


class RecordService:
    def __init__(
        self,
        records: MedicalRecordRepository,
        categories: RecordCategoryRepository,
        admins: HospitalAdminRepository,
        doctors: DoctorRepository,
        hospitals: HospitalRepository,
        patients: PatientDirectoryService,
        storage: ObjectStorage,
        queue: JobQueue,
        consent: ConsentEnforcer,
        grant_scope: GrantScope,
        listing_auditor: ListingAuditor,
        record_auditor: RecordAuditor,
        export_auditor: ExportAuditor | None = None,
        *,
        presign_ttl_seconds: int,
        max_upload_bytes: int,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._records = records
        self._categories = categories
        self._admins = admins
        self._doctors = doctors
        self._hospitals = hospitals
        self._patients = patients
        self._storage = storage
        self._queue = queue
        # Five names, one collaborator in production (ADR-016 direction 2, ADR-020,
        # ADR-022, FHIR-01): asking permission, asking what is in scope, recording that
        # a listing happened, recording events that never reach the choke point, and
        # recording exports are different questions, and a seam per question keeps them apart.
        self._consent = consent
        self._grant_scope = grant_scope
        self._listing_auditor = listing_auditor
        self._record_auditor = record_auditor
        self._export_auditor = (
            export_auditor
            if export_auditor is not None
            else (consent if hasattr(consent, "record_export") else None)
        )
        self._presign_ttl_seconds = presign_ttl_seconds
        self.max_upload_bytes = max_upload_bytes
        self._now = clock

    # -- uploads ---------------------------------------------------------------------

    async def upload_for_health_id(
        self,
        caller: AuthenticatedUser,
        *,
        patient_health_id: str,
        category_code: str,
        date_of_service: date,
        description: str | None,
        file: FileUpload,
        request_context: str | None = None,
    ) -> RecordView:
        """Hospital admin uploads a record against a patient's Health ID (the M2 gate
        flow). Requires a VERIFIED hospital (ADR-015)."""
        self._validate_file(file)
        admin = await self._admins.get_by_user_id(caller.user_id)
        if admin is None:
            raise ProfileNotFoundError()
        hospital = await self._hospitals.get_by_id(admin.hospital_id)
        if hospital is None:
            raise ProfileNotFoundError()
        if hospital.verification_status is not HospitalVerificationStatus.VERIFIED:
            raise HospitalNotVerifiedError()
        patient = await self._patients.get_by_health_id(patient_health_id)
        if patient is None:
            raise UnknownPatientError()
        category = await self._resolve_category(category_code)
        record = await self._store(
            caller,
            patient_id=patient.id,
            category=category,
            origin=RecordOrigin.HOSPITAL_UPLOAD,
            uploaded_by_hospital_id=hospital.id,
            date_of_service=date_of_service,
            description=description,
            file=file,
            request_context=request_context,
            actor_hospital_id=hospital.id,
        )
        return RecordView(record=record, category=category, hospital=hospital)

    async def upload_to_own_locker(
        self,
        caller: AuthenticatedUser,
        *,
        category_code: str,
        date_of_service: date,
        description: str | None,
        file: FileUpload,
        request_context: str | None = None,
    ) -> RecordView:
        """Patient uploads to their own medical locker (RBAC: own locker only)."""
        self._validate_file(file)
        patient = await self._patients.get_by_user_id(caller.user_id)
        if patient is None:
            raise ProfileNotFoundError()
        category = await self._resolve_category(category_code)
        record = await self._store(
            caller,
            patient_id=patient.id,
            category=category,
            origin=RecordOrigin.PATIENT_LOCKER,
            uploaded_by_hospital_id=None,
            date_of_service=date_of_service,
            description=description,
            file=file,
            request_context=request_context,
            actor_hospital_id=None,
        )
        return RecordView(record=record, category=category, hospital=None)

    # -- reads (ADR-013 layers 2 + 3 — see module docstring) --------------------------

    async def list_for_caller(
        self,
        caller: AuthenticatedUser,
        *,
        category_code: str | None,
        search: str | None = None,
        sort: SortDirection = SortDirection.NEWEST_FIRST,
        after: DateCursor | None,
        limit: int,
    ) -> RecordPage:
        """The caller's relationship-scoped record listing, in clinical-date order.

        ``sort``, ``search`` and ``category_code`` together define *which* sequence is being
        paginated, so a cursor is only meaningful alongside the same three. The router
        rejects a cursor that disagrees with ``sort``; the other two the client resets, which
        the frontend does by dropping the cursor whenever a control changes.
        """
        category_id: UUID | None = None
        if category_code is not None:
            category_id = (await self._resolve_category(category_code)).id
        if caller.role is Role.PATIENT:
            patient = await self._patients.get_by_user_id(caller.user_id)
            if patient is None:
                raise ProfileNotFoundError()
            rows = await self._records.list_page(
                patient_id=patient.id,
                category_id=category_id,
                search=search,
                sort=sort,
                after=after,
                limit=limit + 1,
            )
        elif caller.role is Role.HOSPITAL_ADMIN:
            admin = await self._admins.get_by_user_id(caller.user_id)
            if admin is None:
                raise ProfileNotFoundError()
            rows = await self._records.list_page(
                uploaded_by_hospital_id=admin.hospital_id,
                category_id=category_id,
                search=search,
                sort=sort,
                after=after,
                limit=limit + 1,
            )
        else:
            # No other role has a listing scope. Fail closed by construction rather than
            # by relying on the route's gate to admit nobody else.
            raise ProfileNotFoundError()
        has_more = len(rows) > limit
        page = rows[:limit]
        next_cursor = None
        if has_more:
            last = page[-1][0]
            next_cursor = encode_date_cursor(
                DateCursor(
                    sort=sort,
                    sort_date=last.date_of_service,
                    item_id=last.id,
                    created_at=last.created_at,
                )
            )
        return RecordPage(items=[self._to_view(row) for row in page], next_cursor=next_cursor)

    async def list_existing_categories(
        self, caller: AuthenticatedUser, *, patient_health_id: str
    ) -> list[RecordCategory]:
        """Which record categories this patient holds anything in — existence, not content.

        Step 1 of the canonical consent flow (docs/SYSTEM_ARCHITECTURE.md §Consent Flow): a
        clinician has to learn that records exist somewhere before they can ask for them,
        and they cannot ask for a category the patient has nothing in.

        **This read deliberately does not pass ``consent.enforce``, and that is not a hole
        in the choke point.** ``enforce`` answers "may this clinician read *this record* in
        *this category*", which by construction is unanswerable before any grant exists —
        gating discovery on it would make the consent flow unstartable. What is returned
        here is not record content and not metadata about a record: no id, no filename, no
        hospital, no date, no description, no count. It is the vocabulary subset the patient
        has data in, which is exactly what step 1 specifies. Everything past this point —
        every byte of metadata and every file — still crosses ``enforce`` exactly once.

        The relationship this module *can* decide is ADR-015's: the caller must be a
        clinician whose profile is ACTIVE. A suspended doctor loses every clinical
        capability, discovery included.
        """
        doctor = await self._doctors.get_by_user_id(caller.user_id)
        if doctor is None:
            raise ProfileNotFoundError()
        if doctor.status is not DoctorStatus.ACTIVE:
            raise ClinicianNotActiveError()
        patient = await self._patients.get_by_health_id(patient_health_id)
        if patient is None:
            raise UnknownPatientError()

        held = set(await self._records.list_category_ids_with_records(patient.id))
        # The vocabulary is ten rows and already ordered by code, so filtering it in memory
        # both resolves the ids and fixes the response order — no second scan, and two
        # patients with the same categories always answer identically.
        return [category for category in await self._categories.list_all() if category.id in held]

    async def list_shared_for_clinician(
        self,
        caller: AuthenticatedUser,
        *,
        patient_health_id: str,
        after: DateCursor | None,
        limit: int,
        request_context: str | None = None,
    ) -> GrantedRecordPage:
        """The records a consented clinician may read for one patient, newest first.

        Step 4 of the consent flow (docs/SYSTEM_ARCHITECTURE.md), and the step that made
        the other three usable: until this existed a clinician could hold a live grant and
        still have no way to learn a single record id, because ids are random (ADR-012's
        no-enumeration rule applies to every identifier) and no listing admitted them.

        **Authorization is a filter here, and a verdict everywhere else.** The granted
        category set comes from ``consent`` — this module never restates the grant
        predicate — and narrows what the page offers. It does not permit anything: opening
        any record from this page still crosses ``enforce`` exactly once
        (``get_for_caller``), and so does taking its file. Revoking a grant between the
        listing and the read refuses the read, which is the property that makes it safe to
        hand out ids at all.

        ``consent.enforce`` is deliberately *not* called per record. It authorizes one
        document and audits that outcome, so calling it down a page would write a
        ``RECORD_VIEWED`` for every record the clinician merely saw listed — and an
        ``ACCESS_DENIED`` for every one they did not — turning the patient's trail into a
        record of reads that never happened. The listing writes one truthful event instead
        (ADR-020); see ``ListingAuditor``.

        Two rules this module owns are applied before consent is consulted at all: the
        caller must be a clinician whose profile is ACTIVE (ADR-015 — a suspended doctor is
        refused outright rather than handed an empty page, exactly as at
        ``list_existing_categories``), and the Health ID must resolve to a patient.

        The clock is read once and passed down, so the grant filter and the audit row
        describe the same instant and every row on a page is judged as of one moment.
        """
        doctor = await self._doctors.get_by_user_id(caller.user_id)
        if doctor is None:
            raise ProfileNotFoundError()
        if doctor.status is not DoctorStatus.ACTIVE:
            raise ClinicianNotActiveError()
        patient = await self._patients.get_by_health_id(patient_health_id)
        if patient is None:
            raise UnknownPatientError()

        at = self._now()
        granted = await self._grant_scope.granted_category_ids(caller, patient_id=patient.id, at=at)
        # Exactly one audit event per request, written before anything is returned — an
        # empty scope is a refusal the patient is entitled to see, not a silent nothing.
        await self._listing_auditor.record_listing(
            caller,
            patient_id=patient.id,
            granted_category_ids=granted,
            at=at,
            request_context=request_context,
        )
        if not granted:
            # Nothing is in scope, so there is nothing to ask medical_records for.
            return GrantedRecordPage(
                items=[],
                next_cursor=None,
                granted_categories=[],
                patient_id=patient.id,
            )

        # Ordered by the vocabulary, like the existence projection: two clinicians holding
        # the same categories always see them listed identically.
        categories = [
            category for category in await self._categories.list_all() if category.id in granted
        ]
        rows = await self._records.list_page_for_grantee(
            patient_id=patient.id, category_ids=granted, after=after, limit=limit + 1
        )
        has_more = len(rows) > limit
        page = rows[:limit]
        next_cursor = None
        if has_more:
            last = page[-1][0]
            # Always newest-first: this listing offers no sort control, so the cursor pins
            # the only direction it is ever issued for.
            next_cursor = encode_date_cursor(
                DateCursor(
                    sort=SortDirection.NEWEST_FIRST,
                    sort_date=last.date_of_service,
                    item_id=last.id,
                    created_at=last.created_at,
                )
            )
        return GrantedRecordPage(
            items=[self._to_view(row) for row in page],
            next_cursor=next_cursor,
            granted_categories=categories,
            patient_id=patient.id,
        )

    async def get_for_caller(
        self,
        caller: AuthenticatedUser,
        record_id: UUID,
        *,
        action: AuditAction = AuditAction.RECORD_VIEWED,
        request_context: str | None = None,
    ) -> RecordView:
        """Single record metadata, authorized and audited; outside the caller's scope it is
        indistinguishable from nonexistent (404-not-403, docs/API_GUIDELINES.md).

        The one place a record read is authorized. ``action`` distinguishes what the audit
        trail records — reading metadata is not the same event as taking the file.
        """
        row = await self._records.get_with_context(record_id)
        if row is None:
            raise RecordNotFoundError()
        await self._authorize_read(caller, row[0], action=action, request_context=request_context)
        return self._to_view(row)

    async def create_download_link(
        self, caller: AuthenticatedUser, record_id: UUID, *, request_context: str | None = None
    ) -> DownloadLink:
        """Short-lived presigned URL for the record's file, issued only after the same
        authorization every metadata read passes — recorded as a download, not a view."""
        view = await self.get_for_caller(
            caller,
            record_id,
            action=AuditAction.RECORD_DOWNLOADED,
            request_context=request_context,
        )
        url = await self._storage.create_download_url(
            view.record.s3_key,
            expires_in_seconds=self._presign_ttl_seconds,
            filename=view.record.original_filename,
            content_type=view.record.content_type,
        )
        return DownloadLink(url=url, expires_in_seconds=self._presign_ttl_seconds)

    # -- FHIR export -------------------------------------------------------------------

    async def export_fhir(
        self,
        caller: AuthenticatedUser,
        *,
        patient_health_id: str | None = None,
        request_context: str | None = None,
    ) -> bytes:
        """Export consented clinical records for a patient as a canonical FHIR R4 Bundle.

        Authorization and scope:
        - PATIENT: Caller exports their own locker records. ``patient_health_id`` must be absent
          (the target patient is derived strictly from the caller's authenticated user identity).
          Scope covers all categories, including hidden records.
        - DOCTOR: Caller must be an ACTIVE clinician. ``patient_health_id`` is required and
          resolved to the patient. Active consent is checked at the current instant via
          ``_grant_scope.granted_category_ids``. If no categories are granted (or consent is
          expired/revoked), ACCESS_DENIED is audited and ConsentRequiredError is raised.
          Otherwise, records are selected strictly within the granted categories and hidden
          records are excluded at the repository/database level.
        - Other roles (HOSPITAL_ADMIN, SYSTEM_ADMIN): Refused.

        Concurrency & isolation note:
        The authorization decision time is captured at ``at = self._now()``. Under Read Committed
        isolation, concurrent grant revocations committed before the grant check takes effect
        immediately; this transaction does not claim to eliminate race conditions if a grant is
        revoked concurrently after the read check.

        Audit:
        Exactly one RECORD_EXPORTED event is recorded upon successful bundle assembly.
        If serialization fails or storage is unavailable, the transaction rolls back and no
        success audit event is committed.
        """
        at = self._now()

        if caller.role is Role.PATIENT:
            if patient_health_id is not None:
                raise InvalidExportRequestError(
                    "patientHealthId must not be provided for patient self-export."
                )
            patient = await self._patients.get_by_user_id(caller.user_id)
            if patient is None:
                raise ProfileNotFoundError()
            granted_category_ids = None
            include_hidden = True

        elif caller.role is Role.DOCTOR:
            if not patient_health_id:
                raise InvalidExportRequestError("patientHealthId is required for clinician export.")
            doctor = await self._doctors.get_by_user_id(caller.user_id)
            if doctor is None:
                raise ProfileNotFoundError()
            if doctor.status is not DoctorStatus.ACTIVE:
                raise ClinicianNotActiveError()

            patient = await self._patients.get_by_health_id(patient_health_id)
            if patient is None:
                raise UnknownPatientError()

            granted = await self._grant_scope.granted_category_ids(
                caller, patient_id=patient.id, at=at
            )
            if not granted:
                if self._export_auditor is not None:
                    await self._export_auditor.record_export(
                        caller,
                        patient_id=patient.id,
                        granted_category_ids=frozenset(),
                        at=at,
                        request_context=request_context,
                    )
                raise ConsentRequiredError()

            granted_category_ids = granted
            include_hidden = False

        else:
            raise ClinicianNotActiveError()

        # Retrieve candidate records from database using SQL-level scoping
        records = await self._records.list_for_export(
            patient_id=patient.id,
            category_ids=granted_category_ids,
            include_hidden=include_hidden,
        )

        # Retrieve stored objects from object storage
        records_and_payloads: list[tuple[MedicalRecord, bytes]] = []
        for record in records:
            payload = await self._storage.get_object(record.s3_key)
            records_and_payloads.append((record, payload))

        # Pure serialization and subject validation
        bundle_dict = create_fhir_bundle(patient, records_and_payloads, timestamp=at)
        bundle_bytes = serialize_bundle_to_json(bundle_dict)

        # Audit successful export
        if self._export_auditor is not None:
            await self._export_auditor.record_export(
                caller,
                patient_id=patient.id,
                granted_category_ids=granted_category_ids,
                at=at,
                request_context=request_context,
            )

        return bundle_bytes

    # -- patient-controlled visibility -------------------------------------------------

    async def set_visibility(
        self, caller: AuthenticatedUser, record_id: UUID, *, is_hidden: bool
    ) -> RecordView:
        """Hide or unhide one of the caller's own records (docs/DOMAIN_MODEL.md §3).

        **Ownership is the signature, not a check.** The patient row is resolved from the
        authenticated ``user_id`` and the record must already belong to it; no parameter
        names a patient, so changing somebody else's record is not expressible. A record
        owned by another patient and a record that does not exist raise the same error and
        are indistinguishable to the caller (the 403-vs-404 rule, docs/API_GUIDELINES.md).

        **Any record the patient owns, regardless of origin.** The read layers already
        treat every record alike — ``_authorize_read`` and both grantee queries test the
        flag and never the origin — so gating the write by ``PATIENT_LOCKER`` would give one
        flag two rules, and would leave the patient unable to predict which of their records
        carries the control.

        **Not a read, so not the read path.** ``consent.enforce`` is deliberately not called:
        it authorizes and audits access to record *content*, and this reads none. Ownership
        here is an ADR-013 layer-2 relationship this module evaluates itself, exactly as the
        hospital-upload branch of ``_authorize_read`` does.

        **Nothing is audited**, and that is a decision rather than an omission: ``AuditAction``
        has no member that states "the owner changed a record's visibility", and the trail
        exists to hold *other* parties accountable to the patient. Reusing ``RECORD_VIEWED``
        would invent a read that never happened and ``CONSENT_REVOKED`` would assert a
        withdrawal the ``consent_grants`` table contradicts — hiding revokes nothing. The
        patient's own administrative actions belong with the deferred operational log
        (.claude/TODO.md), which is where the other events of that family already wait.

        Idempotent: setting the value it already holds succeeds and changes nothing but
        ``updated_at``. Exactly one attribute is assigned here, so no request shape can
        reach a clinical column, the object-storage key, or the file behind it.

        One limitation worth stating: a presigned download URL issued *before* a record was
        hidden stays valid until it expires (``s3_presign_ttl_seconds``, 300s by default).
        Hiding stops new URLs from being minted; it cannot recall a signature already given.
        """
        patient = await self._patients.get_by_user_id(caller.user_id)
        if patient is None:
            raise ProfileNotFoundError()
        row = await self._records.get_with_context(record_id)
        if row is None or row[0].patient_id != patient.id:
            raise RecordNotFoundError()
        record = row[0]
        record.is_hidden = is_hidden
        await self._records.update(record)
        return self._to_view(row)

    async def list_categories(self) -> list[RecordCategory]:
        return await self._categories.list_all()

    # -- internals ---------------------------------------------------------------------

    def _validate_file(self, file: FileUpload) -> None:
        if file.content_type not in ALLOWED_CONTENT_TYPES:
            raise UnsupportedFileTypeError(ALLOWED_CONTENT_TYPES)
        if len(file.data) == 0:
            raise EmptyFileError()
        if len(file.data) > self.max_upload_bytes:
            raise FileTooLargeError(self.max_upload_bytes)

    async def _resolve_category(self, code: str) -> RecordCategory:
        category = await self._categories.get_by_code(code.strip().upper())
        if category is None:
            raise UnknownCategoryError()
        return category

    async def _store(
        self,
        caller: AuthenticatedUser,
        *,
        patient_id: UUID,
        category: RecordCategory,
        origin: RecordOrigin,
        uploaded_by_hospital_id: UUID | None,
        date_of_service: date,
        description: str | None,
        file: FileUpload,
        request_context: str | None,
        actor_hospital_id: UUID | None,
    ) -> MedicalRecord:
        record_id = uuid4()
        # UUIDs only in the object key — filenames leak information (docs/SECURITY.md).
        s3_key = f"records/{patient_id}/{record_id}"
        record = await self._records.add(
            MedicalRecord(
                id=record_id,
                patient_id=patient_id,
                category_id=category.id,
                origin=origin,
                uploaded_by_hospital_id=uploaded_by_hospital_id,
                date_of_service=date_of_service,
                description=description,
                original_filename=file.filename,
                content_type=file.content_type,
                size_bytes=len(file.data),
                s3_key=s3_key,
            )
        )
        await self._storage.put_object(s3_key, file.data, content_type=file.content_type)
        # After the object is stored, so the trail never claims an upload that failed —
        # and inside the same transaction, so a later failure takes the event with it.
        await self._record_auditor.record_upload(
            caller,
            patient_id=patient_id,
            record_id=record.id,
            actor_hospital_id=actor_hospital_id,
            request_context=request_context,
        )
        try:
            await self._queue.enqueue(RECORD_UPLOADED_TASK, record_id=str(record_id))
        except QueueUnavailableError:
            # ADR-014: the job is advisory until M5 — the upload must not fail with Redis.
            logger.warning("record_uploaded enqueue failed", extra={"record_id": str(record_id)})
        return record

    async def _authorize_read(
        self,
        caller: AuthenticatedUser,
        record: MedicalRecord,
        *,
        action: AuditAction,
        request_context: str | None,
    ) -> None:
        """Permit the read or raise ``RecordNotFoundError``. Never returns a boolean, so a
        caller cannot proceed by ignoring the answer."""
        if caller.role is Role.HOSPITAL_ADMIN:
            # ADR-013 layer 2, unchanged from M2: a hospital may read what it uploaded, and
            # consent has no say because the basis is the upload relationship, not a grant.
            # Only this module can evaluate that, so it does not cross the choke point.
            #
            # It does, however, reach the trail (ADR-022, finding M3-E). The decision is
            # still made here; what changed is that both outcomes are now written, on the
            # same terms ADR-018 set for clinicians — a refused read by a hospital was the
            # one access event the patient could not see.
            admin = await self._admins.get_by_user_id(caller.user_id)
            allowed = (
                admin is not None
                and record.uploaded_by_hospital_id is not None
                and record.uploaded_by_hospital_id == admin.hospital_id
            )
            await self._record_auditor.record_direct_read(
                caller,
                patient_id=record.patient_id,
                record_id=record.id,
                action=action,
                allowed=allowed,
                # The hospital this administrator acts for, captured now (ADR-023). None
                # only when the account has no admin profile at all — which is itself the
                # refusal being recorded.
                actor_hospital_id=admin.hospital_id if admin is not None else None,
                request_context=request_context,
            )
            if not allowed:
                raise RecordNotFoundError()
            return
        if record.is_hidden and caller.role is not Role.PATIENT:
            # Patient-controlled visibility (docs/DOMAIN_MODEL.md §1). Hiding withdraws a
            # record from the set consent is able to share, so it is settled before the
            # choke point rather than inside it: there is no grant that could answer this,
            # and asking consent would either log a view that never happened or a denial of
            # a grant that is in fact valid. To a grantee the record is simply not there.
            # Spelled as "not PATIENT" rather than "is DOCTOR" so a role added to the read
            # gate later inherits the restriction instead of an exemption; the owner check
            # itself stays with enforce, which refuses a patient who is not the owner.
            raise RecordNotFoundError()
        try:
            # Patients pass trivially, clinicians only on an active grant; either way the
            # outcome is audited inside consent, in this request's transaction.
            await self._consent.enforce(
                caller,
                patient_id=record.patient_id,
                category_id=record.category_id,
                action=action,
                record_id=record.id,
                request_context=request_context,
            )
        except AccessDeniedError as exc:
            # A refusal must be indistinguishable from a record that does not exist.
            raise RecordNotFoundError() from exc

    def _to_view(self, row: RecordRow) -> RecordView:
        record, category, hospital = row
        return RecordView(record=record, category=category, hospital=hospital)
