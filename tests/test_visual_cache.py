"""Priority-4 offline test: shared pHash-keyed VLM-role cache.

No emulator. Validates that identical frames cost ONE underlying call:
  1. same_page: identical (A,B) ordered pair cached; the SWAPPED pair (B,A) is a
     distinct key (order matters) so it is NOT wrongly served.
  2. PageIdentityJudge wired to the cache calls the agent only once for repeated
     identical inputs.
"""
import json
import os, sys
import tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import cv2
import imagehash

from gui_rewalk.src.core.visual_traversal.visual_cache import (
    LRU, PHASH_BUCKET_DISTANCE, VLMCallLedger, VLMRoleCache, frame_phash)
from gui_rewalk.src.core.visual_traversal.visual_agents import (
    PageIdentityJudge)
from gui_rewalk.src.core.visual_traversal.visual_engine import VisualTraversalEngine
from gui_rewalk.src.core.visual_traversal.visual_perception import (
    VisualElement, VisualPerception)


def _png(val):
    img = np.full((60, 60, 3), val % 256, np.uint8)
    img[10:50, 10:50] = (val * 7) % 256  # give it some structure for a real pHash
    return cv2.imencode(".png", img)[1].tobytes()


def _bucket_page(seed):
    rng = np.random.RandomState(seed)
    img = np.full((200, 200, 3), 240, np.uint8)
    img[:16, :] = (200, 120, 30)
    img[30:180, 20:180] = cv2.resize(
        rng.randint(0, 256, (8, 8, 3)).astype(np.uint8),
        (160, 150), interpolation=cv2.INTER_CUBIC)
    return img


def test_phash_bucket_jitter():
    base_img = _bucket_page(3)
    jitter_img = base_img.copy()
    jitter_img[3:13, 170:190] = (255, 255, 255)
    different_img = _bucket_page(99)
    different_img[:16, :] = (40, 160, 60)

    encode = lambda img: cv2.imencode(".png", img)[1].tobytes()
    base, jitter, different = map(
        encode, (base_img, jitter_img, different_img))
    ph = lambda shot: imagehash.hex_to_hash(frame_phash(shot))
    assert ph(base) - ph(jitter) <= PHASH_BUCKET_DISTANCE
    assert ph(base) - ph(different) > PHASH_BUCKET_DISTANCE + 8

    pair_cache = LRU(bucket=PHASH_BUCKET_DISTANCE)
    pair_cache.put((frame_phash(base), frame_phash(different)), "verdict")
    assert pair_cache.get(
        (frame_phash(jitter), frame_phash(different))) == "verdict"
    assert pair_cache.get(
        (frame_phash(different), frame_phash(different))) is None
    identity_cache = VLMRoleCache()
    identity_calls = {"n": 0}
    def judge_identity():
        identity_calls["n"] += 1
        return True
    identity_cache.get_same_page(base, different, judge_identity)
    identity_cache.get_same_page(jitter, different, judge_identity)
    assert identity_calls["n"] == 2, (
        "near-pHash frames must not reuse a page-identity decision")
    print("[0] pHash bucket: near-frame pair hit; different page pair miss")


