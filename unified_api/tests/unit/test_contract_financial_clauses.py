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


def test_royalty_rate_excludes_audit_interest_credit_and_cost_percentages():
    from unified_api.services.contract_financial_clauses import (
        extract_contract_financial_clauses,
    )

    contract = """
    <para>Royalty Records. If Licensee has underpaid Royalties by more than five
    percent (5%), it shall reimburse the audit cost.</para>
    <para>Interest on delinquent royalty payments accrues at LIBOR plus two
    percent (2%).</para>
    <para>No more than fifty percent (50%) of royalty payments may be credited
    in any year.</para>
    <para>For activities where Licensee is one hundred percent (100%)
    responsible for costs and expenses, Licensee shall reimburse Licensor.</para>
    """

    assert extract_contract_financial_clauses(contract) == []


def test_royalty_payout_percentage_remains_an_explicit_rate():
    from unified_api.services.contract_financial_clauses import (
        extract_contract_financial_clauses,
    )

    contract = """
    <para>The Royalty Payout shall equal thirty percent (30%) of Net Sales for
    the calendar year and shall be payable in cash.</para>
    """

    clause = extract_contract_financial_clauses(contract)[0]
    assert clause["clause_type"] == "royalty_rate"
    assert clause["rate_min_pct"] == 30


def test_milestone_does_not_claim_a_nearby_upfront_or_combined_package_amount():
    from unified_api.services.contract_financial_clauses import (
        extract_contract_financial_clauses,
    )

    contract = """
    <para>Licensee will receive an upfront payment and committed research
    funding of as much as $10 million. Licensee may also receive undisclosed
    milestones and royalties.</para>
    <para>The agreement includes $123 million in upfront and potential
    development milestone payments, including a $30 million cash upfront
    licensing payment. Sales milestones are undisclosed.</para>
    """

    clauses = extract_contract_financial_clauses(contract)
    assert all(clause["clause_type"] != "milestone_payment" for clause in clauses)


def test_upfront_does_not_claim_research_funding_aggregate():
    from unified_api.services.contract_financial_clauses import (
        extract_contract_financial_clauses,
    )

    contract = """
    <para>Company will receive an upfront payment and committed research
    funding of as much as $10 million.</para>
    """

    assert extract_contract_financial_clauses(contract) == []


def test_combined_package_keeps_only_the_explicit_upfront_amount():
    from unified_api.services.contract_financial_clauses import (
        extract_contract_financial_clauses,
    )

    contract = """
    <para>The agreement includes $123 million in upfront and potential
    development milestone payments, including a $30 million cash upfront
    licensing payment.</para>
    """

    clauses = extract_contract_financial_clauses(contract)
    assert [clause["clause_type"] for clause in clauses] == ["upfront_payment"]
    assert clauses[0]["amount_min_millions"] == 30
    assert clauses[0]["amount_max_millions"] == 30


def test_license_fee_installments_are_not_milestones_when_triggered_by_one():
    from unified_api.services.contract_financial_clauses import (
        extract_contract_financial_clauses,
    )

    contract = """
    <para>Issue Fee. Licensee will pay a license issue fee of $100,000 in two
    installments. The first installment of $50,000 is due when Licensee
    achieves the Essential Milestone, and the second installment of $50,000 is
    due on the Effective Date.</para>
    """

    clauses = extract_contract_financial_clauses(contract)
    assert [clause["clause_type"] for clause in clauses] == ["upfront_payment"]
    assert clauses[0]["amount_min_millions"] == 0.05
    assert clauses[0]["amount_max_millions"] == 0.1
    assert clauses[0]["rate_min_pct"] is None


def test_payment_lists_capture_all_rows_without_crossing_categories():
    from unified_api.services.contract_financial_clauses import (
        extract_contract_financial_clauses,
    )

    contract = """
    <para>(d) milestone payments as follows: (i) $10,000 upon filing an IND;
    (ii) $25,000 upon filing an NDA; and (iii) $100,000 upon NDA approval.</para>
    <para>(e) Licensee shall pay annual minimum royalties of $5,000.</para>
    """

    milestone = next(
        clause for clause in extract_contract_financial_clauses(contract)
        if clause["clause_type"] == "milestone_payment"
    )
    assert milestone["amount_min_millions"] == 0.01
    assert milestone["amount_max_millions"] == 0.1
    assert [
        value["amount_millions"]
        for value in milestone["extracted_values"]["monetary_values"]
    ] == [0.01, 0.025, 0.1]


def test_initial_and_research_payments_do_not_pollute_milestone_or_upfront():
    from unified_api.services.contract_financial_clauses import (
        extract_contract_financial_clauses,
    )

    contract = """
    <para>Company will make an initial payment of $50 million, with up to
    $455 million in additional milestone payments.</para>
    <para>Near-term payments include $4 million in upfront license fees and
    $8 million in research and development funding. An additional $58 million
    in milestone payments relates to regulatory approvals.</para>
    """

    clauses = extract_contract_financial_clauses(contract)
    by_type = {clause["clause_type"]: clause for clause in clauses}
    assert by_type["milestone_payment"]["amount_min_millions"] == 58
    assert by_type["milestone_payment"]["amount_max_millions"] == 455
    assert by_type["upfront_payment"]["amount_min_millions"] == 4
    assert by_type["upfront_payment"]["amount_max_millions"] == 4


