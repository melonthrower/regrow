import numpy as np

from gui_rewalk.src.core.visual_traversal.runtime.landing import (
    _change_evidence_from_hash,
)


def test_change_evidence_accepts_numpy_boolean_results():
    same = _change_evidence_from_hash(np.bool_(True), same_node=True)
    changed = _change_evidence_from_hash(np.bool_(False), same_node=True)
    moved = _change_evidence_from_hash(np.bool_(False), same_node=False)

    assert same == {
        "verdict": "no_effect",
        "note": "before/after perceptual hashes are identical",
        "same_node": True,
    }
    assert changed["verdict"] == "transitioned_consistent"
    assert changed["same_node"] is True
    assert moved["verdict"] == "transitioned_consistent"
    assert moved["same_node"] is False


def test_change_evidence_leaves_unknown_hash_unclassified():
    assert _change_evidence_from_hash(None, same_node=True) is None
