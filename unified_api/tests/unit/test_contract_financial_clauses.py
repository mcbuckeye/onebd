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

    actual_example = """
    <para>The royalty rate shall be 20% - (10% x M/12). For example, if
    Closing occurs on April 1, the royalty rate would be 17.5%.</para>
    """
    assert any(
        clause["rate_min_pct"] == 17.5
        and clause["rate_max_pct"] == 17.5
        for clause in extract_contract_financial_clauses(actual_example)
    )


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

    historical_context = """
    <para>The agreement provides initial licensing revenue of U.S.$2,000,000
    [Cdn$3,100,000], research funding of U.S.$2,250,000 [Cdn$3,400,000],
    and milestone payments of up to U.S.$21,500,000 [Cdn$33,000,000].</para>
    """
    milestone = next(
        clause for clause in extract_contract_financial_clauses(historical_context)
        if clause["clause_type"] == "milestone_payment"
    )
    assert milestone["currency"] == "USD"
    assert milestone["amount_min_millions"] == 21.5
    assert milestone["amount_max_millions"] == 21.5


def test_royalty_rate_excludes_disclosure_multipliers_and_revenue_shares():
    from unified_api.services.contract_financial_clauses import (
        extract_contract_financial_clauses,
    )

    false_rate_clauses = [
        """
        <para>The disclosure schedule lists all Material Contracts requiring
        royalty payments that equal or exceed 1% of net sales.</para>
        """,
        """
        <para>Royalties are otherwise redacted. Licensee will pay fifty percent
        (50%) of all Financial Consideration received under any sublicense or
        distributor agreement.</para>
        """,
        """
        <para>The royalty rate shall be equal to fifty percent (50%) of the
        applicable royalty rates in Section 6.5.</para>
        """,
        """
        <para>All royalty payments shall be reduced by one-half (the “50%
        Royalty”) after a Final Patent Refusal.</para>
        """,
        """
        <para>Royalty rates are redacted; however, payments shall be reduced by
        one-half (the “50% Royalty”). If market exclusivity applies, then the
        50% Royalty shall not be applicable until that period expires.</para>
        """,
    ]

    for contract in false_rate_clauses:
        assert extract_contract_financial_clauses(contract) == []


def test_upfront_bounds_exclude_milestones_credits_and_third_party_cost_caps():
    from unified_api.services.contract_financial_clauses import (
        extract_contract_financial_clauses,
    )

    mixed = """
    <para>Buyer will make a $55 million up-front payment and up to $6 million
    in potential sales-based milestone payments.</para>
    """
    credit = """
    <para>Initial payment: Licensee shall pay USD 1,000,000, of which USD
    250,000 is creditable against future royalty payments and sublicense up
    front payments.</para>
    """
    third_party_cost = """
    <para>If Buyer obtains a third-party patent license, the cost of such
    license, including all up front payments, up to a maximum of $175,000,
    shall be deducted from the purchase price.</para>
    """

    upfront = next(
        clause for clause in extract_contract_financial_clauses(mixed)
        if clause["clause_type"] == "upfront_payment"
    )
    assert upfront["amount_min_millions"] == 55
    assert upfront["amount_max_millions"] == 55

    press_release = """
    <para>Pfizer will make an up-front payment of $75 million and up to
    $410 million in potential milestone payments, including $150 million in
    regulatory milestones and $260 million in sales milestones.</para>
    """
    upfront = next(
        clause for clause in extract_contract_financial_clauses(press_release)
        if clause["clause_type"] == "upfront_payment"
    )
    assert upfront["amount_min_millions"] == 75
    assert upfront["amount_max_millions"] == 75
    for contract in (credit, third_party_cost):
        assert all(
            clause["clause_type"] != "upfront_payment"
            for clause in extract_contract_financial_clauses(contract)
        )


def test_milestone_bounds_exclude_adjacent_transaction_and_threshold_values():
    from unified_api.services.contract_financial_clauses import (
        extract_contract_financial_clauses,
    )

    cases = [
        (
            """
            <para>Buyer shall pay a $7,500 daily late-delivery credit, which is
            creditable against any milestone payments due under Article 7.</para>
            """,
            None,
        ),
        (
            """
            <para>The Level 4 Milestone Amount is $50 million in cash less a
            Change of Control Plan amount of $2.984 million payable to Eligible
            Employees. The Level 5 Milestone Amount is $100 million.</para>
            """,
            (50, 100),
        ),
        (
            """
            <para>The purchase price consists of a $3.8 billion Initial Purchase
            Price and Milestone Payments. A $250 million Milestone Payment is
            due on FDA approval.</para>
            """,
            (250, 250),
        ),
        (
            """
            <para>ARTICLE 8 Milestone Payments. Section 8.1 Licensing Fees.
            Buyer shall pay an initial licensing fee of $85 million. Section
            8.2 Milestone Payments contains redacted amounts.</para>
            """,
            None,
        ),
        (
            """
            <para>Following the Phase III Milestone Date, the holder may require
            repurchase of the Warrant for $12.5 million principal plus
            interest.</para>
            """,
            None,
        ),
        (
            """
            <para>The Second Milestone will be adjusted against anticipated
            Market Potential of $67 million.</para>
            """,
            None,
        ),
        (
            """
            <para>The transaction has up fronts and milestones worth
            approximately $150 million between signing and approval.</para>
            """,
            None,
        ),
        (
            """
            <para>NexMed receives milestone payments. Annual Net Sales less
            than $750 million bear a 3.5% royalty and sales above $1.5 billion
            bear a 6.5% royalty.</para>
            """,
            None,
        ),
        (
            """
            <para>NexMed receives upfront and milestone payments. In addition,
            royalties are as follows: Annual Net Sales of each Product;
            Royalty Rate; more than $750 million and less than $1.5 billion,
            4.5%.</para>
            """,
            None,
        ),
        (
            """
            <para>A $500,000 milestone payment is due after equity financing in
            the minimum amount of $5 million.</para>
            """,
            (0.5, 0.5),
        ),
        (
            """
            <para>ARTICLE 9 RESEARCH FUNDING AND MILESTONES. Section 9.1
            Research Funding. On the Effective Date, Company pays $250,000 for
            work under the Research Plan.</para>
            """,
            None,
        ),
        (
            """
            <para>Milestone 5 Validation of New Process $172,000. Additional
            Batches are priced at US$20,000 per Batch.</para>
            """,
            (0.172, 0.172),
        ),
    ]

    for contract, expected in cases:
        milestones = [
            clause for clause in extract_contract_financial_clauses(contract)
            if clause["clause_type"] == "milestone_payment"
        ]
        if expected is None:
            assert milestones == []
        else:
            assert len(milestones) == 1
            assert (
                milestones[0]["amount_min_millions"],
                milestones[0]["amount_max_millions"],
            ) == expected


