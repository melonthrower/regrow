"""Current-frame target doubts; reuse visual recall and the normal action contract."""
from copy import deepcopy
from pathlib import Path
import json
from regrow.recognition.matching import SceneMatcher, match_appearances

POINTER_ACTIONS = {'tap', 'click', 'double_click', 'long_press', 'right_click', 'hover', 'drag', 'input_text'}


def action_key(proposal):
    return {key: proposal.get(key) for key in ('action', 'target', 'x', 'y', 'text', 'end_x', 'end_y')}


def frames(request):
    return list(request.get('image_refs') or request.get('screenshots') or [])


def confirmed(request, proposal, current_frame=None):
    review = request.get('action_target_confirmation', {})
    valid = review.get('frames') == frames(request) and review.get('action') == action_key(proposal)
    if not valid or current_frame is None:
        return valid
    from PIL import Image
    import numpy as np
    try:
        with Image.open(frames(request)[0]) as old, Image.open(current_frame) as now:
            return np.array_equal(np.asarray(old.convert('RGB')), np.asarray(now.convert('RGB')))
    except (OSError, IndexError):
        return False


def at_point(request, proposal):
    """Locate supplied identities on this frame, using the existing matcher."""
    images = frames(request)
    if len(images) != 1 or not Path(images[0]).is_file():
        return [], []
    from PIL import Image
    import numpy as np
    matcher = SceneMatcher(images[0]); cache = {}
    def locate(path):
        if path not in cache:
            with Image.open(path) as image:
                cache[path] = matcher.locate_pixels(np.asarray(image.convert('RGB')))
        return cache[path]
    x, y = proposal['x'], proposal['y']
    candidates = []; rows = []; seen = set()
    for item in request.get('backend_candidates', []):
        rid = item.get('region_ref', request['source']['region'])
        key = (rid, item['id'])
        if key in seen:
            continue
        seen.add(key)
        appearances = item.get('appearances') or ([{'image': item['image']}] if item.get('image') else [])
        hit = match_appearances(appearances, locate)
        row = {'target': rid + '/' + item['id'], '名称': item['name'],
               '所属区块': item.get('region_name', rid),
               '历史身份范围（非当前坐标）': item.get('bbox'),
               '历史外观描述': item.get('icon_description', ''), '定位': hit.get('box') if hit.get('accepted') else None,
               '定位可靠': bool(hit.get('accepted'))}
        rows.append(row)
        contains = hit.get('accepted') and hit.get('box') and (
            hit['box'][0] <= x < hit['box'][2] and hit['box'][1] <= y < hit['box'][3])
        if contains:
            candidates.append(row)
    return rows, candidates


def unresolved(request, proposal):
    """Bind an unmatched target at a unique current visual position, else ask Luna."""
    if confirmed(request, proposal):
        # Respect Luna's current-frame conclusion that this is not a supplied
        # identity. A similar crop must not override that semantic judgment.
        return None
    rows, candidates = at_point(request, proposal)
    if len(candidates) == 1:
        selected = candidates[0]
        rid, cid = selected['target'].split('/')
        return {'region_ref': rid, 'control_ref': cid,
                'basis': 'unique current-frame appearance at proposed coordinates',
                'visual_binding': {'frame': frames(request)[0],
                                   'point': [proposal['x'], proposal['y']],
                                   'candidate': deepcopy(selected)}}
    raise Conflict({'原选择': {'target': proposal['target']},
                    '点击位置': [proposal['x'], proposal['y']],
                    '位置处其他候选': candidates, '已有身份定位': rows,
                    '说明': 'target未能唯一对应已有身份，当前位置也没有唯一可靠的外观对应。结合当前图和已有目录核对；旧对象返回给定ID，确为未登记对象时保留准确描述。'})


def conflict(request, proposal, binding):
    """Check an explicit identity or recheck an automatically associated target."""
    if proposal.get('action') not in POINTER_ACTIONS or not binding.get('control_ref'):
        return None
    if confirmed(request, proposal):
        return None
    proof = binding.get('visual_binding')
    if proof and frames(request) == [proof['frame']] and proof['point'] == [proposal['x'], proposal['y']]:
        return None
    rows, candidates = at_point(request, proposal)
    target = binding['region_ref'] + '/' + binding['control_ref']
    original = next((row for row in rows if row['target'] == target), None)
    if any(row['target'] == target for row in candidates) and (not proof or len(candidates) == 1):
        return None
    if proof:
        return {'原选择': original or {'target': target},
                '点击位置': [proposal['x'], proposal['y']],
                '位置处其他候选': candidates,
                '说明': '投递前图中，先前按坐标关联的控件不再有唯一可靠对应；请核对当前对象与原动作。'}
    if not candidates:
        return None
    return {'原选择': original or {'target': proposal['target']},
            '点击位置': [proposal['x'], proposal['y']], '位置处其他候选': candidates,
            '说明': '原ID未在该点获得对应定位，其他身份在该点有外观线索；不是已判定原ID错误，身份框不是点击范围。'}


class Conflict(ValueError):
    blocked_by = 'binding_conflict'
    def __init__(self, doubt):
        self.action_target_doubt = doubt
        names = '、'.join(row['名称'] for row in doubt.get('位置处其他候选', []))
        super().__init__('本次操作对象需核对：' + ('点击位置的候选为' + names if names else '点击位置没有唯一可靠的已有控件定位') + '。')


def request(root, job):
    from regrow.prompts.compose import parts
    original = deepcopy(job['request'])
    from regrow.runtime.action_commands import for_request, normalize
    proposal = normalize(for_request(job['candidate'], original))
    selected = parts(root, 'action_target_review')
    selected += [deepcopy(p) for p in original.get('fixed_parts', []) if p['path'].startswith(('平台/', '动作/'))]
    body = {'原动作上下文': original['user_prompt'], '原拟执行动作': proposal,
            '定位疑点': deepcopy(job['action_target_doubt'])}
    if job.get('rejected_reply'):
        body['上次回复问题'] = job['error']
        body['上次回复'] = deepcopy(job['rejected_reply'])
    q = {'role': 'action_target_review', 'stage': 'action_target_review', 'pipeline_step': 'action',
         'system_prompt': '\n\n'.join(p['text'] for p in selected),
         'user_prompt': json.dumps(body, ensure_ascii=False), 'fixed_parts': selected,
         'response_schema': deepcopy(original['response_schema']),
         'screenshots': list(original.get('screenshots', [])), 'image_refs': frames(original),
         'source': deepcopy(original['source']), 'original_request': original}
    for key in ('control_indexes', 'backend_candidates'):
        if key in original:
            q[key] = deepcopy(original[key])
    if original.get('frame_context'):
        q['frame_context'] = deepcopy(original['frame_context'])
    return q


def accept(request, reply, call):
    """Same action schema, same validation; no parallel decision protocol."""
    import jsonschema
    from regrow.runtime.action_commands import for_request, normalize
    original = deepcopy(request['original_request'])
    jsonschema.validate(reply, original['response_schema'])
    proposal = normalize(for_request(reply, original))
    original['action_target_confirmation'] = {'action': action_key(proposal),
                                              'frames': frames(original), 'call': call}
    return original, deepcopy(reply)
