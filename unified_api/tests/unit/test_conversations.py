"""Conversation persistence regression tests."""

from unified_api.routers.conversations import SAVE_MESSAGE_SQL


def test_message_metadata_uses_a_valid_sqlalchemy_jsonb_bind() -> None:
    """PostgreSQL casts must not hide the bind name from SQLAlchemy."""
    assert "CAST(:metadata AS JSONB)" in str(SAVE_MESSAGE_SQL)
    assert "metadata" in SAVE_MESSAGE_SQL._bindparams
    assert "metadata::jsonb" not in str(SAVE_MESSAGE_SQL)