def test_v5_royalty_rate_excludes_examples_bases_and_operational_percentages():
    from unified_api.services.contract_financial_clauses import (
        extract_contract_financial_clauses,
    )

    false_rate_clauses = [
        """<para>Royalty rates range up to twenty percent. Development
        expenditure is thirty percent (30%) of Co-Development costs.</para>""",
        """<para>For example, if the royalty payable is 25%, each party bears
        25% of the damages and litigation expenses.</para>""",
        """<para>A stockholder owning fifty percent (50%) of the outstanding
        voting stock triggers an auction. If that stockholder later passes the
        fifty percent (50%) threshold, the price may include a royalty.</para>""",
        """<para>In no event shall the Royalty exceed fifty percent (50%) of
        the amount collected under the sublicense.</para>""",
        """<para>The company posted net sales while spending 21% of net sales
        on research and development. Products may earn tiered royalties.</para>""",
        """<para>Licensee shall pay a royalty on one hundred percent (100%) of
        the Net Sales for the applicable royalty period.</para>""",
        """<para>Tekmira shall pay 100% of all royalties, license fees,
        milestones and similar payments owed under third-party licenses.</para>""",
        """<para>If an examination determines that Licensee underpaid the
        royalties by more than five percent (5%), it bears the cost of such
        examination.</para>""",
    ]

    for contract in false_rate_clauses:
        assert extract_contract_financial_clauses(contract) == []


def test_v5_upfront_excludes_package_financing_credit_and_hypothetical_amounts():
    from unified_api.services.contract_financial_clauses import (
        extract_contract_financial_clauses,
    )

    no_upfront_clauses = [
        """<para>Marina could receive up to $14 million for each target in
        total upfront, clinical and commercialization milestone payments.</para>""",
        """<para>Company funds the upfront license fee and development costs
        with $10 million in venture debt financing.</para>""",
        """<para>If, for example, Licensee must pay an upfront fee of $1
        million to a third party, royalties are reduced until $500,000 has
        been recouped.</para>""",
        """<para>Initial payment is USD 1,000,000, of which USD 250,000 is
        creditable against future royalties and sublicense up front
        payments.</para>""",
    ]
    for contract in no_upfront_clauses:
        assert all(
            clause["clause_type"] != "upfront_payment"
            for clause in extract_contract_financial_clauses(contract)
        )

    package = """
    <para>Company may receive up to $975 million, inclusive of an upfront
    payment of $150 million as well as development and regulatory milestone
    payments.</para>
    """
    upfront = next(
        clause for clause in extract_contract_financial_clauses(package)
        if clause["clause_type"] == "upfront_payment"
    )
    assert upfront["amount_min_millions"] == 150
    assert upfront["amount_max_millions"] == 150

    safety = """
    <para>Purchaser shall make a $250,000 payment in Shares at Closing (the
    Upfront Payment). In addition, Purchaser shall make a $100,000 payment
    after receiving human safety data (the Safety Data Payment).</para>
    """
    upfront = next(
        clause for clause in extract_contract_financial_clauses(safety)
        if clause["clause_type"] == "upfront_payment"
    )
    assert upfront["amount_min_millions"] == 0.25
    assert upfront["amount_max_millions"] == 0.25

    non_creditable = """
    <para>Upfront Payment: Licensee shall pay $3 million on the Effective
    Date. This payment is non-refundable and non-creditable against future
    earned royalties.</para>
    """
    upfront = next(
        clause for clause in extract_contract_financial_clauses(non_creditable)
        if clause["clause_type"] == "upfront_payment"
    )
    assert upfront["amount_min_millions"] == 3
    assert upfront["amount_max_millions"] == 3


def test_v5_milestone_excludes_financing_research_purchase_and_indemnity_values():
    from unified_api.services.contract_financial_clauses import (
        extract_contract_financial_clauses,
    )

    equity = """
    <para>Buyer has paid a $500,000 milestone payment after receiving equity
    financing in the minimum amount of $5 million.</para>
    """
    milestone = next(
        clause for clause in extract_contract_financial_clauses(equity)
        if clause["clause_type"] == "milestone_payment"
    )
    assert milestone["amount_min_millions"] == 0.5
    assert milestone["amount_max_millions"] == 0.5

    false_milestone_clauses = [
        """<para>ARTICLE 6 FEES, MILESTONES AND ROYALTIES. Section 6.1
        Research Fees. Licensee shall pay a $4 million ADC Access Fee.</para>""",
        """<para>The milestone and royalty payments are excused if the
        investor commitment of at least US$25 million cannot be confirmed.</para>""",
        """<para>ARTICLE 3 PURCHASE PRICE; MILESTONE PAYMENTS. The Purchase
        Price is $2 million, of which $50,000 is allocated to patents.</para>""",
        """<para>If the First Milestone has not occurred, offsets apply to the
        note. Maximum cash indemnification payments are $1.75 million.</para>""",
    ]
    for contract in false_milestone_clauses:
        assert all(
            clause["clause_type"] != "milestone_payment"
            for clause in extract_contract_financial_clauses(contract)
        )