def test_historical_milestone_and_upfront_distribution_allocations_are_excluded():
    from unified_api.services.contract_financial_clauses import (
        extract_contract_financial_clauses,
    )

    contract = """
    <para>To the extent Company has paid the milestone in Section 6.5 in the
    amount of $20 million, that amount shall be credited on termination.</para>
    <para>The Payment Agent shall distribute the Upfront Payment as follows:
    $100,000 as the Committee Reimbursement Amount for expenses.</para>
    """

    assert extract_contract_financial_clauses(contract) == []


def test_execution_and_milestone_table_excludes_execution_payment():
    from unified_api.services.contract_financial_clauses import (
        extract_contract_financial_clauses,
    )

    contract = """
    <para>LICENSE EXECUTION AND MILESTONE PAYMENTS</para>
    <para>Upon execution of license $250,000</para>
    <para>Upon start of Phase I Clinical Trials $500,000</para>
    """

    milestone = extract_contract_financial_clauses(contract)[0]
    assert milestone["clause_type"] == "milestone_payment"
    assert milestone["amount_min_millions"] == 0.5
    assert milestone["amount_max_millions"] == 0.5


def test_royalty_rate_excludes_allocation_covenant_and_equity_percentages():
    from unified_api.services.contract_financial_clauses import (
        extract_contract_financial_clauses,
    )

    false_rate_clauses = [
        """
        <para>New Contracts may not provide for royalties or profit share above
        50% in favor of the other party.</para>
        """,
        """
        <para>Each payment of the Royalty shall be allocated and paid 37.28% to
        Fund A, 7.8% to Fund B, and 54.92% to Fund C.</para>
        """,
        """
        <para>Late charges will be assessed as additional royalties on overdue
        payments at one percent (1%) per month.</para>
        """,
        """
        <para>The termination amount includes fifty percent (50%) of amounts
        previously paid as royalties under Section 3.</para>
        """,
        """
        <para>All costs for Products in the Royalty Territory shall be borne
        one hundred percent (100%) by Licensee.</para>
        """,
        """
        <para>If an error in royalties of more than five percent (5%) is found,
        Licensee shall pay the audit costs.</para>
        """,
        """
        <para>Royalties are payable under Section 3. On the Effective Date,
        Licensee shall issue capital stock equal to ten percent (10%) of its
        outstanding equity ownership.</para>
        """,
    ]

    for contract in false_rate_clauses:
        assert extract_contract_financial_clauses(contract) == []


def test_milestone_bounds_exclude_expense_funding_reserve_advance_and_escrow():
    from unified_api.services.contract_financial_clauses import (
        extract_contract_financial_clauses,
    )

    false_milestone_clauses = [
        """
        <para>Revenue includes a milestone payment and trial reimbursement
        totalling $17.1 million. Amortization expense was $3.0 million per
        quarter.</para>
        """,
        """
        <para>Milestone 3 pays $7 million. Concurrent with that milestone,
        Licensee shall also pay $8 million for future research and development
        efforts.</para>
        """,
        """
        <para>A milestone payment of $500,000 is due on NDA submission. If cash
        reserves are less than $5 million, the payment may be made by note.</para>
        """,
        """
        <para>The First Milestone is expected next year. Company paid an
        advance of $35,000, in addition to $25,000 already advanced, to
        partially fund the R&amp;D Program.</para>
        """,
        """
        <para>The purchase price is reduced by Milestone Payments received
        before Closing. Buyer will deposit $3 million as the Escrow Amount.</para>
        """,
    ]

    expected = [None, (7, 7), (0.5, 0.5), None, None]
    for contract, bounds in zip(false_milestone_clauses, expected, strict=True):
        milestones = [
            clause for clause in extract_contract_financial_clauses(contract)
            if clause["clause_type"] == "milestone_payment"
        ]
        if bounds is None:
            assert milestones == []
        else:
            assert len(milestones) == 1
            assert (
                milestones[0]["amount_min_millions"],
                milestones[0]["amount_max_millions"],
            ) == bounds


def test_upfront_bounds_exclude_contingent_and_total_package_amounts():
    from unified_api.services.contract_financial_clauses import (
        extract_contract_financial_clauses,
    )

    contingent = """
    <para>Upfront Payment. Licensee shall pay $1 million on the Effective Date
    and $500,000 upon the first IND approval.</para>
    """
    package = """
    <para>The partnership, valued up to $60 million, includes a $15 million
    up-front purchase of stock, milestone payments, and clinical costs.</para>
    """

    for contract, expected in ((contingent, 1), (package, 15)):
        upfront = next(
            clause for clause in extract_contract_financial_clauses(contract)
            if clause["clause_type"] == "upfront_payment"
        )
        assert upfront["amount_min_millions"] == expected
        assert upfront["amount_max_millions"] == expected


def test_payment_bounds_do_not_mix_us_and_canadian_dollar_amounts():
    from unified_api.services.contract_financial_clauses import (
        extract_contract_financial_clauses,
    )

    contract = """
    <para>Company may receive milestone payments of up to U.S.$21.5 million
    [Cdn$33 million] upon successful clinical development.</para>
    """

    milestone = extract_contract_financial_clauses(contract)[0]
    assert milestone["currency"] == "USD"
    assert milestone["amount_min_millions"] == 21.5
    assert milestone["amount_max_millions"] == 21.5


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
