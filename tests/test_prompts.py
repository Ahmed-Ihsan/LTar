"""Regression tests for versioned prompt constants (PROMPTS.md §5).

These tests guard against silent drift of the mandatory rule markers and
the structural template sections. Any prompt wording change MUST increment
the version suffix and update the corresponding assertions here
(PROMPTS.md §5).
"""
from __future__ import annotations

import pytest

from src.components.translation_pipeline.prompts import (
    ALL_PROMPT_CONSTANTS,
    AUDITOR_SYSTEM_V1,
    AUDITOR_SYSTEM_V2,
    AUDITOR_SYSTEM_V3,
    AUDITOR_SYSTEM_V4,
    AUDITOR_USER_TEMPLATE_V1,
    AUDITOR_USER_TEMPLATE_V2,
    AUDITOR_USER_TEMPLATE_V3,
    AUDITOR_USER_TEMPLATE_V4,
    SHARED_SYSTEM_RULES_V1,
    SHARED_SYSTEM_RULES_V2,
    SHARED_SYSTEM_RULES_V3,
    SHARED_SYSTEM_RULES_V4,
    TRANSLATOR_REVISION_ADDENDUM_V1,
    TRANSLATOR_REVISION_ADDENDUM_V2,
    TRANSLATOR_REVISION_ADDENDUM_V3,
    TRANSLATOR_REVISION_ADDENDUM_V4,
    TRANSLATOR_SYSTEM_V1,
    TRANSLATOR_SYSTEM_V2,
    TRANSLATOR_SYSTEM_V3,
    TRANSLATOR_SYSTEM_V4,
    TRANSLATOR_USER_TEMPLATE_V1,
    TRANSLATOR_USER_TEMPLATE_V2,
    TRANSLATOR_USER_TEMPLATE_V3,
    TRANSLATOR_USER_TEMPLATE_V4,
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


# ---------------------------------------------------------------------------
# V2 prompt regression tests
# ---------------------------------------------------------------------------
_RULE_BEARING_PROMPTS_V2: dict[str, str] = {
    "SHARED_SYSTEM_RULES_V2": SHARED_SYSTEM_RULES_V2,
    "TRANSLATOR_SYSTEM_V2": TRANSLATOR_SYSTEM_V2,
    "AUDITOR_SYSTEM_V2": AUDITOR_SYSTEM_V2,
}


class TestV2MandatoryMarkers:
    @pytest.mark.parametrize("marker", _MANDATORY_MARKERS)
    def test_shared_rules_v2_contain_every_mandatory_marker(self, marker: str) -> None:
        assert marker in SHARED_SYSTEM_RULES_V2

    @pytest.mark.parametrize(
        ("name", "prompt"), list(_RULE_BEARING_PROMPTS_V2.items())
    )
    @pytest.mark.parametrize("marker", _MANDATORY_MARKERS)
    def test_v2_rule_bearing_prompts_contain_mandatory_markers(
        self, name: str, prompt: str, marker: str
    ) -> None:
        assert marker in prompt, f"{name} missing mandatory marker: {marker!r}"


class TestV2SharedRulesNotInlined:
    def test_translator_system_v2_includes_shared_rules_verbatim(self) -> None:
        assert SHARED_SYSTEM_RULES_V2 in TRANSLATOR_SYSTEM_V2

    def test_auditor_system_v2_includes_shared_rules_verbatim(self) -> None:
        assert SHARED_SYSTEM_RULES_V2 in AUDITOR_SYSTEM_V2

    def test_shared_rules_v2_is_single_source(self) -> None:
        assert TRANSLATOR_SYSTEM_V2.count(SHARED_SYSTEM_RULES_V2) == 1
        assert AUDITOR_SYSTEM_V2.count(SHARED_SYSTEM_RULES_V2) == 1


class TestV2TranslatorPromptStructure:
    def test_system_role_has_direction_placeholders(self) -> None:
        assert "{source_lang}" in TRANSLATOR_SYSTEM_V2
        assert "{target_lang}" in TRANSLATOR_SYSTEM_V2

    def test_user_template_has_required_sections(self) -> None:
        for section in (
            "=== DIRECTION ===",
            "=== GLOSSARY BINDINGS (MANDATORY",
            "=== CONTEXT",
            "=== SOURCE ===",
            "=== PRIOR DRAFT (revision pass only) ===",
            "=== AUDIT CRITIQUE (revision pass only) ===",
            "=== OUTPUT ===",
        ):
            assert section in TRANSLATOR_USER_TEMPLATE_V2

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
            assert placeholder in TRANSLATOR_USER_TEMPLATE_V2

    def test_revision_addendum_v2_present(self) -> None:
        assert "REVISION pass" in TRANSLATOR_REVISION_ADDENDUM_V2
        assert "Glossary Bindings" in TRANSLATOR_REVISION_ADDENDUM_V2

    def test_v2_has_court_hierarchy_mapping(self) -> None:
        assert "محكمة البداية" in SHARED_SYSTEM_RULES_V2
        assert "Court of First Instance" in SHARED_SYSTEM_RULES_V2
        assert "محكمة التمييز" in SHARED_SYSTEM_RULES_V2
        assert "Court of Cassation" in SHARED_SYSTEM_RULES_V2

    def test_v2_has_translation_methodology(self) -> None:
        assert "TRANSLATION METHODOLOGY" in TRANSLATOR_SYSTEM_V2

    def test_v2_has_priority_awareness(self) -> None:
        assert "priority" in TRANSLATOR_SYSTEM_V2.lower()


class TestV2AuditorPromptStructure:
    def test_system_role_has_four_criteria(self) -> None:
        for criterion in (
            "GLOSSARY COMPLIANCE",
            "LEGAL FIDELITY",
            "COMPLETENESS",
            "LANGUAGE QUALITY",
        ):
            assert criterion in AUDITOR_SYSTEM_V2

    def test_system_role_has_decision_rule(self) -> None:
        assert "verdict = REVISE" in AUDITOR_SYSTEM_V2
        assert "verdict = APPROVE" in AUDITOR_SYSTEM_V2

    def test_system_role_describes_json_schema(self) -> None:
        for field in ('"verdict"', '"critique"', '"violations"', '"confidence"'):
            assert field in AUDITOR_SYSTEM_V2

    def test_user_template_has_required_sections(self) -> None:
        for section in (
            "=== DIRECTION ===",
            "=== GLOSSARY BINDINGS (ground truth",
            "=== CONTEXT ===",
            "=== SOURCE ===",
            "=== DRAFT ===",
            "=== OUTPUT ===",
        ):
            assert section in AUDITOR_USER_TEMPLATE_V2

    def test_user_template_has_placeholders(self) -> None:
        for placeholder in (
            "{source_lang}",
            "{target_lang}",
            "{glossary_bindings}",
            "{context_chunks}",
            "{input_text}",
            "{draft}",
        ):
            assert placeholder in AUDITOR_USER_TEMPLATE_V2

    def test_v2_auditor_checks_court_hierarchy(self) -> None:
        assert "Court of First Instance" in AUDITOR_SYSTEM_V2

    def test_v2_auditor_checks_register(self) -> None:
        assert "register" in AUDITOR_SYSTEM_V2.lower()


class TestV2Registry:
    def test_v2_prompt_constants_registered(self) -> None:
        expected_v2 = {
            "SHARED_SYSTEM_RULES_V2",
            "TRANSLATOR_SYSTEM_V2",
            "TRANSLATOR_USER_TEMPLATE_V2",
            "TRANSLATOR_REVISION_ADDENDUM_V2",
            "AUDITOR_SYSTEM_V2",
            "AUDITOR_USER_TEMPLATE_V2",
        }
        assert expected_v2 <= set(ALL_PROMPT_CONSTANTS)


# ---------------------------------------------------------------------------
# V3 prompt regression tests (EN→AR quality optimization)
# ---------------------------------------------------------------------------
_RULE_BEARING_PROMPTS_V3: dict[str, str] = {
    "SHARED_SYSTEM_RULES_V3": SHARED_SYSTEM_RULES_V3,
    "TRANSLATOR_SYSTEM_V3": TRANSLATOR_SYSTEM_V3,
    "AUDITOR_SYSTEM_V3": AUDITOR_SYSTEM_V3,
}


class TestV3MandatoryMarkers:
    @pytest.mark.parametrize("marker", _MANDATORY_MARKERS)
    def test_shared_rules_v3_contain_every_mandatory_marker(self, marker: str) -> None:
        assert marker in SHARED_SYSTEM_RULES_V3

    @pytest.mark.parametrize(
        ("name", "prompt"), list(_RULE_BEARING_PROMPTS_V3.items())
    )
    @pytest.mark.parametrize("marker", _MANDATORY_MARKERS)
    def test_v3_rule_bearing_prompts_contain_mandatory_markers(
        self, name: str, prompt: str, marker: str
    ) -> None:
        assert marker in prompt, f"{name} missing mandatory marker: {marker!r}"


class TestV3AdditiveOverV2:
    """V3 must contain all of V2 (additive, OCP) plus the new EN→AR guidance."""

    def test_shared_rules_v3_contains_v2_verbatim(self) -> None:
        assert SHARED_SYSTEM_RULES_V2 in SHARED_SYSTEM_RULES_V3

    def test_translator_system_v3_contains_v2_verbatim(self) -> None:
        assert TRANSLATOR_SYSTEM_V2 in TRANSLATOR_SYSTEM_V3

    def test_auditor_system_v3_contains_v2_verbatim(self) -> None:
        assert AUDITOR_SYSTEM_V2 in AUDITOR_SYSTEM_V3

    def test_revision_addendum_v3_contains_v2_verbatim(self) -> None:
        assert TRANSLATOR_REVISION_ADDENDUM_V2 in TRANSLATOR_REVISION_ADDENDUM_V3

    def test_user_templates_v3_equal_v2(self) -> None:
        assert TRANSLATOR_USER_TEMPLATE_V3 == TRANSLATOR_USER_TEMPLATE_V2
        assert AUDITOR_USER_TEMPLATE_V3 == AUDITOR_USER_TEMPLATE_V2


class TestV3EnArGuidance:
    def test_shared_rules_v3_has_en_ar_fidelity_rule(self) -> None:
        assert "ENGLISH-TO-ARABIC FIDELITY" in SHARED_SYSTEM_RULES_V3
        assert "common-law" in SHARED_SYSTEM_RULES_V3.lower()

    def test_translator_v3_has_direction_specific_guidance(self) -> None:
        assert "DIRECTION-SPECIFIC GUIDANCE" in TRANSLATOR_SYSTEM_V3
        assert "English -> Arabic" in TRANSLATOR_SYSTEM_V3
        assert "idafa" in TRANSLATOR_SYSTEM_V3.lower()

    def test_translator_v3_keeps_direction_placeholders(self) -> None:
        # V3 is built from V2 which carries the placeholders.
        assert "{source_lang}" in TRANSLATOR_SYSTEM_V3
        assert "{target_lang}" in TRANSLATOR_SYSTEM_V3
        # And still formats cleanly.
        formatted = TRANSLATOR_SYSTEM_V3.format(
            source_lang="en", target_lang="ar"
        )
        assert "en -> ar" in formatted

    def test_auditor_v3_has_en_ar_audit_checks(self) -> None:
        assert "COMMON-LAW CALQUES" in AUDITOR_SYSTEM_V3
        assert "UNTRANSLATED ENGLISH" in AUDITOR_SYSTEM_V3

    def test_revision_addendum_v3_has_calque_recheck(self) -> None:
        assert "common-law calque" in TRANSLATOR_REVISION_ADDENDUM_V3.lower()


class TestV3Registry:
    def test_v3_prompt_constants_registered(self) -> None:
        expected_v3 = {
            "SHARED_SYSTEM_RULES_V3",
            "TRANSLATOR_SYSTEM_V3",
            "TRANSLATOR_USER_TEMPLATE_V3",
            "TRANSLATOR_REVISION_ADDENDUM_V3",
            "AUDITOR_SYSTEM_V3",
            "AUDITOR_USER_TEMPLATE_V3",
        }
        assert expected_v3 <= set(ALL_PROMPT_CONSTANTS)


# ---------------------------------------------------------------------------
# V4 prompt regression tests (Arabic-script enforcement — anti-romanization)
# ---------------------------------------------------------------------------
_RULE_BEARING_PROMPTS_V4: dict[str, str] = {
    "SHARED_SYSTEM_RULES_V4": SHARED_SYSTEM_RULES_V4,
    "TRANSLATOR_SYSTEM_V4": TRANSLATOR_SYSTEM_V4,
    "AUDITOR_SYSTEM_V4": AUDITOR_SYSTEM_V4,
}


class TestV4MandatoryMarkers:
    @pytest.mark.parametrize("marker", _MANDATORY_MARKERS)
    def test_shared_rules_v4_contain_every_mandatory_marker(self, marker: str) -> None:
        assert marker in SHARED_SYSTEM_RULES_V4

    @pytest.mark.parametrize(
        ("name", "prompt"), list(_RULE_BEARING_PROMPTS_V4.items())
    )
    @pytest.mark.parametrize("marker", _MANDATORY_MARKERS)
    def test_v4_rule_bearing_prompts_contain_mandatory_markers(
        self, name: str, prompt: str, marker: str
    ) -> None:
        assert marker in prompt, f"{name} missing mandatory marker: {marker!r}"


class TestV4AdditiveOverV3:
    """V4 must contain all of V3 (additive, OCP) plus the new script rules."""

    def test_shared_rules_v4_contains_v3_verbatim(self) -> None:
        assert SHARED_SYSTEM_RULES_V3 in SHARED_SYSTEM_RULES_V4

    def test_translator_system_v4_contains_v3_verbatim(self) -> None:
        assert TRANSLATOR_SYSTEM_V3 in TRANSLATOR_SYSTEM_V4

    def test_auditor_system_v4_contains_v3_verbatim(self) -> None:
        assert AUDITOR_SYSTEM_V3 in AUDITOR_SYSTEM_V4

    def test_revision_addendum_v4_contains_v3_verbatim(self) -> None:
        assert TRANSLATOR_REVISION_ADDENDUM_V3 in TRANSLATOR_REVISION_ADDENDUM_V4

    def test_user_templates_v4_contain_v3_plus_web_search(self) -> None:
        """V4 user templates are V3 + a web search results section."""
        assert TRANSLATOR_USER_TEMPLATE_V3 in TRANSLATOR_USER_TEMPLATE_V4
        assert AUDITOR_USER_TEMPLATE_V3 in AUDITOR_USER_TEMPLATE_V4
        assert "{web_search_results}" in TRANSLATOR_USER_TEMPLATE_V4
        assert "{web_search_results}" in AUDITOR_USER_TEMPLATE_V4


class TestV4ArabicScriptEnforcement:
    """V4 adds an explicit Arabic-script-only rule to prevent romanization."""

    def test_shared_rules_v4_has_arabic_script_rule(self) -> None:
        assert "ARABIC SCRIPT" in SHARED_SYSTEM_RULES_V4
        assert "romaniz" in SHARED_SYSTEM_RULES_V4.lower()

    def test_translator_v4_reinforces_script_requirement(self) -> None:
        assert "Arabic script" in TRANSLATOR_SYSTEM_V4
        assert "romaniz" in TRANSLATOR_SYSTEM_V4.lower()

    def test_translator_v4_keeps_direction_placeholders(self) -> None:
        assert "{source_lang}" in TRANSLATOR_SYSTEM_V4
        assert "{target_lang}" in TRANSLATOR_SYSTEM_V4
        formatted = TRANSLATOR_SYSTEM_V4.format(source_lang="en", target_lang="ar")
        assert "en -> ar" in formatted

    def test_auditor_v4_has_romanized_arabic_check(self) -> None:
        assert "ROMANIZED ARABIC" in AUDITOR_SYSTEM_V4
        assert "romaniz" in AUDITOR_SYSTEM_V4.lower()

    def test_revision_addendum_v4_has_romanization_recheck(self) -> None:
        assert "romaniz" in TRANSLATOR_REVISION_ADDENDUM_V4.lower()


class TestV4Registry:
    def test_v4_prompt_constants_registered(self) -> None:
        expected_v4 = {
            "SHARED_SYSTEM_RULES_V4",
            "TRANSLATOR_SYSTEM_V4",
            "TRANSLATOR_USER_TEMPLATE_V4",
            "TRANSLATOR_REVISION_ADDENDUM_V4",
            "AUDITOR_SYSTEM_V4",
            "AUDITOR_USER_TEMPLATE_V4",
        }
        assert expected_v4 <= set(ALL_PROMPT_CONSTANTS)