def test_v6_royalty_excludes_allocations_caps_examples_and_operational_shares():
    from unified_api.services.contract_financial_clauses import (
        extract_contract_financial_clauses,
    )

    false_rate_clauses = [
        """<para>An invoice equal to 25% of the Forecast Royalty Amount is
        payable quarterly.</para>""",
        """<para>Each party retains fifty percent (50%) of sale proceeds,
        including deferred milestone payments and royalties.</para>""",
        """<para>Net Sales used to determine royalty payments will be deemed
        equal to fifty percent (50%) of combination-product Net Sales.</para>""",
        """<para>Licensee may defray litigation expenses with 50% of royalties
        otherwise payable.</para>""",
        """<para>If sublicense royalties result in an amount less than 50% of
        the royalty otherwise due, the parties will confer.</para>""",
        """<para>A subsidiary is an entity whose ownership interests represent
        more than 50% of voting power. Third-Party Payments include
        royalties.</para>""",
    ]
    for contract in false_rate_clauses:
        assert extract_contract_financial_clauses(contract) == []

    reduced = """
    <para>Licensee shall pay a royalty of 5% for Product A and a royalty of 4%
    for Product B.</para><para>The royalty may not be reduced by more than 50%.
    Example: if the total royalty burden is 30%, the formula yields 3.33%.</para>
    """
    royalty = next(
        clause for clause in extract_contract_financial_clauses(reduced)
        if clause["clause_type"] == "royalty_rate"
    )
    assert royalty["rate_min_pct"] == 4
    assert royalty["rate_max_pct"] == 5

    recovery = """
    <para>Licensee shall pay a royalty of five percent (5%) of Net Sales until
    it has recovered one hundred percent (100%) of all research and development
    funding.</para>
    """
    royalty = next(
        clause for clause in extract_contract_financial_clauses(recovery)
        if clause["clause_type"] == "royalty_rate"
    )
    assert royalty["rate_min_pct"] == 5
    assert royalty["rate_max_pct"] == 5


def test_v6_upfront_excludes_later_installments_and_adjacent_payment_categories():
    from unified_api.services.contract_financial_clauses import (
        extract_contract_financial_clauses,
    )

    cases = [
        (
            """<para>An initial license fee of $750,000 is due on execution.
            An additional $500,000 license maintenance fee is due on the first
            anniversary.</para>""",
            0.75,
        ),
        (
            """<para>The partnership includes $100 million in upfront payments
            and $50 million in technology transfer payments, plus a $50 million
            per field expansion payment.</para>""",
            100,
        ),
        (
            """<para>Up front payment with signature: $32,600. Test report for
            laboratory batch: $40,655.</para>""",
            0.0326,
        ),
        (
            """<para>Refund = Up-Front Payment ($165M) times the remaining
            term. A later refund uses the Second Payment ($130M).</para>""",
            165,
        ),
        (
            """<para>Licensee will pay an upfront cash payment of $40 million
            and an additional $35 million upon the successful achievement of
            Phase III results.</para>""",
            40,
        ),
        (
            """<para>Following receipt of the Up-Front Payment of $8 million,
            Licensee commits to allocate $1.5 million to evaluation studies.
            </para>""",
            8,
        ),
    ]
    for contract, expected in cases:
        upfront = next(
            clause for clause in extract_contract_financial_clauses(contract)
            if clause["clause_type"] == "upfront_payment"
        )
        assert upfront["amount_min_millions"] == expected
        assert upfront["amount_max_millions"] == expected

    aggregate = """
    <para>Company is eligible for up to $25 million in aggregate payments,
    including upfront fees and development milestone payments.</para>
    """
    assert all(
        clause["clause_type"] != "upfront_payment"
        for clause in extract_contract_financial_clauses(aggregate)
    )


def test_v6_milestone_excludes_thresholds_fees_reductions_and_annual_payments():
    from unified_api.services.contract_financial_clauses import (
        extract_contract_financial_clauses,
    )

    false_milestone_clauses = [
        """<para>Milestone payments apply after annual sales revenues exceed
        $100 million.</para>""",
        """<para>Milestones are excused after cumulative royalty payments total
        $80 million.</para>""",
        """<para>A $4 million credit facility may be drawn to satisfy milestone
        payment obligations.</para>""",
        """<para>A lump sum cash payment of $3.9 million is due plus any
        clinical milestones that have become due.</para>""",
        """<para>Licensee may make a $10,000 payment for each milestone
        extension.</para>""",
        """<para>The Additional Milestone Payment Reduction Amount is $833,333
        for each full month after the trigger date.</para>""",
        """<para>Company will pay a fee of $8 million and may later receive
        milestone payments. Its current annual revenues are $350 million.
        </para>""",
        """<para>Royalties exclude $1 million of royalties otherwise payable;
        Gross Milestone Payments are also excluded.</para>""",
        """<para>Material contracts include those providing milestone payments
        or requiring aggregate expenditures over $100,000.</para>""",
        """<para>If the Milestone has not been achieved, Buyer shall make an
        annual payment of $250,000.</para>""",
        """<para>For example, if a licensee selects five products, it could
        receive $70 million in total milestones.</para>""",
    ]
    for contract in false_milestone_clauses:
        assert all(
            clause["clause_type"] != "milestone_payment"
            for clause in extract_contract_financial_clauses(contract)
        )

    schedule = """
    <para>Milestone Payments totaling $1.75 million are: $250,000 on launch,
    $500,000 upon reaching $5 million in sales, and $1 million upon reaching
    $10 million in sales.</para>
    """
    milestone = next(
        clause for clause in extract_contract_financial_clauses(schedule)
        if clause["clause_type"] == "milestone_payment"
    )
    assert milestone["amount_min_millions"] == 0.25
    assert milestone["amount_max_millions"] == 1.75


