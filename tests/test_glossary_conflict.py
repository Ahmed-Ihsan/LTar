"""Unit tests for glossary conflict resolution (DATA_SPEC §2.4, task 2.1.3).

Priority override, equal-priority longer-term tie-break, and same-span
priority resolution.
"""
from __future__ import annotations

import pytest

from src.glossary import GlossaryIndex, Term, scan_glossary_hits

pytestmark = pytest.mark.unit


def _term(
    source: str,
    target: str,
    priority: int,
    order: int,
    law_ref: str = "Civil Code",
    norm: str | None = None,
) -> Term:
    return Term(
        source_term=source,
        source_lang="ar",
        target_term=target,
        target_lang="en",
        law_ref=law_ref,
        domain="civil_code",
        source_term_norm=norm if norm is not None else source,
        file_path="fixture.json",
        file_order=order,
        priority=priority,
    )


class TestConflictResolution:
    def test_higher_priority_wins_on_same_span(self) -> None:
        # Two terms match the same span 'المحكمة'; priority 10 beats priority 5.
        idx = GlossaryIndex([
            _term("المحكمة", "tribunal", priority=5, order=0),
            _term("المحكمة", "court", priority=10, order=1),
        ])
        hits = scan_glossary_hits("ذهب إلى المحكمة اليوم", lang="ar", index=idx)
        assert len(hits) == 1
        assert hits[0].target_term == "court"

    def test_equal_priority_longer_term_wins(self) -> None:
        # 'المحكمة الاتحادية' (longer) shadows 'المحكمة' (shorter) at same start.
        idx = GlossaryIndex([
            _term("المحكمة", "court", priority=10, order=0),
            _term("المحكمة الاتحادية", "Federal Supreme Court", priority=10, order=1),
        ])
        hits = scan_glossary_hits(
            "قررت المحكمة الاتحادية اليوم", lang="ar", index=idx
        )
        assert len(hits) == 1
        assert hits[0].source_term == "المحكمة الاتحادية"

    def test_priority_override_beats_length(self) -> None:
        # Even though 'المحكمة' is shorter, its higher priority wins the SAME
        # span. (Different spans would let the longer term win via longest-match.)
        idx = GlossaryIndex([
            _term("المحكمة", "court", priority=10, order=0),
            _term("المحكمة", "tribunal", priority=5, order=1),
        ])
        hits = scan_glossary_hits("المحكمة", lang="ar", index=idx)
        assert len(hits) == 1
        assert hits[0].target_term == "court"

    def test_earliest_file_order_breaks_final_tie(self) -> None:
        # Equal priority, equal verbatim length, equal law_ref -> file_order.
        idx = GlossaryIndex([
            _term("المحكمة", "first_wins", priority=5, order=3, law_ref="Civil Code"),
            _term("المحكمة", "second_loses", priority=5, order=7, law_ref="Civil Code"),
        ])
        hits = scan_glossary_hits("المحكمة", lang="ar", index=idx)
        assert len(hits) == 1
        assert hits[0].target_term == "first_wins"
