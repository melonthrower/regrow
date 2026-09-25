"""Explicit template admission; observation evidence alone grants no eligibility."""
from copy import deepcopy


def usable(observation, field='image'):
    quality = 'icon_quality' if field == 'icon_image' else 'image_quality'
    return bool(observation.get(field) and observation.get(quality) == 'clear'
                and observation.get('image_quality_reason', '').strip())


def latest(item):
    return next((o for o in reversed(item.get('observations', [])) if usable(o)), None)


def image(item):
    observation = latest(item)
    return observation['image'] if observation else None


def assessment(proposal):
    # Missing fields in historical replies remain unreviewed, never grandfathered.
    return {key: proposal[key] for key in
            ('image_quality', 'icon_quality', 'image_quality_reason') if key in proposal}


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