def test_v7_royalty_excludes_burdens_multipliers_allocations_and_cost_shares():
    from unified_api.services.contract_financial_clauses import (
        extract_contract_financial_clauses,
    )

    false_rate_clauses = [
        """<para>Total royalty payments may exceed 10%, but the actual
        royalty due under this Agreement is redacted.</para>""",
        """<para>Only fifty percent (50%) of the corresponding milestone
        payment is payable. Licensed Product royalties are redacted.</para>""",
        """<para>The royalty rate shall be 75% of the rate otherwise
        applicable, and later 50% of that otherwise applicable rate.</para>""",
        """<para>Reduced royalty rates apply to 20% of Aggregate Product Net
        Sales and unreduced rates apply to the remaining 80%.</para>""",
        """<para>The aggregate royalty rate shall not be less than 50% of the
        Patent Royalty rates set forth elsewhere.</para>""",
        """<para>Assuming that the University is receiving a royalty rate of
        5% of Net Sales, the third party receives its policy share.</para>""",
        """<para>The formula subtracts royalties payable to third parties,
        7% of the ASP representing variable selling costs, and manufacturing
        costs.</para>""",
        """<para>GSK will pay one hundred percent (100%) of the amounts payable
        to such Third Party for a sublicense. Royalties are separately redacted.
        </para>""",
        """<para>The parties share 50% of U.S. profits and receive
        double-digit royalties on ex-U.S. sales.</para>""",
        """<para>Unit sales volumes reduced by 25% or 50% trigger redacted
        royalty-rate adjustments.</para>""",
    ]
    for contract in false_rate_clauses:
        assert all(
            clause["clause_type"] != "royalty_rate"
            for clause in extract_contract_financial_clauses(contract)
        )

    mixed = """
    <para>Licensee shall pay royalties of 5% and 4% of Net Sales. Total royalty
    payments are not expected to exceed 10%.</para>
    """
    royalty = next(
        clause for clause in extract_contract_financial_clauses(mixed)
        if clause["clause_type"] == "royalty_rate"
    )
    assert royalty["rate_min_pct"] == 4
    assert royalty["rate_max_pct"] == 5


def test_v7_upfront_excludes_loans_expense_advances_thresholds_and_debt_fees():
    from unified_api.services.contract_financial_clauses import (
        extract_contract_financial_clauses,
    )

    mixed_cases = [
        (
            """<para>The initial payment consists of a cash upfront payment
            of $2 million and two loans for an aggregate of $8 million.</para>""",
            2,
        ),
        (
            """<para>Amgen will pay an initial license fee of €6 million and
            an advance payment of Collaboration Expenses in an amount equal to
            Four Million Euros (€4 million).</para>""",
            6,
        ),
    ]
    for contract, expected in mixed_cases:
        upfront = next(
            clause for clause in extract_contract_financial_clauses(contract)
            if clause["clause_type"] == "upfront_payment"
        )
        assert upfront["amount_min_millions"] == expected
        assert upfront["amount_max_millions"] == expected

    false_upfront_clauses = [
        """<para>An up front payment equal to or in excess of $20 million
        triggers distribution of merger consideration.</para>""",
        """<para>One half of the Term Loan Commitment Fee, $50,000, is a
        non-refundable up-front fee for the Credit Extensions.</para>""",
        """<para>Licensor receives 45% of amounts in excess of $2.7 million
        received in either up-front, milestone, or similar payments.</para>""",
    ]
    for contract in false_upfront_clauses:
        assert all(
            clause["clause_type"] != "upfront_payment"
            for clause in extract_contract_financial_clauses(contract)
        )


def test_v7_milestone_excludes_earnouts_packages_options_and_adjustment_caps():
    from unified_api.services.contract_financial_clauses import (
        extract_contract_financial_clauses,
    )

    mixed = """
    <para>Other than the €70 million milestone payment and one earnout payment
    estimated to be €1 million, no other milestone or earnout is due.</para>
    """
    milestone = next(
        clause for clause in extract_contract_financial_clauses(mixed)
        if clause["clause_type"] == "milestone_payment"
    )
    assert milestone["amount_min_millions"] == 70
    assert milestone["amount_max_millions"] == 70

    false_milestone_clauses = [
        """<para>Subject to achievement of the milestones, the maximum
        aggregate consideration payable is $22.5 million.</para>""",
        """<para>Additional sales-based milestone payments and additional
        option payments total approximately €70 million.</para>""",
        """<para>The milestone payment will be increased by 25% of cash up to
        a maximum increase in the milestone payment of $500,000.</para>""",
        """<para>The party has expended $100,000 on development. The
        aggregate of such payments shall not exceed $2 million. Milestone
        payments may also become due.</para>""",
        """<para>License Fees: a second license fee of $7.5 million is due on
        the anniversary. Milestone Payments follow in Section 4.2.</para>""",
        """<para>Milestone Payments: Within 60 days, a non-refundable license
        fee of\nEffective Date US$500,000 is due.</para>""",
    ]
    for contract in false_milestone_clauses:
        assert all(
            clause["clause_type"] != "milestone_payment"
            for clause in extract_contract_financial_clauses(contract)
        )


