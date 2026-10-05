import asyncio
from uuid import uuid4

from app.modules.ai.query import AIQueryService


class FakeConsentScope:
    def __init__(self, category_ids):
        self.category_ids = category_ids
        self.calls = []

    async def granted_category_ids(self, requester, *, patient_id, at):
        self.calls.append(
            {
                "requester": requester,
                "patient_id": patient_id,
                "at": at,
            }
        )
        return self.category_ids


class FakeRetrieval:
    def __init__(self):
        self.calls = []

    async def search(
        self,
        *,
        patient_id,
        category_ids,
        query,
        limit,
    ):
        self.calls.append(
            {
                "patient_id": patient_id,
                "category_ids": category_ids,
                "query": query,
                "limit": limit,
            }
        )
        return []


def test_ai_query_service_passes_consent_scope_to_retrieval():
    consent = FakeConsentScope(frozenset({uuid4(), uuid4()}))
    retrieval = FakeRetrieval()

    service = AIQueryService(
        retrieval=retrieval,
        consent=consent,
    )

    patient_id = uuid4()
    requester = object()

    asyncio.run(
        service.search(
            requester,
            patient_id=patient_id,
            query="diabetes",
            limit=5,
        )
    )

    assert len(consent.calls) == 1
    assert len(retrieval.calls) == 1

    assert retrieval.calls[0]["patient_id"] == patient_id
    assert retrieval.calls[0]["category_ids"] == consent.category_ids
    assert retrieval.calls[0]["query"] == "diabetes"
    assert retrieval.calls[0]["limit"] == 5

def test_ai_query_service_returns_no_results_without_consent_scope():
    consent = FakeConsentScope(frozenset())
    retrieval = FakeRetrieval()

    service = AIQueryService(
        retrieval=retrieval,
        consent=consent,
    )

    patient_id = uuid4()
    requester = object()

    results = asyncio.run(
        service.search(
            requester,
            patient_id=patient_id,
            query="diabetes",
            limit=10,
        )
    )

    assert results == []

    # Retrieval must still be called with the empty authorized scope.
    assert len(retrieval.calls) == 1
    assert retrieval.calls[0]["category_ids"] == frozenset()