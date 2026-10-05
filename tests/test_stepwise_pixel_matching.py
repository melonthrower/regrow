"""Conservative original-size matching and whole-surface stability."""
import numpy as np
from PIL import Image

from tests.test_recovery_discovery import mod
from tests.test_stepwise_visual_backtrack import module as backtrack_module


def test_exact_crop_uses_pixels_without_edges_or_resizing(monkeypatch):
    matcher = mod('image_match')
    def forbidden(*args, **kwargs):
        raise AssertionError('matching must use original-size pixels')
    monkeypatch.setattr(matcher.cv2, 'Canny', forbidden)
    monkeypatch.setattr(matcher.cv2, 'resize', forbidden)
    pixels = np.random.default_rng(21).integers(0, 256, (70, 100, 3), dtype=np.uint8)
    hit = matcher._search(pixels[13:43, 25:65], pixels)
    assert hit['accepted'] and hit['box'] == [25, 13, 65, 43]
    assert hit['scale'] == 1


def test_runner_up_below_candidate_threshold_still_blocks_acceptance():
    matcher = mod('image_match')
    rng = np.random.default_rng(27)
    signal = rng.normal(size=(32, 32))
    signal -= signal.mean()
    signal /= signal.std()
    def correlated(correlation):
        noise = rng.normal(size=signal.shape)
        noise -= noise.mean()
        noise -= (noise * signal).mean() * signal
        noise /= noise.std()
        return correlation * signal + np.sqrt(1 - correlation ** 2) * noise
    def rgb(values):
        gray = np.clip(128 + 25 * values, 0, 255).astype(np.uint8)
        return np.repeat(gray[:, :, None], 3, axis=2)
    template = rgb(signal)
    scene = rgb(rng.normal(size=(100, 130)))
    scene[10:42, 10:42] = rgb(correlated(.92))
    scene[55:87, 85:117] = rgb(correlated(.89))
    hit = matcher._search(template, scene)
    assert .91 < hit['score'] < .93
    assert .02 < hit['gap'] < .04
    assert len(hit['candidates']) == 1
    assert not hit['accepted']


def test_uninformative_template_cannot_identify_a_control():
    matcher = mod('image_match')
    scene = np.random.default_rng(3).integers(0, 256, (60, 80, 3), dtype=np.uint8)
    hit = matcher._search(np.full((20, 20, 3), 128, dtype=np.uint8), scene)
    assert not hit['accepted']


def test_surface_comparison_tolerates_small_change_but_checks_both_halves(tmp_path, monkeypatch):
    matcher = mod('image_match')
    backtrack = backtrack_module(monkeypatch)
    pixels = np.random.default_rng(42).integers(0, 256, (100, 120, 3), dtype=np.uint8)
    old, new = tmp_path / 'old.png', tmp_path / 'new.png'
    Image.fromarray(pixels).save(old)
    slight = pixels.copy()
    slight[5:8, 5:8] = 128
    Image.fromarray(slight).save(new)
    assert backtrack.same_surface(old, new)
    changed = pixels.copy()
    changed[:10] = 128
    # The whole-image score passes; the changed upper half must still reject.
    assert matcher._search(pixels, changed)['accepted']
    Image.fromarray(changed).save(new)
    assert not backtrack.same_surface(old, new)

def test_exact_blank_surface_is_stable_but_different_blank_surface_is_not(tmp_path, monkeypatch):
    backtrack = backtrack_module(monkeypatch)
    old, new = tmp_path / 'old.png', tmp_path / 'new.png'
    Image.new('RGB', (60, 80), 'white').save(old)
    Image.new('RGB', (60, 80), 'white').save(new)
    assert backtrack.same_surface(old, new)
    Image.new('RGB', (60, 80), 'black').save(new)
    assert not backtrack.same_surface(old, new)
