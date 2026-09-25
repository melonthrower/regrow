from tools.mingle_mapping_probe_entry import (
    _target_matches,
)


def test_forced_target_matching_tolerates_descriptive_suffix() -> None:
    assert _target_matches("Weekend Plan", "Weekend Plan chat") is True
    assert _target_matches("Close Chats", "Chats") is False
    assert _target_matches("Add attachment", "Back arrow") is False
