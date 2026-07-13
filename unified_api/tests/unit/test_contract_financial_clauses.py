"""Contract financial-clause parser and worker tests."""

from unittest.mock import MagicMock, patch


def test_extracts_tiered_royalty_rates_with_exact_provenance():
    from unified_api.services.contract_financial_clauses import (
        extract_contract_financial_clauses,
    )

    contract = """
    <para>7.5 Royalties.</para>
    <para>Licensee shall pay royalties on annual Net Sales at the following
    tiered rates: eight percent (8%) for Net Sales up to $100 million,
    ten percent (10%) for Net Sales over $100 million through $500 million,
    and twelve percent (12%) thereafter.</para>
    """

    clauses = extract_contract_financial_clauses(
        contract,
        contract_id=41,
        deal_id=99,
    )

    assert len(clauses) == 1
    clause = clauses[0]
    assert clause["contract_id"] == 41
    assert clause["deal_id"] == 99
    assert clause["clause_type"] == "royalty_rate"
    assert clause["rate_min_pct"] == 8
    assert clause["rate_max_pct"] == 12
    assert clause["is_tiered"] is True
    assert clause["amount_min_millions"] is None
    assert clause["amount_max_millions"] is None
    assert [
        value["amount_millions"]
        for value in clause["extracted_values"]["monetary_values"]
    ] == [100, 100, 500]
    assert "Licensee shall pay royalties" in clause["source_text"]
    assert len(clause["source_hash"]) == 64
    assert clause["source_char_end"] > clause["source_char_start"]


def test_extracts_milestone_and_upfront_amounts_in_millions():
    from unified_api.services.contract_financial_clauses import (
        extract_contract_financial_clauses,
    )

    contract = """
    <para>Upfront Payment. Licensee will pay a non-refundable upfront payment
    of $25 million on the Effective Date.</para>
    <para>Milestone Payments. Licensee shall pay $5,000,000 upon IND acceptance
    and USD 1.5 billion upon first commercial approval.</para>
    """

    clauses = extract_contract_financial_clauses(contract)
    by_type = {clause["clause_type"]: clause for clause in clauses}

    assert by_type["upfront_payment"]["amount_min_millions"] == 25
    assert by_type["upfront_payment"]["amount_max_millions"] == 25
    assert by_type["upfront_payment"]["currency"] == "USD"
    assert by_type["milestone_payment"]["amount_min_millions"] == 5
    assert by_type["milestone_payment"]["amount_max_millions"] == 1500
    assert by_type["milestone_payment"]["currency"] == "USD"


def test_redacted_and_unrelated_percentage_text_is_not_extracted():
    from unified_api.services.contract_financial_clauses import (
        extract_contract_financial_clauses,
    )

    contract = """
    <para>Royalties shall be paid at [***] percent ([***]%) of Net Sales.</para>
    <para>The study enrolled 50% of its target population.</para>
    <para>Milestones are described in Exhibit A but all amounts are [***].</para>
    """

    assert extract_contract_financial_clauses(contract) == []


def test_deduplicates_multiple_royalty_mentions_in_one_clause():
    from unified_api.services.contract_financial_clauses import (
        extract_contract_financial_clauses,
    )

    contract = (
        "<para>Royalties. The royalty payable on Net Sales is 7%. "
        "Such royalty shall increase to 9% after the threshold.</para>"
    )

    clauses = extract_contract_financial_clauses(contract)

    assert len(clauses) == 1
    assert clauses[0]["rate_min_pct"] == 7
    assert clauses[0]["rate_max_pct"] == 9


def test_milestone_amount_excludes_sales_threshold_and_share_par_value():
    from unified_api.services.contract_financial_clauses import (
        extract_contract_financial_clauses,
    )

    contract = """
    <para>A one-time milestone payment of $50,000,000 is payable after aggregate
    Net Sales reach $200,000,000. Shares have a par value of $0.001 per share.</para>
    """

    clause = extract_contract_financial_clauses(contract)[0]

    assert clause["amount_min_millions"] == 50
    assert clause["amount_max_millions"] == 50
    assert [
        value["amount_millions"]
        for value in clause["extracted_values"]["monetary_values"]
    ] == [50]