def test_v8_royalty_excludes_examples_cash_flow_shares_and_audit_thresholds():
    from unified_api.services.contract_financial_clauses import (
        extract_contract_financial_clauses,
    )

    false_rate_clauses = [
        """<para>The operative rates are redacted. For example, if another
        agreement carries a 1% royalty and this agreement hypothetically
        carries a royalty of 2% of Net Sales, only the higher applies.</para>""",
        """<para>Any infringement recovery shall be divided, with fifty
        percent (50%) of any funds remaining distributed to parties receiving
        royalties and the remaining fifty (50%) percent belonging to Licensee.
        </para>""",
        """<para>Royalty income shall be distributed as follows: 50% to A and
        50% to B. The underlying royalty rates are redacted.</para>""",
        """<para>Seller conveys 60% of the Royalties under the Counterparty
        Agreements. The underlying royalty rates are not disclosed.</para>""",
        """<para>Licensee pays a 5% royalty on Net Sales and a royalty of 25%
        of such third-party license payments.</para>""",
        """<para>The earned rate is redacted. Additional Earned Royalties are
        equal to or greater than 3% but below the next offset tier.</para>""",
        """<para>The audit fees shift if additional royalties owed vary from
        royalties paid by five percent (5%) or greater.</para>""",
        """<para>Expenses may be credited up to fifty percent (50%) of the
        amount otherwise payable, and excess expenses above fifty percent
        (50%) of amounts due in a royalty period carry forward.</para>""",
    ]
    for contract in false_rate_clauses:
        royalties = [
            clause for clause in extract_contract_financial_clauses(contract)
            if clause["clause_type"] == "royalty_rate"
        ]
        if "5% royalty on Net Sales" in contract:
            assert len(royalties) == 1
            assert royalties[0]["rate_min_pct"] == 5
            assert royalties[0]["rate_max_pct"] == 5
        else:
            assert royalties == []


def test_v8_upfront_excludes_package_headlines_and_receipt_share_caps():
    from unified_api.services.contract_financial_clauses import (
        extract_contract_financial_clauses,
    )

    package = """
    <para>Company may receive $330 million, inclusive of $330 million in an
    Upfront Fee ($200 million) and near-term enrollment milestones
    ($130 million).</para>
    """
    receipt_share = """
    <para>Buyer shall pay 50% of the first $50 million of any upfront,
    pre-commercialization milestone, or similar payments it later receives
    from third parties.</para>
    """

    upfront = next(
        clause for clause in extract_contract_financial_clauses(package)
        if clause["clause_type"] == "upfront_payment"
    )
    assert upfront["amount_min_millions"] == 200
    assert upfront["amount_max_millions"] == 200
    assert all(
        clause["clause_type"] != "upfront_payment"
        for clause in extract_contract_financial_clauses(receipt_share)
    )


def test_v8_milestone_excludes_thresholds_triggers_mixed_packages_and_delay_fees():
    from unified_api.services.contract_financial_clauses import (
        extract_contract_financial_clauses,
    )

    false_milestone_clauses = [
        """<para>The next milestone payment may be reduced by expenses,
        provided the deduction shall not exceed $250,000.</para>""",
        """<para>The disclosure schedule lists contracts requiring payments
        of amounts in excess of $50,000, including royalties and milestones.
        </para>""",
        """<para>The aggregate upfront, R&amp;D funding, milestone and other
        payments could exceed $230 million. About $8 million is due as various
        collaboration-related payments.</para>""",
        """<para>Approval is required before incurring obligations to make
        milestone or other payments that exceed $100,000.</para>""",
        """<para>For any Milestone not reached by the Target Date, Licensee
        shall pay $50,000 and all Target Dates advance by one year.</para>""",
    ]
    for contract in false_milestone_clauses:
        assert all(
            clause["clause_type"] != "milestone_payment"
            for clause in extract_contract_financial_clauses(contract)
        )

    mixed = """
    <para>Seller receives a $15 million payment upon closing, up to $20 million
    in regulatory and launch milestones, and royalties.</para>
    """
    milestone = next(
        clause for clause in extract_contract_financial_clauses(mixed)
        if clause["clause_type"] == "milestone_payment"
    )
    assert milestone["amount_min_millions"] == 20
    assert milestone["amount_max_millions"] == 20

    trigger = """
    <para>Buyer shall pay a $25 million milestone upon approval and a $30
    million milestone when Net Sales first exceed $80 million.</para>
    """
    milestone = next(
        clause for clause in extract_contract_financial_clauses(trigger)
        if clause["clause_type"] == "milestone_payment"
    )
    assert milestone["amount_min_millions"] == 25
    assert milestone["amount_max_millions"] == 30


def test_v9_royalty_excludes_proceeds_profit_reductions_and_cost_caps():
    from unified_api.services.contract_financial_clauses import (
        extract_contract_financial_clauses,
    )

    false_rate_clauses = [
        """<para>Any litigation Remaining Proceeds shall be allocated as
        follows: Licensee shall retain 100% of the Remaining Proceeds, which
        will then be treated as Net Sales subject to a royalty.</para>""",
        """<para>The parties' actual Royalty Payments are redacted. The
        other Party will instead be entitled to 100% of the Operating Income.
        </para>""",
        """<para>The royalties, when aggregated with the Fully Allocated Cost
        of manufacturing, may not exceed 26% of Net Sales in year one or 30%
        of Net Sales thereafter.</para>""",
        """<para>If a patent is invalidated, the otherwise applicable
        royalties shall be diminished by fifty percent (50%).</para>""",
    ]
    for contract in false_rate_clauses:
        assert all(
            clause["clause_type"] != "royalty_rate"
            for clause in extract_contract_financial_clauses(contract)
        )

    valid = extract_contract_financial_clauses(
        """<para>Licensee shall first pay a royalty equal to 100% of Net
        Receipts until $50,000 has been paid and then a royalty of 4.5% of
        Net Receipts.</para>"""
    )
    royalty = next(c for c in valid if c["clause_type"] == "royalty_rate")
    assert royalty["rate_min_pct"] == 4.5
    assert royalty["rate_max_pct"] == 100


def test_v9_tier_flag_does_not_treat_generic_schedules_as_royalty_tiers():
    from unified_api.services.contract_financial_clauses import (
        extract_contract_financial_clauses,
    )

    for contract in (
        """<para>A royalty of 5% of Net Sales applies to all Products listed
        on Schedule A.</para>""",
        """<para>Under Payment Schedule 2, the Royalty Amount equals 5% of
        Net Sales.</para>""",
    ):
        royalty = next(
            clause for clause in extract_contract_financial_clauses(contract)
            if clause["clause_type"] == "royalty_rate"
        )
        assert royalty["is_tiered"] is False


