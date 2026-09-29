"""Bind local scrolls to an already registered, frame-specific Region boundary."""
from pathlib import Path
import foreground_scope


def attach(run, state, request):
    request.pop('region_scroll_bounds', None)
    source = request.get('source', {})
    frames = request.get('image_refs', [])
    if (not request.get('allow_scroll') or request.get('navigation_advice')
            or source.get('region') not in state.get('interactive_regions', [])
            or source.get('observation') != (state.get('observation') or {}).get('id')
            or len(frames) != 1):
        return request
    frame = Path(run) / frames[0]
    scope = foreground_scope.load(run, frame)
    box = (scope or {}).get('region_bounds', {}).get(source['region'])
    if box and foreground_scope.contains(box, scope):
        request['region_scroll_bounds'] = {
            'region': source['region'], 'observation': source['observation'],
            'frame_sha256': foreground_scope.fingerprint(frame), 'box': list(box),
        }
    return request


def bind(request, proposal, base):
    if not request.get('allow_scroll'):
        return {**base, 'status': 'unresolved', 'reason': 'scroll is outside the routed task'}
    scope = request.get('region_scroll_bounds') or {}
    frames = request.get('image_refs', [])
    if (len(frames) != 1 or not Path(frames[0]).is_file()
            or scope.get('region') != base['region_ref']
            or scope.get('observation') != base['observation_ref']
            or scope.get('frame_sha256') != foreground_scope.fingerprint(frames[0])):
        return {**base, 'status': 'unresolved',
                'reason': 'current-frame Region boundary missing; observe the current foreground'}
    coords = [proposal.get(k) for k in ('x', 'y', 'end_x', 'end_y')]
    if any(type(v) is not int for v in coords):
        return {**base, 'status': 'unresolved', 'reason': 'scroll needs integer coordinates'}
    left, top, right, bottom = scope['box']
    x, y, ex, ey = coords
    desktop = request.get('platform') == 'desktop'
    if (not (left <= x < right and top <= y < bottom)
            or (not desktop and not (left <= ex < right and top <= ey < bottom))
            or (x, y) == (ex, ey)):
        return {**base, 'status': 'unresolved', 'reason': 'swipe leaves Region or has no displacement'}
    return {**base, 'status': 'matched',
            'basis': 'wheel origin lies in same-frame observed Region; endpoint is direction' if desktop
            else 'both swipe endpoints lie in same-frame observed Region'}
