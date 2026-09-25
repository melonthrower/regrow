from gui_rewalk.src.core.visual_traversal.state.registry import VisualStateRegistry


def test_revisit_enriches_variant_without_rehashing_page_identity():
    registry = VisualStateRegistry(namespace="clock")
    page_id, first_variant = registry.record_page_variant(
        "clock-root", "Clock", elements=["World", "Alarm"])

    revisited_page, enriched_variant = registry.record_page_variant(
        "clock-root", "A drifting label",
        elements=["World", "Alarm", "Timer"])

    assert revisited_page == page_id
    assert enriched_variant != first_variant
    assert registry.page_id_of("clock-root") == page_id


def test_resume_installs_persisted_page_identity_and_then_freezes_it():
    registry = VisualStateRegistry(namespace="clock")
    restored_page, _ = registry.record_page_variant(
        "alarm", "A newly perceived label", elements=["Alarm"],
        persisted_page_id="page-from-graph")

    assert restored_page == "page-from-graph"
    revisited_page, _ = registry.record_page_variant(
        "alarm", "Another label", elements=["Alarm", "Add alarm"],
        persisted_page_id="conflicting-later-value")
    assert revisited_page == "page-from-graph"
