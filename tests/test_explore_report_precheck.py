"""Reject already-invalid inventory before paying for semantic identity review."""
from copy import deepcopy
from dataclasses import replace

import pytest

from gui_rewalk.src.core.explore.contracts import parse_turn
from gui_rewalk.src.core.explore.inventory import apply_page_report
from gui_rewalk.src.core.explore.region_review import review_page_report_element_candidates
from gui_rewalk.src.core.explore.models import Region
from .explore_fixtures import _known_screen, _report, _seed_ledger, _turn


def _candidate_report():
    report = parse_turn(_turn(screen=_known_screen(), page_report=_report()),
                        has_pending_action=False).page_report
    region = report.regions[0]
    element = replace(region.elements[0], element_ref="")
    return replace(report, regions=[replace(region, region_ref="r1", elements=[element])])


@pytest.mark.parametrize("invalid", ["duplicate_action", "unknown_operation"])
def test_invalid_operation_report_is_rejected_before_element_review(invalid):
    ledger = _seed_ledger()
    before = deepcopy(ledger.__dict__)
    report = _candidate_report()
    region = report.regions[0]
    element = region.elements[0]
    operation = element.operations[0]
    if invalid == "duplicate_action":
        operations = [replace(operation, target="Toggle source"),
                      replace(operation, target="Open source menu")]
    else:
        operations = [replace(operation, operation_ref="co_missing")]
    report = replace(report, regions=[replace(region, elements=[replace(element, operations=operations)])])

    class Reviewer:
        def review_element_identities(self, **kwargs):
            pytest.fail("already-invalid report reached paid reviewer")

    with pytest.raises(ValueError) as error:
        review_page_report_element_candidates(ledger, Reviewer(), report=report,
            state_id="s1", screenshot=b"unused")
    assert ledger.__dict__ == before
    if invalid == "duplicate_action":
        assert "Toggle source" in str(error.value)
        assert "Open source menu" in str(error.value)
        assert "不同交互落点" in str(error.value)
    else:
        assert "co_missing" in str(error.value)


def test_unknown_operation_feedback_names_existing_explicit_owner_binding():
    ledger = _seed_ledger()
    report = _candidate_report()
    region = report.regions[0]
    element = region.elements[0]
    report = replace(report, regions=[replace(region, elements=[replace(element,
        element_ref="el1", operations=[replace(element.operations[0], operation_ref="co_missing")])])])
    result = apply_page_report(ledger, state_id="s1", report=report)
    assert not result.ok
    assert "el1" in result.issue
    assert "已登记绑定：co1" in result.issue


def test_foreign_region_is_rejected_before_review_with_current_state_refs():
    ledger = _seed_ledger()
    ledger.regions["r-old"] = Region("r-old", "Previous content", "Historical candidate")
    report = _candidate_report()
    report = replace(report, regions=[report.regions[0],
        replace(report.regions[0], region_ref="r-old", name="Previous content")])
    before = deepcopy(ledger.__dict__)

    class Reviewer:
        def review_element_identities(self, **kwargs):
            pytest.fail("foreign State reference reached paid reviewer")

    with pytest.raises(ValueError) as error:
        review_page_report_element_candidates(ledger, Reviewer(), report=report,
            state_id="s1", screenshot=b"unused")
    assert "r-old" in str(error.value)
    assert "r1" in str(error.value)
    assert ledger.regions["r1"].name in str(error.value)
    result = apply_page_report(ledger, state_id="s1", report=report)
    assert not result.ok
    assert "r1" in result.issue
    assert ledger.__dict__ == before
