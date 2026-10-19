"""Explicit template admission; observation evidence alone grants no eligibility."""
from regrow.records.object_store import observation_history
from regrow.records.object_store import owned_controls
from copy import deepcopy
import hashlib
from pathlib import Path

def usable(observation, field='image'):
    quality = 'icon_quality' if field == 'icon_image' else 'image_quality'
    return bool(observation.get(field) and observation.get(quality, 'clear') == 'clear' and (field not in observation.get('template_rejections', {})))

def latest(item):
    return next((o for o in reversed(observation_history(item)) if usable(o)), None)

def image(item):
    observation = latest(item)
    return observation['image'] if observation else None

def assessment(proposal):
    return {key: deepcopy(proposal[key]) for key in ('image_quality', 'icon_quality', 'image_quality_reason', 'template_rejections') if key in proposal}

def uniform_pixels(image):
    return all((low == high for (low, high) in image.convert('RGBA').getextrema()))

def crop_rejection(box, size, owner=None):
    """Geometry qualifies optional templates, never establishes action success."""
    if box is None:
        return None
    (l, t, r, b) = [box[k] for k in ('left', 'top', 'right', 'bottom')]
    if not (0 <= l < r <= size[0] and 0 <= t < b <= size[1]):
        return '身份框为空、倒置或超出实际来源图；不使用该模板'
    return None

def check_control_crop(image, field, source_field):
    if not uniform_pixels(image):
        return
    error = ValueError('控件 ' + source_field + ' 的 ' + field + ' 裁图完全单色，不能确认独立身份外观。请按实际来源图核对：不能把旧位置当作当前可见控件；纯色色块需包含可辨边界，无法可靠裁取时bbox填null，保留已确认身份和具体缺口。单色不证明控件不存在。')
    raise error

def reject_uniform_history(records, snapshot, source):
    """Explicit maintenance: retain model evidence, revoke only proven uniform templates."""
    from PIL import Image
    if not source:
        raise ValueError('template review requires an audit source')
    audit = []
    for (rid, region) in records.items():
        for (cid, control) in owned_controls(region).items():
            for observation in observation_history(control):
                for field in ('image', 'icon_image'):
                    if not usable(observation, field):
                        continue
                    path = (Path(snapshot) / observation[field]).resolve()
                    with Image.open(path) as pixels:
                        if not uniform_pixels(pixels):
                            continue
                    finding = {'kind': 'uniform_pixels', 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'source': source, 'reason': '完全单色裁图无独立身份外观；不判定控件不存在。'}
                    observation.setdefault('template_rejections', {})[field] = finding
                    audit.append({'region': rid, 'control': cid, 'field': field, 'observation': deepcopy(observation.get('evidence', {})), **finding})
    return audit

def evidence_limit(observation):
    rejected = observation.get('template_rejections', {})
    if not rejected:
        return None
    return {'未获资格的模板': {field: value['reason'] for (field, value) in rejected.items()}, '限定': '这次观察的相应视觉身份依据不足；保留原描述但不能据其断言当前可见或可操作，也不判控件不存在。'}

def extend_schema(schema):
    for kind in ('regions', 'controls'):
        item = schema['properties'][kind]['items']
        fields = ('image_quality', 'image_quality_reason', 'icon_quality')
        for field in fields:
            item['properties'].pop(field, None)
        item['required'] = [key for key in item['required'] if key not in fields]
        item['allOf'] = [branch for branch in item.get('allOf', []) if not set(branch.get('then', {}).get('required', [])).intersection(fields)]
        item.setdefault('allOf', []).append({'if': {'properties': {'ref': {'enum': [None, '']}}, 'required': ['ref']}, 'then': {'required': ['bbox']}})
    return schema

def admitted_box(proposal, field='bbox'):
    quality = 'icon_quality' if field == 'icon_bbox' else 'image_quality'
    if quality in proposal and proposal[quality] != 'clear':
        return None
    return proposal.get(field)


def variants(item):
    """Admitted full-control appearances, newest first; each retains its source."""
    rows = observation_history(item)
    if not rows and isinstance(item.get('image'), str):
        rows = [item]
    result = []
    seen = set()
    for row in reversed(rows):
        if usable(row) and row['image'] not in seen:
            result.append(row)
            seen.add(row['image'])
    return result
