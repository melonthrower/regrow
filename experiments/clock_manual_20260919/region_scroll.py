"""Use model coordinates for Region scrolling; observe the result before updating."""
from pathlib import Path
from PIL import Image


def bind(request, proposal, base):
    if not (request.get('allow_scroll') or request.get('navigation_advice')):
        return {**base, 'status': 'unresolved', 'reason': 'scroll is outside the routed task'}
    frames = request.get('image_refs', [])
    if len(frames) != 1 or not Path(frames[0]).is_file():
        return {**base, 'status': 'unresolved', 'reason': 'current screenshot is missing'}
    coords = [proposal.get(k) for k in ('x', 'y', 'end_x', 'end_y')]
    if any(type(v) is not int for v in coords):
        return {**base, 'status': 'unresolved', 'reason': 'scroll needs integer coordinates'}
    with Image.open(frames[0]) as frame:
        width, height = frame.size
    x, y, ex, ey = coords
    desktop = request.get('platform') == 'desktop'
    if (not (0 <= x < width and 0 <= y < height)
            or (not desktop and not (0 <= ex < width and 0 <= ey < height))
            or (x, y) == (ex, ey)):
        return {**base, 'status': 'unresolved',
                'reason': 'scroll coordinates outside screenshot or no displacement'}
    return {**base, 'status': 'matched', 'model_grounded': True,
            'basis': 'Region scroll uses model coordinates in current screenshot; verify the actual result'}
