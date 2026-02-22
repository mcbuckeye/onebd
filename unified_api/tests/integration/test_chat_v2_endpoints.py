"""
TDD: Chat v2 endpoint tests — write these FIRST, then implement.
These require OpenAI API key to be set (skip if not available).
"""
import os
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    from unified_api.main import app
    with TestClient(app) as c:
        yield c


# Skip all tests if no OpenAI key
pytestmark = pytest.mark.skipif(
    not os.environ.get("OPENAI_API_KEY"),
    reason="OPENAI_API_KEY not set — skipping LLM-dependent tests"
)


class TestChatV2Endpoint:
    """Test POST /api/chat/v2"""

    def test_chat_v2_returns_200(self, client):
        resp = client.post("/api/chat/v2", json={"message": "How many deals are in the database?"})
        assert resp.status_code == 200

    def test_chat_v2_response_structure(self, client):
        data = client.post("/api/chat/v2", json={"message": "Show me the 5 largest deals"}).json()
        assert "answer" in data
        assert isinstance(data["answer"], str)
        assert len(data["answer"]) > 10  # non-trivial answer
        assert "intent" in data
        assert "confidence" in data
        assert "follow_ups" in data
        assert "actions" in data

    def test_chat_v2_confidence_has_required_fields(self, client):
        data = client.post("/api/chat/v2", json={"message": "Count of oncology deals"}).json()
        conf = data["confidence"]
        assert "data_completeness" in conf
        assert "sample_size" in conf

    def test_chat_v2_follow_ups_are_strings(self, client):
        data = client.post("/api/chat/v2", json={"message": "Pfizer deal history"}).json()
        assert isinstance(data["follow_ups"], list)
        for f in data["follow_ups"]:
            assert isinstance(f, str)

    def test_chat_v2_actions_have_label_and_type(self, client):
        data = client.post("/api/chat/v2", json={"message": "Top acquirers"}).json()
        assert isinstance(data["actions"], list)
        for a in data["actions"]:
            assert "label" in a
            assert "type" in a

    def test_chat_v2_accepts_history(self, client):
        resp = client.post("/api/chat/v2", json={
            "message": "And what about 2023?",
            "history": [
                {"role": "user", "content": "How many deals in 2024?"},
                {"role": "assistant", "content": "There were approximately 5,000 deals in 2024."},
            ],
        })
        assert resp.status_code == 200

    def test_chat_v2_returns_sql_query_for_deal_search(self, client):
        data = client.post("/api/chat/v2", json={"message": "Show me 5 recent oncology deals"}).json()
        # For SQL-routed queries, sql_query should be present
        if data["intent"] in ["deal_search", "company_lookup", "valuation", "market_trends"]:
            assert data.get("sql_query") is not None