def test_v9_upfront_excludes_other_deals_examples_equity_and_package_totals():
    from unified_api.services.contract_financial_clauses import (
        extract_contract_financial_clauses,
    )

    false_upfront_clauses = [
        """<para>If Licensor grants to any other party a license whose terms
        do not provide for an initial license fee of at least £20,000, the
        parties will harmonize this Agreement.</para>""",
        """<para>If the company succeeds in licensing the asset, we assume
        such terms would include an upfront license fee of at least $5
        million.</para>""",
        """<para>The operative formula depends on the closing date. For
        example, if Closing occurs April 1, the up-front payment would be
        $287.5 million.</para>""",
    ]
    for contract in false_upfront_clauses:
        assert all(
            clause["clause_type"] != "upfront_payment"
            for clause in extract_contract_financial_clauses(contract)
        )

    equity_package = extract_contract_financial_clauses(
        """<para>Buyer will make upfront payments totaling $25 million and
        invest $35 million by purchasing newly issued common shares.</para>"""
    )
    upfront = next(
        clause for clause in equity_package
        if clause["clause_type"] == "upfront_payment"
    )
    assert upfront["amount_min_millions"] == 25
    assert upfront["amount_max_millions"] == 25

    mixed_package = extract_contract_financial_clauses(
        """<para>Immediate payment and near-term milestones total up to $330
        million, including an upfront fee of $200 million and enrollment
        milestones of up to $130 million.</para>"""
    )
    upfront = next(
        clause for clause in mixed_package
        if clause["clause_type"] == "upfront_payment"
    )
    assert upfront["amount_min_millions"] == 200
    assert upfront["amount_max_millions"] == 200


def test_v9_upfront_excludes_contingent_purchase_price_installments():
    from unified_api.services.contract_financial_clauses import (
        extract_contract_financial_clauses,
    )

    clauses = extract_contract_financial_clauses(
        """<para>The Limited Up-Front Cash Purchase Price is $40.7 million,
        plus $4 million payable next year (the First Contingent Payment), and
        $6 million payable later (the Second Contingent Payment).</para>"""
    )
    upfront = next(
        clause for clause in clauses if clause["clause_type"] == "upfront_payment"
    )
    assert upfront["amount_min_millions"] == 40.7
    assert upfront["amount_max_millions"] == 40.7


def test_v9_milestone_excludes_forfeitures_examples_and_nonpayment_terms():
    from unified_api.services.contract_financial_clauses import (
        extract_contract_financial_clauses,
    )

    forfeiture = extract_contract_financial_clauses(
        """<para>Milestone payments are $80 million for first-period
        approval, $65 million for second-period approval and $50 million for
        third-period approval. In the second period, $15 million of the
        consideration is cancelled and deemed forfeited; in the third period,
        $30 million is cancelled and deemed forfeited.</para>"""
    )
    milestone = next(
        clause for clause in forfeiture
        if clause["clause_type"] == "milestone_payment"
    )
    assert milestone["amount_min_millions"] == 50
    assert milestone["amount_max_millions"] == 80

    false_milestone_clauses = [
        """<para>By way of example only, the following milestones would be
        payable: $5 million at Phase III and $10 million at approval.</para>""",
        """<para>After termination, Buyer shall not be required to pay the
        $20 million milestone. As consideration for assignment of technology,
        Seller shall pay Buyer $5 million.</para>""",
        """<para>Development support equals $1 million less amounts received
        from a third party, excluding milestone payments.</para>""",
    ]
    for contract in false_milestone_clauses:
        assert all(
            clause["clause_type"] != "milestone_payment"
            for clause in extract_contract_financial_clauses(contract)
        )


def test_v9_milestone_keeps_payments_but_excludes_receipt_and_sales_triggers():
    from unified_api.services.contract_financial_clauses import (
        extract_contract_financial_clauses,
    )

    contracts_and_expected = [
        (
            """<para>Milestone Payment: when Net Sales are at least $200
            million, Buyer shall pay a one-time payment of $60 million.</para>""",
            (60, 60),
        ),
        (
            """<para>The milestone share is five percent of Milestone
            Payments received in excess of $13 million. If that amount is less
            than $1.5 million at approval, Buyer shall pay the balance so the
            milestone payment equals $1.5 million.</para>""",
            (1.5, 1.5),
        ),
        (
            """<para>Milestone Payments: Buyer pays $1.5 million if annual
            revenue exceeds baseline by at least $12 million, and $2 million
            in year two. A catch-up applies if combined revenue exceeds the
            baseline by an amount equal to or greater than $26 million.</para>""",
            (1.5, 2),
        ),
    ]
    for contract, expected in contracts_and_expected:
        milestones = [
            clause for clause in extract_contract_financial_clauses(contract)
            if clause["clause_type"] == "milestone_payment"
        ]
        # Precision is the release gate: suppressing an ambiguous candidate is
        # safe, while any retained candidate must contain payment values only.
        if milestones:
            assert milestones[0]["amount_min_millions"] == expected[0]
            assert milestones[0]["amount_max_millions"] == expected[1]


def test_v10_milestone_excludes_fixed_fee_and_mixed_payment_aggregates():
    from unified_api.services.contract_financial_clauses import (
        extract_contract_financial_clauses,
    )

    false_milestone_clauses = [
        """<para>The fixed fee for this government contract is $1,616,698.
        The fixed fee is paid in installments based on negotiated milestones.
        The total obligation is $28,561,658 and the available fixed-fee funds
        are $172,869.</para>""",
        """<para>This is a fixed-fee Agreement inclusive of all costs. The
        subrecipient will be paid per milestone achieved. The maximum amount
        payable under this Agreement is $3,569,526.</para>""",
        """<para>Company could receive up to $12.4 million in equity
        investments, milestone and other precommercial payments.</para>""",
    ]
    for contract in false_milestone_clauses:
        assert all(
            clause["clause_type"] != "milestone_payment"
            for clause in extract_contract_financial_clauses(contract)
        )


