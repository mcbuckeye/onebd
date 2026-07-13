"""
TDD: Finance detail parser tests.
"""
from unittest.mock import MagicMock, patch


class TestFinanceDetailParser:
    """Test parsing of finance_detail_raw into structured data."""

    def test_parse_upfront_payment(self):
        from unified_api.services.finance_parser import parse_finance_detail
        result = parse_finance_detail("Upfront payment of $50 million")
        assert result["upfront"] is not None
        assert result["upfront"]["amount"] == 50
        assert result["upfront"]["currency"] == "USD"

    def test_parse_milestone_payments(self):
        from unified_api.services.finance_parser import parse_finance_detail
        result = parse_finance_detail(
            "Up to $200 million in development milestones and $300 million in commercial milestones"
        )
        assert result["milestones"]["development"] is not None
        assert result["milestones"]["commercial"] is not None

    def test_parse_royalty_rate(self):
        from unified_api.services.finance_parser import parse_finance_detail
        result = parse_finance_detail("Tiered royalties ranging from 8% to 15% on net sales")
        assert result["royalties"] is not None
        assert result["royalties"]["min_rate"] == 8
        assert result["royalties"]["max_rate"] == 15

    def test_parse_total_value(self):
        from unified_api.services.finance_parser import parse_finance_detail
        result = parse_finance_detail("Total deal value of up to $1.2 billion")
        assert result["total_value"] is not None
        assert result["total_value"]["amount"] == 1200  # in millions

    def test_parse_empty_string(self):
        from unified_api.services.finance_parser import parse_finance_detail
        result = parse_finance_detail("")
        assert result["upfront"] is None
        assert result["royalties"] is None
        assert result["total_value"] is None

    def test_parse_none_input(self):
        from unified_api.services.finance_parser import parse_finance_detail
        result = parse_finance_detail(None)
        assert isinstance(result, dict)

    def test_parse_complex_detail(self):
        from unified_api.services.finance_parser import parse_finance_detail
        text = """
        $75 million upfront payment. Up to $500 million in development and
        regulatory milestone payments. Up to $750 million in commercial milestones.
        Tiered royalties from 10% to 20% on worldwide net sales.
        Total potential deal value of approximately $1.325 billion.
        """
        result = parse_finance_detail(text)
        assert result["upfront"]["amount"] == 75
        assert result["total_value"]["amount"] == 1325
        assert result["royalties"]["min_rate"] == 10
        assert result["royalties"]["max_rate"] == 20

    def test_parse_million_abbreviation(self):
        from unified_api.services.finance_parser import parse_finance_detail
        result = parse_finance_detail("$50M upfront payment")
        assert result["upfront"]["amount"] == 50

    def test_parse_billion_to_millions(self):
        from unified_api.services.finance_parser import parse_finance_detail
        result = parse_finance_detail("Total deal value of $2.5 billion")
        assert result["total_value"]["amount"] == 2500  # stored in millions

    def test_parse_euro_amounts(self):
        from unified_api.services.finance_parser import parse_finance_detail
        result = parse_finance_detail("€50 million upfront payment")
        assert result["upfront"] is not None
        assert result["upfront"]["amount"] == 50
        assert result["upfront"]["currency"] == "EUR"

    def test_parse_yen_amounts(self):
        from unified_api.services.finance_parser import parse_finance_detail
        result = parse_finance_detail("¥5 billion upfront payment")
        assert result["upfront"] is not None
        assert result["upfront"]["amount"] == 5000  # stored in millions
        assert result["upfront"]["currency"] == "JPY"

    def test_parse_up_to_pattern(self):
        from unified_api.services.finance_parser import parse_finance_detail
        result = parse_finance_detail("up to $100 million in milestones")
        # Should extract $100M even with "up to"
        assert result["milestones"]["development"] is not None or \
               result["milestones"]["regulatory"] is not None or \
               result["milestones"]["commercial"] is not None

    def test_parse_approximately_pattern(self):
        from unified_api.services.finance_parser import parse_finance_detail
        result = parse_finance_detail("approximately $75 million upfront")
        assert result["upfront"] is not None
        assert result["upfront"]["amount"] == 75

    def test_parse_no_financial_terms_disclosed(self):
        from unified_api.services.finance_parser import parse_finance_detail
        result = parse_finance_detail("No financial terms disclosed")
        assert result["upfront"] is None
        assert result["total_value"] is None
        assert result.get("undisclosed", False) is True

    def test_parse_combined_development_regulatory_milestones(self):
        from unified_api.services.finance_parser import parse_finance_detail
        result = parse_finance_detail("$500M in development and regulatory milestones")
        # Should capture in development milestones
        assert result["milestones"]["development"] is not None
        assert result["milestones"]["development"]["amount"] == 500

    def test_parse_combined_development_commercial_milestones(self):
        from unified_api.services.finance_parser import parse_finance_detail
        result = parse_finance_detail("$400 million in development and commercial milestone payments")
        assert result["milestones"]["development"] is not None
        assert result["milestones"]["development"]["amount"] == 400

    def test_parse_pound_sterling(self):
        from unified_api.services.finance_parser import parse_finance_detail
        result = parse_finance_detail("£100 million upfront payment")
        assert result["upfront"] is not None
        assert result["upfront"]["amount"] == 100
        assert result["upfront"]["currency"] == "GBP"

    def test_parse_scientific_milestone(self):
        from unified_api.services.finance_parser import parse_finance_detail
        result = parse_finance_detail("$250M in clinical and regulatory milestones")
        assert result["milestones"]["development"] is not None
        assert result["milestones"]["development"]["amount"] == 250

    def test_parse_sales_milestones(self):
        from unified_api.services.finance_parser import parse_finance_detail
        result = parse_finance_detail("Up to $600 million in sales-based milestones")
        assert result["milestones"]["commercial"] is not None
        assert result["milestones"]["commercial"]["amount"] == 600

    def test_parse_multiple_currencies_prefers_first(self):
        from unified_api.services.finance_parser import parse_finance_detail
        result = parse_finance_detail("€50 million upfront, with additional $100 million in milestones")
        assert result["upfront"]["currency"] == "EUR"
        # Development milestones should be captured even with different currency
        assert result["milestones"]["development"] is not None or \
               result["milestones"]["regulatory"] is not None or \
               result["milestones"]["commercial"] is not None


