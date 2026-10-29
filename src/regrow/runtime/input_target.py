"""Check target appearance, falling back to continuity of the actual focus surface."""
from regrow.records.object_store import owned_controls
from pathlib import Path
from regrow.recognition import matching as image_match
import numpy as np
from regrow.recognition.visual_backtrack import choose_position
from PIL import Image
from regrow.recognition import identity_templates as templates

def context(snapshot, records, binding, request):
    """Keep the bound target appearance; the model already supplied this action point."""
    snapshot = Path(snapshot)
    rid = binding['region_ref']
    cid = binding['control_ref']
    if cid is None:
        return None
    r = records[rid]
    control = owned_controls(r)[cid]
    row = templates.latest(control) or {}
    if not row.get('image'):
        return None
    source = {'region': rid, 'control': cid, 'name': control['name'], 'image': str((snapshot / row['image']).resolve()) if row.get('image') else None, 'frame': request['image_refs'][0]}
    return {'source': source}

def locate(target, before, after):
    """Verify the chosen target in the actual before/after focus frames."""
    if not target.get('image'):
        return None
    try:
        with Image.open(before) as a, Image.open(after) as b:
            sizes = (a.size, b.size)
        control = choose_position(image_match.locate(target['image'], before), image_match.locate(target['image'], after), *sizes)
        if not control:
            with Image.open(target['image']) as image:
                image = image.convert('RGB')
                (w, h) = image.size
                (dx, dy) = (max(1, w // 4), max(1, h // 4))
                if w - 2 * dx < 3 or h - 2 * dy < 3:
                    return None
                content = np.asarray(image.crop((dx, dy, w - dx, h - dy)))
            control = choose_position(image_match.SceneMatcher(before).locate_pixels(content), image_match.SceneMatcher(after).locate_pixels(content), *sizes)
        if not control:
            return None
        return {'control_box': control}
    except (OSError, ValueError):
        return None

def resolve(context, before, after):
    source = context['source']
    hit = locate(source, before, after)
    if hit:
        return {'status': 'same_target', 'target': {k: source[k] for k in ('region', 'control')}, **hit}
    from regrow.recognition.visual_backtrack import same_surface
    if same_surface(before, after):
        return {'status':'same_surface', 'reason':'历史外观未确认匹配；实际点击前后表面保持一致，沿本轮模型选点继续输入，不据此确认控件身份。'}
    return {'status': 'unresolved', 'reason': '聚焦后输入对象未可靠确认；保留实际点击，交由后续观察和动作选择定位。'}