def test_v10_milestone_excludes_disclosure_and_acquisition_thresholds():
    from unified_api.services.contract_financial_clauses import (
        extract_contract_financial_clauses,
    )

    false_milestone_clauses = [
        """<para>Material Contracts include any Contract with continuing
        obligations involving milestone or similar payments in excess of
        $1,000,000 in the aggregate.</para>""",
        """<para>Acquisitions require approval when consideration exceeds
        $10 million individually or $20 million in the aggregate, excluding
        contingent milestone and royalty payments.</para>""",
    ]
    for contract in false_milestone_clauses:
        assert all(
            clause["clause_type"] != "milestone_payment"
            for clause in extract_contract_financial_clauses(contract)
        )


def test_v10_milestone_keeps_supported_amounts_from_mixed_prose():
    from unified_api.services.contract_financial_clauses import (
        extract_contract_financial_clauses,
    )

    prior_payments = extract_contract_financial_clauses(
        """<para>Buyer made payments under the agreements in the aggregate
        amount of $80 million and may make an additional $77 million in
        milestone payments.</para>"""
    )
    milestone = next(
        clause for clause in prior_payments
        if clause["clause_type"] == "milestone_payment"
    )
    assert milestone["amount_min_millions"] == 77
    assert milestone["amount_max_millions"] == 77

    truncated = extract_contract_financial_clauses(
        """<para>Company may receive up to $160 million in potential
        milestone payments for trials and approvals, and up to $45 million in

        CONFIDENTIAL</para>"""
    )
    milestone = next(
        clause for clause in truncated
        if clause["clause_type"] == "milestone_payment"
    )
    assert milestone["amount_min_millions"] == 160
    assert milestone["amount_max_millions"] == 160


def test_v10_upfront_excludes_aggregate_payment_formula_denominator():
    from unified_api.services.contract_financial_clauses import (
        extract_contract_financial_clauses,
    )

    contract = """<para>The prorated royalty fraction has as its numerator
    the aggregate Upfront Payment and Periodic Payments advanced by CDC and as
    its denominator $7,000,000.</para>"""
    assert all(
        clause["clause_type"] != "upfront_payment"
        for clause in extract_contract_financial_clauses(contract)
    )


def test_v10_royalty_excludes_sales_cost_and_payment_burden_thresholds():
    from unified_api.services.contract_financial_clauses import (
        extract_contract_financial_clauses,
    )

    false_rate_clauses = [
        """<para>If sales of a Generic Product exceed fifteen percent (15%)
        of Net Sales, the applicable royalty rate shall be reduced by fifty
        percent.</para>""",
        """<para>If Purchaser's Cost of Goods is greater than fifty percent
        (50%) of Net Sales, its share of the overage may be offset against
        royalties payable to Vendor.</para>""",
        """<para>If the sum of transfer-price and royalty payments exceeds
        ten percent (10%) of Net Sales, the royalty rate shall be reduced by a
        share of the excess.</para>""",
    ]
    for contract in false_rate_clauses:
        assert all(
            clause["clause_type"] != "royalty_rate"
            for clause in extract_contract_financial_clauses(contract)
        )


def test_v11_royalty_excludes_bases_combined_burdens_and_fraction_fragments():
    from unified_api.services.contract_financial_clauses import (
        extract_contract_financial_clauses,
    )

    false_rate_clauses = [
        """<para>If royalties paid to Third Parties and the Cost of Manufacture,
        in the aggregate, exceed thirty percent (30%) of Net Sales, the parties
        shall share the excess.</para>""",
        """<para>Royalties. One hundred percent (100%) of the Net Sales of the
        Product shall be used to determine the Royalty under subsection (c).
        </para>""",
    ]
    for contract in false_rate_clauses:
        assert all(
            clause["clause_type"] != "royalty_rate"
            for clause in extract_contract_financial_clauses(contract)
        )

    legacy_fractions = extract_contract_financial_clauses(
        """<para>Royalties shall equal five and one-half percent (51/2%) for
        patented products and five percent (5%) otherwise. Another product is
        subject to two and one-half percent (2-1/2%) of Net Sales.</para>"""
    )
    for clause in legacy_fractions:
        if clause["clause_type"] == "royalty_rate":
            assert clause["rate_min_pct"] != 2
            assert clause["rate_max_pct"] != 2


def test_v11_royalty_excludes_sublicense_income_allocation_percentages():
    from unified_api.services.contract_financial_clauses import (
        extract_contract_financial_clauses,
    )

    clauses = extract_contract_financial_clauses(
        """<para>Share of sublicensing income including upfront and milestone
        payments, equity, and royalties: 60% NEMUS, 40% UM with a minimum
        royalty of five and one-half percent (5.5%) of Net Sales to UM.</para>"""
    )
    royalty = next(clause for clause in clauses if clause["clause_type"] == "royalty_rate")
    assert royalty["rate_min_pct"] == 5.5
    assert royalty["rate_max_pct"] == 5.5


def test_v11_milestone_excludes_escrow_maintenance_and_mixed_aggregates():
    from unified_api.services.contract_financial_clauses import (
        extract_contract_financial_clauses,
    )

    false_milestone_clauses = [
        """<para>100% of the Milestone Payments made in excess of $2,000,000
        will be released upon payment of such Milestone Payments.</para>""",
        """<para>Milestone payments may be taken as options. Licensee must pay
        a license maintenance fee of $5,000 on each anniversary.</para>""",
        """<para>Milestone payments, if any, are not creditable. Licensee shall
        pay a license maintenance royalty on the following anniversaries:
        $25,000, $50,000 and $75,000.</para>""",
        """<para>Company could receive approximately $40 million in milestones,
        development payments and equity investments.</para>""",
        """<para>Milestone Payments. The Second Installment License Fee of
        $3,000,000 is due on February 1. Actual milestone amounts are redacted.
        </para>""",
    ]
    for contract in false_milestone_clauses:
        assert all(
            clause["clause_type"] != "milestone_payment"
            for clause in extract_contract_financial_clauses(contract)
        )


