"""Use model coordinates for Region scrolling; observe the result before updating."""
from pathlib import Path
from PIL import Image

def target_region(request, target):
    """Resolve the selected Region from the supplied current surface, without boxes."""
    view = request.get('page_context', {})
    regions = {}

    def collect(nodes):
        for node in nodes:
            regions[node['ref']] = node['name']
            collect(node.get('children', []))
    collect(view.get('current_tree', []))
    if 'current_tree' not in view:
        source = request.get('source', {}).get('region')
        if source:
            regions[source] = request.get('region_target', source)
    target = target.strip() if isinstance(target, str) else ''
    if target in regions:
        return target
    matches = [rid for rid, name in regions.items() if target and target == name]
    return matches[0] if len(matches) == 1 else None

def bind(request, proposal, base):
    if not (request.get('allow_scroll') or request.get('navigation_advice')):
        return {**base, 'status': 'unresolved', 'reason': 'scroll is outside the routed task'}
    region = target_region(request, proposal.get('target'))
    if region is None:
        return {**base, 'status': 'unresolved', 'reason': '滚动 target 请填写当前区块树中实际要滚动的区块 ID'}
    frames = request.get('image_refs', [])
    if len(frames) != 1 or not Path(frames[0]).is_file():
        return {**base, 'status': 'unresolved', 'reason': 'current screenshot is missing'}
    coords = [proposal.get(k) for k in ('x', 'y', 'end_x', 'end_y')]
    if any((type(v) is not int for v in coords)):
        return {**base, 'status': 'unresolved', 'reason': 'scroll needs integer coordinates'}
    with Image.open(frames[0]) as frame:
        (width, height) = frame.size
    (x, y, ex, ey) = coords
    desktop = request.get('platform') == 'desktop'
    if not (0 <= x < width and 0 <= y < height) or (not desktop and (not (0 <= ex < width and 0 <= ey < height))) or (x, y) == (ex, ey):
        return {**base, 'status': 'unresolved', 'reason': 'scroll coordinates outside screenshot or no displacement'}
    return {**base, 'region_ref': region, 'status': 'matched', 'model_grounded': True, 'basis': 'explicit current Region selection; model coordinates locate the scroll, its effect is observed afterwards'}