def test_milestone_section_does_not_capture_preceding_stock_purchase():
    from unified_api.services.contract_financial_clauses import (
        extract_contract_financial_clauses,
    )

    contract = """
    <para>The parties entered into a Stock Purchase Agreement to purchase
    US $9 million of preferred stock.<br/>8.2 Milestone Payments.<br/>
    Licensee shall pay a $25 million milestone payment on approval.</para>
    """

    clause = extract_contract_financial_clauses(contract)[0]

    assert clause["amount_min_millions"] == 25
    assert clause["amount_max_millions"] == 25


def test_contract_clause_batch_returns_busy_when_lock_is_held():
    from unified_api.services.contract_financial_clauses import (
        CONTRACT_CLAUSE_PARSER_VERSION,
        extract_contract_financial_clause_batch,
    )

    session = MagicMock()
    session.execute.return_value.scalar.return_value = False

    result = extract_contract_financial_clause_batch(session)

    assert result == {
        "status": "busy",
        "processed": 0,
        "clauses_extracted": 0,
        "errors": 0,
        "parser_version": CONTRACT_CLAUSE_PARSER_VERSION,
        "sample": [],
    }
    session.execute.assert_called_once()


def test_contract_clause_review_rejects_invalid_decision_or_blank_reviewer():
    import pytest

    from unified_api.services.contract_financial_clauses import (
        review_contract_financial_clause,
    )

    session = MagicMock()
    with pytest.raises(ValueError, match="accepted or rejected"):
        review_contract_financial_clause(
            session,
            clause_id=1,
            review_status="pending",
            reviewer="analyst",
        )
    with pytest.raises(ValueError, match="reviewer is required"):
        review_contract_financial_clause(
            session,
            clause_id=1,
            review_status="accepted",
            reviewer="  ",
        )
    session.execute.assert_not_called()


def test_celery_contract_clause_extraction_runs_resumable_batch():
    expected = {
        "status": "completed",
        "processed": 1000,
        "clauses_extracted": 250,
        "errors": 0,
        "sample": [],
    }
    session = MagicMock()
    context = MagicMock()
    context.__enter__.return_value = session
    with (
        patch(
            "unified_api.services.database.get_cortellis_session",
            return_value=context,
        ),
        patch(
            "unified_api.services.contract_financial_clauses."
            "extract_contract_financial_clause_batch",
            return_value=expected,
        ) as extract,
    ):
        from unified_api.workers.celery_app import (
            extract_contract_financial_clauses,
        )

        assert extract_contract_financial_clauses.run() == expected
        extract.assert_called_once_with(session, batch_size=1000)


def test_celery_contract_clause_rebuild_commits_each_batch():
    batches = [
        {"processed": 1000, "clauses_extracted": 250, "errors": 0},
        {"processed": 12, "clauses_extracted": 4, "errors": 0},
        {"processed": 0, "clauses_extracted": 0, "errors": 0},
    ]
    session = MagicMock()
    context = MagicMock()
    context.__enter__.return_value = session
    with (
        patch(
            "unified_api.services.database.get_cortellis_session",
            return_value=context,
        ),
        patch(
            "unified_api.services.contract_financial_clauses."
            "extract_contract_financial_clause_batch",
            side_effect=batches,
        ),
    ):
        from unified_api.workers.celery_app import (
            rebuild_contract_financial_clauses,
        )

        result = rebuild_contract_financial_clauses.run()

    assert result == {
        "status": "completed",
        "batches": 3,
        "processed": 1012,
        "clauses_extracted": 254,
        "errors": 0,
        "busy_retries": 0,
    }
    assert session.commit.call_count == 3
