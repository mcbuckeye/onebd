"""
TDD: Clinical protocol analyzer tests.

Dedicated mode for analyzing clinical study protocols with
optimized prompts for endpoints, I/E criteria, dosing, etc.
"""
import pytest
from unittest.mock import MagicMock


class TestProtocolQuestionClassifier:
    """Classify protocol questions to use optimized prompts."""

    def test_classifies_endpoint_question(self):
        from unified_api.services.protocol_analyzer import classify_protocol_question
        assert classify_protocol_question("What are the primary endpoints?") == "endpoints"

    def test_classifies_inclusion_exclusion(self):
        from unified_api.services.protocol_analyzer import classify_protocol_question
        assert classify_protocol_question("What are the inclusion criteria?") == "eligibility"

    def test_classifies_dosing(self):
        from unified_api.services.protocol_analyzer import classify_protocol_question
        assert classify_protocol_question("What is the dosing regimen?") == "dosing"

    def test_classifies_sample_size(self):
        from unified_api.services.protocol_analyzer import classify_protocol_question
        assert classify_protocol_question("What is the sample size and power calculation?") == "statistics"

    def test_classifies_safety(self):
        from unified_api.services.protocol_analyzer import classify_protocol_question
        assert classify_protocol_question("What safety monitoring is in place?") == "safety"

    def test_classifies_general(self):
        from unified_api.services.protocol_analyzer import classify_protocol_question
        assert classify_protocol_question("Tell me about this protocol") == "general"


class TestProtocolPromptTemplates:
    """Optimized prompts for different protocol question types."""

    def test_endpoint_prompt_exists(self):
        from unified_api.services.protocol_analyzer import PROTOCOL_PROMPTS
        assert "endpoints" in PROTOCOL_PROMPTS
        assert "primary" in PROTOCOL_PROMPTS["endpoints"].lower()

    def test_eligibility_prompt_exists(self):
        from unified_api.services.protocol_analyzer import PROTOCOL_PROMPTS
        assert "eligibility" in PROTOCOL_PROMPTS
        assert "inclusion" in PROTOCOL_PROMPTS["eligibility"].lower()

    def test_dosing_prompt_exists(self):
        from unified_api.services.protocol_analyzer import PROTOCOL_PROMPTS
        assert "dosing" in PROTOCOL_PROMPTS
        assert "dose" in PROTOCOL_PROMPTS["dosing"].lower()

    def test_statistics_prompt_exists(self):
        from unified_api.services.protocol_analyzer import PROTOCOL_PROMPTS
        assert "statistics" in PROTOCOL_PROMPTS
        assert "sample size" in PROTOCOL_PROMPTS["statistics"].lower()

    def test_safety_prompt_exists(self):
        from unified_api.services.protocol_analyzer import PROTOCOL_PROMPTS
        assert "safety" in PROTOCOL_PROMPTS
