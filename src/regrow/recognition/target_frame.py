"""Compare the located action control, or its Region, before GUI delivery."""
from pathlib import Path

import numpy as np
from PIL import Image

from regrow.recognition import foreground_scope, identity_templates, matching


def compare(reference, current, region, snapshot, proposal, *, run=None,
            control=None, control_ref=None, platform='android'):
    """Return None when existing evidence cannot bound the action locations."""
    rid = region.get('id')
    if not rid:
        return None
    try:
        with Image.open(reference) as old, Image.open(current) as new:
            if old.size != new.size:
                return None
            before = np.asarray(old.convert('RGB'))
            after = np.asarray(new.convert('RGB'))
        scene = None
        def locate_object(obj):
            nonlocal scene
            if scene is None:
                scene = matching.SceneMatcher(reference)
            def locate(path):
                with Image.open(Path(snapshot) / path) as image:
                    return scene.locate_pixels(np.asarray(image.convert('RGB')))
            hit = matching.match_appearances(identity_templates.variants(obj), locate)
            return hit.get('box') if hit.get('accepted') else None

        def covers_action(box):
            if not box:
                return False
            left, top, right, bottom = box
            if not (0 <= left < right <= before.shape[1] and
                    0 <= top < bottom <= before.shape[0]):
                return False
            points = [('x', 'y')]
            if proposal.get('action') == 'drag' or (proposal.get('action') == 'scroll' and platform == 'android'):
                points.append(('end_x', 'end_y'))
            for xkey, ykey in points:
                x, y = proposal.get(xkey), proposal.get(ykey)
                if x is not None and y is not None and not (left <= x < right and top <= y < bottom):
                    return False
            return True

        box = locate_object(control) if control else None
        scope_kind, basis = 'control', 'recorded_control_located_in_reference'
        if not covers_action(box):
            scope = foreground_scope.load(run, reference) if run else None
            box = (scope or {}).get('region_bounds', {}).get(rid)
            scope_kind, basis = 'region', 'same_frame_registered_region'
        if not covers_action(box):
            box = locate_object(region)
            basis = 'recorded_region_located_in_reference'
        if not covers_action(box):
            return None
        left, top, right, bottom = box
        return {'scope': scope_kind, 'region': rid,
                **({'control': control_ref} if scope_kind == 'control' else {}),
                'box': list(box), 'basis': basis,
                'unchanged': bool(np.array_equal(before[top:bottom, left:right],
                                               after[top:bottom, left:right]))}
    except (OSError, ValueError, KeyError):
        return None
