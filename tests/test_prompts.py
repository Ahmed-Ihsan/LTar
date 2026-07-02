"""Regression tests for versioned prompt constants (PROMPTS.md §5).

These tests guard against silent drift of the mandatory rule markers and
the structural template sections. Any prompt wording change MUST increment
the version suffix and update the corresponding assertions here
(PROMPTS.md §5).
"""
from __future__ import annotations

import pytest

from src.prompts import (
    ALL_PROMPT_CONSTANTS,
    AUDITOR_SYSTEM_V1,
    AUDITOR_USER_TEMPLATE_V1,
    SHARED_SYSTEM_RULES_V1,
    TRANSLATOR_REVISION_ADDENDUM_V1,
    TRANSLATOR_SYSTEM_V1,
    TRANSLATOR_USER_TEMPLATE_V1,
)

pytestmark = pytest.mark.unit

# Mandatory rule markers that MUST appear in every rule-bearing prompt
# (the shared rules and both agent system prompts that concatenate them).
# User-turn templates are not rule-bearing and are checked separately.
_MANDATORY_MARKERS: tuple[str, ...] = (
    "GLOSSARY SUPREMACY",
    "NO HALLUCINATION",
    "JURISDICTION",
)

# Prompts that embed the shared system rules and therefore must carry every
# mandatory marker.
_RULE_BEARING_PROMPTS: dict[str, str] = {
    "SHARED_SYSTEM_RULES_V1": SHARED_SYSTEM_RULES_V1,
    "TRANSLATOR_SYSTEM_V1": TRANSLATOR_SYSTEM_V1,
    "AUDITOR_SYSTEM_V1": AUDITOR_SYSTEM_V1,
}


class TestMandatoryMarkers:
    @pytest.mark.parametrize("marker", _MANDATORY_MARKERS)
    def test_shared_rules_contain_every_mandatory_marker(self, marker: str) -> None:
        assert marker in SHARED_SYSTEM_RULES_V1

    @pytest.mark.parametrize(
        ("name", "prompt"), list(_RULE_BEARING_PROMPTS.items())
    )
    @pytest.mark.parametrize("marker", _MANDATORY_MARKERS)
    def test_rule_bearing_prompts_contain_mandatory_markers(
        self, name: str, prompt: str, marker: str
    ) -> None:
        assert marker in prompt, f"{name} missing mandatory marker: {marker!r}"


class TestSharedRulesNotInlined:
    """DRY (engineering-principles §2.1.3): agent system prompts must
    concatenate the shared rules, not inline a divergent copy."""

    def test_translator_system_includes_shared_rules_verbatim(self) -> None:
        assert SHARED_SYSTEM_RULES_V1 in TRANSLATOR_SYSTEM_V1

    def test_auditor_system_includes_shared_rules_verbatim(self) -> None:
        assert SHARED_SYSTEM_RULES_V1 in AUDITOR_SYSTEM_V1

    def test_shared_rules_is_single_source(self) -> None:
        # The shared rules block must appear exactly once in each agent system
        # prompt (no duplicated/divergent copy).
        assert TRANSLATOR_SYSTEM_V1.count(SHARED_SYSTEM_RULES_V1) == 1
        assert AUDITOR_SYSTEM_V1.count(SHARED_SYSTEM_RULES_V1) == 1


class TestTranslatorPromptStructure:
    def test_system_role_has_direction_placeholders(self) -> None:
        assert "{source_lang}" in TRANSLATOR_SYSTEM_V1
        assert "{target_lang}" in TRANSLATOR_SYSTEM_V1

    def test_user_template_has_required_sections(self) -> None:
        for section in (
            "=== DIRECTION ===",
            "=== GLOSSARY BINDINGS (MANDATORY) ===",
            "=== CONTEXT (retrieved from Iraqi laws corpus) ===",
            "=== SOURCE ===",
            "=== PRIOR DRAFT (revision pass only) ===",
            "=== AUDIT CRITIQUE (revision pass only) ===",
            "=== OUTPUT ===",
        ):
            assert section in TRANSLATOR_USER_TEMPLATE_V1

    def test_user_template_has_placeholders(self) -> None:
        for placeholder in (
            "{source_lang}",
            "{target_lang}",
            "{glossary_bindings}",
            "{context_chunks}",
            "{input_text}",
            "{prior_draft}",
            "{critique}",
        ):
            assert placeholder in TRANSLATOR_USER_TEMPLATE_V1

    def test_revision_addendum_present(self) -> None:
        assert "REVISION pass" in TRANSLATOR_REVISION_ADDENDUM_V1
        assert "Glossary Bindings" in TRANSLATOR_REVISION_ADDENDUM_V1


class TestAuditorPromptStructure:
    def test_system_role_has_four_criteria(self) -> None:
        for criterion in (
            "GLOSSARY COMPLIANCE",
            "LEGAL FIDELITY",
            "COMPLETENESS",
            "LANGUAGE QUALITY",
        ):
            assert criterion in AUDITOR_SYSTEM_V1

    def test_system_role_has_decision_rule(self) -> None:
        assert "verdict = REVISE" in AUDITOR_SYSTEM_V1
        assert "verdict = APPROVE" in AUDITOR_SYSTEM_V1

    def test_system_role_describes_json_schema(self) -> None:
        for field in ('"verdict"', '"critique"', '"violations"', '"confidence"'):
            assert field in AUDITOR_SYSTEM_V1

    def test_user_template_has_required_sections(self) -> None:
        for section in (
            "=== DIRECTION ===",
            "=== GLOSSARY BINDINGS (ground truth) ===",
            "=== CONTEXT ===",
            "=== SOURCE ===",
            "=== DRAFT ===",
            "=== OUTPUT ===",
        ):
            assert section in AUDITOR_USER_TEMPLATE_V1

    def test_user_template_has_placeholders(self) -> None:
        for placeholder in (
            "{source_lang}",
            "{target_lang}",
            "{glossary_bindings}",
            "{context_chunks}",
            "{input_text}",
            "{draft}",
        ):
            assert placeholder in AUDITOR_USER_TEMPLATE_V1


class TestRegistry:
    def test_all_prompt_constants_registered(self) -> None:
        expected = {
            "SHARED_SYSTEM_RULES_V1",
            "TRANSLATOR_SYSTEM_V1",
            "TRANSLATOR_USER_TEMPLATE_V1",
            "TRANSLATOR_REVISION_ADDENDUM_V1",
            "AUDITOR_SYSTEM_V1",
            "AUDITOR_USER_TEMPLATE_V1",
        }
        assert expected <= set(ALL_PROMPT_CONSTANTS)

    @pytest.mark.parametrize("name", list(ALL_PROMPT_CONSTANTS))
    def test_every_prompt_is_non_empty(self, name: str) -> None:
        assert ALL_PROMPT_CONSTANTS[name].strip() != ""