class TestCortellisFinanceJsonParser:
    def test_extracts_upfront_with_payment_basis_and_provenance(self):
        from unified_api.services.finance_parser import extract_financial_terms

        payload = {
            "PaymentsToPrincipal": {
                "PaymentsPaid": {
                    "PaymentsGeneral": {
                        "Payment": {
                            "Date": "2025-01-02T00:00:00Z",
                            "Type": "Upfront Payment",
                            "Values": {
                                "@attributes": {
                                    "accuracy": "=",
                                    "disclosureStatus": "Known",
                                },
                                "ValueReported": {
                                    "@text": "75.00",
                                    "@attributes": {"unit": "Million", "currency": "EUR"},
                                },
                                "ValueConvertedToUSD": {
                                    "@text": "80.00",
                                    "@attributes": {"unit": "Million"},
                                },
                            },
                        }
                    }
                }
            }
        }

        terms = extract_financial_terms(payload, deal_id=42)

        assert len(terms) == 1
        assert terms[0]["deal_id"] == 42
        assert terms[0]["recipient"] == "principal"
        assert terms[0]["basis"] == "paid"
        assert terms[0]["term_type"] == "upfront_payment"
        assert terms[0]["amount_reported_millions"] == 75
        assert terms[0]["reported_currency"] == "EUR"
        assert terms[0]["amount_usd_millions"] == 80
        assert terms[0]["confidence"] == 1
        assert terms[0]["source_path"].startswith("PaymentsToPrincipal")

    def test_extracts_milestone_breakdown_without_losing_total(self):
        from unified_api.services.finance_parser import extract_financial_terms

        payload = {
            "PaymentsToPrincipal": {
                "PaymentsProjectedSigning": {
                    "PaymentsGeneral": {
                        "Payment": {
                            "Type": "Milestones",
                            "Values": {
                                "@attributes": {"disclosureStatus": "Known"},
                                "ValueConvertedToUSD": {
                                    "@text": "500",
                                    "@attributes": {"unit": "Million"},
                                },
                            },
                            "PaymentBreakdown": {
                                "Payment": [
                                    {"Type": "Dev/Reg Milestones", "Values": {}},
                                    {"Type": "Sales Milestones", "Values": {}},
                                ]
                            },
                        }
                    }
                }
            }
        }

        terms = extract_financial_terms(payload)

        assert [term["term_type"] for term in terms] == [
            "milestone_total",
            "development_regulatory_milestone",
            "commercial_milestone",
        ]
        assert terms[0]["amount_usd_millions"] == 500
        assert terms[1]["is_breakdown"] is True

    def test_percentage_term_never_uses_bogus_converted_million_value(self):
        from unified_api.services.finance_parser import extract_financial_terms

        payload = {
            "PaymentsToPartner": {
                "PaymentsProjectedCurrent": {
                    "PaymentsPercentage": {
                        "Payment": {
                            "Type": "Royalty(%)",
                            "Values": {
                                "@attributes": {"disclosureStatus": "Known"},
                                "ValueReported": {
                                    "@text": "12.5",
                                    "@attributes": {"unit": "%"},
                                },
                                "ValueConvertedToUSD": {
                                    "@text": "12.5",
                                    "@attributes": {"unit": "Million"},
                                },
                            },
                        }
                    }
                }
            }
        }

        term = extract_financial_terms(payload)[0]

        assert term["term_type"] == "royalty_rate"
        assert term["rate_min_pct"] == 12.5
        assert term["rate_max_pct"] == 12.5
        assert term["amount_usd_millions"] is None

    def test_cortellis_abbreviated_billion_and_trillion_units_are_normalized(self):
        from unified_api.services.finance_parser import extract_financial_terms

        def payload(unit, value):
            return {
                "PaymentsToPrincipal": {
                    "PaymentsPaid": {
                        "PaymentsGeneral": {
                            "Payment": {
                                "Type": "Upfront Payment",
                                "Values": {
                                    "@attributes": {"disclosureStatus": "Known"},
                                    "ValueReported": {
                                        "@text": str(value),
                                        "@attributes": {"unit": unit, "currency": "USD"},
                                    },
                                    "ValueConvertedToUSD": {
                                        "@text": str(value),
                                        "@attributes": {"unit": unit},
                                    },
                                },
                            }
                        }
                    }
                }
            }

        billion = extract_financial_terms(payload("B", 1.5))[0]
        trillion = extract_financial_terms(payload("T", 2))[0]

        assert billion["amount_usd_millions"] == 1500
        assert trillion["amount_usd_millions"] == 2_000_000

    def test_all_known_percentage_terms_capture_directional_bounds(self):
        from unified_api.services.finance_parser import extract_financial_terms

        payload = {
            "PaymentsToPartner": {
                "PaymentsProjectedCurrent": {
                    "PaymentsPercentage": {
                        "Payment": [
                            {
                                "Type": "Profit Split(%)",
                                "Values": {
                                    "@attributes": {
                                        "accuracy": "=<",
                                        "disclosureStatus": "Known",
                                    },
                                    "ValueReported": {
                                        "@text": "40",
                                        "@attributes": {"unit": "%"},
                                    },
                                },
                            },
                            {
                                "Type": "Equity Stake(%)",
                                "Values": {
                                    "@attributes": {
                                        "accuracy": ">=",
                                        "disclosureStatus": "Known",
                                    },
                                    "ValueReported": {
                                        "@text": "10",
                                        "@attributes": {"unit": "%"},
                                    },
                                },
                            },
                        ]
                    }
                }
            }
        }

        profit_split, equity_stake = extract_financial_terms(payload)

        assert (profit_split["rate_min_pct"], profit_split["rate_max_pct"]) == (
            None,
            40,
        )
        assert (equity_stake["rate_min_pct"], equity_stake["rate_max_pct"]) == (
            10,
            None,
        )

    def test_non_json_payload_returns_no_structured_terms(self):
        from unified_api.services.finance_parser import extract_financial_terms

        assert extract_financial_terms("Upfront payment of $50 million") == []

    def test_persisted_term_validation_replays_source_payload(self):
        from unified_api.services.finance_parser import extract_financial_terms
        from unified_api.services.financial_terms import validate_financial_term_record

        payload = {
            "PaymentsToPrincipal": {
                "PaymentsPaid": {
                    "PaymentsGeneral": {
                        "Payment": {
                            "Type": "Upfront Payment",
                            "Values": {
                                "@attributes": {
                                    "accuracy": "=",
                                    "disclosureStatus": "Known",
                                },
                                "ValueReported": {
                                    "@text": "1.25",
                                    "@attributes": {"unit": "B", "currency": "USD"},
                                },
                                "ValueConvertedToUSD": {
                                    "@text": "1.25",
                                    "@attributes": {"unit": "B"},
                                },
                            },
                        }
                    }
                }
            }
        }
        term = extract_financial_terms(payload, deal_id=42)[0]

        assert validate_financial_term_record(term) == []

        term["amount_usd_millions"] = 1.25
        mismatches = validate_financial_term_record(term)
        assert mismatches == [{
            "field": "amount_usd_millions",
            "expected": 1250.0,
            "actual": 1.25,
        }]


def test_celery_financial_extraction_runs_resumable_batch():
    expected = {"processed": 1000, "terms_extracted": 2500, "errors": 0}
    session = MagicMock()
    context = MagicMock()
    context.__enter__.return_value = session
    with (
        patch(
            "unified_api.services.database.get_cortellis_session",
            return_value=context,
        ),
        patch(
            "unified_api.services.financial_terms.extract_financial_term_batch",
            return_value=expected,
        ) as extract,
    ):
        from unified_api.workers.celery_app import extract_cortellis_financial_terms

        assert extract_cortellis_financial_terms.run() == expected
        extract.assert_called_once_with(session, batch_size=1000)
