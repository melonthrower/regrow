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


def conflict(request, proposal, binding):
    """A box supplies identity evidence, never a clickable-area guarantee.

    Missing matches alone do not reject an action. Only a different identity
    localized at the proposed point supplies a concrete question for Luna.
    """
    if proposal.get('action') not in POINTER_ACTIONS or not binding.get('control_ref'):
        return None
    if confirmed(request, proposal):
        return None
    images = frames(request)
    if len(images) != 1 or not Path(images[0]).is_file():
        return None
    from PIL import Image
    import numpy as np
    matcher = SceneMatcher(images[0]); cache = {}
    def locate(path):
        if path not in cache:
            with Image.open(path) as image:
                cache[path] = matcher.locate_pixels(np.asarray(image.convert('RGB')))
        return cache[path]
    x, y = proposal['x'], proposal['y']
    candidates = []; seen = set(); original = None
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
        at_point = hit.get('accepted') and hit.get('box') and (
            hit['box'][0] <= x < hit['box'][2] and hit['box'][1] <= y < hit['box'][3])
        if key == (binding['region_ref'], binding['control_ref']):
            original = row
            if at_point:
                return None
        elif at_point:
            candidates.append(row)
    if not candidates:
        return None
    return {'原选择': original or {'target': proposal['target']},
            '点击位置': [x, y], '位置处其他候选': candidates,
            '说明': '原ID未在该点获得对应定位，其他身份在该点有外观线索；不是已判定原ID错误，身份框不是点击范围。'}


class Conflict(ValueError):
    blocked_by = 'binding_conflict'
    def __init__(self, doubt):
        self.action_target_doubt = doubt
        names = '、'.join(row['名称'] for row in doubt['位置处其他候选'])
        super().__init__('本次操作对象需核对：点击位置识别到' + names + '，与原选择的定位不一致。')


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
