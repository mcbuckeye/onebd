"""Authorization and provenance tests for governed enrichment endpoints."""

from contextlib import contextmanager
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from unified_api.routers import enrichment
from unified_api.services.auth import create_access_token


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(enrichment.router)
    return TestClient(app)


def _authorization(role: str, *, email: str = "reviewer@example.com") -> dict[str, str]:
    token = create_access_token(42, email, role)
    return {"Authorization": f"Bearer {token}"}


def test_contract_clause_review_queue_requires_an_admin():
    with _client() as client:
        anonymous = client.get(
            "/api/enrichment/contract-financial-clauses/review-sample"
        )
        analyst = client.get(
            "/api/enrichment/contract-financial-clauses/review-sample",
            headers=_authorization("analyst"),
        )

    assert anonymous.status_code == 401
    assert analyst.status_code == 403


def test_contract_clause_review_uses_authenticated_identity_and_audits(monkeypatch):
    session = MagicMock()

    @contextmanager
    def fake_session():
        yield session

    review = MagicMock(return_value={
        "id": 17,
        "contract_id": 11,
        "deal_id": 9,
        "clause_type": "royalty_rate",
        "review_status": "accepted",
        "reviewer": "reviewer@example.com",
        "review_note": "Matches the excerpt",
        "reviewed_at": "2026-07-14T00:00:00",
        "review_parser_version": "contract-financial-v9",
    })
    audit = MagicMock()
    monkeypatch.setattr(enrichment, "get_cortellis_session", fake_session)
    monkeypatch.setattr(enrichment, "review_contract_financial_clause", review)
    monkeypatch.setattr(enrichment, "log_audit", audit)

    with _client() as client:
        response = client.patch(
            "/api/enrichment/contract-financial-clauses/17/review",
            headers=_authorization("admin"),
            json={
                "review_status": "accepted",
                "note": "Matches the excerpt",
                "reviewer": "spoofed@example.com",
            },
        )

    assert response.status_code == 200
    review.assert_called_once_with(
        session,
        clause_id=17,
        review_status="accepted",
        reviewer="reviewer@example.com",
        note="Matches the excerpt",
    )
    audit.assert_called_once_with(
        "contract_financial_clause_review",
        user_id=42,
        entity_type="contract_financial_clause",
        entity_id="17",
        metadata={
            "review_status": "accepted",
            "parser_version": "contract-financial-v9",
        },
    )


def test_financial_parser_mutation_requires_an_admin():
    with _client() as client:
        response = client.post("/api/enrichment/parse-financials?dry_run=true")

    assert response.status_code == 401