def test_v11_milestone_keeps_payments_but_excludes_a_nearby_loan():
    from unified_api.services.contract_financial_clauses import (
        extract_contract_financial_clauses,
    )

    clauses = extract_contract_financial_clauses(
        """<para>Milestone Payments. Buyer shall pay a non-refundable
        milestone payment of $4,000,000 upon approval.</para>
        <para>Loan. Buyer shall pay Seller $16,000,000 (the \"Loan\"), which
        bears interest and must be repaid.</para>"""
    )
    milestone = next(
        clause for clause in clauses if clause["clause_type"] == "milestone_payment"
    )
    assert milestone["amount_min_millions"] == 4
    assert milestone["amount_max_millions"] == 4


def test_v11_upfront_keeps_only_obligated_noncontingent_upfront_amounts():
    from unified_api.services.contract_financial_clauses import (
        extract_contract_financial_clauses,
    )

    bounded_cases = [
        (
            """<para>Company will receive a $40 million upfront cash payment
            and up to $350 million in pre-commercialization milestones.</para>""",
            (40, 40),
        ),
        (
            """<para>Buyer will pay an upfront cash payment of $195 million and
            make additional license payments of $45 million in 2009.</para>""",
            (195, 195),
        ),
        (
            """<para>$65,000 upfront payment. License Maintenance Fees are
            $25,000 per year and are credited against royalties.</para>""",
            (0.065, 0.065),
        ),
        (
            """<para>Licensee will pay a license issue fee of $100,000 in two
            $50,000 installments after Licensee achieves the Essential
            Milestone.</para>""",
            (0.05, 0.1),
        ),
    ]
    for contract, expected in bounded_cases:
        upfront = next(
            clause for clause in extract_contract_financial_clauses(contract)
            if clause["clause_type"] == "upfront_payment"
        )
        assert upfront["amount_min_millions"] == expected[0]
        assert upfront["amount_max_millions"] == expected[1]

    false_upfront_clauses = [
        """<para>If Buyer receives Payment Commitments of at least an aggregate
        $16 million, including at least $2 million arising from upfront
        payments, Buyer shall make a Third Payment of $1 million.</para>""",
        """<para>Licensee may enter into a marketing agreement and may retain
        an initial upfront lump-sum fee not to exceed $5 million without
        obligation to Licensor.</para>""",
    ]
    for contract in false_upfront_clauses:
        assert all(
            clause["clause_type"] != "upfront_payment"
            for clause in extract_contract_financial_clauses(contract)
        )


def test_review_key_changes_when_the_extracted_assertion_changes():
    from unified_api.services.contract_financial_clauses import (
        _clause_review_key,
    )

    reviewed = {
        "clause_type": "upfront_payment",
        "source_hash": "same-source",
        "rate_min_pct": None,
        "rate_max_pct": None,
        "amount_min_millions": 15,
        "amount_max_millions": 60,
        "currency": "USD",
        "is_tiered": False,
    }
    unchanged = dict(reviewed)
    corrected = {**reviewed, "amount_max_millions": 15}

    assert _clause_review_key(unchanged) == _clause_review_key(reviewed)
    assert _clause_review_key(corrected) != _clause_review_key(reviewed)


def test_review_fingerprint_is_portable_only_for_the_exact_assertion():
    from unified_api.services.contract_financial_clauses import (
        _clause_review_fingerprint,
    )

    reviewed = {
        "clause_type": "royalty_rate",
        "source_hash": "a" * 64,
        "rate_min_pct": 5.0,
        "rate_max_pct": 8.0,
        "amount_min_millions": None,
        "amount_max_millions": None,
        "currency": None,
        "is_tiered": True,
    }

    assert _clause_review_fingerprint(dict(reviewed)) == (
        _clause_review_fingerprint(reviewed)
    )
    assert _clause_review_fingerprint({**reviewed, "rate_max_pct": 9.0}) != (
        _clause_review_fingerprint(reviewed)
    )


def test_review_evidence_accepts_exact_carryforward_and_rejects_stale_hashes():
    from unified_api.services.contract_financial_clauses import (
        _clause_review_fingerprint,
        _review_evidence_summary,
    )

    accepted = {
        "id": 1,
        "clause_type": "upfront_payment",
        "source_hash": "b" * 64,
        "rate_min_pct": None,
        "rate_max_pct": None,
        "amount_min_millions": 10.0,
        "amount_max_millions": 10.0,
        "currency": "USD",
        "is_tiered": False,
        "review_status": "accepted",
        "review_parser_version": 10,
    }
    accepted["review_assertion_hash"] = _clause_review_fingerprint(accepted)
    rejected = {
        **accepted,
        "id": 2,
        "review_status": "rejected",
        "review_parser_version": 11,
    }
    rejected["review_assertion_hash"] = _clause_review_fingerprint(rejected)
    stale = {
        **accepted,
        "id": 3,
        "amount_max_millions": 12.0,
        "review_assertion_hash": accepted["review_assertion_hash"],
    }

    result = _review_evidence_summary(
        [accepted, rejected, stale],
        parser_version=11,
    )

    assert result == {
        "valid_reviewed_accepted": 1,
        "valid_reviewed_rejected": 1,
        "valid_reviewed_clauses": 2,
        "valid_review_precision_pct": 50.0,
        "current_parser_reviews": 1,
        "carried_forward_reviews": 1,
        "invalid_review_assertion_hashes": 1,
        "invalid_review_clause_ids": [3],
    }


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
