"""Audit event serialization tests."""

from unittest.mock import MagicMock, patch


def test_log_audit_serializes_jsonb_metadata():
    from unified_api.services.audit import log_audit

    session = MagicMock()
    context = MagicMock()
    context.__enter__.return_value = session

    with patch(
        "unified_api.services.audit.get_cortellis_session",
        return_value=context,
    ):
        log_audit(
            "review",
            user_id=42,
            metadata={"review_status": "accepted", "parser_version": "v9"},
        )

    params = session.execute.call_args_list[-1].args[1]
    assert params["metadata"] == (
        '{"review_status": "accepted", "parser_version": "v9"}'
    )
