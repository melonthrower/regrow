"""Explicit template admission; observation evidence alone grants no eligibility."""
from copy import deepcopy
import hashlib
from pathlib import Path


def usable(observation, field='image'):
    quality = 'icon_quality' if field == 'icon_image' else 'image_quality'
    return bool(observation.get(field) and observation.get(quality) == 'clear'
                and observation.get('image_quality_reason', '').strip()
                and field not in observation.get('template_rejections', {}))


def latest(item):
    return next((o for o in reversed(item.get('observations', [])) if usable(o)), None)


def image(item):
    observation = latest(item)
    return observation['image'] if observation else None


def assessment(proposal):
    # Missing fields in historical replies remain unreviewed, never grandfathered.
    return {key: deepcopy(proposal[key]) for key in
            ('image_quality', 'icon_quality', 'image_quality_reason', 'template_rejections') if key in proposal}


def uniform_pixels(image):
    return all(low == high for low, high in image.convert('RGBA').getextrema())


def crop_rejection(box, size, scope=None, owner=None):
    """Geometry qualifies optional templates, never establishes action success."""
    if box is None:return None
    l,t,r,b=[box[k] for k in ('left','top','right','bottom')]
    if not (0<=l<r<=size[0] and 0<=t<b<=size[1]):
        return '身份框为空、倒置或超出实际来源图；不使用该模板'
    if scope:
        import foreground_scope
        if not foreground_scope.contains([l,t,r,b],scope):
            return '身份框不在该次观察的可交互前景内；不使用该模板'
    if owner and (max(l,owner['left'])>=min(r,owner['right']) or max(t,owner['top'])>=min(b,owner['bottom'])):
        return '身份框与所属区块完全分离；不使用该模板'
    return None


def check_control_crop(image, field, source_field):
    if not uniform_pixels(image):return
    error=ValueError('控件 '+source_field+' 的 '+field+' 裁图完全单色，不能确认独立身份外观。'
                     '请按实际来源图核对：不能把旧位置当作当前可见控件；纯色色块需包含可辨边界，'
                     '否则保留观察并标uncertain，不作身份模板。单色不证明控件不存在。')
    raise error


def reject_uniform_history(records, snapshot, source):
    """Explicit maintenance: retain model evidence, revoke only proven uniform templates."""
    from PIL import Image
    if not source:raise ValueError('template review requires an audit source')
    audit=[]
    for rid,region in records.items():
        for cid,control in region.get('controls',{}).items():
            for observation in control.get('observations',[]):
                for field in ('image','icon_image'):
                    if not usable(observation,field):continue
                    path=(Path(snapshot)/'regions'/rid/observation[field]).resolve()
                    with Image.open(path) as pixels:
                        if not uniform_pixels(pixels):continue
                    finding={'kind':'uniform_pixels','sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                             'source':source,'reason':'完全单色裁图无独立身份外观；不判定控件不存在。'}
                    observation.setdefault('template_rejections',{})[field]=finding
                    audit.append({'region':rid,'control':cid,'field':field,
                                  'observation':deepcopy(observation.get('evidence',{})),**finding})
    return audit


def evidence_limit(observation):
    rejected=observation.get('template_rejections',{})
    if not rejected:return None
    return {'未获资格的模板':{field:value['reason'] for field,value in rejected.items()},
            '限定':'这次观察的相应视觉身份依据不足；保留原描述但不能据其断言当前可见或可操作，也不判控件不存在。'}


def extend_schema(schema):
    for kind in ('regions', 'controls'):
        item = schema['properties'][kind]['items']
        fields = {'image_quality': {'type': 'string', 'enum': ['clear', 'occluded', 'uncertain']},
                  'image_quality_reason': {'type': 'string', 'minLength': 1}}
        if kind == 'controls':
            fields['icon_quality'] = deepcopy(fields['image_quality'])
        item['properties'].update(fields)
        item['required'] = list(dict.fromkeys(item['required'] + list(fields)))
    return schema


def admitted_box(proposal, field='bbox'):
    quality = 'icon_quality' if field == 'icon_bbox' else 'image_quality'
    if proposal.get(quality) != 'clear' or not proposal.get('image_quality_reason', '').strip():
        return None
    return proposal.get(field)