def main():
    test_phash_bucket_jitter()
    cache = VLMRoleCache()
    A, B = _png(30), _png(200)

    # 1. same_page ordered-pair caching
    sp = {"n": 0}
    def compute_same():
        sp["n"] += 1
        return True
    assert cache.get_same_page(A, B, compute_same) is True
    assert cache.get_same_page(A, B, compute_same) is True   # cached
    assert sp["n"] == 1, sp["n"]
    cache.get_same_page(B, A, compute_same)                  # swapped -> distinct key
    assert sp["n"] == 2, sp["n"]
    print("[1] same_page: (A,B) cached; (B,A) is a distinct ordered key")

    # 2. PageIdentityJudge wired to cache calls the agent once for the same pair
    class PJAgent:
        def __init__(self):
            self.n = 0
        def predict_mm(self, prompt, images):
            self.n += 1
            return '{"same": true}', None
    pa = PJAgent()
    judge = PageIdentityJudge(pa, cache=VLMRoleCache())
    judge.same_page(A, B); judge.same_page(A, B); judge.same_page(A, B)
    assert pa.n == 1, f"judge agent called {pa.n}x for identical pair (want 1)"
    print("[2] PageIdentityJudge: 3 identical pairs -> 1 agent call")

    # 5. Exact-frame grounding cache returns fresh objects. A forced refresh is
    # a real new call, but remains tentative until reviewer promotion.
    class GroundAgent:
        max_retry = 3

        def __init__(self):
            self.n = 0

        def predict_mm(self, _prompt, _images):
            self.n += 1
            label = f"Page {self.n}"
            response = {
                "window": [0, 0, 1000, 1000],
                "is_modal": False,
                "modal": None,
                "is_system_dialog": False,
                "is_interruption": False,
                "page": label,
                "elements": [{
                    "name": label, "type": "link",
                    "category": "navigation", "interactive": True,
                    "bbox": [100, 100, 300, 200],
                }],
            }
            return json.dumps(response), 10, 2, 1

    ga = GroundAgent()
    ledger = VLMCallLedger()
    gc = VLMRoleCache(ledger=ledger)
    perception = VisualPerception(None, agent=ga, use_ocr=False)
    perception.use_vlm_grounding = True
    perception.cache = gc
    perception.vlm_ledger = ledger
    first = perception.detect_and_name(A, apply_filter=False)
    first[0].visited = True
    second = perception.detect_and_name(A, apply_filter=False)
    assert ga.n == 1, f"same exact frame re-grounded {ga.n}x"
    assert first[0] is not second[0] and not second[0].visited
    assert second[0].name == "Page 1"
    forced = perception.detect_and_name(
        A, apply_filter=False, force_refresh=True)
    assert ga.n == 2 and forced[0].name == "Page 2"
    again = perception.detect_and_name(A, apply_filter=False)
    assert again[0].name == "Page 1", "tentative refresh poisoned cache"
    print("[5] grounding: exact frame cached as raw response; force refresh bypasses")

    # 6. Region cache is exact-frame LRU; forced refresh bypasses and replaces it.
    engine = object.__new__(VisualTraversalEngine)
    engine.vlm_ledger = ledger
    engine.vlm_cache = gc
    engine._seg_cache_key = None
    engine._seg_cache_val = None
    region_calls = {"n": 0}

    def segment(_shot):
        region_calls["n"] += 1
        return [{"role": f"content-{region_calls['n']}",
                 "bbox": [0, 0, 10, 10], "scrollable": False}]

    engine._segment_regions = segment
    r1 = engine._segment_regions_cached(A)
    r2 = engine._segment_regions_cached(A)
    assert region_calls["n"] == 1 and r1 == r2
    r3 = engine._segment_regions_cached(A, force_refresh=True)
    assert region_calls["n"] == 2 and r3[0]["role"] == "content-2"
    assert engine._segment_regions_cached(A) == r3
    engine._segment_regions = lambda _shot: []
    assert engine._segment_regions_cached(A, force_refresh=True) == r3
    assert engine._segment_regions_cached(A) == r3
    print("[6] regions: exact cache + refresh; empty refresh preserves canonical")

    # An early region-set return must clear the previous frame's review context.
    early = object.__new__(VisualTraversalEngine)
    early._last_regions_desc = [{"role": "stale"}]
    early._is_touch = True
    early.perception = type("P", (), {"last_all_elements": []})()
    assert early._arrival_region_set({"screenshot": A}, []) == set()
    assert early._last_regions_desc == []
    same_elements = [VisualElement(
        0, "A", [0, 0, 10, 10], [5, 5],
        el_type="tab", category="navigation")]
    som_a = np.zeros((4, 4, 3), np.uint8)
    som_b = np.ones((4, 4, 3), np.uint8)
    assert (early._review_subject_signature(same_elements, som_a)
            != early._review_subject_signature(same_elements, som_b))
    print("[6b] region desc clears on early return; review signature binds SoM")

    # 7. Reuse merged QA as modal self-heal's first verdict. If later attempts
    # disagree, restore BOTH elements and last_* metadata from the winning one.
    class PromoteCache:
        def __init__(self):
            self.promoted = None

        def put_grounding(self, _shot, response):
            self.promoted = response

    class HealPerception:
        def __init__(self):
            self.cache = PromoteCache()
            self.calls = 0
            self.last_is_modal = True
            self.last_window_xywh = [0, 0, 100, 100]
            self.last_is_system_dialog = False
            self.last_is_interruption = False
            self.last_page_name = "Initial"
            self.last_all_elements = []
            self.last_node_local_functions = []
            self.last_som_image = np.zeros((2, 2, 3), np.uint8)
            self.last_grounding_response = "initial-response"

        def detect_and_name(self, _shot, force_refresh=False):
            assert force_refresh
            self.calls += 1
            name = "Winner" if self.calls == 1 else "Rejected"
            self.last_page_name = name
            self.last_grounding_response = name.lower() + "-response"
            self.last_som_image = np.full((2, 2, 3), self.calls, np.uint8)
            return [VisualElement(
                0, name, [0, 0, 10, 10], [5, 5],
                el_type="tab", category="navigation")]

    class HealReviewer:
        def __init__(self):
            self.calls = 0

        def review(self, _som, elements):
            self.calls += 1
            n = 1 if elements[0].name == "Winner" else 3
            return {"wrong": list(range(n))}

    heal = object.__new__(VisualTraversalEngine)
    heal.perception = HealPerception()
    heal.reviewer = HealReviewer()
    initial = [VisualElement(
        0, "Initial", [0, 0, 10, 10], [5, 5],
        el_type="tab", category="navigation")]
    winner, _, winning_review = heal._heal_grounding_via_review(
        A, initial, heal.perception.last_som_image,
        initial_review={"wrong": [0, 1]})
    assert heal.reviewer.calls == 2, "merged verdict was reviewed again"
    assert winner[0].name == "Winner"
    assert heal.perception.last_page_name == "Winner"
    assert heal.perception.cache.promoted == "winner-response"
    assert len(winning_review["wrong"]) == 1
    print("[7] modal heal: merged QA reused; winning elements+metadata promoted")

    # 8. Ledger persists role-level calls/tokens/cache hits.
    with tempfile.TemporaryDirectory() as td:
        lp = os.path.join(td, "vlm_calls.json")
        out = VLMCallLedger(lp)
        out.predict("probe", ga, "x", [np.zeros((2, 2, 3), np.uint8)])
        out.cache_hit("probe")
        out.save()
        saved = json.load(open(lp, encoding="utf-8"))
        assert saved["roles"]["probe"]["calls"] == 1
        assert saved["roles"]["probe"]["cache_hits"] == 1
        assert saved["roles"]["probe"]["prompt_tokens"] == 10
    print("[8] ledger: role calls/tokens/cache hits persisted")

    print("ALL PASS — semantic caches dedupe safely, force-refresh remains usable, "
          "modal QA is reused with winner metadata, and role costs are observable.")


if __name__ == "__main__":
    main()
