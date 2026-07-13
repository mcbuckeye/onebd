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
